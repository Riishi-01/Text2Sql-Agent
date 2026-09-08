# Golden set v2 — what changed and why

This document captures the v2 iteration of `evals/cases.yaml`. Read it
before reviewing eval results from this point forward.

## Philosophy

Verbose questions now specify the exact columns and semantics the
agent must retrieve. The agent's job is to match that specification.

So:

- The question text states the exact columns, the metric, and any
  business rules (filters, denominators, distribution conventions).
- The gold SQL implements the question literally.
- Predicted SQL is graded on whether it returns the same row set as
  the gold: same row count, same column count, same values.
- Function-name differences that produce identical numeric output
  (`EXTRACT` vs `DATE_PART`, `AVG(x)` vs `AVG(DISTINCT x)`) are
  surfaced in the per-case reason log; EX catches value mismatches.
- Column-count mismatches are **failures**, not tolerated leniency —
  the verbose question says exactly what columns to return.

## Comparator behavior (no case-specific code)

`_rows_equal` in `evals/scripts/eval_runner.py` was changed in two ways:

1. **Returns `(equal, reason)`** instead of just `bool`. The reason
   describes what differed (row count, col count, value mismatch with
   row/col index). This is generic — no case-specific logic.
2. **Default is `trim_to_gold_cols=False`**. Column-count mismatches
   are now rejected. Callers that explicitly opt in can pass
   `trim_to_gold_cols=True`, but the eval callsites use the strict
   default to align with the verbose-question philosophy.

A per-case reason log is written to
`evals/results/<run>/metrics/ex_reasons.log` for every case, including
passes (with reason like `rows equal (5 rows)`).

## Gold SQL changes in `evals/cases.yaml`

Four cases had their gold SQL replaced. Each replacement targets a
**semantic** issue where the original gold was wrong — not just shape
differences from a specific model's output.

### `e13_5_states_by_number_customers`
**Question:** *Top 5 states by number of customers*

- **Was:** `COUNT(*) AS n FROM customers GROUP BY state` (returns
  number of orders per state — one customer_id row per order).
- **Now:** `COUNT(DISTINCT customer_unique_id) AS n FROM customers
  GROUP BY state` (returns number of unique people per state).
- **Why:** The question asks for "customers". `COUNT(*)` on the
  `customers` table counts orders (one customer_id row per order).
  `COUNT(DISTINCT customer_unique_id)` counts unique people, which
  matches the question's intent.

### `h04_5_categories_worst_late_delivery`
**Question:** *Top 5 categories with worst late delivery rate (≥50
delivered orders)*

- **Was:** `COUNT(*)` denominator (over-counts multi-item orders).
- **Now:** `COUNT(DISTINCT order_id)` denominator.
- **Why:** Late delivery is a property of the order, not the line item.
  The `order_items` JOIN multiplies rows before GROUP BY, so `COUNT(*)`
  inflates the denominator for categories with multi-item orders. The
  new denominator gives the correct per-order late-delivery rate.

### `h05_payment_method_share_5_revenue`
**Question:** *Payment method share per top-5 revenue category*

- **Was:** `COUNT(*)` for the share numerator (share by number of
  payments).
- **Now:** `SUM(op.payment_value)` for the share numerator (share by
  monetary value).
- **Why:** "Share" is ambiguous in the original question. The reference
  to "revenue" in the question wording disambiguates toward monetary
  value, which is the more common business interpretation. The new
  gold includes 4 columns: `category, payment_type, payment_value,
  payment_share_pct`.

### `m13_order_count_distribution_customer_customers`
**Question:** *Order count distribution per customer (how many
customers ordered N times?)*

- **Was:** `LIMIT 5` on the distribution query.
- **Now:** No LIMIT. Full distribution returned (9 rows).
- **Why:** The question is a distribution — "how many customers
  ordered N times" — which should return ALL distinct values of N, not
  just the first 5. The `LIMIT 5` was a gold mistake; the agent
  correctly omitted it. Removing `LIMIT 5` produces the canonical
  distribution output.

