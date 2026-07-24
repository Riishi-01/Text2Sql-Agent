#!/usr/bin/env python3
"""Convert the golden set CSV into cases_v3-style YAML case directories.

Reads:
    evals/golden_set/Text2SQL Agent Eval Golden set.csv

Writes:
    evals/cases/{id}/case.yaml
    evals/cases/{id}/runner.py

Each CSV row becomes one case directory. The case id is built from the
difficulty (e=easy, m=medium, h=hard) plus a running counter within that
difficulty, plus a short slug derived from the question text, e.g.:

    e01_top_selling_health_beauty
    m01_top_states_delivery_time
    h01_avg_ltv_per_customer

Rubric columns in the CSV (Rubric_table, Rubric_time_frame, Rubric_filters,
Rubric_aggregation, Rubric_join) are free-text. Empty cells are mapped to
required: false (NA) in the YAML; non-empty cells are preserved verbatim as
a descriptive string plus a `required: true` flag, since the CSV does not
encode fully structured rubric specs (unlike the cases_v3 spec's
expected_columns/expected_filters lists). This keeps the conversion
lossless while still being machine-checkable for "was this graded or not".
"""
import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "golden_set" / "Text2SQL Agent Eval Golden set.csv"
CASES_DIR = REPO_ROOT / "cases"

DIFFICULTY_PREFIX = {
    "easy": "e",
    "medium": "m",
    "hard": "h",
}

STOPWORDS = {
    "the", "a", "an", "of", "for", "in", "on", "at", "to", "with", "and",
    "or", "is", "are", "what", "how", "many", "list", "top", "per",
}


def slugify(question: str, max_words: int = 5) -> str:
    """Build a short, filesystem-safe slug from a question string."""
    text = question.strip().lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    words = [w for w in text.split() if w]
    # Keep meaningful words, drop stopwords, but always keep at least 2 words
    filtered = [w for w in words if w not in STOPWORDS]
    chosen = filtered if len(filtered) >= 2 else words
    slug_words = chosen[:max_words]
    slug = "_".join(slug_words)
    return slug or "case"


def parse_ground_truth(raw: str) -> Dict[str, Any]:
    """Parse the Ground Truth column into an `expected` dict.

    Two shapes appear in the CSV:
      - JSON array of arrays: [[val1, val2], ...]
      - JSON object: {"columns": [...], "rows": [[...], ...]}
    """
    raw = (raw or "").strip()
    if not raw:
        return {"expected_rows": None}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"expected_rows_raw": raw}

    if isinstance(parsed, dict) and "rows" in parsed:
        rows = parsed["rows"]
        cols = parsed.get("columns", [])
        shape = {"rows": len(rows), "cols": len(cols) if cols else (len(rows[0]) if rows else 0)}
        result: Dict[str, Any] = {"shape": shape, "expected_rows": rows}
        if cols:
            result["columns"] = cols
        # Scalar shortcut: single row, single column
        if len(rows) == 1 and len(rows[0]) == 1:
            result["scalar"] = rows[0][0]
        return result

    if isinstance(parsed, list):
        shape = {"rows": len(parsed), "cols": len(parsed[0]) if parsed else 0}
        result = {"shape": shape, "expected_rows": parsed}
        if len(parsed) == 1 and len(parsed[0]) == 1:
            result["scalar"] = parsed[0][0]
        return result

    return {"expected_rows_raw": raw}


def parse_rubric_field(raw: str) -> Dict[str, Any]:
    """Map a free-text rubric cell to a structured-but-honest YAML block.

    Empty -> {"required": False}  (NA, not graded)
    Non-empty -> {"required": True, "spec": <original text>, "items": [...]}
    `items` is a best-effort split on ';' or ',' at the top level, kept for
    convenience; `spec` preserves the raw string as the source of truth.
    """
    raw = (raw or "").strip()
    if not raw:
        return {"required": False}

    # Split on ';' first (used for multi-join specs), else ','.
    if ";" in raw:
        items = [p.strip() for p in raw.split(";") if p.strip()]
    else:
        items = [p.strip() for p in raw.split(",") if p.strip()]

    return {"required": True, "spec": raw, "items": items}


def build_rubric(row: Dict[str, str]) -> Dict[str, Any]:
    return {
        "table": parse_rubric_field(row.get("Rubric_table", "")),
        "time_frame": parse_rubric_field(row.get("Rubric_time_frame", "")),
        "filters": parse_rubric_field(row.get("Rubric_filters", "")),
        "aggregation": parse_rubric_field(row.get("Rubric_aggregation", "")),
        "join": parse_rubric_field(row.get("Rubric_join", "")),
        # Reserved dimension, not present in the CSV; always NA for now.
        "date_operator": {"required": False},
    }


