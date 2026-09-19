# Failure analysis — gpt-5.4 full-39 single run (2026-09-19)

- **Date:** 2026-09-19
- **Run ID:** `v2_gpt5_4_20260919_144406`
- **Model:** agent(gpt-5.4)
- **Prompt bank:** `agent/prompts/fewshotexample_v2.yaml` (active, no golden-set mirrors)
- **Cases:** 39 / 39 (full golden set)
- **Workers:** 10 (ThreadPoolExecutor)
- **Result:** 32 pass / 7 review / 5 fail / 2 errors / 1 false positive
- **Pass rate:** 82.05% | **EX rate:** 84.62% | **Rubric clean:** 89.74%
- **Cost:** $0.70 total ($0.018/case) | **Wall time:** ~14s

> **Auditability note:** This run used the decontaminated prompt bank
> `fewshotexample_v2.yaml` — none of the 15 few-shot examples mirror
> any golden-set question. The 32/39 pass rate is achieved without
> in-context teaching artifacts. Legacy v1 failure analysis retained
> as [`gpt54_full39_v1_run.md`](gpt54_full39_v1_run.md) for historical
> reference only.

## Summary of the 7 failures

| Pattern | Cases | Root cause |
|---|---|---|
| **Ambiguous phrasing** (defaulted to row list not COUNT) | e06 | "Orders delivered late" → 1000 rows instead of `COUNT(*)` |
| **Over-generation** (added unrequested breakdown cols) | h04 | Decomposed rate into `late_orders` + `delivered_orders` |
| **False positive** (right rows, missing intent filter) | h06 | No `order_status='delivered'` filter; coincidental row match |
| **Execution error** (raw date subtraction) | h10, m01 | `ROUND(interval, integer)` — no `DATE_PART` wrapper |
| **Tiebreak drift** | m05 | Different secondary ORDER BY at LIMIT boundary |
| **Missing audit column** | m09 | Dropped `COUNT(*) AS n` |

The h10/m01 execution errors and h06 false positive are new patterns
introduced by removing v1's Ex 5 (DATE_PART example) and Ex 13 (audit
col example) — both were decontaminated as part of the v2 rewrite.

## Per-failure detail

### ❌ `e06_orders_delivered_late` *(easy)*

**Question:** Orders delivered late

**EX:** ✗  **Rubric:** table=correct, filters=flag, aggregation=**wrong**, join=NA
**EX reason:** `[e06] row count differs: gold=1, predicted=1000`

**Gold SQL:**
```sql
SELECT COUNT(*)
FROM orders
WHERE order_status = 'delivered'
  AND order_delivered_customer_date IS NOT NULL
  AND order_estimated_delivery_date IS NOT NULL
  AND order_delivered_customer_date > order_estimated_delivery_date
```

**Generated SQL:**
```sql
SELECT
    o.order_id,
    o.order_delivered_customer_date,
    o.order_estimated_delivery_date
FROM orders o
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date > o.order_estimated_delivery_date
LIMIT 1000;
```

**Briefing:** Ambiguous phrasing. The noun-only question "Orders
delivered late" without a "how many" / "count" trigger defaults to a
row list in v2; v1's Ex 12 explicitly taught the noun-only → COUNT(*)
default. Fix: re-include a no-trigger-word count example in v2's bank.

---

### ❌ `h04_5_categories_worst_late_delivery` *(hard)*

**Question:** Top 5 product categories with the worst late-delivery rate,
where the rate is the percentage of delivered orders (with non-null
delivery date and estimated delivery date) that were delivered after the
estimated date, computed as (count of late orders) divided by (count of
delivered orders) per category, and only categories with at least 50
delivered orders are eligible

**EX:** ✗  **Rubric:** table=correct, filters=flag, aggregation=flag, join=correct
**EX reason:** `[h04] col count differs on row 0: gold=3, predicted=4 (extras on predicted)`

