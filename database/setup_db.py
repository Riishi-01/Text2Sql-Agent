"""Setup PostgreSQL database with sandbox role and load Olist dataset."""
import asyncio
import csv
import sys
from pathlib import Path

import asyncpg
from asyncpg import Connection

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import settings


async def create_database_and_role(conn: Connection):
    """Create database and sandbox user with read-only access."""
    
    # Create database if not exists
    try:
        await conn.execute(
            f'CREATE DATABASE {settings.SANDBOX_DB};'
        )
        print(f"✓ Created database: {settings.SANDBOX_DB}")
    except asyncpg.exceptions.DuplicateDatabaseError:
        print(f"✓ Database {settings.SANDBOX_DB} already exists")
    
    # Create sandbox user if not exists
    try:
        await conn.execute(
            f"CREATE USER {settings.SANDBOX_USER} WITH PASSWORD '{settings.SANDBOX_PASSWORD}';"
        )
        print(f"✓ Created user: {settings.SANDBOX_USER}")
    except asyncpg.exceptions.DuplicateObjectError:
        print(f"✓ User {settings.SANDBOX_USER} already exists")
    
    # Grant connect to database
    await conn.execute(
        f"GRANT CONNECT ON DATABASE {settings.SANDBOX_DB} TO {settings.SANDBOX_USER};"
    )
    print(f"✓ Granted connect on {settings.SANDBOX_DB}")


async def create_tables(conn: Connection):
    """Create tables for Olist dataset."""
    
    # Drop existing tables first
    tables = ['order_items', 'order_payments', 'order_reviews', 'orders', 
              'products', 'customers', 'sellers', 'geolocation', 'product_category_translation']
    for table in tables:
        await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    
    table_definitions = {
        "customers": """
            CREATE TABLE IF NOT EXISTS customers (
                customer_id VARCHAR(50) PRIMARY KEY,
                customer_unique_id VARCHAR(50),
                customer_zip_code_prefix VARCHAR(10),
                customer_city VARCHAR(100),
                customer_state VARCHAR(5)
            );
        """,
        "sellers": """
            CREATE TABLE IF NOT EXISTS sellers (
                seller_id VARCHAR(50) PRIMARY KEY,
                seller_zip_code_prefix VARCHAR(10),
                seller_city VARCHAR(100),
                seller_state VARCHAR(5)
            );
        """,
        "products": """
            CREATE TABLE IF NOT EXISTS products (
                product_id VARCHAR(50) PRIMARY KEY,
                product_category_name VARCHAR(100),
                product_name_lenght INTEGER,
                product_description_lenght INTEGER,
                product_photos_qty INTEGER,
                product_weight_g INTEGER,
                product_length_cm INTEGER,
                product_height_cm INTEGER,
                product_width_cm INTEGER
            );
        """,
        "product_category_translation": """
            CREATE TABLE IF NOT EXISTS product_category_translation (
                product_category_name VARCHAR(100) PRIMARY KEY,
                product_category_name_english VARCHAR(100)
            );
        """,
        "orders": """
            CREATE TABLE IF NOT EXISTS orders (
                order_id VARCHAR(50) PRIMARY KEY,
                customer_id VARCHAR(50) REFERENCES customers(customer_id),
                order_status VARCHAR(20),
                order_purchase_timestamp TIMESTAMP,
                order_approved_at TIMESTAMP,
                order_delivered_carrier_date TIMESTAMP,
                order_delivered_customer_date TIMESTAMP,
                order_estimated_delivery_date TIMESTAMP
            );
        """,
        "order_items": """
            CREATE TABLE IF NOT EXISTS order_items (
                order_id VARCHAR(50),
                order_item_id INTEGER,
                product_id VARCHAR(50) REFERENCES products(product_id),
                seller_id VARCHAR(50) REFERENCES sellers(seller_id),
                shipping_limit_date TIMESTAMP,
                price DECIMAL(10, 2),
                freight_value DECIMAL(10, 2),
                PRIMARY KEY (order_id, order_item_id)
            );
        """,
        "order_payments": """
            CREATE TABLE IF NOT EXISTS order_payments (
                order_id VARCHAR(50),
                payment_sequential INTEGER,
                payment_type VARCHAR(20),
                payment_installments INTEGER,
                payment_value DECIMAL(10, 2),
                PRIMARY KEY (order_id, payment_sequential)
            );
        """,
        "order_reviews": """
            CREATE TABLE IF NOT EXISTS order_reviews (
                review_id VARCHAR(50) PRIMARY KEY,
                order_id VARCHAR(50),
                review_score INTEGER,
                review_comment_title TEXT,
                review_comment_message TEXT,
                review_creation_date TIMESTAMP,
                review_answer_timestamp TIMESTAMP
            );
        """,
        "geolocation": """
            CREATE TABLE IF NOT EXISTS geolocation (
                geolocation_zip_code_prefix VARCHAR(10),
                geolocation_lat DOUBLE PRECISION,
                geolocation_lng DOUBLE PRECISION,
                geolocation_city VARCHAR(100),
                geolocation_state VARCHAR(5)
            );
        """,
    }
    
    for table_name, sql in table_definitions.items():
        await conn.execute(sql)
        print(f"✓ Created table: {table_name}")


