# Text2SQL Evals Suite

A structured evaluation harness for the Olist NL2SQL agent, built from the
39-case golden set. This directory is the source of truth for eval cases,
execution scripts, and results.

## Directory Structure

```
evals/
├── scripts/
│   ├── convert_csv_to_yaml.py   # One-time: golden_set CSV → cases/*/case.yaml
│   ├── validate_cases.py        # Validates every case.yaml + runner.py
│   ├── eval_runner.py           # Main parallel runner (gold + model modes)
│   ├── checkpoint_manager.py    # Resumable-run checkpoint lifecycle
│   ├── db_loader.py             # PostgreSQL connection helper
│   └── rubric.py                # sqlglot-based rubric grading
│
├── golden_set/
│   └── Text2SQL Agent Eval Golden set.csv   # Original source data (39 rows)
│
├── cases/                       # 39 case directories, one per golden-set row
│   ├── e01_5_selling_products_health_beauty/
│   │   ├── case.yaml
│   │   └── runner.py
│   ├── m01_5_states_longest_delivery_time/
│   │   ├── case.yaml
│   │   └── runner.py
│   ├── h01_average_total_spend_unique_customer/
│   │   ├── case.yaml
│   │   └── runner.py
│   └── ... (39 total: e=16 easy, m=13 medium, h=10 hard)
│
├── results/                     # Created at runtime by eval_runner.py
│   ├── eval_run.csv              # Latest run copy (backward compat)
│   ├── eval_run.report.md        # Latest report copy (backward compat)
│   ├── eval_run.summary.json     # Latest summary copy (backward compat)
│   ├── checkpoints/
│   │   └── eval_run_{ts}.checkpoint.jsonl
│   └── summary/                  # One directory per run
│       └── {run_id}/
│           ├── metrics/
│           │   ├── eval_run.csv        # 19-col per-query CSV
│           │   ├── per_query.json      # Same data as JSON list
│           │   ├── summary.json        # Aggregate metrics
│           │   └── report.md           # Human-readable Markdown report
│           ├── passes/
│           │   └── passes.json         # Array of all passed cases
│           └── failures/
│               └── failures.json       # Array of all failed/errored cases
│
└── README.md                    # This file
```

## Case Naming Convention

Case IDs follow `{difficulty_prefix}{counter:02d}_{question_slug}`:

- `e01`–`e16` — easy (16 cases)
- `m01`–`m13` — medium (13 cases)
- `h01`–`h10` — hard (10 cases)

The counter is assigned in CSV row order within each difficulty tier; the
slug is derived from the question text (stopwords stripped, first 5 words).

## case.yaml Format

```yaml
id: e01_5_selling_products_health_beauty
source_query_id: 1                # original Query_id from the CSV
difficulty: easy                  # easy | medium | hard
discourse: ranking+filter         # from the CSV `label` column
tables: [category_translation, order_items, products]   # extracted from gold_sql
trap: null                        # reserved, not populated from CSV
tags: [ranking, filter]           # discourse split on '+'
question: "top 5 selling products in health beauty, category"
gold_sql: |
  SELECT i.product_id, COUNT(*) AS n_sold
  FROM order_items i
  JOIN products p ON i.product_id = p.product_id
  ...
expected:
  shape: {rows: 5, cols: 2}
  expected_rows: [[...], ...]
  scalar: 96096                   # only present when result is a single row/col
acceptable_variants:
  - "(see gold_sql)"
business_meaning: "..."           # from CSV Description, falls back to question
rubric:
  table:       {required: true,  spec: "...", items: [...]}
  time_frame:  {required: false}                     # NA — empty in golden set
  filters:     {required: true,  spec: "...", items: [...]}
  aggregation: {required: true,  spec: "...", items: [...]}
  join:        {required: true,  spec: "...", items: [...]}
  date_operator: {required: false}                   # reserved, not in CSV
```

**Rubric semantics:** a dimension with `required: false` means the golden
set had no value in that column — treat it as **N/A, do not grade it**. A
dimension with `required: true` carries the original free-text `spec` plus
a best-effort split into `items` (on `;` if present, else `,`).

## runner.py Interface

```python
def run(question: str, db_path: str, case: dict) -> str:
    """Return the SQL to execute for this case."""
```

- `inject_failure` absent or `"no_failure"` → returns `case["gold_sql"]` verbatim (gold mode).
- Any other value → the runner is expected to return a deliberately broken
  variant of the SQL, used to test the eval harness's failure detection.
  The generated templates currently implement only `no_failure`; add
  additional `if failure_mode == "...":` branches per case as needed.

## Running the Scripts

```bash
# Re-generate cases/ from the golden set CSV (destructive — overwrites cases/)
python3 evals/scripts/convert_csv_to_yaml.py

# Validate every case.yaml + runner.py
python3 evals/scripts/validate_cases.py

# Run the full eval suite (gold mode, default)
python3 evals/scripts/eval_runner.py

# Single case / filter by difficulty
python3 evals/scripts/eval_runner.py --case m07_10_cities_by_number_unique
python3 evals/scripts/eval_runner.py --difficulty hard

# Model mode (calls OpenAI instead of using gold_sql)
python3 evals/scripts/eval_runner.py --model gpt-4o-mini

# Resume an interrupted run
python3 evals/scripts/eval_runner.py --resume

# Limit thread pool size / custom output path
python3 evals/scripts/eval_runner.py --max-workers 4
python3 evals/scripts/eval_runner.py --output results/my_run.csv
```

## Checkpointing

`eval_runner.py` writes one JSON line per completed case to
`results/checkpoints/eval_run_{ts}.checkpoint.jsonl` as it goes. If the run
is interrupted (crash, Ctrl-C, timeout), re-running with `--resume` loads
the latest checkpoint, skips already-completed `query_id`s, and only
executes the remaining cases. On successful completion the checkpoint is
converted into the final CSV/JSON outputs and removed.

Each run produces a directory at `results/summary/{run_id}/` with three subdirs:

**`metrics/`** — aggregate and full data

| File | Contents |
|------|----------|
| `eval_run.csv` | 19-column per-query results (query_id, question, em, ex, latency_sec, tokens, cost, status, rubric dims, difficulty, gold_sql, predicted_sql, error, ground_truth_rows) |
| `per_query.json` | Same data as the CSV, as a JSON list of dicts |
| `summary.json` | Aggregate metrics: pass rate, EM/EX rates, by-difficulty breakdown, by-dimension rubric fail rates, failure list |
| `report.md` | Human-readable Markdown report with scorecard, rubric health table (worst-first), and per-failure SQL diffs |

**`passes/`**

| File | Contents |
|------|----------|
| `passes.json` | Array of concise docs for every case with `status == "pass"` — includes query_id, question, difficulty, em, ex, rubric verdicts, gold_sql, predicted_sql |

**`failures/`**

| File | Contents |
|------|----------|
| `failures.json` | Array of concise docs for every case with `status != "pass"` — same fields as passes.json plus error message |

**Root-level latest copies** (`results/eval_run.*`) are updated after every run for backward compatibility.

## Database

Cases execute against the project's PostgreSQL database (see
`core/config.py` for connection settings — same `nl2sql_ro` role used by
the production agent). `db_loader.py` opens one connection per worker
thread; connections are never shared across threads.