**Gold SQL:**
```sql
SELECT COALESCE(t.product_category_name_english, p.product_category_name) AS category,
       ROUND(SUM(CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN 1 ELSE 0 END) * 100.0 / COUNT(DISTINCT o.order_id), 2) AS late_delivery_rate_pct,
       COUNT(DISTINCT o.order_id) AS n_delivered_orders
FROM orders o
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
LEFT JOIN product_category_translation t ON p.product_category_name = t.product_category_name
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
  AND o.order_estimated_delivery_date IS NOT NULL
GROUP BY COALESCE(t.product_category_name_english, p.product_category_name)
HAVING COUNT(DISTINCT o.order_id) >= 50
ORDER BY late_delivery_rate_pct DESC, n_delivered_orders DESC
LIMIT 5
```

**Generated SQL:**
```sql
SELECT
    COALESCE(pct.product_category_name_english, p.product_category_name) AS category,
    ROUND(
        100.0 * COUNT(DISTINCT CASE
            WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN o.order_id
        END) / COUNT(DISTINCT o.order_id),
        2
    ) AS late_delivery_rate,
    COUNT(DISTINCT CASE
        WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN o.order_id
    END) AS late_orders,
    COUNT(DISTINCT o.order_id) AS delivered_orders
FROM orders o
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
LEFT JOIN product_category_translation pct
    ON p.product_category_name = pct.product_category_name
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
  AND o.order_estimated_delivery_date IS NOT NULL
GROUP BY COALESCE(pct.product_category_name_english, p.product_category_name)
HAVING COUNT(DISTINCT o.order_id) >= 50
ORDER BY late_delivery_rate DESC, delivered_orders DESC
LIMIT 5;
```

**Briefing:** Over-generation. Gold returns
`(category, late_delivery_rate_pct, n_delivered_orders)` — the rate
plus the count the percentage is over. Model decomposed the calculation
into `late_orders` and `delivered_orders` as separate columns. Both
SQLs compute the rate correctly but the predicted SQL exposes the
intermediate state. Fix: explicit guidance that percentage questions
return `(category, rate_pct, n_orders)` not the breakdown.

---

### ❌ `h06_compare_avg_review_score_time` *(hard)* — **false positive**

**Question:** Compare avg review score: on-time vs late deliveries

**EX:** ✗  **Rubric:** table=correct, filters=**wrong**, aggregation=correct, join=correct
**EX reason:** `[h06] rows equal (2 rows)` — rows match gold, but rubric correctly flagged wrong filter

**Gold SQL:**
```sql
SELECT
  CASE WHEN order_delivered_customer_date <= order_estimated_delivery_date THEN 'on_time' ELSE 'late' END AS delivery_status,
  ROUND(AVG(review_score), 3) AS avg_score,
  COUNT(*) AS n
FROM order_reviews r
JOIN orders o ON r.order_id = o.order_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
  AND o.order_estimated_delivery_date IS NOT NULL
GROUP BY delivery_status
```

**Generated SQL:**
```sql
SELECT
    CASE
        WHEN o.order_delivered_customer_date <= o.order_estimated_delivery_date THEN 'on_time'
        ELSE 'late'
    END AS delivery_status,
    ROUND(AVG(r.review_score), 3) AS avg_review_score,
    COUNT(*) AS n
FROM orders o
JOIN order_reviews r ON o.order_id = r.order_id
WHERE o.order_delivered_customer_date IS NOT NULL
  AND o.order_estimated_delivery_date IS NOT NULL
GROUP BY delivery_status;
```

**Briefing:** False positive (right rows, wrong reason). Predicted SQL
omits the `WHERE o.order_status = 'delivered'` filter. In the current
dataset, non-delivered orders have NULL delivery dates, so the
`IS NOT NULL` checks happen to exclude them — producing identical
rows. But if data changed (e.g., a non-delivered order with a set
delivery date), the predicted SQL would silently include it. The
strict rubric correctly rejects this as wrong-by-reason even though
rows match. Fix: prompt rule "delivery comparisons require
`order_status='delivered'` in WHERE".