async def load_csv_data(conn: Connection, table_name: str, file_name: str):
    """Load data from CSV file into table."""
    from datetime import datetime
    
    file_path = settings.DATA_DIR / file_name
    
    if not file_path.exists():
        print(f"⚠ File not found: {file_path}")
        return
    
    # Read CSV
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    if not rows:
        print(f"⚠ No data in {file_name}")
        return
    
    # Get column names
    columns = list(rows[0].keys())
    
    # Prepare insert query
    placeholders = ', '.join([f'${i+1}' for i in range(len(columns))])
    column_names = ', '.join(columns)
    
    # Define integer columns for each table
    int_columns = {
        'products': ['product_name_lenght', 'product_description_lenght', 'product_photos_qty',
                     'product_weight_g', 'product_length_cm', 'product_height_cm', 'product_width_cm'],
        'order_items': ['order_item_id'],
        'order_payments': ['payment_sequential', 'payment_installments'],
        'order_reviews': ['review_score'],
    }
    
    float_columns = {
        'order_items': ['price', 'freight_value'],
        'order_payments': ['payment_value'],
        'geolocation': ['geolocation_lat', 'geolocation_lng'],
    }
    
    datetime_columns = {
        'orders': ['order_purchase_timestamp', 'order_approved_at', 'order_delivered_carrier_date',
                   'order_delivered_customer_date', 'order_estimated_delivery_date'],
        'order_items': ['shipping_limit_date'],
        'order_reviews': ['review_creation_date', 'review_answer_timestamp'],
    }
    
    def parse_datetime(val):
        """Parse datetime string."""
        if not val or val == '':
            return None
        try:
            return datetime.strptime(val, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                return datetime.strptime(val, '%Y-%m-%d')
            except ValueError:
                return None
    
    # Build batch insert
    args = []
    for row in rows:
        row_values = []
        for col in columns:
            val = row.get(col, None)
            if val == '' or val is None:
                row_values.append(None)
            elif table_name in datetime_columns and col in datetime_columns[table_name]:
                row_values.append(parse_datetime(val))
            elif table_name in int_columns and col in int_columns[table_name]:
                try:
                    row_values.append(int(float(val)))
                except (ValueError, TypeError):
                    row_values.append(None)
            elif table_name in float_columns and col in float_columns[table_name]:
                try:
                    row_values.append(float(val))
                except (ValueError, TypeError):
                    row_values.append(None)
            else:
                row_values.append(val)
        args.append(row_values)
    
    # Execute batch insert
    query = f"""
        INSERT INTO {table_name} ({column_names})
        VALUES ({placeholders})
        ON CONFLICT DO NOTHING
    """
    await conn.executemany(query, args)
    
    print(f"✓ Loaded {len(rows)} rows into {table_name}")


async def grant_sandbox_permissions(conn: Connection):
    """Grant read-only permissions to sandbox user."""
    
    tables = [
        'customers', 'sellers', 'products', 'product_category_translation',
        'orders', 'order_items', 'order_payments', 'order_reviews', 'geolocation'
    ]
    
    for table in tables:
        await conn.execute(
            f"GRANT SELECT ON {table} TO {settings.SANDBOX_USER};"
        )
    
    print(f"✓ Granted SELECT permissions on all tables to {settings.SANDBOX_USER}")
    
    # Revoke CREATE on schema public to prevent table creation
    await conn.execute(
        f"REVOKE ALL ON SCHEMA public FROM {settings.SANDBOX_USER};"
    )
    await conn.execute(
        f"GRANT USAGE ON SCHEMA public TO {settings.SANDBOX_USER};"
    )
    print(f"✓ Restricted schema permissions for {settings.SANDBOX_USER}")
    
    # Set statement timeout for the sandbox user
    await conn.execute(
        f"ALTER ROLE {settings.SANDBOX_USER} SET statement_timeout = '{settings.QUERY_TIMEOUT_SECONDS}s';"
    )
    print(f"✓ Set statement timeout to {settings.QUERY_TIMEOUT_SECONDS}s")


async def main():
    """Main setup function."""
    print("Setting up PostgreSQL database...")
    print(f"Admin DB: {settings.ADMIN_DB_URL}")
    print(f"Sandbox DB: {settings.SANDBOX_DB}")
    print(f"Sandbox User: {settings.SANDBOX_USER}")
    print()
    
    # Connect to default postgres database for admin tasks
    admin_conn = await asyncpg.connect(settings.ADMIN_DB_URL)
    
    try:
        # Create database and user
        await create_database_and_role(admin_conn)
    finally:
        await admin_conn.close()
    
    # Connect to the new database with explicit credentials
    db_conn = await asyncpg.connect(
        host='localhost',
        port=5432,
        user='postgres',
        password='postgres',
        database=settings.SANDBOX_DB
    )
    
    try:
        # Create tables
        await create_tables(db_conn)
        
        # Load data
        print("\nLoading data...")
        await load_csv_data(db_conn, 'customers', 'olist_customers_dataset.csv')
        await load_csv_data(db_conn, 'sellers', 'olist_sellers_dataset.csv')
        await load_csv_data(db_conn, 'products', 'olist_products_dataset.csv')
        await load_csv_data(db_conn, 'product_category_translation', 'product_category_name_translation.csv')
        await load_csv_data(db_conn, 'orders', 'olist_orders_dataset.csv')
        await load_csv_data(db_conn, 'order_items', 'olist_order_items_dataset.csv')
        await load_csv_data(db_conn, 'order_payments', 'olist_order_payments_dataset.csv')
        await load_csv_data(db_conn, 'order_reviews', 'olist_order_reviews_dataset.csv')
        await load_csv_data(db_conn, 'geolocation', 'olist_geolocation_dataset.csv')
        
        # Grant permissions
        print("\nSetting up sandbox permissions...")
        await grant_sandbox_permissions(db_conn)
        
    finally:
        await db_conn.close()
    
    print("\n✅ Database setup complete!")
    print(f"\nConnection string for sandbox user:")
    print(f"postgresql://{settings.SANDBOX_USER}:{settings.SANDBOX_PASSWORD}@localhost:5432/{settings.SANDBOX_DB}")


if __name__ == "__main__":
    asyncio.run(main())
