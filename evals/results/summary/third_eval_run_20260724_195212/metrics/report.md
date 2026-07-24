# Eval Report — Run third_eval_run_20260724_195212

| Field            | Value          |
|------------------|----------------|
| Model            | agent(gpt-4o)        |
| Total queries    | 39        |
| Wall time        | 291.39 s     |
| Parallel workers | 1  |
| Total cost       | $0.4187   |

## Top-Line Metrics

- **EM rate:** 0.00%
- **EX rate:** 58.97%
- **Rubric-clean rate:** 82.05%  *(cases with no wrong rubric dimension)*
- **False positive rate:** 5.13%  *(EX pass but rubric wrong — 2 of 39)*
- **Review:** 2  *(EX pass with a rubric flag — needs a human look)*
- **Pass / Review / Fail / Error / Timeout:** 21 / 2 / 14 / 4 / 0

## Rubric Dimension Health

> Sorted by (wrong + flag)% descending — worst dimension first.

| Dimension   | Graded | ✅ Correct% | ❌ Wrong% | ⚠️ Flag% | — NA%  |
|-------------|-------:|------------:|----------:|---------:|-------:|
| time_frame  |      4 |        0.0% |    100.0% |     0.0% |  89.7% |
| filters     |      9 |        0.0% |     22.2% |    77.8% |  76.9% |
| join        |     16 |       68.8% |      0.0% |    31.2% |  59.0% |
| aggregation |     39 |       82.1% |      2.6% |    15.4% |   0.0% |
| table       |     39 |       97.4% |      0.0% |     2.6% |   0.0% |

## By-Difficulty Breakdown

| Difficulty | N  | EX Pass% | Avg Cost (USD) | Avg Latency (s) |
|------------|---:|---------:|---------------:|----------------:|
| easy       | 16 |   81.25% |        $0.0103 |           6.378 |
| medium     | 13 |   53.85% |        $0.0107 |           8.111 |
| hard       | 10 |   30.00% |        $0.0115 |           8.052 |

## Failures

### ❌ `e01_5_selling_products_health_beauty` *(easy)*

**Question:** top 5 selling products in health beauty, category

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=wrong, `aggregation`=correct, `join`=correct, `date_operator`=NA

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

**Predicted SQL:**
```sql
SELECT
    COALESCE(pct.product_category_name_english, p.product_category_name) as category,
    p.product_id,
    COUNT(oi.order_id) as total_sales
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
LEFT JOIN product_category_translation pct
    ON p.product_category_name = pct.product_category_name
WHERE COALESCE(pct.product_category_name_english, p.product_category_name) = 'health_beauty'
GROUP BY category, p.product_id
ORDER BY total_sales DESC
LIMIT 5;
```

### ❌ `e03_most_used_payment_methods_computers` *(easy)*

**Question:** What is the most used payment methods for computers accessories

**EM:** ✗  **EX:** ✓  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=wrong, `aggregation`=correct, `join`=correct, `date_operator`=NA

**Gold SQL:**
```sql
SELECT op.payment_type, COUNT(*) AS n
FROM order_payments op
JOIN orders o ON op.order_id = o.order_id
JOIN order_items i ON o.order_id = i.order_id
JOIN products p ON i.product_id = p.product_id
LEFT JOIN product_category_translation t ON p.product_category_name = t.product_category_name
WHERE t.product_category_name_english = 'computers_accessories'
GROUP BY op.payment_type
ORDER BY n DESC
```

**Predicted SQL:**
```sql
SELECT
    op.payment_type,
    COUNT(op.payment_type) as usage_count
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
LEFT JOIN product_category_translation pct
    ON p.product_category_name = pct.product_category_name
JOIN order_payments op ON oi.order_id = op.order_id
WHERE COALESCE(pct.product_category_name_english, p.product_category_name) = 'computers_accessories'
GROUP BY op.payment_type
ORDER BY usage_count DESC
LIMIT 10;
```

### ❌ `e06_orders_delivered_late` *(easy)*

**Question:** Orders delivered late

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=flag, `aggregation`=wrong, `join`=NA, `date_operator`=NA

**Gold SQL:**
```sql
SELECT COUNT(*)
FROM orders
WHERE order_status = 'delivered'
  AND order_delivered_customer_date IS NOT NULL
  AND order_estimated_delivery_date IS NOT NULL
  AND order_delivered_customer_date > order_estimated_delivery_date
```

**Predicted SQL:**
```sql
SELECT
    o.order_id,
    o.order_purchase_timestamp,
    o.order_delivered_customer_date,
    o.order_estimated_delivery_date,
    EXTRACT(DAY FROM o.order_delivered_customer_date - o.order_estimated_delivery_date) as days_late
FROM orders o
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date > o.order_estimated_delivery_date
LIMIT 1000;
```