def extract_tables(sql: str) -> List[str]:
    """Best-effort table name extraction via regex (FROM/JOIN clauses)."""
    tables = set()
    for match in re.finditer(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, re.IGNORECASE):
        tables.add(match.group(1).lower())
    return sorted(tables)


def literal_multiline(text: str) -> "LiteralStr":
    return LiteralStr(text)


class LiteralStr(str):
    """Marker class so the YAML dumper renders this string with `|` block style."""


def literal_str_representer(dumper: yaml.Dumper, data: LiteralStr):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="|")


yaml.add_representer(LiteralStr, literal_str_representer)


def build_case_dict(row: Dict[str, str], case_id: str) -> Dict[str, Any]:
    difficulty = (row.get("Difficulty") or "").strip().lower()
    question = (row.get("Query") or "").strip()
    gold_sql = (row.get("Expected Sql Query") or "").strip()
    description = (row.get("Description") or "").strip()
    label = (row.get("label") or "").strip()

    expected = parse_ground_truth(row.get("Ground Truth", ""))
    rubric = build_rubric(row)
    tables = extract_tables(gold_sql)

    case: Dict[str, Any] = {
        "id": case_id,
        "source_query_id": int(row["Query_id"]) if row.get("Query_id", "").strip().isdigit() else row.get("Query_id"),
        "difficulty": difficulty,
        "discourse": label or None,
        "tables": tables,
        "trap": None,
        "tags": [t.strip() for t in label.split("+")] if label else [],
        "question": question,
        "gold_sql": literal_multiline(gold_sql + "\n") if gold_sql else "",
        "expected": expected,
        "acceptable_variants": ["(see gold_sql)"],
        "business_meaning": description or question,
        "rubric": rubric,
    }
    return case


CASE_YAML_KEY_ORDER = [
    "id", "source_query_id", "difficulty", "discourse", "tables", "trap",
    "tags", "question", "gold_sql", "expected", "acceptable_variants",
    "business_meaning", "rubric",
]


def ordered_dump(case: Dict[str, Any]) -> str:
    ordered = {k: case[k] for k in CASE_YAML_KEY_ORDER if k in case}
    return yaml.dump(
        ordered,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=100,
    )


RUNNER_TEMPLATE = '''"""Runner for {case_id}.

def run(question, db_path, case) -> str
    Returns the SQL to execute for this case. In gold mode (default,
    inject_failure == "no_failure") this simply returns the case's own
    gold_sql. Failure-injection modes return deliberately broken SQL so the
    eval harness can be tested against known-bad predictions.
"""
from typing import Dict


def run(question: str, db_path: str, case: Dict) -> str:
    failure_mode = case.get("inject_failure", "no_failure")

    if failure_mode == "no_failure":
        return case["gold_sql"].strip()

    raise ValueError(f"Unknown failure_mode: {{failure_mode}}")
'''


def slugify_case_id(row: Dict[str, str], counters: Dict[str, int]) -> str:
    difficulty = (row.get("Difficulty") or "").strip().lower()
    prefix = DIFFICULTY_PREFIX.get(difficulty)
    if prefix is None:
        raise ValueError(f"Unknown difficulty '{difficulty}' for Query_id={row.get('Query_id')}")

    counters[prefix] = counters.get(prefix, 0) + 1
    num = counters[prefix]
    slug = slugify(row.get("Query", ""))
    return f"{prefix}{num:02d}_{slug}"


def main() -> None:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Golden set CSV not found at {CSV_PATH}")

    CASES_DIR.mkdir(parents=True, exist_ok=True)

    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    counters: Dict[str, int] = {}
    created = []

    for row in rows:
        case_id = slugify_case_id(row, counters)
        case_dir = CASES_DIR / case_id
        case_dir.mkdir(parents=True, exist_ok=True)

        case_dict = build_case_dict(row, case_id)
        yaml_text = ordered_dump(case_dict)
        (case_dir / "case.yaml").write_text(yaml_text, encoding="utf-8")

        runner_text = RUNNER_TEMPLATE.format(case_id=case_id)
        (case_dir / "runner.py").write_text(runner_text, encoding="utf-8")

        created.append(case_id)

    print(f"Created {len(created)} cases in {CASES_DIR}")
    for prefix in ("e", "m", "h"):
        count = sum(1 for c in created if c.startswith(prefix))
        print(f"  {prefix}: {count}")


if __name__ == "__main__":
    main()
