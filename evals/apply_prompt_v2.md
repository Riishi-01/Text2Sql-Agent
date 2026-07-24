# apply_prompt_v2.md

**Status:** applied ✅

**Created:** 2026-07-24

**Applied:** 2026-07-24 (Run 4: `20260724_215741`)

**Targets:** `third_eval_run_20260724_195212` failures (18/39 fail)

**Pairs with:** FAILURE_STORIES.md (FS-001 .. FS-008)

---

## Expected After Apply

| Metric | Before (Run 3) | After (Run 4) |
|--------|---------------|---------------|
| Pass rate | 53.8% (21/39) | **66.7% (26/39)** |
| Easy | 75.0% (12/16) | 81.3% (13/16) |
| Medium | 38.5% (5/13) | 69.2% (9/13) |
| Hard | 0% (0/10) | **40.0% (4/10)** |
| Total cost (gpt-4o-mini) | $0.419 (gpt-4o) | **$0.034** |

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

## Actual Run 4 Results (20260724_215741)

### Newly Passing (+6 gross, −1 regression = +5 net)

| Case | Difficulty | Root cause fixed |
|------|-----------|-----------------|
| `e06_orders_delivered_late` | easy | COUNT scalar shape (Ex8) |
| `h06_compare_avg_review_score_time` | hard | Direct CASE in SELECT (Ex10) |
| `h08_5_state_category_pairs_by` | hard | freight + no scope creep (Rule §2+§3) |
| `m03_avg_order_value_gmv_state` | medium | Grain trap (Ex9) + no filter (Rule §3) |
| `m08_monthly_order_count_full_trend` | medium | TO_CHAR bucket (Ex9) |
| `m10_10_sellers_by_total_revenue` | medium | Ex3 rewrite: freight + stripped cols |

### Regression (−1)

| Case | Cause |
|------|-------|
| `h02_overall_repeat_customer_rate_customers` | Column ambiguity error — unrelated hallucination |

### Still Failing (13 cases)

| Case | Difficulty | Status | Root cause |
|------|-----------|--------|-----------|
| `e01_5_selling_products_health_beauty` | easy | error | Hallucinated `p.product_name` column |
| `e03_most_used_payment_methods_computers` | easy | fail | Rubric flag (FS-006) — ex=1 |
| `e13_5_states_by_number_customers` | easy | fail | Gold ambiguity: gold uses `COUNT(*)`, agent uses `COUNT(DISTINCT customer_unique_id)` |
| `h02_overall_repeat_customer_rate_customers` | hard | error | Ambiguous `customer_id` column in subquery |
| `h04_5_categories_worst_late_delivery` | hard | fail | CTE removed; SQL logic still produces wrong results |
| `h05_payment_method_share_5_revenue` | hard | fail | Complex window fn; no CTE but results differ |
| `h07_multi_item_orders_items_from` | hard | error | GROUP BY scope: `total_orders.total_count` not in GROUP BY |
| `h09_monthly_avg_order_value_trend` | hard | fail | Still uses EXTRACT split; TO_CHAR rule not adopted |
| `h10_average_days_between_delivery_review` | hard | fail | Rubric time_frame flag — SQL executes correctly |
| `m01_5_states_longest_delivery_time` | medium | fail | Rubric time_frame flag — ex=1, SQL correct |
| `m05_bottom_5_categories_by_average` | medium | fail | Subquery logic issue |
| `m09_avg_payment_value_payment_type` | medium | fail | Extra/missing columns vs gold |
| `m13_order_count_distribution_customer_customers` | medium | fail | LIMIT still applied to distribution |

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
