# Data Orientation Guide

## Normalization Gotchas

### Customers Table
- **customer_id** is NOT the unique customer identifier
- **customer_unique_id** identifies the same person across multiple orders
- Same customer can appear multiple times with different customer_id values
- Always use COUNT(DISTINCT customer_unique_id) for unique customer counts

### Orders vs Order Items
- One order can have multiple items (multiple rows in order_items)
- When calculating order-level metrics, join order_items and GROUP BY order_id
- Never assume one row per order in order_items

### Order Payments
- One order can have multiple payment methods (multiple rows)
- payment_value is the amount for THAT payment method only
- Sum payment_value by order_id for total order payment

### Order Reviews
- One order can have multiple reviews (customer updated their review)
- review_creation_date determines recency
- Use DISTINCT ON or window functions to get latest review per order

## Soft Foreign Keys

The Olist database does NOT have declared foreign key constraints. These relationships are logical:

| Table | Column | References |
|-------|--------|------------|
| orders | customer_id | customers.customer_id |
| order_items | order_id | orders.order_id |
| order_items | product_id | products.product_id |
| order_items | seller_id | sellers.seller_id |
| order_payments | order_id | orders.order_id |
| order_reviews | order_id | orders.order_id |
| products | product_category_name | product_category_translation.product_category_name |

**Implications**:
- LEFT JOIN may return NULLs even for valid relationships
- Always handle NULL cases in joins
- Data integrity is not guaranteed at database level

## The Geolocation Trap

### DO NOT USE: geolocation table
The raw geolocation table has **duplicate zip codes** with different coordinates:
- Same zip_code_prefix can have multiple rows
- Different lat/lng values for same zip
- Joining on zip code produces duplicate rows

### USE: geolocation_by_zip (materialized view)
This view has ONE row per zip code with averaged coordinates:
- Unique on geolocation_zip_code_prefix
- Pre-aggregated lat/lng values
- Safe for joins

```sql
-- WRONG: Creates duplicates
FROM customers c
JOIN geolocation g ON c.customer_zip_code_prefix = g.geolocation_zip_code_prefix

-- CORRECT: One row per customer
FROM customers c
JOIN geolocation_by_zip gz ON c.customer_zip_code_prefix = gz.geolocation_zip_code_prefix
```

## NULL Handling

### Products
- product_category_name can be NULL (unclassified products)
- Use COALESCE or LEFT JOIN with product_category_translation

### Orders
- order_delivered_customer_date is NULL for non-delivered orders
- Always filter by order_status when analyzing delivery metrics

### Reviews
- review_comment_title and review_comment_message are often NULL
- ~99% of reviews have no comment text

## Date/Time Fields

### Timestamps
All timestamp fields are in ISO format without timezone:
- order_purchase_timestamp
- order_approved_at
- order_delivered_carrier_date
- order_delivered_customer_date
- review_creation_date

### Best Practices
```sql
-- Date range filtering
WHERE o.order_purchase_timestamp >= '2017-01-01'
  AND o.order_purchase_timestamp < '2018-01-01'

-- Extract date parts
EXTRACT(YEAR FROM o.order_purchase_timestamp)
EXTRACT(MONTH FROM o.order_purchase_timestamp)
EXTRACT(DOW FROM o.order_purchase_timestamp)  -- 0=Sunday, 6=Saturday
```

## Data Types

### IDs
All ID fields are VARCHAR, not INTEGER:
- customer_id, seller_id, product_id, order_id
- Use string comparison, not numeric

### Monetary Values
- price, freight_value, payment_value are DECIMAL
- Values in Brazilian Reais (BRL)

### Numeric Metrics
- review_score: INTEGER (1-5)
- product_weight_g: INTEGER (grams)
- product dimensions: INTEGER (cm)

## Common Query Patterns

### Joining Orders to Items
```sql
FROM orders o
JOIN order_items oi ON o.order_id = oi.order_id
-- Multiple rows per order!
```

### Getting Total Order Value
```sql
SELECT order_id, SUM(price + freight_value) as total_value
FROM order_items
GROUP BY order_id
```

### Counting Unique Customers
```sql
SELECT COUNT(DISTINCT customer_unique_id)
FROM customers
```

### Category with English Names
```sql
FROM products p
LEFT JOIN product_category_translation pct 
  ON p.product_category_name = pct.product_category_name
-- pct.product_category_name_english may be NULL
```
