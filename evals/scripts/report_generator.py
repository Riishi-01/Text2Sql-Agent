#!/usr/bin/env python3
"""Report generator for the Text2SQL eval suite.

Generates eval_run_{ts}.report.md — a human-readable Markdown report —
as the 4th output file per eval run.

Public interface
----------------
    generate_report(summary, per_query, path, *, wall_time_sec, parallel_workers)

Design constraints
------------------
- Pure renderer: consumes summary dict + per_query list already built by
  eval_runner.py.  Does NOT recompute any scoring metric.
- No third-party dependencies — plain f-strings and str.join only.
- Output is valid UTF-8 Markdown with no trailing whitespace per line.
- Handles edge cases: empty failures list, missing optional fields,
  dimensions with zero graded rows, None wall_time / workers.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

RUBRIC_DIMS = ["table", "time_frame", "filters", "aggregation", "join"]

# ── Helpers ───────────────────────────────────────────────────────────────


def _pct(numerator: float, denominator: float, default: str = "—") -> str:
    """Format a safe percentage string."""
    if not denominator:
        return default
    return f"{100.0 * numerator / denominator:.1f}%"


def _usd(value: float) -> str:
    return f"${value:.4f}"


def _strip_trailing(text: str) -> str:
    """Remove trailing whitespace from every line; ensure trailing newline."""
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines) + "\n"


def _build_per_query_index(per_query: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Return query_id → row dict for O(1) lookup during failure rendering."""
    return {row["query_id"]: row for row in per_query}


# ── Section renderers ─────────────────────────────────────────────────────


def _section_header(
    summary: Dict[str, Any],
    wall_time_sec: Optional[float],
    parallel_workers: Optional[int],
) -> str:
    run_id = summary.get("run_id", "unknown")
    model = summary.get("model", "unknown")
    total = summary.get("total", 0)
    cost = summary.get("metrics", {}).get("total_cost_usd", 0.0)

    wall_str = f"{wall_time_sec:.2f} s" if wall_time_sec is not None else "N/A"
    workers_str = str(parallel_workers) if parallel_workers is not None else "N/A"

    lines = [
        f"# Eval Report — Run {run_id}",
        "",
        f"| Field            | Value          |",
        f"|------------------|----------------|",
        f"| Model            | {model}        |",
        f"| Total queries    | {total}        |",
        f"| Wall time        | {wall_str}     |",
        f"| Parallel workers | {workers_str}  |",
        f"| Total cost       | {_usd(cost)}   |",
        "",
    ]
    return "\n".join(lines)


def _section_topline(summary: Dict[str, Any]) -> str:
    m = summary.get("metrics", {})
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    review = summary.get("review", 0)
    errors = summary.get("errors", 0)
    timeouts = summary.get("timeouts", 0)

    em_rate = m.get("em_rate", 0.0)
    ex_rate = m.get("ex_rate", 0.0)
    rubric_clean = m.get("rubric_clean_rate", 0.0)
    fp_rate = m.get("false_positive_rate", 0.0)
    fp_count = round(fp_rate * total)

    lines = [
        "## Top-Line Metrics",
        "",
        f"- **EM rate:** {em_rate:.2%}",
        f"- **EX rate:** {ex_rate:.2%}",
        f"- **Rubric-clean rate:** {rubric_clean:.2%}  "
        f"*(cases with no wrong rubric dimension)*",
        f"- **False positive rate:** {fp_rate:.2%}  "
        f"*(EX pass but rubric wrong — {fp_count} of {total})*",
        f"- **Review:** {review}  *(EX pass with a rubric flag — needs a human look)*",
        f"- **Pass / Review / Fail / Error / Timeout:** "
        f"{passed} / {review} / {failed} / {errors} / {timeouts}",
        "",
    ]
    return "\n".join(lines)