### ❌ `e13_5_states_by_number_customers` *(easy)*

**Question:** Top 5 states by number of customers (with most customers first)

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=NA, `aggregation`=correct, `join`=NA, `date_operator`=NA

**Gold SQL:**
```sql
SELECT customer_state, COUNT(*) AS n FROM customers GROUP BY customer_state ORDER BY n DESC LIMIT 5
```

**Predicted SQL:**
```sql
SELECT
    c.customer_state,
    COUNT(DISTINCT c.customer_unique_id) as customer_count
FROM customers c
GROUP BY c.customer_state
ORDER BY customer_count DESC
LIMIT 5;
```

### ❌ `h04_5_categories_worst_late_delivery` *(hard)*

**Question:** Top 5 categories with worst late delivery rate (>=50 delivered orders)

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=flag, `aggregation`=correct, `join`=flag, `date_operator`=NA

**Error:**
```
SQL validation failed:
  - R5 allow-list: Table 'category_delivery_stats' not in allowed list
```

**Gold SQL:**
```sql
SELECT T3.product_category_name_english AS category,
       COUNT(*) AS n_delivered,
       ROUND(100.0 * SUM(CASE WHEN T1.order_delivered_customer_date > T1.order_estimated_delivery_date THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_late
FROM orders T1
JOIN order_items T4 ON T1.order_id = T4.order_id
JOIN products T5 ON T4.product_id = T5.product_id
LEFT JOIN product_category_translation T3 ON T5.product_category_name = T3.product_category_name
WHERE T1.order_status = 'delivered'
  AND T1.order_delivered_customer_date IS NOT NULL
  AND T1.order_estimated_delivery_date IS NOT NULL
GROUP BY T3.product_category_name_english
HAVING COUNT(*) >= 50
ORDER BY pct_late DESC
LIMIT 5
```

**Predicted SQL:**
```sql
WITH category_delivery_stats AS (
    SELECT
        COALESCE(pct.product_category_name_english, p.product_category_name) as category,
        COUNT(o.order_id) as delivered_orders,
        SUM(CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN 1 ELSE 0 END) as late_deliveries
    FROM orders o
    JOIN order_items oi ON o.order_id = oi.order_id
    JOIN products p ON oi.product_id = p.product_id
    LEFT JOIN product_category_translation pct
        ON p.product_category_name = pct.product_category_name
    WHERE o.order_status = 'delivered'
    GROUP BY category
    HAVING COUNT(o.order_id) >= 50
)
SELECT
    category,
    late_deliveries::FLOAT / delivered_orders as late_delivery_rate
FROM category_delivery_stats
ORDER BY late_delivery_rate DESC
LIMIT 5;
```

### ❌ `h05_payment_method_share_5_revenue` *(hard)*

**Question:** Payment method share per top-5 revenue category (using window function)

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=NA, `aggregation`=flag, `join`=flag, `date_operator`=NA

**Error:**
```
SQL validation failed:
  - R5 allow-list: Table 'payment_method_share' not in allowed list
```

**Gold SQL:**
```sql
SELECT cat AS category, payment_type, ROUND(100.0 * n / SUM(n) OVER (PARTITION BY cat), 1) AS pct
FROM (
  SELECT T3.product_category_name_english AS cat, op.payment_type, COUNT(*) AS n
  FROM order_payments op
  JOIN orders o ON op.order_id = o.order_id
  JOIN order_items i ON o.order_id = i.order_id
  JOIN products p ON i.product_id = p.product_id
  LEFT JOIN product_category_translation T3 ON p.product_category_name = T3.product_category_name
  WHERE T3.product_category_name_english IN (
    SELECT T3.product_category_name_english
    FROM order_items i
    JOIN products p ON i.product_id = p.product_id
    LEFT JOIN product_category_translation T3 ON p.product_category_name = T3.product_category_name
    GROUP BY T3.product_category_name_english
    ORDER BY SUM(i.price + i.freight_value) DESC LIMIT 5
  )
GROUP BY T3.product_category_name_english, op.payment_type
) AS sub
ORDER BY cat, pct DESC
```

