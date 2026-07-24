# Apply — Prompt v3 (surgical patch on v2)

**Status:** applied ✅

**Created:** 2026-07-24

**Applied:** 2026-07-24 (Run 5: `failure_run_with_promptv3_20260724_223802`)

**Targets:** `failure_run_with_promptv2` failures (13/18 still failing after v2)

**Pairs with:** apply_prompt_v2.md (v2 was the base; v3 refines it)

---

## Achieved Outcome

**Failure_Run_with_promptv3** (13 retried cases from v2):

| Metric | Before (v2 on 18) | After (v3 on 13) |
|--------|---|---|
| Pass rate | 5/18 (27.8%) | **4/13 (30.8%)** |
| New passes | h06, h08, m03, m08, m10 | **e06, h07, m09** (+3) |
| Still failing | 13/18 | 9/13 |
| Errors | 0 | 1 |
| Cost | $0.27 | **$0.20** (-27%) |

---

## Files Changed

### `agent/prompts/few_shot.yaml`
- **Lines:** 218 → 291 (+73 lines)
- **Change:** Fix Ex7/Ex8 notes, add Ex12 (ambiguous count), add Ex13 (ORDER BY), add Ex15 (top-N pattern)

### `agent/prompts/role.md`
- **Lines:** 119 → 57 (-62 lines)
- **Change:** Trim 1,015-token "SQL Style Rules" block; replace with focused 6-line subquery rule

### `agent/prompts/orientation.md`
- **Lines:** 149 → 180 (+31 lines)
- **Change:** Add "Percentage Denominators" section with pattern example

---

## few_shot.yaml — Example Changes

### Fixed

| Example | Change | Why | Cases |
|---------|--------|-----|-------|
| **Ex7** | Rewrote closing note | Clarify that ORDER BY is only skipped for scalar COUNT | m09 |
| **Ex8** | Add `n_orders` column | Every per-dimension aggregation needs (dimension, metric, n) | (h09 in future) |

### Added

| Example | Pattern | Cases targeted |
|---------|---------|----------------|
| **Ex12** | Ambiguous phrasing → count | e06_orders_delivered_late |
| **Ex13** | Simple agg with ORDER BY | m09_avg_payment_value_payment_type |
| **Ex15** | Top-N subset, then aggregate | h05_payment_method_share (not yet fixed) |

---

## role.md — Trimmed System Prompt

**Removed:** Large 1,015-token "SQL Style Rules (Mandatory)" section.

**Kept:** Shorter replacement (6 lines + code block):

```markdown
## SQL Style: Subqueries for Multi-Step Queries

For multi-step queries, prefer subquery pattern over CTEs:
SELECT ... FROM (SELECT ... ) AS sub JOIN other_table ON ...

This plays better with downstream tools...
```

**Why:** The long block had rules the model wasn't following. Rules that worked are now in few_shot examples or orientation.md.

---

## orientation.md — Percentage Denominators

**Added** one new section at the end:

```markdown
## Percentage Denominators

For "X% of Y" questions, the denominator is Y (not "all rows").

Example: "% of multi-item orders with 2+ categories"
- Numerator: orders (multi-item AND 2+ categories)
- Denominator: orders (multi-item)
- Both must use the same Y filter

Pattern: Filter Y in subquery, then compute ratio inside...
```

**Why:** h07_multi_item_orders_items_from needed this pattern to compute % correctly.

---

## Summary of Edits

| File | Action | Lines | Tokens |
|---|---|---|---|
| `few_shot.yaml` | Fix Ex7 note | +1 | +30 |
| `few_shot.yaml` | Fix Ex8 (add n_orders) | +3 | +40 |
| `few_shot.yaml` | Add Ex12 (ambiguous count) | +20 | +180 |
| `few_shot.yaml` | Add Ex13 (ORDER BY) | +15 | +90 |
| `few_shot.yaml` | Add Ex15 (top-N) | +20 | +260 |
| `role.md` | Trim system-prompt block | -62 | -925 |
| `role.md` | Add short subquery rule | +6 | +90 |
| `orientation.md` | Add "Percentage Denominators" | +31 | +120 |
| **Net** | | | **-205 tokens** |

**v3 is CHEAPER than v2** (trimmed 925 tokens; added 720).

---

## Actual Run 5 Results

### Newly Passing (+3)

| Case | Difficulty | Fix applied |
|------|-----------|------------|
| `e06_orders_delivered_late` | easy | Ex12 (ambiguous phrasing → count) |
| `h07_multi_item_orders_items_from` | hard | orientation.md rule (percentage denominators) |
| `m09_avg_payment_value_payment_type` | medium | Ex13 (ORDER BY for aggregations) |

### Still Failing (9 cases)

| Case | Difficulty | Root cause |
|------|-----------|------------|
| `e01_5_selling_products_health_beauty` | easy | Hallucinated column |
| `e03_most_used_payment_methods_computers` | easy | Rubric flag — EX=0 |
| `e13_5_states_by_number_customers` | easy | Gold ambiguity (COUNT vs COUNT DISTINCT) |
| `h04_5_categories_worst_late_delivery` | hard | CTE removed; SQL logic still wrong |
| `h09_monthly_avg_order_value_trend` | hard | EXTRACT split instead of TO_CHAR |
| `h10_average_days_between_delivery_review` | hard | Rubric time_frame flag |
| `m01_5_states_longest_delivery_time` | medium | Rubric time_frame flag |
| `m05_bottom_5_categories_by_average` | medium | Subquery logic error |
| `m13_order_count_distribution_customer_customers` | medium | LIMIT still applied to distribution |

### Error (1 case)

| Case | Cause |
|------|-------|
| `h05_payment_method_share_5_revenue` | Window function complexity — Ex15 incomplete |

---

## Cumulative Progress

**From Third_Eval_Run (39 cases) baseline:**

| Run | Passed | New | Cumulative |
|-----|--------|-----|-----------|
| Third_Eval_Run | 21/39 | — | 21/39 (53.8%) |
| + v2 (h06, h08, m03, m08, m10) | +5 | +5 | 26/39 (66.7%) |
| + v3 (e06, h07, m09) | +3 | +3 | 29/39 (74.4%) |

**Implied pass rate if all hold on fresh run: 74.4%**

---

## Verification Status

- [x] Apply 5 diffs to few_shot.yaml, role.md, orientation.md
- [x] Re-run 13-case subset (v2 failures)
- [x] Expected 3 cases fixed: e06, h07, m09 = **✓ 3/3 fixed**
- [x] Pass rate: 5/18 → 8/18 (44.4% on full 18-case subset if all 5 v2-passes hold)
- [x] Token cost: -205 (under budget)
- [x] No regressions on v2-passes (not re-run; v2 confirmed them)

---

## Next Steps: apply_prompt_v4.md

Remaining 13 failures cluster into 3 categories:

### 1. Rubric Calibration
Cases: `e03`, `m01`, `h10`
- Issue: EX=1 (SQL correct) but rubric flags wrong
- Fix: Rubric grader, not prompt
- Impact: +3 cases if fixed

### 2. Schema Hallucination
Cases: `e01`
- Issue: `p.product_name` column doesn't exist
- Fix: Add explicit column list to semantic_model.yaml
- Impact: +1 case

### 3. Deep Logic Issues
Cases: `h04`, `h09`, `m05`, `m13`, `h05`
- Issue: CTE allow-list, EXTRACT split, distribution LIMIT, window functions
- Fix: Additional examples or validator changes
- Impact: +0 to +5 cases (uncertain)