def _section_rubric_table(summary: Dict[str, Any]) -> str:
    total = summary.get("total", 0)
    by_dim = summary.get("by_dim_fail_rate", {})

    # Build rows with sort key = (wrong% + flag%) descending.
    rows = []
    for dim in RUBRIC_DIMS:
        d = by_dim.get(dim, {"graded": 0, "pass": 0, "flag": 0, "wrong": 0})
        graded = d.get("graded", 0)
        correct = d.get("pass", 0)
        flag = d.get("flag", 0)
        wrong = d.get("wrong", 0)
        na_count = total - graded

        correct_pct = 100.0 * correct / graded if graded else 0.0
        wrong_pct = 100.0 * wrong / graded if graded else 0.0
        flag_pct = 100.0 * flag / graded if graded else 0.0
        na_pct = 100.0 * na_count / total if total else 0.0

        sort_key = wrong_pct + flag_pct
        rows.append((sort_key, dim, graded, correct_pct, wrong_pct, flag_pct, na_pct))

    rows.sort(key=lambda r: r[0], reverse=True)

    header = [
        "## Rubric Dimension Health",
        "",
        "> Sorted by (wrong + flag)% descending — worst dimension first.",
        "",
        "| Dimension   | Graded | ✅ Correct% | ❌ Wrong% | ⚠️ Flag% | — NA%  |",
        "|-------------|-------:|------------:|----------:|---------:|-------:|",
    ]

    table_rows = []
    for _, dim, graded, correct_pct, wrong_pct, flag_pct, na_pct in rows:
        table_rows.append(
            f"| {dim:<11} | {graded:>6} | {correct_pct:>10.1f}% "
            f"| {wrong_pct:>8.1f}% | {flag_pct:>7.1f}% | {na_pct:>5.1f}% |"
        )

    return "\n".join(header + table_rows + [""])


def _section_difficulty(
    summary: Dict[str, Any],
    per_query: List[Dict[str, Any]],
) -> str:
    by_diff = summary.get("by_difficulty", {})

    # Compute avg cost + avg latency from per_query grouped by difficulty.
    cost_by_diff: Dict[str, List[float]] = {}
    lat_by_diff: Dict[str, List[float]] = {}
    for row in per_query:
        d = row.get("difficulty", "")
        cost_by_diff.setdefault(d, []).append(float(row.get("cost_usd", 0.0)))
        lat_by_diff.setdefault(d, []).append(float(row.get("latency_sec", 0.0)))

    header = [
        "## By-Difficulty Breakdown",
        "",
        "| Difficulty | N  | EX Pass% | Avg Cost (USD) | Avg Latency (s) |",
        "|------------|---:|---------:|---------------:|----------------:|",
    ]

    table_rows = []
    for diff in ("easy", "medium", "hard"):
        stats = by_diff.get(diff, {})
        n = stats.get("n", 0)
        if n == 0:
            continue
        ex = stats.get("ex", 0.0)
        costs = cost_by_diff.get(diff, [])
        lats = lat_by_diff.get(diff, [])
        avg_cost = sum(costs) / len(costs) if costs else 0.0
        avg_lat = sum(lats) / len(lats) if lats else 0.0
        table_rows.append(
            f"| {diff:<10} | {n:>2} | {ex:>8.2%} | {_usd(avg_cost):>14} | {avg_lat:>15.3f} |"
        )

    return "\n".join(header + table_rows + [""])


