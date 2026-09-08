#!/usr/bin/env python3
"""Parallel eval runner for the Text2SQL golden-set suite.

Modes:
  gold mode (default)  — predicted_sql = case's own gold_sql
  model mode (--model) — predicted_sql = OpenAI chat completion (bare prompt)
  agent mode (--agent) — predicted_sql = run_agent(question) full LangGraph pipeline

Pass/Fail Logic:
  PASS   = EX == 1 AND no rubric dimension == "wrong"
           (rubric "flag" on join → route to manual review, not auto-fail)
  FAIL   = EX == 0
           OR any rubric dimension == "wrong" despite EX == 1 (coincidental-match FP caught)
  REVIEW = EX == 1 AND rubric has "flag" (not "wrong") → needs human look
  EM     = logged for drift-tracking, never gates pass/fail

Usage:
    python3 eval_runner.py
    python3 eval_runner.py --agent --agent-model gpt-4o-mini
    python3 eval_runner.py --case e01_5_selling_products_health_beauty
    python3 eval_runner.py --difficulty hard
    python3 eval_runner.py --inject forgot_filter
    python3 eval_runner.py --model gpt-4o-mini
    python3 eval_runner.py --max-workers 5
    python3 eval_runner.py --output results/my_run
    python3 eval_runner.py --resume
"""
import argparse
import csv
import json
import logging
import re
import shutil
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

SCRIPTS_DIR = Path(__file__).resolve().parent
EVALS_DIR = SCRIPTS_DIR.parent
PROJECT_ROOT = EVALS_DIR.parent          # repo root — so `agent` package is importable
CASES_YAML_PATH = EVALS_DIR / "cases.yaml"
RESULTS_DIR = EVALS_DIR / "results"
SUMMARY_DIR = RESULTS_DIR / "summary"      # results/summary/{run_id}/
CHECKPOINTS_DIR = RESULTS_DIR / "checkpoints"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import report_generator  # noqa: E402
import rubric as rubric_mod  # noqa: E402
from checkpoint_manager import CheckpointManager  # noqa: E402
from db_loader import (  # noqa: E402
    DEFAULT_STATEMENT_TIMEOUT_MS,
    TransientDBError,
    connection_scope,
    execute_query,
)

logger = logging.getLogger("eval_runner")
logging.basicConfig(level=logging.INFO, format="%(message)s")

CSV_COLUMNS = [
    "query_id", "question", "em", "ex", "latency_sec", "input_tokens",
    "output_tokens", "cost_usd", "status", "table", "time_frame", "filters",
    "aggregation", "join", "difficulty", "gold_sql", "predicted_sql",
    "error", "ground_truth_rows",
]

PRICING_USD_PER_1M = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4.1": {"input": 10.00, "output": 40.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "o4-mini": {"input": 4.00, "output": 16.00},
    "gpt-5.4": {"input": 2.50, "output": 15.00},
}

MAX_RETRIES = 2
BACKOFF_SECONDS = (0.5, 1.0)
FLOAT_TOLERANCE = 0.01  # 1%

SCHEMA_SUMMARY = """\
Tables:
  customers(customer_id, customer_unique_id, customer_zip_code_prefix, customer_city, customer_state)
  sellers(seller_id, seller_zip_code_prefix, seller_city, seller_state)
  products(product_id, product_category_name, product_weight_g, ...)
  category_translation(product_category_name, product_category_name_english)
  orders(order_id, customer_id, order_status, order_purchase_timestamp,
         order_delivered_customer_date, order_estimated_delivery_date)
  order_items(order_id, product_id, seller_id, price, freight_value)
  order_payments(order_id, payment_type, payment_value)
  order_reviews(order_id, review_score, review_creation_date)
"""


# ── Discovery ─────────────────────────────────────────────────────────────