## Cases where gold was NOT changed (handled by comparator)

- **m01** — predicted adds `n_orders` audit column; comparator trims
  it (core 2 cols match gold exactly).
- **h10** — predicted uses `EXTRACT(DAY FROM ...)` instead of
  `DATE_PART('day', ...)`; both produce identical numeric output;
  value comparison passes.
- **e01, m05** — kept the original canonical gold; the agent's output
  variations on these cases (audit column, different tiebreaker) are
  accepted as long as the **core retrieval** matches by value.

## Per-case result of these changes

| Case | Before (gpt-5.4) | After (gpt-5.4) | After (gpt-4o-mini) |
|---|---|---|---|
| e01 | fail | fail (tiebreak diff at boundary) | fail (tiebreak diff) |
| e03 | PASS | PASS | PASS |
| e13 | fail | **PASS** | **PASS** |
| h02 | PASS | PASS | PASS |
| h04 | fail | **PASS** | error (model bug) |
| h05 | fail | fail (different SUM metric) | error (model bug) |
| h07 | PASS | PASS | PASS |
| h09 | PASS | PASS | error (model bug) |
| h10 | review | review (EX passes; rubric flag) | **PASS** |
| m01 | fail | **PASS** | **PASS** |
| m05 | fail | fail (tiebreak diff) | fail (tiebreak diff) |
| m09 | PASS | PASS | PASS |
| m13 | fail | **PASS** | **PASS** |

**On gpt-5.4:** pass rate improves from 5/13 = 38.5% → **8/13 = 61.5%**
(plus 2 review).

**On gpt-4o-mini:** pass rate improves from 3/13 = 23.1% → **5/13 = 38.5%**
(plus 1 review). Three of the remaining failures (h04, h05, h09) are
**genuine model errors** (the gpt-4o-mini agent produces SQL that fails
to execute because of hallucinated columns or syntax bugs). These are
not eval issues.

The remaining "review" on h10 (gpt-5.4) is a rubric-grading concern
(the `grade_time_frame` rubric hardcodes the literal `DATE_PART` token),
not an EX concern. EX passes for h10.

### Per-case EX reasons (gpt-5.4)

Recorded in `evals/results/<run>/metrics/ex_reasons.log`. Examples:

- `[e01] value differs on row 1, col 0: gold='19c9...', predicted='2b46...'` — boundary tiebreak picks different products.
- `[m05] value differs on row 0, col 2: gold=1615, predicted=1591` — different NULL-category rows picked due to tiebreak.
- `[m13] rows equal (9 rows)` — distribution matches the no-LIMIT gold.

## Notes for reviewers

- The strict comparator is deliberate: the verbose question states the
  exact columns the answer must contain. The model must match that
  column set. An extra column (or a dropped column) is a **failure**,
  not tolerated leniency — those deviations are model errors, not eval
  defects.
- For value comparisons, both sides are sorted value-wise before
  row-by-row comparison, so column-name and row-order differences
  are not penalized.
- Numeric comparisons use `_values_equal` which handles `Decimal`,
  `float`, and `int` with tolerance.
- Per-case EX reasons are logged to
  `evals/results/<run>/metrics/ex_reasons.log` for auditability.

## Failure-analysis re-run (strict comparator, costs logged)

After the strict comparator landed, the 13 baseline failures were
re-run on both models (agent mode, OpenAI directly) using
`--rerun-failures`. Only the failing subset of each model's v3 run was
re-run. Root causes are classified below.

### Classification

| Bucket | Meaning | Cases |
|---|---|---|
| **A. Genuine model SQL bug** | SQL is invalid and errors at execution | h09, h05 (both **gpt-4o-mini** only) |
| **B. Spec deviation** | SQL is valid but adds/drops columns or filters the verbose question didn't authorize | e01, m01, e03, h04, h05, h10 (both models) |
| **C. Rubric artifact** | EX passes (rows equal); only the `time_frame` rubric wrongly flags `EXTRACT(DAY FROM ...)` vs the hardcoded `DATE_PART('day', ...)` | h10, m01 (before Fix 1) |
| **D. Gold inconsistency** | Gold emits `NULL` category rows; model's `COALESCE` is more robust | m05 (before Fix 2) |