**Predicted SQL:**
```sql
WITH category_revenue AS (
    SELECT
        COALESCE(pct.product_category_name_english, p.product_category_name) as category,
        SUM(oi.price) as total_revenue
    FROM order_items oi
    JOIN products p ON oi.product_id = p.product_id
    LEFT JOIN product_category_translation pct
        ON p.product_category_name = pct.product_category_name
    GROUP BY COALESCE(pct.product_category_name_english, p.product_category_name)
),
top_5_categories AS (
    SELECT category
    FROM category_revenue
    ORDER BY total_revenue DESC
    LIMIT 5
),
payment_method_share AS (
    SELECT
        COALESCE(pct.product_category_name_english, p.product_category_name) as category,
        op.payment_type,
        SUM(op.payment_value) as payment_value
    FROM order_items oi
    JOIN products p ON oi.product_id = p.product_id
    LEFT JOIN product_category_translation pct
        ON p.product_category_name = pct.product_category_name
    JOIN orders o ON oi.order_id = o.order_id
    JOIN order_payments op ON o.order_id = op.order_id
    WHERE COALESCE(pct.product_category_name_english, p.product_category_name) IN (
        SELECT category FROM top_5_categories
    )
    GROUP BY COALESCE(pct.product_category_name_english, p.product_category_name), op.payment_type
),
total_payment_value_per_category AS (
    SELECT
        category,
        SUM(payment_value) as total_payment_value
    FROM payment_method_share
    GROUP BY category
)
SELECT
    pms.category,
    pms.payment_type,
    pms.payment_value,
    tpv.total_payment_value,
    (pms.payment_value / tpv.total_payment_value) * 100 as payment_share_percentage
FROM payment_method_share pms
JOIN total_payment_value_per_category tpv ON pms.category = tpv.category
ORDER BY pms.category, payment_share_percentage DESC
LIMIT 100;
```

### ❌ `h06_compare_avg_review_score_time` *(hard)*

**Question:** Compare avg review score: on-time vs late deliveries

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=flag, `aggregation`=flag, `join`=correct, `date_operator`=NA

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

**Predicted SQL:**
```sql
SELECT
    delivery_status,
    AVG(orv.review_score) as avg_review_score
FROM (
    SELECT
        o.order_id,
        CASE
            WHEN o.order_delivered_customer_date <= o.order_estimated_delivery_date THEN 'on_time'
            ELSE 'late'
        END as delivery_status
    FROM orders o
    WHERE o.order_status = 'delivered'
      AND o.order_delivered_customer_date IS NOT NULL
      AND o.order_estimated_delivery_date IS NOT NULL
) as delivery_statuses
JOIN order_reviews orv ON delivery_statuses.order_id = orv.order_id
GROUP BY delivery_status
ORDER BY delivery_status;
```

### ❌ `h07_multi_item_orders_items_from` *(hard)*

**Question:** % of multi-item orders with items from 2+ categories

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=NA, `aggregation`=correct, `join`=flag, `date_operator`=NA

**Error:**
```
SQL validation failed:
  - R5 allow-list: Table 'multi_item_orders' not in allowed list
```

**Gold SQL:**
```sql
SELECT ROUND(100.0 * SUM(CASE WHEN n_categories >= 2 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_multi_category
FROM (
  SELECT o.order_id, COUNT(DISTINCT T3.product_category_name_english) AS n_categories
  FROM orders o
  JOIN order_items i ON o.order_id = i.order_id
  JOIN products p ON i.product_id = p.product_id
  LEFT JOIN product_category_translation T3 ON p.product_category_name = T3.product_category_name
  GROUP BY o.order_id
  HAVING COUNT(*) >= 2
) AS sub
```

**Predicted SQL:**
```sql
WITH order_category_counts AS (
    SELECT
        oi.order_id,
        COUNT(DISTINCT COALESCE(pct.product_category_name_english, p.product_category_name)) as category_count
    FROM order_items oi
    JOIN products p ON oi.product_id = p.product_id
    LEFT JOIN product_category_translation pct
        ON p.product_category_name = pct.product_category_name
    GROUP BY oi.order_id
),
multi_item_orders AS (
    SELECT
        order_id
    FROM order_items
    GROUP BY order_id
    HAVING COUNT(order_item_id) > 1
)
SELECT
    (COUNT(DISTINCT occ.order_id)::decimal / COUNT(DISTINCT mio.order_id)) * 100 as percent_multi_category_orders
FROM order_category_counts occ
JOIN multi_item_orders mio ON occ.order_id = mio.order_id
WHERE occ.category_count > 1;
```

### ❌ `h08_5_state_category_pairs_by` *(hard)*

**Question:** Top 5 (state, category) pairs by total revenue

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=flag, `time_frame`=NA, `filters`=NA, `aggregation`=correct, `join`=flag, `date_operator`=NA