---

### ❌ `h10_average_days_between_delivery_review` *(hard)* — **execution error**

**Question:** Average days between delivery and review creation

**EX:** ✗  **Rubric:** table=correct, time_frame=**wrong**, filters=**wrong**, aggregation=correct, join=correct
**EX reason:** `Query execution failed: function round(interval, integer) does not exist`

**Gold SQL:**
```sql
SELECT ROUND(AVG(DATE_PART('day', r.review_creation_date - o.order_delivered_customer_date))::numeric, 2) AS avg_review_lag_days,
       COUNT(*) AS n
FROM order_reviews r
JOIN orders o ON r.order_id = o.order_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
  AND r.review_creation_date IS NOT NULL
```

**Generated SQL:**
```sql
SELECT
    ROUND(AVG(r.review_creation_date - o.order_delivered_customer_date), 2) AS avg_days_between_delivery_and_review
FROM orders o
JOIN order_reviews r ON o.order_id = r.order_id
WHERE o.order_delivered_customer_date IS NOT NULL
  AND r.review_creation_date IS NOT NULL;
```

**Briefing:** Execution error. PostgreSQL's `ROUND(interval, integer)`
doesn't exist — the model wrote `ROUND(AVG(date_diff), 2)` directly
where `date_diff` evaluates to an `interval`. Gold wraps it in
`DATE_PART('day', ...)::numeric` first to coerce to numeric. v1's Ex 5
used `DATE_PART`; v2 dropped that example. Fix: re-include a
DATE_PART day-diff example in v2's bank.

---

### ❌ `m01_5_states_longest_delivery_time` *(medium)* — **execution error**

**Question:** Top 5 states with longest delivery time

**EX:** ✗  **Rubric:** table=correct, time_frame=**wrong**, filters=**wrong**, aggregation=correct, join=correct
**EX reason:** `Query execution failed: function round(interval, integer) does not exist`

**Gold SQL:**
```sql
SELECT c.customer_state,
       ROUND(AVG(DATE_PART('day', o.order_delivered_customer_date - o.order_purchase_timestamp))::numeric, 2) AS avg_days
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
GROUP BY c.customer_state
ORDER BY avg_days DESC
LIMIT 5
```

**Generated SQL:**
```sql
SELECT
    c.customer_state,
    ROUND(AVG(o.order_delivered_customer_date - o.order_purchase_timestamp), 2) AS avg_delivery_days
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_delivered_customer_date IS NOT NULL
GROUP BY c.customer_state
ORDER BY avg_delivery_days DESC
LIMIT 5;
```

**Briefing:** Same root cause as h10 — `ROUND(interval, integer)`
doesn't exist. Gold wraps the date diff in `DATE_PART('day', ...)::numeric`.
Fix: same as h10.

---

### ❌ `m05_bottom_5_categories_by_average` *(medium)*

**Question:** Bottom 5 named product categories (with an English translation)
by average review score, considering only categories with at least 100
reviews and excluding rows with no category

**EX:** ✗  **Rubric:** table=correct, aggregation=correct, join=flag
**EX reason:** `[m05] value differs on row 1, col 0: gold='construction_tools_safety', predicted='fashion_male_clothing'`

**Gold SQL:**
```sql
SELECT T3.product_category_name_english AS category,
       ROUND(AVG(T1.review_score), 2) AS avg_score,
       COUNT(*) AS n_reviews
FROM order_reviews T1
JOIN orders T2 ON T1.order_id = T2.order_id
JOIN order_items T4 ON T2.order_id = T4.order_id
JOIN products T5 ON T4.product_id = T5.product_id
LEFT JOIN product_category_translation T3 ON T5.product_category_name = T3.product_category_name
WHERE T3.product_category_name_english IS NOT NULL
GROUP BY T3.product_category_name_english
HAVING COUNT(*) >= 100
ORDER BY avg_score ASC, T3.product_category_name_english
LIMIT 5
```