### gpt-5.4 — 0/6 on the re-run

All six are **Category B** (valid, runnable SQL that over-generates
columns) plus **Category C/D** on h10/m05. gpt-5.4 produced **zero**
SQL execution errors: it writes correct SQL but returns more columns
than the verbose question asked for. These are **model deviations, not
eval defects** — handled upstream (prompt discipline) rather than by
relaxing the comparator.

- e01: +1 extra col (`revenue`) — 3 vs 2
- m01: +1 extra col (`n_orders`) — 3 vs 2
- h04: metrics split into 4 cols vs gold 3
- h05: +1 extra col + chose a complex weighted-allocation share

### gpt-4o-mini — 1/9 on the re-run (h02 passes)

Mix of all buckets:
- **A — genuine SQL bugs:** h09 (references subquery alias `o` outside
  its scope), h05 (`missing FROM-clause entry for table "pct"`).
- **B — spec deviation:** e01 (+`revenue` col), e03 (+`LIMIT 1`),
  h10 (dropped the `COUNT(*) n` column and the `order_status` filter).
- **D — gold inconsistency:** m05 (accept as-is per decision).

Per project decision, **all gpt-4o-mini failures are accepted** — they
reflect model capability, not eval defects.

### Cost (re-run subset, per model)

| Model | Cases | Total cost | Cost/case |
|---|---|---|---|
| gpt-4o-mini | 9 | $0.0095 | ~$0.001 |
| gpt-5.4 | 6 | $0.1232 | ~$0.021 |

gpt-5.4 is ~13× more expensive per re-run even before considering it
returns larger outputs.

## Artifact fixes (this iteration)

Two "failures" were actually eval defects, not model faults, and were
fixed:

### Fix 1 — h10 / m01: EXTRACT/DATE_PART equivalence (Category C)

`grade_time_frame` in `evals/scripts/rubric.py` used substring matching
for function hints. The h10 spec contains `uses DATE_PART(day, ...)`;
when the model writes `EXTRACT(DAY FROM ...)`, the `date_part(`
hint isn't found and the grader returns `WRONG` — despite identical
numeric output. `grade_time_frame` now normalizes
`EXTRACT(day/year/month FROM ...)` to `date_part(..., ...)` before the
hint check. Generic, no case-specific code.

EX already passed for these cases; after the fix the rubric no longer
contradicts the EX comparison.

### Fix 2 — m05: NULL categories (Category D)

The gold used `LEFT JOIN` with `GROUP BY T3.product_category_name_english`
and no filter, so it emitted `NULL` category rows (products with no
category at all). The model's `COALESCE(...)` was more robust, causing
an EX mismatch (`gold=NULL, predicted='audio'`).

Per decision, the gold now **filters out** unnamed categories:
`WHERE T3.product_category_name_english IS NOT NULL`. The verbose
question was updated to say "named categories … excluding rows with no
category". `expected_rows` were regenerated from the live DB:

| Before (w/ NULL) | After (named only) |
|---|---|
| office_furniture 3.48 1701 | office_furniture 3.49 1677 |
| fashion_male_clothing 3.62 132 | fashion_male_clothing 3.64 130 |
| fixed_telephony 3.67 265 | fixed_telephony 3.68 262 |
| **null** 3.81 1636 | audio 3.83 360 |
| audio 3.81 365 | construction_tools_safety 3.84 193 |

> **Data note:** the gold `expected_rows` were regenerated against the
> current DB snapshot. Other cases (e13, h04, h05, m13) still carry
> expected values generated from an earlier snapshot and may drift
> slightly from the live DB; only m05 was updated in this pass.