**Gold SQL:**
```sql
SELECT T4.customer_state, T3.product_category_name_english AS category,
       ROUND(SUM(i.price + i.freight_value), 2) AS revenue
FROM order_items i
JOIN orders o ON i.order_id = o.order_id
JOIN customers T4 ON o.customer_id = T4.customer_id
JOIN products p ON i.product_id = p.product_id
LEFT JOIN product_category_translation T3 ON p.product_category_name = T3.product_category_name
GROUP BY T4.customer_state, T3.product_category_name_english
ORDER BY revenue DESC
LIMIT 5
```

**Predicted SQL:**
```sql
SELECT
    c.customer_state,
    COALESCE(pct.product_category_name_english, p.product_category_name) as category,
    SUM(oi.price) as total_revenue
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
LEFT JOIN product_category_translation pct
    ON p.product_category_name = pct.product_category_name
WHERE o.order_status = 'delivered'
GROUP BY c.customer_state, COALESCE(pct.product_category_name_english, p.product_category_name)
ORDER BY total_revenue DESC
LIMIT 5;
```

### ❌ `h09_monthly_avg_order_value_trend` *(hard)*

**Question:** Monthly avg order value trend (with subquery to pre-aggregate per-order)

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=wrong, `filters`=NA, `aggregation`=correct, `join`=correct, `date_operator`=NA

**Gold SQL:**
```sql
SELECT TO_CHAR(o.order_purchase_timestamp, 'YYYY-MM') AS ym,
       ROUND(AVG(order_total), 2) AS avg_order_value,
       COUNT(*) AS n_orders
FROM (
  SELECT o.order_id, o.order_purchase_timestamp, SUM(i.price + i.freight_value) AS order_total
  FROM orders o JOIN order_items i ON o.order_id = i.order_id
  GROUP BY o.order_id, o.order_purchase_timestamp
) o
GROUP BY ym
ORDER BY ym
```

**Predicted SQL:**
```sql
SELECT
    EXTRACT(YEAR FROM o.order_purchase_timestamp) AS year,
    EXTRACT(MONTH FROM o.order_purchase_timestamp) AS month,
    AVG(order_total) AS avg_order_value
FROM (
    SELECT
        oi.order_id,
        SUM(oi.price + oi.freight_value) AS order_total
    FROM order_items oi
    GROUP BY oi.order_id
) AS order_totals
JOIN orders o ON order_totals.order_id = o.order_id
WHERE o.order_status = 'delivered'
GROUP BY year, month
ORDER BY year, month
LIMIT 1000;
```

### ❌ `h10_average_days_between_delivery_review` *(hard)*

**Question:** Average days between delivery and review creation

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=wrong, `filters`=flag, `aggregation`=correct, `join`=correct, `date_operator`=NA

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

**Predicted SQL:**
```sql
SELECT
    AVG(EXTRACT(DAY FROM r.review_creation_date - o.order_delivered_customer_date)) as avg_days_between_delivery_and_review
FROM orders o
JOIN order_reviews r ON o.order_id = r.order_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
  AND r.review_creation_date IS NOT NULL;
```

### ❌ `m01_5_states_longest_delivery_time` *(medium)*

**Question:** Top 5 states with longest delivery time

**EM:** ✗  **EX:** ✓  **Rubric:** `table`=correct, `time_frame`=wrong, `filters`=flag, `aggregation`=correct, `join`=correct, `date_operator`=NA

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

**Predicted SQL:**
```sql
SELECT
    c.customer_state,
    AVG(
        EXTRACT(DAY FROM o.order_delivered_customer_date - o.order_purchase_timestamp)
    ) as avg_delivery_days
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
GROUP BY c.customer_state
ORDER BY avg_delivery_days DESC
LIMIT 5;
```

### ❌ `m03_avg_order_value_gmv_state` *(medium)*

**Question:** Avg order value (GMV) per state, top 5

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=NA, `aggregation`=flag, `join`=correct, `date_operator`=NA

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

**Predicted SQL:**
```sql
SELECT
    c.customer_state,
    AVG(oi.price + oi.freight_value) as avg_order_value
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
JOIN order_items oi ON o.order_id = oi.order_id
WHERE o.order_status = 'delivered'
GROUP BY c.customer_state
ORDER BY avg_order_value DESC
LIMIT 5;
```

### ❌ `m05_bottom_5_categories_by_average` *(medium)*

**Question:** Bottom 5 categories by average review score (only categories with at least 100 reviews)

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=NA, `aggregation`=correct, `join`=flag, `date_operator`=NA

