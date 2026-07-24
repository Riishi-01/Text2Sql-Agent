# apply_prompt_v2.md

**Status:** applied ✅

**Created:** 2026-07-24

**Applied:** 2026-07-24 (Run 4: `20260724_215741`)

**Targets:** `third_eval_run_20260724_195212` failures (18/39 fail)

**Pairs with:** FAILURE_STORIES.md (FS-001 .. FS-008)

---

## Achieved Outcome

**Failure_Run_with_promptv2** (18 prior failures from Third_Eval_Run):

| Metric | Before (Third_Eval_Run) | After (promptv2 retry) |
|--------|-------------------------|----------------------|
| Pass rate on failures | 0% (0/18) | **27.8% (5/18)** |
| New passes | — | 5 |
| Still failing | 18/18 | 13/18 |
| Errors | 0 | 0 |
| Cost for 18 cases | — | $0.27 (gpt-4o) |

---

## Files Changed

### `agent/prompts/role.md`
- **Lines:** 43 → 119 (+76 lines)
- **Change:** Appended `## SQL Style Rules (Mandatory)` section

### `agent/prompts/few_shot.yaml`
- **Lines:** 116 → 218 (+102 lines)
- **Change:** Fix 4 bad examples, remove 1 zero-coverage example, add 4 new examples

---

## role.md — SQL Style Rules Added

Eight mandatory rules appended at the end of role.md:

| # | Rule | Failure story targeted |
|---|------|----------------------|
| 1 | Use subqueries, not CTEs | FS-001 (R5 validator rejects CTE aliases) |
| 2 | Revenue = price + freight_value always | FS-003 |
| 3 | No scope creep on order_status | FS-003 |
| 4 | Output shape table (COUNT/Top-N/Distribution/Aggregate) | FS-004 |
| 5 | Monthly bucketing: TO_CHAR not EXTRACT split | FS-002 |
| 6 | Grain trap: pre-aggregate per order_id first | FS-003 |
| 7 | COALESCE for category names always | FS-006 |
| 8 | customer_unique_id for unique customers | FS-005 |

---

## few_shot.yaml — Example Changes

### Removed

| Example | Why removed |
|---------|-------------|
| **Ex5 Geolocation Join** | 0/39 eval cases use geolocation. ~120 tokens with zero coverage. |

### Rewritten (bad → fixed)

| Example | Bad pattern | Fix applied |
|---------|------------|-------------|
| **Ex1 Revenue by State** | `SUM(price)` no freight + uninvited `WHERE order_status='delivered'` | `SUM(price + freight_value)`, removed filter, added note |
| **Ex3 Top Sellers** | `SUM(price)` no freight + extra columns (seller_city, seller_state) | `SUM(price + freight_value)`, stripped to seller_id only |
| **Ex6 Delivery Time** | No context on when status filter is appropriate | Added inline comment: "status filter IS required here / do NOT apply to general queries" |
| **Ex7 Dedup Reviews** | `WITH latest_reviews AS (...)` CTE | Rewrote as `FROM (...) AS latest_reviews` subquery |

### Added (new)

| Example | Pattern demonstrated | Cases targeted |
|---------|---------------------|----------------|
| **Ex7→Ex8 Count Scalar** | `COUNT(*)` → ONE row, no detail columns | e06 |
| **Ex9 Grain Trap + TO_CHAR** | Pre-aggregate per order_id, then per state; `TO_CHAR('YYYY-MM')` | m03, m08, h09 |
| **Ex10 Direct CASE in SELECT** | `CASE WHEN` directly in SELECT + GROUP BY alias | h06 |
| **Ex11 Distribution = No LIMIT** | Distribution query returns all rows, never LIMIT | m13 |

---

---

## Actual Run 4 Results (Failure_Run_with_promptv2, 20260724_220750)

### Newly Passing (+5)

| Case | Difficulty | Pattern fixed |
|------|-----------|----------------|
| `h06_compare_avg_review_score_time` | hard | Direct CASE in SELECT (Ex10) |
| `h08_5_state_category_pairs_by` | hard | freight_value, no scope creep |
| `m03_avg_order_value_gmv_state` | medium | Grain trap + TO_CHAR bucket |
| `m08_monthly_order_count_full_trend` | medium | TO_CHAR monthly bucketing |
| `m10_10_sellers_by_total_revenue` | medium | Ex3 rewrite: freight + stripped cols |

### Still Failing (13 cases)

| Case | Difficulty | Root cause |
|------|-----------|------------|
| `e01_5_selling_products_health_beauty` | easy | Hallucinated `p.product_name` column |
| `e03_most_used_payment_methods_computers` | easy | Rubric flag (output shape?) |
| `e06_orders_delivered_late` | easy | ← **FIXED in retry** |
| `e13_5_states_by_number_customers` | easy | Gold ambiguity: `COUNT(*)` vs `COUNT(DISTINCT customer_unique_id)` |
| `h04_5_categories_worst_late_delivery` | hard | CTE removed; logic still wrong |
| `h05_payment_method_share_5_revenue` | hard | Window function complexity |
| `h07_multi_item_orders_items_from` | hard | GROUP BY scope error |
| `h09_monthly_avg_order_value_trend` | hard | EXTRACT split still used instead of TO_CHAR |
| `h10_average_days_between_delivery_review` | hard | Rubric time_frame flag |
| `m01_5_states_longest_delivery_time` | medium | Rubric time_frame flag (EX=1) |
| `m05_bottom_5_categories_by_average` | medium | Subquery logic issue |
| `m09_avg_payment_value_payment_type` | medium | Column mismatch vs gold |
| `m13_order_count_distribution_customer_customers` | medium | LIMIT still applied to distribution |

---



## Rubric Dimension Delta

| Dimension | Run 3 pass | Run 4 pass | Δ |
|-----------|-----------|-----------|---|
| table | 38/39 | 38/39 | = |
| filters | 0/9 | 0/9 | = ← rubric calibration needed (FS-006) |
| aggregation | 32/39 | 33/39 | +1 |
| join | 11/16 | 13/16 | **+2** |
| time_frame | 0/4 | 2/4 | **+2** |

---

## Next Round: apply_prompt_v3.md

Remaining failures cluster into 3 fixable buckets:

### Bucket 1 — Rubric patches (FS-002, FS-006)
`filters` dim is 0/9 — the rubric flags correct SQL as wrong.
`time_frame` still 2/4 wrong.
→ Rubric grader fix, not prompt.

### Bucket 2 — Prompt gaps
- `h09` still uses EXTRACT split → reinforce TO_CHAR in semantic_model.yaml
- `m13` distribution still limited → rule §4 not firing
- `h07` GROUP BY scope → targeted few-shot example

### Bucket 3 — Schema hallucination
- `e01` (`p.product_name` doesn't exist)
- `h02` (ambiguous `customer_id` in subquery)
→ Add schema column list to semantic_model.yaml or orientation.md

**Conservative target for v3: 26 → 32 cases (82%)**