def discover_cases(case_filter: Optional[str] = None, difficulty_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load cases from single cases.yaml file.
    
    Args:
        case_filter: Optional case ID or prefix to filter by
        difficulty_filter: Optional difficulty to filter by
        
    Returns:
        List of case dicts matching the filters
    """
    if not CASES_YAML_PATH.exists():
        raise FileNotFoundError(f"Cases file not found: {CASES_YAML_PATH}")
    
    with open(CASES_YAML_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    cases = data.get("cases", [])
    
    # Apply filters
    if case_filter:
        cases = [c for c in cases if c.get("id") == case_filter or (c.get("id") or "").startswith(case_filter)]
    if difficulty_filter:
        cases = [c for c in cases if c.get("difficulty") == difficulty_filter]
    
    return cases


def slugify_run_name(name: str) -> str:
    """Turn a human run title into a filesystem-safe slug.

    "baseline 4o-mini!" → "baseline_4o_mini"
    """
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return slug


def build_run_id(name: Optional[str], timestamp: Optional[str] = None) -> str:
    """Compose a run_id. Named runs get "{slug}_{timestamp}"; else timestamp only."""
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    if name:
        slug = slugify_run_name(name)
        if slug:
            return f"{slug}_{ts}"
    return ts


def find_run_dir(run_name: str) -> Optional[Path]:
    """Locate a prior run's summary directory by exact id or name prefix.

    Accepts a full run_id (e.g. "baseline_20260724_191500") or a name slug
    (e.g. "baseline") and returns the most recent matching directory.
    """
    if not SUMMARY_DIR.exists():
        return None
    exact = SUMMARY_DIR / run_name
    if exact.is_dir():
        return exact
    slug = slugify_run_name(run_name)
    matches = sorted(
        (d for d in SUMMARY_DIR.iterdir()
         if d.is_dir() and (d.name == run_name or d.name.startswith(slug + "_") or d.name.startswith(run_name))),
        key=lambda d: d.stat().st_mtime,
    )
    return matches[-1] if matches else None


def load_failed_ids_from_run(run_name: str) -> List[str]:
    """Read the failing query_ids from a prior run.

    Prefers the consolidated {run_id}.yaml; falls back to failures/failures.json.
    """
    run_dir = find_run_dir(run_name)
    if run_dir is None:
        raise FileNotFoundError(f"No prior run found matching: {run_name!r} under {SUMMARY_DIR}")

    # 1) Consolidated YAML  ({run_id}.yaml)
    yaml_path = run_dir / f"{run_dir.name}.yaml"
    if yaml_path.exists():
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        failures = data.get("failures") or []
        ids = [f.get("query_id") for f in failures if f.get("query_id")]
        if ids:
            return ids

    # 2) Fallback: failures/failures.json
    failures_json = run_dir / "failures" / "failures.json"
    if failures_json.exists():
        arr = json.loads(failures_json.read_text(encoding="utf-8"))
        return [f.get("query_id") for f in arr if f.get("query_id")]

    return []


def get_gold_sql(case: Dict[str, Any]) -> str:
    """Get gold SQL for a case.
    
    In gold mode (no inject_failure), returns the case's gold_sql.
    This replaces the old runner.py approach.
    
    Args:
        case: Case dict with gold_sql field
        
    Returns:
        SQL string to execute
    """
    return (case.get("gold_sql") or "").strip()


def inject_failure(case: Dict[str, Any], failure_mode: str) -> str:
    """Inject a failure mode into the gold SQL.
    
    This is a simplified version - in production you'd have specific
    failure injection logic per case type.
    
    Args:
        case: Case dict
        failure_mode: Name of failure mode (e.g., "forgot_filter")
        
    Returns:
        Modified SQL with the failure injected
        
    Raises:
        ValueError: If failure_mode is not recognized
    """
    # For now, just raise error - in future we can add specific failure modes
    raise ValueError(f"Unknown failure_mode: {failure_mode}")


# ── SQL normalization / EM / EX ──────────────────────────────────────────


def normalize_sql(sql: str) -> str:
    """Collapse whitespace, lowercase, strip quotes/backticks, normalize
    commas/parens/operators for exact-match comparison."""
    s = sql.strip().lower()
    s = s.replace("`", "").replace('"', "")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"\s*\(\s*", "(", s)
    s = re.sub(r"\s*\)\s*", ")", s)
    s = re.sub(r"\s*=\s*", " = ", s)
    s = s.rstrip(";").strip()
    return s


def compute_em(gold_sql: str, predicted_sql: str) -> Tuple[int, int]:
    """Return (em, em_raw)."""
    em_raw = 1 if gold_sql.strip() == predicted_sql.strip() else 0
    em = 1 if normalize_sql(gold_sql) == normalize_sql(predicted_sql) else 0
    return em, em_raw


def _row_to_jsonable(row: Any) -> Any:
    if isinstance(row, dict):
        return {k: _row_to_jsonable(v) for k, v in row.items()}
    if isinstance(row, (list, tuple)):
        return [_row_to_jsonable(v) for v in row]
    if isinstance(row, Decimal):
        return float(row)
    return row


def _is_number(x: Any) -> bool:
    """True for int/float/Decimal (but not bool, which is an int subclass)."""
    if isinstance(x, bool):
        return False
    return isinstance(x, (int, float, Decimal))


def _values_equal(a: Any, b: Any, tol: float = FLOAT_TOLERANCE) -> bool:
    """Compare two scalar values with relative float tolerance.

    Handles int/float/Decimal uniformly (PostgreSQL numeric columns come back
    as Decimal, which the old isinstance(a,(int,float)) check silently skipped —
    causing e.g. 4.0888 vs 4.0888019 to be treated as unequal).
    """
    if _is_number(a) and _is_number(b):
        fa, fb = float(a), float(b)
        if fa == fb:
            return True
        denom = max(abs(fa), abs(fb), 1e-9)
        return abs(fa - fb) / denom <= tol
    return a == b


def _row_values(row: Any) -> List[Any]:
    """Extract a positional list of values from a row.

    Column NAMES are intentionally ignored — result equality depends on the
    values, not what the SELECT list aliased them to. Gold and predicted SQL
    routinely use different aliases (e.g. `COUNT(*) AS n` vs `... AS cnt`).
    """
    if isinstance(row, dict):
        return list(row.values())
    if isinstance(row, (list, tuple)):
        return list(row)
    return [row]


def _row_sort_key(row: Any) -> tuple:
    """Stable, value-based sort key for a row.

    Uses ONLY the values (not column names) and normalizes numbers to a rounded
    float so that near-equal values (within tolerance) sort together. Each value
    becomes a (type_tag, value) pair so mixed types sort deterministically
    without raising TypeError.
    """
    key = []
    for v in _row_values(row):
        if _is_number(v):
            # Round to 6 decimals for a stable ordering that tolerates tiny
            # float/Decimal representation differences.
            key.append((0, round(float(v), 6)))
        elif v is None:
            key.append((1, ""))
        else:
            key.append((2, str(v)))
    return tuple(key)


def _rows_equal(
    rows_a: List[Any],
    rows_b: List[Any],
    *,
    label: str = "",
    trim_to_gold_cols: bool = False,
) -> Tuple[bool, str]:
    """Compare two row sets for EX equivalence.

    Returns (equal, reason). Empty reason when equal.

    Generic behaviors (no case-specific logic):
    - Row order is ignored: both sides are sorted by value-based key first.
    - When trim_to_gold_cols is True, if predicted has more columns than
      gold, the trailing extra columns are dropped so the comparison runs
      against the gold's column count. Symmetric: if gold has more, gold's
      trailing columns are also dropped. Default is False — verbose
      questions now specify the exact column count expected, so deviations
      are real failures, not tolerated leniency.
    - Value comparison uses _values_equal, which applies numeric tolerance
      and NULL==NULL semantics.

    A non-empty reason describes the first disagreement found:
    row count, col count mismatch, or value mismatch with row/col location.
    """
    if len(rows_a) != len(rows_b):
        return False, (
            f"[{label}] row count differs: gold={len(rows_a)}, predicted={len(rows_b)}"
        )

    sorted_a = sorted(rows_a, key=_row_sort_key)
    sorted_b = sorted(rows_b, key=_row_sort_key)

    for i, (ra, rb) in enumerate(zip(sorted_a, sorted_b)):
        vals_a = _row_values(ra)
        vals_b = _row_values(rb)

        if len(vals_a) != len(vals_b):
            if not trim_to_gold_cols:
                which = "predicted" if len(vals_b) > len(vals_a) else "gold"
                return False, (
                    f"[{label}] col count differs on row {i}: "
                    f"gold={len(vals_a)}, predicted={len(vals_b)} "
                    f"(extras on {which})"
                )
            # trim_to_gold_cols=True: tolerate trailing extras; compare common prefix
            n = min(len(vals_a), len(vals_b))
        else:
            n = len(vals_a)

        for j in range(n):
            if not _values_equal(vals_a[j], vals_b[j]):
                return False, (
                    f"[{label}] value differs on row {i}, col {j}: "
                    f"gold={vals_a[j]!r}, predicted={vals_b[j]!r}"
                )

    if len(rows_a) == 0:
        return True, f"[{label}] both empty"
    return True, f"[{label}] rows equal ({len(rows_a)} rows)"


def compute_ex(
    gold_rows: List[Any],
    predicted_rows: List[Any],
    *,
    label: str = "",
    log_path: Optional[Path] = None,
    trim_to_gold_cols: bool = True,
) -> int:
    """Returns 1 if EX-equal, 0 otherwise. Optionally logs the reason."""
    try:
        equal, reason = _rows_equal(
            gold_rows,
            predicted_rows,
            label=label,
            trim_to_gold_cols=trim_to_gold_cols,
        )
    except Exception as e:
        reason = f"[{label}] EX error: {e}"
        equal = False

    if log_path is not None:
        try:
            with log_path.open("a") as f:
                f.write(reason + "\n")
        except Exception:
            pass
    return 1 if equal else 0


# ── Cost / pricing (model mode) ──────────────────────────────────────────


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = PRICING_USD_PER_1M.get(model)
    if not pricing:
        return 0.0
    return (input_tokens / 1e6) * pricing["input"] + (output_tokens / 1e6) * pricing["output"]


def call_model(model: str, question: str) -> Tuple[str, int, int, float]:
    """Call the OpenAI API for model mode. Returns (sql, input_tokens, output_tokens, latency_sec)."""
    import os

    from openai import OpenAI

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    system_prompt = (
        "You are an expert SQL assistant for the Olist Brazilian e-commerce "
        "dataset. Translate the user's question into a single PostgreSQL "
        "SELECT query. Return ONLY the SQL, no explanation, no markdown.\n\n"
        f"{SCHEMA_SUMMARY}"
    )

    start = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        temperature=0,
        max_tokens=800,
    )
    latency_sec = time.perf_counter() - start

    content = response.choices[0].message.content or ""
    sql = re.sub(r"```(?:sql)?\s*\n?", "", content).replace("```", "").strip()

    usage = response.usage
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

    return sql, input_tokens, output_tokens, latency_sec


def call_model_with_retry(model: str, question: str, max_retries: int = MAX_RETRIES) -> Tuple[str, int, int, float]:
    import openai

    attempt = 0
    while True:
        try:
            return call_model(model, question)
        except openai.RateLimitError:
            if attempt >= max_retries:
                raise
            delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
            time.sleep(delay)
            attempt += 1


def call_agent(question: str) -> Tuple[dict, int, int, float]:
    """Call run_agent() through the full LangGraph pipeline.

    Returns (agent_state, input_tokens, output_tokens, latency_sec).
    Token counts are extracted from the agent state (captured from LLM response).
    """
    from agent.graph import run_agent  # imported here to avoid module-level cost

    start = time.perf_counter()
    state = run_agent(question)
    latency_sec = time.perf_counter() - start

    # Extract token counts from agent state
    input_tokens = state.get("input_tokens", 0) or 0
    output_tokens = state.get("output_tokens", 0) or 0

    return state, input_tokens, output_tokens, latency_sec


# ── Per-case worker ───────────────────────────────────────────────────────


def run_single_case(
    case: Dict[str, Any],
    model: Optional[str],
    inject_failure: Optional[str],
    use_agent: bool = False,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> Dict[str, Any]:
    """Execute one case end-to-end.

    Modes:
      - agent mode (use_agent=True): calls run_agent(question) via LangGraph,
        reuses agent's executed rows for EX scoring, fetches gold rows separately.
      - model mode (model != None): calls OpenAI directly with bare schema prompt.
      - gold mode (default): runs gold_sql as-is (harness sanity check).

    Intended to be run inside a ThreadPoolExecutor worker. Opens exactly
    one PostgreSQL connection for gold-row fetch and (in non-agent modes)
    predicted-SQL execution.
    """
    query_id = case["id"]
    question = case.get("question", "")
    difficulty = case.get("difficulty", "")
    gold_sql = case.get("gold_sql", "").strip()

    result: Dict[str, Any] = {
        "query_id": query_id,
        "question": question,
        "em": 0,
        "ex": 0,
        "ex_reason": "",
        "latency_sec": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "status": "error",
        "outcome": "fail",
        "table": "NA",
        "time_frame": "NA",
        "filters": "NA",
        "aggregation": "NA",
        "join": "NA",
        "difficulty": difficulty,
        "gold_sql": gold_sql,
        "predicted_sql": "",
        "error": "",
        "ground_truth_rows": "",
    }

    attempt = 0
    while True:
        try:
            # ── Agent mode ─────────────────────────────────────────────────
            if use_agent:
                agent_state, input_tokens, output_tokens, latency_sec = call_agent(question)

                from core.config import settings as _cfg
                cost_usd = compute_cost(_cfg.openai_model, input_tokens, output_tokens)

                predicted_sql = (agent_state.get("sql") or "").strip()
                agent_rows    = agent_state.get("rows")    # None if refused/errored
                agent_error   = (agent_state.get("error") or "").strip()

                result["predicted_sql"] = predicted_sql
                result["latency_sec"]   = round(latency_sec, 6)
                result["input_tokens"]  = input_tokens
                result["output_tokens"] = output_tokens
                result["cost_usd"]      = round(cost_usd, 8)

                # Fetch gold rows for EX comparison (separate DB connection).
                with connection_scope(statement_timeout_ms) as conn:
                    gold_rows, _ = execute_query(conn, gold_sql)

                result["ground_truth_rows"] = json.dumps(_row_to_jsonable(gold_rows), default=str)

                # EM: SQL text comparison.
                em, _ = compute_em(gold_sql, predicted_sql)

                # EX: agent's rows vs gold rows.
                # If refused / errored the agent returns rows=None → treat as []
                predicted_rows = agent_rows if agent_rows is not None else []
                ex, ex_reason = _rows_equal(
                    gold_rows, predicted_rows,
                    label=query_id,
                    trim_to_gold_cols=False,
                )
                result["ex_reason"] = ex_reason

                result["em"] = em
                result["ex"] = ex

                # Rubric on agent's SQL.
                rubric_spec    = case.get("rubric", {})
                rubric_results = rubric_mod.grade_rubric(predicted_sql, rubric_spec)
                result["table"]       = rubric_results.get("table", "NA")
                result["filters"]     = rubric_results.get("filters", "NA")
                result["aggregation"] = rubric_results.get("aggregation", "NA")
                result["join"]        = rubric_results.get("join", "NA")
                time_dim    = rubric_results.get("time_frame", "NA")
                date_op_dim = rubric_results.get("date_operator", "NA")
                result["time_frame"]  = _combine_time_dims(time_dim, date_op_dim)

                any_wrong = rubric_mod.has_any_wrong(rubric_results)
                any_flag = rubric_mod.has_any_flag(rubric_results)

                if agent_error and agent_rows is None:
                    # Refused by validator OR runtime execution error.
                    result["status"] = "error"
                    result["outcome"] = "error"
                    result["error"]  = agent_error
                elif ex == 1 and not any_wrong:
                    # PASS: EX=1 and no rubric dimension is "wrong".
                    # If a dimension is only flagged (not wrong) → REVIEW (soft),
                    # still counts as a pass but routed for a human look.
                    result["status"] = "pass"
                    result["outcome"] = "review" if any_flag else "pass"
                    result["error"]  = ""
                else:
                    # FAIL: EX=0 OR any rubric dimension is "wrong".
                    result["status"] = "fail"
                    result["outcome"] = "fail"
                    result["error"]  = agent_error or ""

                return result

            # ── Model / gold mode ──────────────────────────────────────────
            with connection_scope(statement_timeout_ms) as conn:
                # 1. Get predicted SQL.
                latency_sec = 0.0
                input_tokens = 0
                output_tokens = 0
                cost_usd = 0.0

                if model:
                    predicted_sql, input_tokens, output_tokens, latency_sec = call_model_with_retry(model, question)
                    cost_usd = compute_cost(model, input_tokens, output_tokens)
                else:
                    # Gold mode: use gold_sql directly
                    if inject_failure:
                        predicted_sql = inject_failure(case, inject_failure)
                    else:
                        predicted_sql = get_gold_sql(case)

                result["predicted_sql"] = predicted_sql
                result["latency_sec"] = round(latency_sec, 6)
                result["input_tokens"] = input_tokens
                result["output_tokens"] = output_tokens
                result["cost_usd"] = round(cost_usd, 8)

                # 2. Execute gold + predicted SQL.
                gold_rows, _ = execute_query(conn, gold_sql)
                predicted_rows, _ = execute_query(conn, predicted_sql)

                result["ground_truth_rows"] = json.dumps(_row_to_jsonable(gold_rows), default=str)

                # 3. EM / EX.
                em, _em_raw = compute_em(gold_sql, predicted_sql)
                ex, ex_reason = _rows_equal(
                    gold_rows, predicted_rows,
                    label=query_id,
                    trim_to_gold_cols=False,
                )
                result["ex_reason"] = ex_reason
                result["em"] = em
                result["ex"] = ex

                # 4. Rubric grading.
                rubric_spec = case.get("rubric", {})
                rubric_results = rubric_mod.grade_rubric(predicted_sql, rubric_spec)
                result["table"] = rubric_results.get("table", "NA")
                result["filters"] = rubric_results.get("filters", "NA")
                result["aggregation"] = rubric_results.get("aggregation", "NA")
                result["join"] = rubric_results.get("join", "NA")
                # time_frame column folds in both the Time dim and
                # DateOperator dim per the CSV column spec.
                time_dim = rubric_results.get("time_frame", "NA")
                date_op_dim = rubric_results.get("date_operator", "NA")
                combined_time = _combine_time_dims(time_dim, date_op_dim)
                result["time_frame"] = combined_time

                any_wrong = rubric_mod.has_any_wrong(rubric_results)
                any_flag = rubric_mod.has_any_flag(rubric_results)

                # 5. Status (EM is logged but never gates pass/fail)
                if ex == 1 and not any_wrong:
                    # PASS: EX=1 and no rubric dimension is "wrong".
                    # Flag-only (not wrong) → REVIEW (soft), still a pass.
                    result["status"] = "pass"
                    result["outcome"] = "review" if any_flag else "pass"
                else:
                    # FAIL: EX=0 OR any rubric dimension is "wrong"
                    result["status"] = "fail"
                    result["outcome"] = "fail"
                result["error"] = ""

                return result

        except TransientDBError as e:
            if attempt >= MAX_RETRIES:
                result["status"] = "timeout"
                result["error"] = str(e)
                return result
            delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
            time.sleep(delay)
            attempt += 1
            continue

        except Exception as e:
            result["status"] = "error"
            result["error"] = f"{type(e).__name__}: {e}"
            return result


def _combine_time_dims(time_dim: str, date_op_dim: str) -> str:
    """Fold the Time and DateOperator rubric dims into a single status.

    NA + NA -> NA. Otherwise take the "worse" of the two present values
    (wrong > flag > correct), ignoring NA entries.
    """
    order = {"wrong": 3, "flag": 2, "correct": 1, "NA": 0}
    present = [d for d in (time_dim, date_op_dim) if d != "NA"]
    if not present:
        return "NA"
    return max(present, key=lambda d: order.get(d, 0))


# ── Output writers ────────────────────────────────────────────────────────


def write_csv(results: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in results:
            writer.writerow({col: row.get(col, "") for col in CSV_COLUMNS})


def write_per_query_json(results: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")


_CASE_SPLIT_DIMS = ["table", "time_frame", "filters", "aggregation", "join"]


def _case_split_doc(r: Dict[str, Any]) -> Dict[str, Any]:
    """Return a concise per-case document for passes/ and failures/ files."""
    return {
        "query_id":     r["query_id"],
        "question":     r.get("question", ""),
        "difficulty":   r.get("difficulty", ""),
        "status":       r.get("status", ""),
        "outcome":      r.get("outcome", ""),
        "em":           r["em"],
        "ex":           r["ex"],
        "latency_sec":  r.get("latency_sec", 0.0),
        "cost_usd":     r.get("cost_usd", 0.0),
        "input_tokens": r.get("input_tokens", 0),
        "output_tokens":r.get("output_tokens", 0),
        "error":        r.get("error", ""),
        "gold_sql":     r.get("gold_sql", ""),
        "predicted_sql":r.get("predicted_sql", ""),
        "rubric":       {dim: r.get(dim, "NA") for dim in _CASE_SPLIT_DIMS},
    }


def write_case_splits(
    results: List[Dict[str, Any]],
    passes_dir: Path,
    failures_dir: Path,
) -> None:
    """Write aggregate passes.json and failures.json into their directories.

    - passes_dir/passes.json   — array of all cases with status == 'pass'
    - failures_dir/failures.json — array of all cases with status != 'pass'
    """
    passes   = [_case_split_doc(r) for r in results if r.get("status") == "pass"]
    failures = [_case_split_doc(r) for r in results if r.get("status") != "pass"]

    passes_dir.mkdir(parents=True, exist_ok=True)
    failures_dir.mkdir(parents=True, exist_ok=True)

    (passes_dir   / "passes.json").write_text(
        json.dumps(passes,   indent=2, default=str), encoding="utf-8"
    )
    (failures_dir / "failures.json").write_text(
        json.dumps(failures, indent=2, default=str), encoding="utf-8"
    )


def write_run_yaml(
    results: List[Dict[str, Any]],
    summary: Dict[str, Any],
    run_id: str,
    name: Optional[str],
    mode_label: str,
    path: Path,
) -> None:
    """Write a single consolidated {run_id}.yaml holding passes AND failures.

    This is the human-facing, run-titled artifact: totals up top, then the
    passing cases (including any REVIEW cases) and the failing cases, each with
    gold vs predicted SQL and per-dimension rubric verdicts.
    """
    passes   = [_case_split_doc(r) for r in results if r.get("status") == "pass"]
    failures = [_case_split_doc(r) for r in results if r.get("status") != "pass"]

    doc = {
        "run_id":    run_id,
        "name":      name,
        "mode":      mode_label,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "totals": {
            "total":     summary.get("total", 0),
            "passed":    summary.get("passed", 0),
            "review":    summary.get("review", 0),
            "failed":    summary.get("failed", 0),
            "errors":    summary.get("errors", 0),
            "timeouts":  summary.get("timeouts", 0),
            "pass_rate": summary.get("pass_rate", 0.0),
            "ex_rate":   summary.get("metrics", {}).get("ex_rate", 0.0),
            "em_rate":   summary.get("metrics", {}).get("em_rate", 0.0),
            "total_cost_usd": summary.get("metrics", {}).get("total_cost_usd", 0.0),
        },
        "passes":   passes,
        "failures": failures,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(doc, sort_keys=False, default_flow_style=False, allow_unicode=True, width=1000),
        encoding="utf-8",
    )


def build_summary(
    results: List[Dict[str, Any]], run_id: str, model: Optional[str]
) -> Dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail")
    errors = sum(1 for r in results if r["status"] == "error")
    timeouts = sum(1 for r in results if r["status"] == "timeout")
    # REVIEW is a soft outcome layered on top of a pass (EX=1 with a rubric flag).
    review = sum(1 for r in results if r.get("outcome") == "review")

    em_values = [r["em"] for r in results]
    ex_values = [r["ex"] for r in results]
    latencies = [r["latency_sec"] for r in results if r["latency_sec"]]

    rubric_dims = ["table", "filters", "aggregation", "join", "time_frame"]
    by_dim: Dict[str, Dict[str, int]] = {}
    for dim in rubric_dims:
        graded = [r[dim] for r in results if r.get(dim) != "NA"]
        by_dim[dim] = {
            "graded": len(graded),
            "pass": sum(1 for v in graded if v == "correct"),
            "flag": sum(1 for v in graded if v == "flag"),
            "wrong": sum(1 for v in graded if v == "wrong"),
        }

    rubric_clean = sum(
        1 for r in results if not any(r[d] == "wrong" for d in rubric_dims)
    )
    false_positives = sum(
        1 for r in results if r["ex"] == 1 and any(r[d] == "wrong" for d in rubric_dims)
    )

    by_difficulty: Dict[str, Dict[str, Any]] = {}
    for diff in ("easy", "medium", "hard"):
        subset = [r for r in results if r.get("difficulty") == diff]
        n = len(subset)
        if n == 0:
            by_difficulty[diff] = {"n": 0, "em": 0.0, "ex": 0.0, "pass_rate": 0.0}
            continue
        by_difficulty[diff] = {
            "n": n,
            "em": round(sum(r["em"] for r in subset) / n, 4),
            "ex": round(sum(r["ex"] for r in subset) / n, 4),
            "pass_rate": round(sum(1 for r in subset if r["status"] == "pass") / n, 4),
        }

    failures = []
    for r in results:
        if r["status"] != "pass":
            wrong_dims = [d for d in rubric_dims if r.get(d) == "wrong"]
            failures.append({
                "query_id": r["query_id"],
                "difficulty": r.get("difficulty"),
                "trap": r.get("trap"),
                "em": bool(r["em"]),
                "ex": bool(r["ex"]),
                "rubric_wrong_dims": wrong_dims,
                "error": r.get("error") or None,
                "predicted_sql_excerpt": (r.get("predicted_sql") or "")[:200],
            })

    summary = {
        "run_id": run_id,
        "model": model or "gold",
        "total": total,
        "passed": passed,
        "failed": failed,
        "review": review,
        "errors": errors,
        "timeouts": timeouts,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "metrics": {
            "em_rate": round(sum(em_values) / total, 4) if total else 0.0,
            "ex_rate": round(sum(ex_values) / total, 4) if total else 0.0,
            "rubric_clean_rate": round(rubric_clean / total, 4) if total else 0.0,
            "false_positive_rate": round(false_positives / total, 4) if total else 0.0,
            "avg_latency_sec": round(statistics.mean(latencies), 6) if latencies else 0.0,
            "p50_latency_sec": round(statistics.median(latencies), 6) if latencies else 0.0,
            "p95_latency_sec": round(_percentile(latencies, 95), 6) if latencies else 0.0,
            "total_input_tokens": sum(r["input_tokens"] for r in results),
            "total_output_tokens": sum(r["output_tokens"] for r in results),
            "total_cost_usd": round(sum(r["cost_usd"] for r in results), 6),
        },
        "by_difficulty": by_difficulty,
        "by_dim_fail_rate": by_dim,
        "failures": failures,
    }
    return summary


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return d0 + d1


# ── Main ──────────────────────────────────────────────────────────────────


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Text2SQL eval runner")
    parser.add_argument("--case", help="Run a single case by id (or id prefix)")
    parser.add_argument("--difficulty", choices=["easy", "medium", "hard"], help="Filter by difficulty")
    parser.add_argument("--model", help="Model name for model mode (bare prompt, e.g. gpt-4o-mini).")
    parser.add_argument("--agent", action="store_true",
                        help="Agent mode: call run_agent() with the full LangGraph pipeline.")
    parser.add_argument("--agent-model", dest="agent_model",
                        help="Override settings.openai_model for agent mode (e.g. gpt-4o-mini).")
    parser.add_argument("--inject", help="Failure-injection mode (gold mode only)")
    parser.add_argument("--name", "--title", dest="name",
                        help="Human title for this run; used in run_id and all artifact paths.")
    parser.add_argument("--rerun-failures", dest="rerun_failures", metavar="RUN_NAME",
                        help="Re-run only the failing cases from a prior run (by run_id/name); "
                             "computes fresh metrics for that failing subset.")
    parser.add_argument("--max-workers", type=int, default=10, help="ThreadPoolExecutor worker count")
    parser.add_argument("--output", help="Custom run directory path (overrides summary/{run_id}/)")
    parser.add_argument("--resume", action="store_true", help="Resume from the latest checkpoint")
    parser.add_argument("--force", action="store_true", help="Ignore any existing checkpoint, start fresh")
    parser.add_argument("--list-checkpoints", action="store_true", help="List available checkpoints and exit")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if args.list_checkpoints:
        checkpoints = sorted(CHECKPOINTS_DIR.glob("eval_run_*.checkpoint.jsonl")) if CHECKPOINTS_DIR.exists() else []
        if not checkpoints:
            print("No checkpoints found.")
        for c in checkpoints:
            print(c)
        return 0

    cases = discover_cases(case_filter=args.case, difficulty_filter=args.difficulty)
    if not cases:
        print("No cases matched the given filters.")
        return 1

    # --rerun-failures: restrict to the failing cases of a prior run.
    if args.rerun_failures:
        try:
            failed_ids = load_failed_ids_from_run(args.rerun_failures)
        except FileNotFoundError as e:
            print(str(e))
            return 1
        if not failed_ids:
            print(f"No failing cases found in prior run {args.rerun_failures!r} — nothing to re-run.")
            return 0
        id_set = set(failed_ids)
        cases = [c for c in cases if c.get("id") in id_set]
        if not cases:
            print(f"Prior failures {sorted(id_set)} did not match any current cases.")
            return 1
        print(f"Re-running {len(cases)} failing case(s) from prior run {args.rerun_failures!r}")

    run_id = build_run_id(args.name)
    checkpoint_mgr = CheckpointManager(CHECKPOINTS_DIR, run_id)

    if args.resume and not args.force:
        latest = CheckpointManager.find_latest(CHECKPOINTS_DIR)
        if latest is not None:
            completed = checkpoint_mgr.load_existing(latest)
            run_id = latest.stem.replace("eval_run_", "").replace(".checkpoint", "")
            print(f"Resuming from checkpoint: {len(completed)}/{len(cases)} queries already completed")
        else:
            print("No checkpoint found — starting fresh")

    pending_cases = checkpoint_mgr.get_pending_cases(cases)
    _wall_start = time.perf_counter()

    _agent_model_label = ""
    if args.agent:
        from agent.graph import get_graph
        from agent.prompts import validate_prompts
        from core.config import settings as _cfg

        if args.agent_model:
            _cfg.openai_model = args.agent_model
            logger.info("Agent model overridden → %s", args.agent_model)

        get_graph()          # compile LangGraph DAG once
        validate_prompts()   # ensure all 4 prompt files exist
        _agent_model_label = _cfg.openai_model
        logger.info("Agent pre-warm complete (model=%s)", _cfg.openai_model)

    if args.agent:
        mode_label = f"agent({_agent_model_label})"
    elif args.model:
        mode_label = args.model
    else:
        mode_label = "gold"

    if not pending_cases:
        print("No pending queries, all completed.")
    else:
        print(f"Running {len(pending_cases)} case(s) with max_workers={args.max_workers} (mode={mode_label})")

        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = {
                executor.submit(run_single_case, case, args.model, args.inject, args.agent): case
                for case in pending_cases
            }
            for future in as_completed(futures):
                case = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = {
                        "query_id": case["id"],
                        "question": case.get("question", ""),
                        "em": 0, "ex": 0, "latency_sec": 0.0,
                        "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                        "status": "error",
                        "table": "NA", "time_frame": "NA", "filters": "NA",
                        "aggregation": "NA", "join": "NA",
                        "difficulty": case.get("difficulty", ""),
                        "gold_sql": case.get("gold_sql", ""),
                        "predicted_sql": "", "error": f"{type(e).__name__}: {e}",
                        "ground_truth_rows": "",
                    }
                checkpoint_mgr.append(result)
                rubric_status = "pass" if result["status"] == "pass" else "fail"
                logger.info(
                    "%s em=%d ex=%d rubric=%s %.3fs",
                    result["query_id"], result["em"], result["ex"], rubric_status, result["latency_sec"],
                )

    all_results = checkpoint_mgr.finalize()

    # ── Output directory layout ───────────────────────────────────────────
    # New runs go to:  results/summary/{run_id}/{metrics,passes,failures}/
    # Root-level eval_run.* copies kept for backward compatibility.
    if args.output:
        run_dir = Path(args.output)
    else:
        run_dir = SUMMARY_DIR / run_id

    metrics_dir  = run_dir / "metrics"
    passes_dir   = run_dir / "passes"
    failures_dir = run_dir / "failures"

    for d in (metrics_dir, passes_dir, failures_dir, CHECKPOINTS_DIR, RESULTS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    csv_path       = metrics_dir / "eval_run.csv"
    per_query_path = metrics_dir / "per_query.json"
    summary_path   = metrics_dir / "summary.json"
    ex_log_path    = metrics_dir / "ex_reasons.log"

    write_csv(all_results, csv_path)
    write_per_query_json(all_results, per_query_path)
    summary = build_summary(all_results, run_id, mode_label)
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    # Per-case EX reason log — one line per case, explains why EX passed/failed.
    with ex_log_path.open("w") as f:
        for r in all_results:
            reason = r.get("ex_reason") or ""
            if not reason:
                ex_flag = r.get("ex", 0)
                reason = f"[{r.get('query_id','?')}] EX={'pass' if ex_flag else 'fail'} (no reason captured)"
            f.write(reason + "\n")

    # Split results into passes/ and failures/ aggregate files.
    write_case_splits(all_results, passes_dir, failures_dir)

    # Consolidated, run-titled YAML holding BOTH passes and failures.
    run_yaml_path = run_dir / f"{run_id}.yaml"
    write_run_yaml(all_results, summary, run_id, args.name, mode_label, run_yaml_path)

    # Markdown report → metrics/
    wall_time_sec = time.perf_counter() - _wall_start
    report_path = metrics_dir / "report.md"
    report_generator.generate_report(
        summary,
        all_results,
        report_path,
        wall_time_sec=wall_time_sec,
        parallel_workers=args.max_workers,
    )

    # Root-level latest copies (backward compat — eval_run.* in results/).
    shutil.copyfile(csv_path,       RESULTS_DIR / "eval_run.csv")
    shutil.copyfile(per_query_path, RESULTS_DIR / "eval_run.per_query.json")
    shutil.copyfile(report_path,    RESULTS_DIR / "eval_run.report.md")
    shutil.copyfile(summary_path,   RESULTS_DIR / "eval_run.summary.json")

    checkpoint_mgr.delete()

    # Human-readable summary.
    print()
    print("=" * 60)
    print(f"Run {run_id} ({summary['model']})")
    print(f"Total: {summary['total']}  Passed: {summary['passed']}  Review: {summary.get('review', 0)}  "
          f"Failed: {summary['failed']}  Errors: {summary['errors']}  Timeouts: {summary['timeouts']}")
    print(f"Pass rate: {summary['pass_rate']:.2%}  EM: {summary['metrics']['em_rate']:.2%}  "
          f"EX: {summary['metrics']['ex_rate']:.2%}")
    for diff, stats in summary["by_difficulty"].items():
        if stats["n"]:
            print(f"  {diff}: n={stats['n']} pass_rate={stats['pass_rate']:.2%}")
    print("=" * 60)
    print(f"Run dir:        {run_dir}")
    print(f"  results yaml  {run_yaml_path}")
    print(f"  metrics/      {metrics_dir}")
    print(f"  passes/       {passes_dir / 'passes.json'}")
    print(f"  failures/     {failures_dir / 'failures.json'}")
    print(f"  report.md     {report_path}")
    print(f"Latest copies → {RESULTS_DIR / 'eval_run.*'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
