# Failure stories — golden-set v1 iteration (strict eval)

> Builds on the prompt-engineering work in [`v3.md`](v3.md). Same 13
> baseline-failing cases, but this iteration changes the **eval**: a strict
> comparator and verbose questions, rather than touching prompts alone.
> Detailed per-case rationale lives in
> [`evals/golden_set_v2.md`](../evals/golden_set_v2.md) — this is the concise
> story write-up.

## The problem

After the prompt + gold-SQL fixes, the eval used a **lenient comparator** that
silently trimmed extra columns off the predicted result before comparing. It
could not tell a genuinely correct answer from a close-but-over-generating
one. At the same time, several questions were **ambiguous** — they admitted
multiple defensible answers (e.g. does "customers" mean order rows or unique
people? is a "share" by count or by value?). Ambiguity made it impossible to
grade fairly.

## The change — strict eval philosophy

Three things shifted together:

1. **Strict comparator** — `_rows_equal` now rejects column-count mismatches
   (`trim_to_gold_cols=False`). An extra column or a dropped column is a real
   failure, not tolerated leniency.
2. **Verbose questions** — rewritten to pin the exact metric, grain, and
   column set, so **only one interpretation is defensible**. The gold SQL then
   implements the verbose question literally.
3. **Rubric alignment + artifact fixes** — rubric dimensions
   (`table / filters / aggregation / join / time_frame`) tightened to match
   the verbose questions (e13 requires `DISTINCT`, h05 requires `SUM`), and
   two eval artifacts fixed: `EXTRACT` ↔ `DATE_PART` equivalence in the
   `time_frame` grader, and the m05 NULL-category gold.

## Key insight — the models retrieved the right core tables

On nearly every failure, the rubric graded `table = correct` and
`join = correct`. The models were reaching the right core tables and joining
them correctly — they failed on the **strict spec**: extra/dropped columns,
aggregate grain, or filters. In other words, the model got the data source
right but did not hold to the exact column contract the verbose question
demanded.

| Case | model | table | join | aggregation | filters | time_frame | EX pass |
|---|---|---|---|---|---|---|---|
| e01 | gpt-5.4 | ✅ | ⚠️ | ✅ | ✅ | – | ✗ (extra col) |
| e01 | gpt-4o-mini | ✅ | ✅ | ⚠️ | ✅ | – | ✗ (extra col) |
| h04 | gpt-5.4 | ✅ | ⚠️ | ⚠️ | ⚠️ | – | ✗ (col split) |
| h05 | gpt-5.4 | ✅ | ⚠️ | ✅ | – | – | ✗ (extra col) |
| h09 | gpt-4o-mini | ✅ | ✅ | ✅ | – | ✅ | ✗ (SQL bug) |
| h10 | gpt-5.4 | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ✅ |
| m01 | gpt-5.4 | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ✗ (extra col) |
| m05 | gpt-4o-mini | ✅ | ✅ | ✅ | – | – | ✗ (gold NULL) |

`table` and `join` are correct on essentially every case. The failures
concentrate in the **spec dimensions** — this is exactly what the strict
comparator is designed to surface.

## Worked example 1 — h05: ambiguous question → verbose rewrite

**Before (shared by both models):**
> Payment method share per top-5 revenue category

"Share" is ambiguous — by count of payments, or by monetary value? The model's
best guess is by count.

**After (verbose):**
> For each of the 5 product categories with the highest revenue, show the
> payment method, the payment value, and what percentage of the category's
> payment value each method represents; a category's revenue is the sum of
> (price + freight) of its items.

Now the only defensible answer is a **monetary-value** share.

**Gold change:** `COUNT(*)` numerator → `SUM(op.payment_value)`.
**Rubric change:** aggregation spec `COUNT,SUM` → `SUM` only.

## Worked example 2 — e01: strict eval catches an over-generated column

**Question:** *top 5 selling products in health beauty, category* (2 columns
expected: `product_id`, `n_sold`).

**Gold:**
```sql
SELECT i.product_id, COUNT(*) AS n_sold
FROM order_items i
JOIN products p ON i.product_id = p.product_id
LEFT JOIN product_category_translation t ON p.product_category_name = t.product_category_name
WHERE t.product_category_name_english = 'health_beauty'
GROUP BY i.product_id
ORDER BY n_sold DESC, i.product_id
LIMIT 5
```

**Both models returned a valid query with an extra column:**
```sql
SELECT oi.product_id, COUNT(*) AS items_sold, ROUND(SUM(oi.price + oi.freight_value), 2) AS revenue
...
```
A `revenue` column the question didn't ask for. Under the lenient comparator
this extra column was trimmed and the case could pass; under the **strict**
comparator it is a real failure. This is the comparator working as intended —
the model over-generated and the eval refuses to paper over it.

## Outcomes per model

| Model | Lenient (v2 gold fixes) | Strict (v3 verbose) | Delta | Note |
|---|---|---|---|---|
| gpt-5.4 | 8/13 (61.5%) | 7/13 (53.8%) | −1 | the lost pass over-generated a column → strict is correct |
| gpt-4o-mini | 5/13 (38.5%) | 4/13 (30.8%) | −1 | remaining failures are model SQL bugs (accepted) |

Recall the **start**: both models were **0/13 (0%)** on these cases at
git-clone baseline. Prompt hardening alone took gpt-4o-mini to 23% and gpt-5.4
to 39%; the golden-set iteration (gold fixes + strict eval) then pushed
gpt-5.4 to ~54% and gpt-4o-mini to ~31% on this hard subset.

## Accepted / documented as-is

- **gpt-4o-mini failures are accepted** — the remaining ones (h09, h05 SQL
  errors) are genuine model bugs, not eval defects.
- **gpt-5.4 extra-column deviations** are model issues to handle via future
  prompt discipline, **not** by relaxing the strict comparator.
- **DB snapshot drift** — gold `expected_rows` for e13/h04/h05/m13 were
  generated against an earlier snapshot and may drift slightly from the live
  DB; only m05 was refreshed in this pass.
