# Eval Report — Run 20260724_215741

| Field            | Value          |
|------------------|----------------|
| Model            | agent(gpt-4o-mini)        |
| Total queries    | 39        |
| Wall time        | 22.46 s     |
| Parallel workers | 5  |
| Total cost       | $0.0341   |

## Top-Line Metrics

- **EM rate:** 0.00%
- **EX rate:** 69.23%
- **Rubric-clean rate:** 89.74%  *(cases with no wrong rubric dimension)*
- **False positive rate:** 2.56%  *(EX pass but rubric wrong — 1 of 39)*
- **Review:** 5  *(EX pass with a rubric flag — needs a human look)*
- **Pass / Review / Fail / Error / Timeout:** 26 / 5 / 10 / 3 / 0

## Rubric Dimension Health

> Sorted by (wrong + flag)% descending — worst dimension first.

| Dimension   | Graded | ✅ Correct% | ❌ Wrong% | ⚠️ Flag% | — NA%  |
|-------------|-------:|------------:|----------:|---------:|-------:|
| filters     |      9 |        0.0% |     33.3% |    66.7% |  76.9% |
| time_frame  |      4 |       50.0% |     50.0% |     0.0% |  89.7% |
| join        |     16 |       81.2% |      0.0% |    18.8% |  59.0% |
| aggregation |     39 |       84.6% |      0.0% |    15.4% |   0.0% |
| table       |     39 |       97.4% |      0.0% |     2.6% |   0.0% |

## By-Difficulty Breakdown

| Difficulty | N  | EX Pass% | Avg Cost (USD) | Avg Latency (s) |
|------------|---:|---------:|---------------:|----------------:|
| easy       | 16 |   81.25% |        $0.0009 |           2.556 |
| medium     | 13 |   76.92% |        $0.0009 |           2.418 |
| hard       | 10 |   40.00% |        $0.0009 |           2.774 |

## Failures

### ❌ `e01_5_selling_products_health_beauty` *(easy)*

**Question:** top 5 selling products in health beauty, category

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=wrong, `aggregation`=flag, `join`=flag, `date_operator`=NA

**Error:**
```
Query execution failed: column p.product_name does not exist
LINE 3:     p.product_name,
            ^
```

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
    p.product_id,
    p.product_name,
    SUM(oi.price + oi.freight_value) AS total_sales
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
LEFT JOIN product_category_translation pct ON p.product_category_name = pct.product_category_name
WHERE COALESCE(pct.product_category_name_english, p.product_category_name) = 'beleza_saude'
GROUP BY p.product_id, p.product_name
ORDER BY total_sales DESC
LIMIT 5;
```

### ❌ `e03_most_used_payment_methods_computers` *(easy)*

**Question:** What is the most used payment methods for computers accessories

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=flag, `time_frame`=NA, `filters`=wrong, `aggregation`=correct, `join`=flag, `date_operator`=NA

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
    COUNT(*) AS usage_count
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
JOIN order_payments op ON oi.order_id = op.order_id
WHERE p.product_category_name = 'informatica_acessorios'
GROUP BY op.payment_type
ORDER BY usage_count DESC
LIMIT 1;
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
SELECT c.customer_state, COUNT(DISTINCT c.customer_unique_id) AS customer_count
FROM customers c
GROUP BY c.customer_state
ORDER BY customer_count DESC
LIMIT 5;
```

### ❌ `h02_overall_repeat_customer_rate_customers` *(hard)*

**Question:** Overall repeat customer rate (% of customers with > 1 order)

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=NA, `aggregation`=correct, `join`=NA, `date_operator`=NA

**Error:**
```
Query execution failed: column reference "customer_id" is ambiguous
LINE 4:     SELECT customer_unique_id, COUNT(DISTINCT customer_id) A...
                                                      ^
```

**Gold SQL:**
```sql
SELECT ROUND(100.0 * SUM(CASE WHEN n_orders > 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS repeat_pct
FROM (
  SELECT customer_unique_id, COUNT(DISTINCT customer_id) AS n_orders
  FROM customers GROUP BY customer_unique_id
) AS sub
```

**Predicted SQL:**
```sql
SELECT
    ROUND(COUNT(DISTINCT customer_unique_id) FILTER (WHERE order_count > 1) * 100.0 / COUNT(DISTINCT customer_unique_id), 2) AS repeat_customer_rate
FROM (
    SELECT customer_unique_id, COUNT(DISTINCT customer_id) AS order_count
    FROM customers c
    JOIN orders o ON c.customer_id = o.customer_id
    GROUP BY customer_unique_id
) AS sub;
```

### ❌ `h04_5_categories_worst_late_delivery` *(hard)*

