# Failure analysis — gpt-5.4 full-39 single run (2026-09-19)

> **Status: legacy / archived.** This run used the previous prompt bank
> `few_shot.yaml`, which had several examples that mirrored golden-set
> questions (the smoking-gun was Ex 12, identical SQL to Ex 7). The
> current active bank is `fewshotexample_v2.yaml`; its failure
> analysis is at [`gpt54_full39_v2_run.md`](gpt54_full39_v2_run.md).
> This file is retained for historical comparison only.

- **Date:** 2026-09-19
- **Run ID:** `v2_1_full39_gpt5_4_20260919_150256`
- **Model:** agent(gpt-5.4)
- **Prompt bank:** `agent/prompts/few_shot.yaml` (legacy — no longer loaded)
- **Cases:** 39 / 39 (full golden set)
- **Workers:** 10 (ThreadPoolExecutor)
- **Result:** 32 pass / 9 review / 7 fail / 0 errors / 0 false positives
- **Pass rate:** 82.05% | **EX rate:** 82.05% | **Rubric clean:** 100%
- **Cost:** $0.68 total ($0.017/case) | **Wall time:** ~14s

## Summary of the 7 failures

| Pattern | Cases | Root cause |
|---|---|---|
| **Over-generation** (added unrequested cols) | e01, h03, h04, m01, m03 | Model appended audit / breakdown cols not asked for |
| **Missing audit column** | h10 | Dropped `COUNT(*) AS n` even though it's standard for the pattern |
| **Tiebreak drift** | m05 | Different secondary ORDER BY picked a different row at the LIMIT boundary |

5 of 7 are over-generation — the dominant failure mode. The fix space is
prompt-side: an explicit "return ONLY the columns the question asks for"
rule, paired with a "(metric, n)" audit-column example.

## Per-failure detail

### ❌ `e01_5_selling_products_health_beauty` *(easy)*

**Question:** top 5 selling products in health beauty, category

**EX:** ✗  **Rubric:** table=correct, filters=correct, aggregation=correct, join=flag
**EX reason:** `[e01] col count differs on row 0: gold=2, predicted=3 (extras on predicted)`

**Gold SQL:**
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

**Generated SQL:**
```sql
SELECT
    oi.product_id,
    COUNT(*) AS items_sold,
    ROUND(SUM(oi.price), 2) AS revenue
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
LEFT JOIN product_category_translation pct
    ON p.product_category_name = pct.product_category_name
WHERE pct.product_category_name_english = 'health_beauty'
GROUP BY oi.product_id
ORDER BY items_sold DESC, revenue DESC
LIMIT 5;
```

**Briefing:** Over-generation. The question asks only for "top 5 selling
products" — gold returns `(product_id, n_sold)`. Model added a third
column `revenue` (price-only, no freight_value) plus a secondary `ORDER
BY revenue DESC`. Same root cause as h03, h04, m01, m03. Fix: explicit
"return ONLY the columns the question names" rule.

---

### ❌ `h03_5_sellers_by_number_distinct` *(hard)*

**Question:** Top 5 sellers by number of distinct customer states served

**EX:** ✗  **Rubric:** table=correct, aggregation=correct, join=correct
**EX reason:** `[h03] col count differs on row 0: gold=2, predicted=3 (extras on predicted)`

**Gold SQL:**
```sql
SELECT T1.seller_id, COUNT(DISTINCT T3.customer_state) AS n_states
FROM sellers T1
JOIN order_items T2 ON T1.seller_id = T2.seller_id
JOIN orders T4 ON T2.order_id = T4.order_id
JOIN customers T3 ON T4.customer_id = T3.customer_id
GROUP BY T1.seller_id
ORDER BY n_states DESC, T1.seller_id
LIMIT 5
```

