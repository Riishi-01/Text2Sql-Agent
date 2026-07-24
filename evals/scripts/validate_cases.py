#!/usr/bin/env python3
"""Validate the single cases.yaml file.

Checks:
1. cases.yaml parses with yaml.safe_load
2. Has 'cases' key with list of case dicts
3. Each case has required fields
4. All gold_sql values parse with sqlglot
5. Rubric dimensions are valid

Exits with status 1 if any case fails.
"""
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

try:
    import sqlglot
except ImportError:
    sqlglot = None

SCRIPTS_DIR = Path(__file__).resolve().parent
EVALS_DIR = SCRIPTS_DIR.parent
CASES_YAML_PATH = EVALS_DIR / "cases.yaml"

REQUIRED_CASE_FIELDS = [
    "id", "difficulty", "tables", "question", "gold_sql",
    "expected", "rubric",
]

REQUIRED_RUBRIC_DIMS = [
    "table", "time_frame", "filters", "aggregation", "join", "date_operator",
]

VALID_DIFFICULTIES = {"easy", "medium", "hard"}


def validate_rubric(rubric: Dict[str, Any]) -> List[str]:
    errors = []
    if not isinstance(rubric, dict):
        return ["rubric is not a mapping"]

    for dim in REQUIRED_RUBRIC_DIMS:
        if dim not in rubric:
            errors.append(f"rubric missing dimension '{dim}'")
            continue
        block = rubric[dim]
        if not isinstance(block, dict) or "required" not in block:
            errors.append(f"rubric.{dim} missing 'required' key")
            continue
        if block["required"] is True:
            if "spec" not in block or not block["spec"]:
                errors.append(f"rubric.{dim} required=true but no 'spec'")
            if "items" not in block or not isinstance(block["items"], list):
                errors.append(f"rubric.{dim} required=true but no 'items' list")
        elif block["required"] is False:
            pass  # NA, nothing else needed
        else:
            errors.append(f"rubric.{dim}.required is not a bool")

    return errors


def validate_gold_sql(gold_sql: str) -> List[str]:
    errors = []
    if not gold_sql or not gold_sql.strip():
        errors.append("gold_sql is empty")
        return errors

    if sqlglot is None:
        errors.append("sqlglot not installed — skipped SQL parse check")
        return errors

    try:
        parsed = sqlglot.parse(gold_sql, dialect="postgres")
        if not parsed or not any(parsed):
            errors.append("gold_sql: sqlglot parse returned empty result")
    except Exception as e:
        errors.append(f"gold_sql: sqlglot parse failed: {e}")

    return errors


def validate_cases_yaml() -> int:
    if not CASES_YAML_PATH.exists():
        print(f"Cases file not found: {CASES_YAML_PATH}")
        return 1

    with open(CASES_YAML_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        print("cases.yaml did not parse into a mapping")
        return 1

    if "cases" not in data:
        print("cases.yaml missing 'cases' key")
        return 1

    cases = data["cases"]
    if not isinstance(cases, list):
        print("'cases' is not a list")
        return 1

    total = len(cases)
    passed = 0
    failures: Dict[str, List[str]] = {}

    for case in cases:
        case_id = case.get("id", "unknown")
        errors = []

        for field in REQUIRED_CASE_FIELDS:
            if field not in case:
                errors.append(f"missing required field '{field}'")

        if case.get("difficulty") not in VALID_DIFFICULTIES:
            errors.append(f"invalid difficulty '{case.get('difficulty')}'")

        if "gold_sql" in case:
            errors.extend(validate_gold_sql(case["gold_sql"]))

        if "rubric" in case:
            errors.extend(validate_rubric(case["rubric"]))

        if errors:
            failures[case_id] = errors
            print(f"  FAIL  {case_id}")
            for err in errors:
                print(f"          - {err}")
        else:
            passed += 1
            print(f"  PASS  {case_id}")

    print()
    print(f"{passed}/{total} cases valid")

    if failures:
        print(f"\n{len(failures)} case(s) failed validation:")
        for case_id, errs in failures.items():
            print(f"  {case_id}: {len(errs)} error(s)")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(validate_cases_yaml())