def _render_single_failure(
    failure: Dict[str, Any],
    pq_index: Dict[str, Dict[str, Any]],
) -> str:
    query_id = failure.get("query_id", "unknown")
    difficulty = failure.get("difficulty") or "?"
    em = failure.get("em", False)
    ex = failure.get("ex", False)
    error = (failure.get("error") or "").strip()
    wrong_dims = failure.get("rubric_wrong_dims") or []

    # Emoji: ⚠️ if rubric-only failure (em+ex pass), ❌ otherwise
    prefix = "⚠️" if (em and ex and wrong_dims) else "❌"

    # Pull full SQLs from per_query index; fall back to excerpt from failures[].
    pq = pq_index.get(query_id, {})
    question = pq.get("question", failure.get("question", ""))
    gold_sql = pq.get("gold_sql", "").strip()
    predicted_sql = pq.get("predicted_sql", "").strip()
    if not predicted_sql:
        predicted_sql = (failure.get("predicted_sql_excerpt") or "").strip()

    # All 6 rubric dims inline
    rubric_inline_dims = RUBRIC_DIMS + ["date_operator"]
    rubric_parts = []
    for dim in rubric_inline_dims:
        verdict = pq.get(dim, failure.get(dim, "NA"))
        rubric_parts.append(f"`{dim}`={verdict}")
    rubric_line = ", ".join(rubric_parts)

    em_str = "✓" if em else "✗"
    ex_str = "✓" if ex else "✗"

    parts = [
        f"### {prefix} `{query_id}` *({difficulty})*",
        "",
    ]

    if question:
        parts += [f"**Question:** {question}", ""]

    parts += [
        f"**EM:** {em_str}  **EX:** {ex_str}  **Rubric:** {rubric_line}",
        "",
    ]

    if error:
        parts += [
            "**Error:**",
            "```",
            error,
            "```",
            "",
        ]

    if gold_sql:
        parts += [
            "**Gold SQL:**",
            "```sql",
            gold_sql,
            "```",
            "",
        ]

    if predicted_sql:
        parts += [
            "**Predicted SQL:**",
            "```sql",
            predicted_sql,
            "```",
            "",
        ]

    return "\n".join(parts)


def _section_failures(
    summary: Dict[str, Any],
    per_query: List[Dict[str, Any]],
) -> str:
    failures = summary.get("failures")
    if failures is None:
        failures = []
    pq_index = _build_per_query_index(per_query)

    header = ["## Failures", ""]

    if not failures:
        return "\n".join(header + ["*No failures in this run — all cases passed.*", ""])

    rendered = []
    for f in failures:
        rendered.append(_render_single_failure(f, pq_index))

    return "\n".join(header) + "\n" + "\n".join(rendered)


# ── Public entry point ────────────────────────────────────────────────────


def _render(
    summary: Dict[str, Any],
    per_query: List[Dict[str, Any]],
    wall_time_sec: Optional[float],
    parallel_workers: Optional[int],
) -> str:
    """Render the full report as a string. Pure function — no I/O."""
    sections = [
        _section_header(summary, wall_time_sec, parallel_workers),
        _section_topline(summary),
        _section_rubric_table(summary),
        _section_difficulty(summary, per_query),
        _section_failures(summary, per_query),
    ]
    raw = "\n".join(sections)
    return _strip_trailing(raw)


def generate_report(
    summary: Dict[str, Any],
    per_query: List[Dict[str, Any]],
    path: Path,
    *,
    wall_time_sec: Optional[float] = None,
    parallel_workers: Optional[int] = None,
) -> None:
    """Write the Markdown eval report to *path*.

    Args:
        summary: The dict returned by eval_runner.build_summary().
        per_query: The list of per-case result dicts (all_results from the runner).
        path: Destination file path (.report.md).
        wall_time_sec: Total elapsed wall time for the run (optional).
        parallel_workers: ThreadPoolExecutor worker count (optional).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _render(summary, per_query, wall_time_sec, parallel_workers)
    path.write_text(content, encoding="utf-8")


# ── CLI smoke-check ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 3:
        print("Usage: python3 report_generator.py <summary.json> <per_query.json> [out.md]")
        sys.exit(1)

    summary_path = Path(sys.argv[1])
    pq_path = Path(sys.argv[2])
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("report_check.md")

    summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
    pq_data = json.loads(pq_path.read_text(encoding="utf-8"))

    generate_report(summary_data, pq_data, out_path)
    print(f"Report written → {out_path}")
