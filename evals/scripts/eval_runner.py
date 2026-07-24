#!/usr/bin/env python3
"""Parallel eval runner for the Text2SQL golden-set suite.

Modes:
  gold mode (default)  — predicted_sql = case's own gold_sql
  model mode (--model) — predicted_sql = OpenAI chat completion output

Usage:
    python3 eval_runner.py
    python3 eval_runner.py --case e01_5_selling_products_health_beauty
    python3 eval_runner.py --difficulty hard
    python3 eval_runner.py --inject forgot_filter
    python3 eval_runner.py --model gpt-4o-mini
    python3 eval_runner.py --max-workers 4
    python3 eval_runner.py --output results/my_run.csv
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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

SCRIPTS_DIR = Path(__file__).resolve().parent
EVALS_DIR = SCRIPTS_DIR.parent
CASES_YAML_PATH = EVALS_DIR / "cases.yaml"
RESULTS_DIR = EVALS_DIR / "results"
CHECKPOINTS_DIR = RESULTS_DIR / "checkpoints"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

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
    return row


def _rows_sort_key(rows: List[Any]) -> List[str]:
    return sorted(json.dumps(_row_to_jsonable(r), sort_keys=True, default=str) for r in rows)


def _values_equal(a: Any, b: Any, tol: float = FLOAT_TOLERANCE) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a == b:
            return True
        denom = max(abs(a), abs(b), 1e-9)
        return abs(a - b) / denom <= tol
    return a == b


def _rows_equal(rows_a: List[Any], rows_b: List[Any]) -> bool:
    if len(rows_a) != len(rows_b):
        return False
    sorted_a = sorted(_row_to_jsonable(r) for r in rows_a) if not rows_a else None
    # Sort both by JSON string representation for stable ordering.
    json_a = [(json.dumps(_row_to_jsonable(r), sort_keys=True, default=str), r) for r in rows_a]
    json_b = [(json.dumps(_row_to_jsonable(r), sort_keys=True, default=str), r) for r in rows_b]
    json_a.sort(key=lambda t: t[0])
    json_b.sort(key=lambda t: t[0])

    for (_, ra), (_, rb) in zip(json_a, json_b):
        row_a_vals = list(ra.values()) if isinstance(ra, dict) else list(ra)
        row_b_vals = list(rb.values()) if isinstance(rb, dict) else list(rb)
        if len(row_a_vals) != len(row_b_vals):
            return False
        for va, vb in zip(row_a_vals, row_b_vals):
            if not _values_equal(va, vb):
                return False
    return True


def compute_ex(gold_rows: List[Any], predicted_rows: List[Any]) -> int:
    try:
        return 1 if _rows_equal(gold_rows, predicted_rows) else 0
    except Exception:
        return 0


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


# ── Per-case worker ───────────────────────────────────────────────────────


def run_single_case(
    case: Dict[str, Any],
    model: Optional[str],
    inject_failure: Optional[str],
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> Dict[str, Any]:
    """Execute one case end-to-end on a dedicated connection for this call.

    Intended to be run inside a ThreadPoolExecutor worker. Opens exactly
    one PostgreSQL connection for the whole case (gold + predicted query
    execution), closed via `connection_scope`'s finally block.
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
        "latency_sec": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "status": "error",
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
                ex = compute_ex(gold_rows, predicted_rows)
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

                # 5. Status.
                if em == 1 and ex == 1 and not any_wrong:
                    result["status"] = "pass"
                else:
                    result["status"] = "fail"
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


def build_summary(
    results: List[Dict[str, Any]], run_id: str, model: Optional[str]
) -> Dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail")
    errors = sum(1 for r in results if r["status"] == "error")
    timeouts = sum(1 for r in results if r["status"] == "timeout")

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
    parser.add_argument("--model", help="Model name for model mode (e.g. gpt-4o-mini). Omit for gold mode.")
    parser.add_argument("--inject", help="Failure-injection mode passed to runner.py (gold mode only)")
    parser.add_argument("--max-workers", type=int, default=10, help="ThreadPoolExecutor worker count")
    parser.add_argument("--output", help="Custom output CSV path")
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

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
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
    if not pending_cases:
        print("No pending queries, all completed.")
    else:
        print(f"Running {len(pending_cases)} case(s) with max_workers={args.max_workers} (model={args.model or 'gold'})")

        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = {
                executor.submit(run_single_case, case, args.model, args.inject): case
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

    # Write outputs.
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.output:
        csv_path = Path(args.output)
    else:
        csv_path = RESULTS_DIR / f"eval_run_{run_id}.csv"

    per_query_path = RESULTS_DIR / f"eval_run_{run_id}.per_query.json"
    summary_path = RESULTS_DIR / f"eval_run_{run_id}.summary.json"
    latest_csv_path = RESULTS_DIR / "eval_run.csv"

    write_csv(all_results, csv_path)
    write_per_query_json(all_results, per_query_path)
    summary = build_summary(all_results, run_id, args.model)
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    shutil.copyfile(csv_path, latest_csv_path)

    # Markdown report (4th output file).
    wall_time_sec = time.perf_counter() - _wall_start
    report_path = RESULTS_DIR / f"eval_run_{run_id}.report.md"
    report_generator.generate_report(
        summary,
        all_results,
        report_path,
        wall_time_sec=wall_time_sec,
        parallel_workers=args.max_workers,
    )
    shutil.copyfile(report_path, RESULTS_DIR / "eval_run.report.md")

    checkpoint_mgr.delete()

    # Human-readable summary.
    print()
    print("=" * 60)
    print(f"Run {run_id} ({summary['model']})")
    print(f"Total: {summary['total']}  Passed: {summary['passed']}  Failed: {summary['failed']}  "
          f"Errors: {summary['errors']}  Timeouts: {summary['timeouts']}")
    print(f"Pass rate: {summary['pass_rate']:.2%}  EM: {summary['metrics']['em_rate']:.2%}  "
          f"EX: {summary['metrics']['ex_rate']:.2%}")
    for diff, stats in summary["by_difficulty"].items():
        if stats["n"]:
            print(f"  {diff}: n={stats['n']} pass_rate={stats['pass_rate']:.2%}")
    print("=" * 60)
    print(f"CSV:            {csv_path}")
    print(f"Per-query JSON: {per_query_path}")
    print(f"Summary JSON:   {summary_path}")
    print(f"Report MD:      {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