**Generated SQL:**
```sql
SELECT
    oi.seller_id,
    COUNT(DISTINCT c.customer_state) AS distinct_customer_states,
    COUNT(DISTINCT o.order_id) AS n_orders
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
JOIN customers c ON o.customer_id = c.customer_id
GROUP BY oi.seller_id
ORDER BY distinct_customer_states DESC, n_orders DESC
LIMIT 5;
```

**Briefing:** Over-generation. Question asks for the state-count metric;
gold returns `(seller_id, n_states)`. Model added `n_orders` as a
third column. Same family as e01/h04/m01/m03. Fix: anti-over-generation
rule.

---

### ❌ `h04_5_categories_worst_late_delivery` *(hard)*

**Question:** Top 5 product categories with the worst late-delivery rate,
where the rate is the percentage of delivered orders (with non-null
delivery date and estimated delivery date) that were delivered after the
estimated date, computed as (count of late orders) divided by (count of
delivered orders) per category, and only categories with at least 50
delivered orders are eligible

**EX:** ✗  **Rubric:** table=correct, filters=flag, aggregation=flag, join=flag
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
    category,
    ROUND(late_orders * 100.0 / delivered_orders, 2) AS late_delivery_rate,
    late_orders,
    delivered_orders
FROM (
    SELECT
        COALESCE(t.product_category_name_english, p.product_category_name) AS category,
        COUNT(DISTINCT CASE
            WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date
                THEN o.order_id
            END) AS late_orders,
        COUNT(DISTINCT o.order_id) AS delivered_orders
    FROM orders o
    JOIN order_items oi
        ON o.order_id = oi.order_id
    JOIN products p
        ON oi.product_id = p.product_id
    LEFT JOIN product_category_translation t
        ON p.product_category_name = t.product_category_name
    WHERE o.order_status = 'delivered'
      AND o.order_delivered_customer_date IS NOT NULL
      AND o.order_estimated_delivery_date IS NOT NULL
    GROUP BY COALESCE(t.product_category_name_english, p.product_category_name)
    HAVING COUNT(DISTINCT o.order_id) >= 50
) AS sub
ORDER BY late_delivery_rate DESC, delivered_orders DESC
LIMIT 5;
```

**Briefing:** Over-generation with semantic twist. Gold returns
`(category, late_delivery_rate_pct, n_delivered_orders)` — the
question asks for rate + count, and the count of *delivered orders* is
what the percentage is over. Model decomposed the calculation into
`late_orders` and `delivered_orders` as separate columns. Both SQLs
compute the rate correctly but the predicted SQL exposes the
intermediate state. Fix: explicit guidance that percentage questions
return `(category, rate_pct, n_orders)` not the breakdown.

---

### ❌ `h10_average_days_between_delivery_review` *(hard)*

**Question:** Average days between delivery and review creation

**EX:** ✗  **Rubric:** table=correct, time_frame=correct, filters=flag, aggregation=correct, join=correct
**EX reason:** `[h10] col count differs on row 0: gold=2, predicted=1 (extras on gold)`

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
    ROUND(AVG(EXTRACT(DAY FROM r.review_creation_date - o.order_delivered_customer_date)), 2) AS avg_days_between_delivery_and_review
FROM orders o
JOIN order_reviews r ON o.order_id = r.order_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
  AND r.review_creation_date IS NOT NULL;
```

**Briefing:** Missing audit column. Gold returns `(avg_review_lag_days, n)`;
model dropped `COUNT(*) AS n`. Same pattern as m01/m03 (which add `n_orders`).
Inconsistent — model over-generates for some queries and under-generates
for others. Fix: standard "always include `COUNT(*) AS n` for per-X
aggregations" rule in role.md.

---

### ❌ `m01_5_states_longest_delivery_time` *(medium)*

**Question:** Top 5 states with longest delivery time