**Error:**
```
SQL validation failed:
  - R5 allow-list: Table 'category_translations' not in allowed list
```

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
GROUP BY T3.product_category_name_english
HAVING COUNT(*) >= 100
ORDER BY avg_score ASC, T3.product_category_name_english
LIMIT 5
```

**Predicted SQL:**
```sql
WITH category_reviews AS (
    SELECT
        p.product_category_name,
        AVG(r.review_score) as avg_review_score,
        COUNT(r.review_id) as review_count
    FROM order_reviews r
    JOIN order_items oi ON r.order_id = oi.order_id
    JOIN products p ON oi.product_id = p.product_id
    GROUP BY p.product_category_name
    HAVING COUNT(r.review_id) >= 100
),
category_translations AS (
    SELECT
        pct.product_category_name,
        COALESCE(pct.product_category_name_english, p.product_category_name) as category_name_english
    FROM products p
    LEFT JOIN product_category_translation pct
        ON p.product_category_name = pct.product_category_name
)
SELECT
    ct.category_name_english,
    cr.avg_review_score
FROM category_reviews cr
JOIN category_translations ct ON cr.product_category_name = ct.product_category_name
ORDER BY cr.avg_review_score ASC
LIMIT 5;
```

### ❌ `m08_monthly_order_count_full_trend` *(medium)*

**Question:** Monthly order count (full trend across the dataset)

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=wrong, `filters`=NA, `aggregation`=correct, `join`=NA, `date_operator`=NA

**Gold SQL:**
```sql
SELECT TO_CHAR(order_purchase_timestamp, 'YYYY-MM') AS ym, COUNT(*) AS n
FROM orders
GROUP BY ym
ORDER BY ym
```

**Predicted SQL:**
```sql
SELECT
    EXTRACT(YEAR FROM o.order_purchase_timestamp) AS year,
    EXTRACT(MONTH FROM o.order_purchase_timestamp) AS month,
    COUNT(DISTINCT o.order_id) AS order_count
FROM orders o
GROUP BY year, month
ORDER BY year, month
LIMIT 1000;
```

### ❌ `m09_avg_payment_value_payment_type` *(medium)*

**Question:** Avg payment value per payment type

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=NA, `aggregation`=flag, `join`=NA, `date_operator`=NA

**Gold SQL:**
```sql
SELECT payment_type, ROUND(AVG(payment_value), 2) AS avg_value, COUNT(*) AS n
FROM order_payments
GROUP BY payment_type
ORDER BY avg_value DESC
```

**Predicted SQL:**
```sql
SELECT
    op.payment_type,
    AVG(op.payment_value) as avg_payment_value
FROM order_payments op
GROUP BY op.payment_type
ORDER BY avg_payment_value DESC
LIMIT 10;
```

### ❌ `m10_10_sellers_by_total_revenue` *(medium)*

**Question:** Top 10 sellers by total revenue (price + freight)

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=NA, `aggregation`=correct, `join`=correct, `date_operator`=NA

**Gold SQL:**
```sql
SELECT T1.seller_id, ROUND(SUM(T2.price + T2.freight_value), 2) AS revenue
FROM sellers T1
JOIN order_items T2 ON T1.seller_id = T2.seller_id
GROUP BY T1.seller_id
ORDER BY revenue DESC
LIMIT 10
```

**Predicted SQL:**
```sql
SELECT
    s.seller_id,
    s.seller_city,
    s.seller_state,
    SUM(oi.price + oi.freight_value) as total_revenue
FROM sellers s
JOIN order_items oi ON s.seller_id = oi.seller_id
GROUP BY s.seller_id, s.seller_city, s.seller_state
ORDER BY total_revenue DESC
LIMIT 10;
```

### ❌ `m13_order_count_distribution_customer_customers` *(medium)*

**Question:** Order count distribution per customer (how many customers ordered N times?)

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=NA, `aggregation`=correct, `join`=NA, `date_operator`=NA

**Gold SQL:**
```sql
SELECT n_orders, COUNT(*) AS n_customers
FROM (
  SELECT customer_unique_id, COUNT(DISTINCT customer_id) AS n_orders
  FROM customers GROUP BY customer_unique_id
) AS sub
GROUP BY n_orders
ORDER BY n_orders
LIMIT 5
```

**Predicted SQL:**
```sql
SELECT
    order_count,
    COUNT(customer_unique_id) as customer_count
FROM (
    SELECT
        c.customer_unique_id,
        COUNT(DISTINCT o.order_id) as order_count
    FROM customers c
    JOIN orders o ON c.customer_id = o.customer_id
    GROUP BY c.customer_unique_id
) as customer_orders
GROUP BY order_count
ORDER BY order_count
LIMIT 1000;
```