**Generated SQL:**
```sql
SELECT
    pct.product_category_name_english AS category,
    ROUND(AVG(r.review_score), 3) AS avg_review_score,
    COUNT(*) AS review_count
FROM order_reviews r
JOIN orders o ON r.order_id = o.order_id
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
LEFT JOIN product_category_translation pct
    ON p.product_category_name = pct.product_category_name
WHERE p.product_category_name IS NOT NULL
  AND pct.product_category_name_english IS NOT NULL
GROUP BY pct.product_category_name_english
HAVING COUNT(*) >= 100
ORDER BY avg_review_score ASC, review_count DESC
LIMIT 5;
```

**Briefing:** Tiebreak drift. Gold uses secondary `ORDER BY
T3.product_category_name_english` (alphabetical); predicted uses
secondary `ORDER BY n_reviews DESC` (alias name `review_count`).
At the LIMIT 5 boundary, several categories share the same
`avg_score`; the two orderings pick different rows. Fix: prompt rule
"secondary ORDER BY on category name for deterministic tiebreaks".

---

### ❌ `m09_avg_payment_value_payment_type` *(medium)*

**Question:** Avg payment value per payment type

**EX:** ✗  **Rubric:** table=correct, aggregation=flag, filters=NA, join=NA
**EX reason:** `[m09] col count differs on row 0: gold=3, predicted=2 (extras on gold)`

**Gold SQL:**
```sql
SELECT payment_type, ROUND(AVG(payment_value), 2) AS avg_value, COUNT(*) AS n
FROM order_payments
GROUP BY payment_type
ORDER BY avg_value DESC
```

**Generated SQL:**
```sql
SELECT
    op.payment_type,
    ROUND(AVG(op.payment_value), 2) AS avg_payment_value
FROM order_payments op
GROUP BY op.payment_type
ORDER BY avg_payment_value DESC;
```

**Briefing:** Missing audit column. Gold returns
`(payment_type, avg_value, n)`; model dropped `COUNT(*) AS n`. v1's
Ex 13 taught the model to include this audit column for per-dimension
aggregations. v2 rewrote that example to total-only, losing the signal.
Fix: re-include an "(aggregation_metric, n)" audit-column example.

---

## Reproduction

```bash
python3 evals/scripts/eval_runner.py \
  --agent --agent-model gpt-5.4 --max-workers 10 \
  --name v2_gpt5_4_repro
```

Run artifacts land in `evals/results/summary/v2_gpt5_4_repro_<ts>/`.
The 7 failures above should reproduce (modulo temperature-driven variation).

## v1 vs v2 failure divergence

| Case | v1 outcome | v2 outcome | Why |
|---|---|---|---|
| e01 | FAIL (over-gen) | **PASS** | v2 Ex 15 ANTI-OVER-GENERATION example |
| e06 | **PASS** | FAIL | v1 Ex 12 default-to-COUNT (dropped in v2) |
| h03 | FAIL (over-gen) | **PASS** | DISTINCT pattern clarity in v2 |
| h04 | FAIL (over-gen) | FAIL (over-gen) | Same family, different shape |
| h06 | **PASS** | FAIL (FP) | v1 had implicit filter guidance |
| h10 | FAIL (wrong time_frame) | **ERROR** | v1 Ex 5 DATE_PART (dropped in v2) |
| m01 | FAIL (over-gen) | **ERROR** | Same as h10 |
| m03 | FAIL (over-gen) | **PASS** | Subquery pre-agg pattern |
| m05 | FAIL (tiebreak) | FAIL (tiebreak) | Same pattern |
| m09 | **PASS** | FAIL (missing audit col) | v1 Ex 13 audit-col (dropped in v2) |

Net: 8 cases swapped, same total pass count. v2's failures are
different from v1's — the decontamination shifted which patterns
over-generate, but didn't change the pass-rate number.