**Question:** Top 5 categories with worst late delivery rate (>=50 delivered orders)

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=flag, `aggregation`=flag, `join`=correct, `date_operator`=NA

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
SELECT
    COALESCE(pct.product_category_name_english, p.product_category_name) AS category,
    ROUND(COUNT(CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 2) AS late_delivery_rate
FROM orders o
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
LEFT JOIN product_category_translation pct ON p.product_category_name = pct.product_category_name
WHERE o.order_status = 'delivered'
GROUP BY category
HAVING COUNT(*) >= 50
ORDER BY late_delivery_rate DESC
LIMIT 5;
```

### ❌ `h05_payment_method_share_5_revenue` *(hard)*

**Question:** Payment method share per top-5 revenue category (using window function)

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=NA, `aggregation`=flag, `join`=correct, `date_operator`=NA

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
SELECT
    pct.product_category_name_english AS category,
    op.payment_type,
    ROUND(SUM(op.payment_value), 2) AS total_payment,
    ROUND(SUM(op.payment_value) * 100.0 / SUM(SUM(op.payment_value)) OVER (PARTITION BY pct.product_category_name_english), 2) AS payment_share
FROM order_payments op
JOIN orders o ON op.order_id = o.order_id
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
LEFT JOIN product_category_translation pct ON p.product_category_name = pct.product_category_name
GROUP BY pct.product_category_name_english, op.payment_type
ORDER BY total_payment DESC
LIMIT 5;
```

### ❌ `h07_multi_item_orders_items_from` *(hard)*

**Question:** % of multi-item orders with items from 2+ categories

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=NA, `aggregation`=correct, `join`=correct, `date_operator`=NA

**Error:**
```
Query execution failed: column "total_orders.total_count" must appear in the GROUP BY clause or be used in an aggregate function
LINE 2: ...INCT multi_item_orders.order_id) * 100.0 / NULLIF(total_orde...
                                                             ^
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
SELECT
    ROUND(COUNT(DISTINCT multi_item_orders.order_id) * 100.0 / NULLIF(total_orders.total_count, 0), 2) AS percentage_multi_item_orders
FROM (
    SELECT o.order_id
    FROM order_items oi
    JOIN orders o ON oi.order_id = o.order_id
    GROUP BY o.order_id
    HAVING COUNT(DISTINCT oi.product_id) > 1
) AS multi_item_orders
CROSS JOIN (
    SELECT COUNT(DISTINCT order_id) AS total_count
    FROM orders
) AS total_orders
WHERE multi_item_orders.order_id IN (
    SELECT o.order_id
    FROM order_items oi
    JOIN orders o ON oi.order_id = o.order_id
    JOIN products p ON oi.product_id = p.product_id
    LEFT JOIN product_category_translation pct ON p.product_category_name = pct.product_category_name
    GROUP BY o.order_id
    HAVING COUNT(DISTINCT COALESCE(pct.product_category_name_english, p.product_category_name)) > 1
);
```

### ❌ `h09_monthly_avg_order_value_trend` *(hard)*

**Question:** Monthly avg order value trend (with subquery to pre-aggregate per-order)

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=correct, `filters`=NA, `aggregation`=correct, `join`=correct, `date_operator`=NA

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
    TO_CHAR(order_date, 'YYYY-MM') AS ym,
    ROUND(AVG(order_total), 2) AS avg_order_value
FROM (
    SELECT
        o.order_purchase_timestamp AS order_date,
        o.order_id,
        SUM(oi.price + oi.freight_value) AS order_total
    FROM orders o
    JOIN order_items oi ON o.order_id = oi.order_id
    GROUP BY o.order_id, o.order_purchase_timestamp
) AS sub
GROUP BY ym
ORDER BY ym;
```

### ❌ `h10_average_days_between_delivery_review` *(hard)*

**Question:** Average days between delivery and review creation

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=wrong, `filters`=wrong, `aggregation`=correct, `join`=correct, `date_operator`=NA

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
SELECT AVG(EXTRACT(DAY FROM r.review_creation_date - o.order_delivered_customer_date)) AS avg_days_between_delivery_and_review
FROM order_reviews r
JOIN orders o ON r.order_id = o.order_id
WHERE o.order_delivered_customer_date IS NOT NULL
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
    ROUND(AVG(EXTRACT(DAY FROM o.order_delivered_customer_date - o.order_purchase_timestamp)), 2) AS avg_delivery_days
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
GROUP BY c.customer_state
ORDER BY avg_delivery_days DESC
LIMIT 5;
```

### ❌ `m05_bottom_5_categories_by_average` *(medium)*

**Question:** Bottom 5 categories by average review score (only categories with at least 100 reviews)

**EM:** ✗  **EX:** ✗  **Rubric:** `table`=correct, `time_frame`=NA, `filters`=NA, `aggregation`=correct, `join`=correct, `date_operator`=NA

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
SELECT
    COALESCE(pct.product_category_name_english, p.product_category_name) AS category,
    ROUND(AVG(r.review_score), 2) AS avg_review_score
FROM order_reviews r
JOIN orders o ON r.order_id = o.order_id
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
LEFT JOIN product_category_translation pct ON p.product_category_name = pct.product_category_name
GROUP BY category
HAVING COUNT(r.review_id) >= 100
ORDER BY avg_review_score ASC
LIMIT 5;
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
    ROUND(AVG(op.payment_value), 2) AS avg_payment_value
FROM order_payments op
GROUP BY op.payment_type
ORDER BY avg_payment_value DESC
LIMIT 1000;
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
SELECT n_orders, COUNT(*) AS n_customers
FROM (
    SELECT customer_unique_id, COUNT(DISTINCT customer_id) AS n_orders
    FROM customers
    GROUP BY customer_unique_id
) AS sub
GROUP BY n_orders
ORDER BY n_orders;
```