**EX:** ✗  **Rubric:** table=correct, time_frame=correct, filters=flag, aggregation=correct, join=correct
**EX reason:** `[m01] col count differs on row 0: gold=2, predicted=3 (extras on predicted)`

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
    ROUND(AVG(EXTRACT(DAY FROM o.order_delivered_customer_date - o.order_purchase_timestamp)), 2) AS avg_delivery_days,
    COUNT(DISTINCT o.order_id) AS n_orders
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
GROUP BY c.customer_state
ORDER BY avg_delivery_days DESC
LIMIT 5;
```

**Briefing:** Over-generation. Gold returns `(customer_state, avg_days)`;
model added `n_orders` as a third column. The `EXTRACT` vs `DATE_PART`
choice is rubric-equivalent (numerically identical). Fix: same as e01 —
anti-over-generation rule.

---

### ❌ `m03_avg_order_value_gmv_state` *(medium)*

**Question:** Avg order value (GMV) per state, top 5

**EX:** ✗  **Rubric:** table=correct, aggregation=correct, join=correct
**EX reason:** `[m03] col count differs on row 0: gold=2, predicted=3 (extras on predicted)`

**Gold SQL:**
```sql
SELECT customer_state, ROUND(AVG(order_total), 2) AS avg_gmv
FROM (
  SELECT c.customer_state, o.order_id, SUM(i.price + i.freight_value) AS order_total
  FROM orders o
  JOIN customers c ON o.customer_id = c.customer_id
  JOIN order_items i ON o.order_id = i.order_id
  GROUP BY o.order_id, c.customer_state
) AS sub
GROUP BY customer_state
ORDER BY avg_gmv DESC
LIMIT 5
```

**Generated SQL:**
```sql
SELECT
    sub.customer_state,
    ROUND(AVG(sub.order_total), 2) AS avg_gmv,
    COUNT(*) AS n_orders
FROM (
    SELECT
        c.customer_state,
        o.order_id,
        SUM(oi.price + oi.freight_value) AS order_total
    FROM orders o
    JOIN customers c ON o.customer_id = c.customer_id
    JOIN order_items oi ON o.order_id = oi.order_id
    GROUP BY c.customer_state, o.order_id
) AS sub
GROUP BY sub.customer_state
ORDER BY avg_gmv DESC
LIMIT 5;
```

**Briefing:** Over-generation. Gold returns `(customer_state, avg_gmv)`;
model added `COUNT(*) AS n_orders`. Subquery pre-aggregation pattern is
correct in both — only the outer SELECT differs. Fix: same as e01/m01.

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
    t.product_category_name_english AS category,
    ROUND(AVG(r.review_score)::numeric, 2) AS avg_review_score,
    COUNT(*) AS n_reviews
FROM order_reviews r
JOIN order_items oi
    ON r.order_id = oi.order_id
JOIN products p
    ON oi.product_id = p.product_id
LEFT JOIN product_category_translation t
    ON p.product_category_name = t.product_category_name
WHERE p.product_category_name IS NOT NULL
  AND t.product_category_name_english IS NOT NULL
GROUP BY t.product_category_name_english
HAVING COUNT(*) >= 100
ORDER BY avg_review_score ASC, n_reviews DESC
LIMIT 5;
```

**Briefing:** Tiebreak drift. Gold uses secondary `ORDER BY
T3.product_category_name_english` (alphabetical); predicted uses
secondary `ORDER BY n_reviews DESC`. At the LIMIT 5 boundary, several
categories share the same `avg_score`; the two orderings pick different
rows. The gold filters NULLs with `WHERE T3.product_category_name_english
IS NOT NULL`; predicted filters with both `p.product_category_name IS
NOT NULL` AND `t.product_category_name_english IS NOT NULL` (more
restrictive, but row counts still match). Fix: add "secondary ORDER BY
on category name for deterministic tiebreaks" rule.

---

## Reproduction

```bash
python3 evals/scripts/eval_runner.py \
  --agent --agent-model gpt-5.4 --max-workers 10 \
  --name v2_1_full39_gpt5_4_repro
```

Run artifacts land in `evals/results/summary/v2_1_full39_gpt5_4_repro_<ts>/`.
The 7 failures above should reproduce (modulo temperature-driven variation).
