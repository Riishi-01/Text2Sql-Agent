-- init_db.sql
-- Creates read-only role and geolocation_by_zip materialized view
-- Run as: psql -U postgres -d text2sql -f scripts/init_db.sql

-- ============================================================================
-- 1. Create read-only role (nl2sql_ro)
-- ============================================================================

-- Drop role if exists (cascade to reassign owned objects)
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'nl2sql_ro') THEN
        -- Reassign owned objects before dropping
        REASSIGN OWNED BY nl2sql_ro TO postgres;
        DROP OWNED BY nl2sql_ro;
        DROP ROLE nl2sql_ro;
    END IF;
END
$$;

-- Create read-only role
CREATE ROLE nl2sql_ro WITH LOGIN PASSWORD 'nl2sql_ro_password';

-- Set default transaction to read-only
ALTER ROLE nl2sql_ro SET default_transaction_read_only = on;

-- Set statement timeout (30 seconds default)
ALTER ROLE nl2sql_ro SET statement_timeout = '30s';

-- ============================================================================
-- 2. Grant SELECT permissions on all tables
-- ============================================================================

-- Grant usage on schema
GRANT USAGE ON SCHEMA public TO nl2sql_ro;

-- Grant SELECT on all existing tables
GRANT SELECT ON customers TO nl2sql_ro;
GRANT SELECT ON sellers TO nl2sql_ro;
GRANT SELECT ON products TO nl2sql_ro;
GRANT SELECT ON product_category_translation TO nl2sql_ro;
GRANT SELECT ON orders TO nl2sql_ro;
GRANT SELECT ON order_items TO nl2sql_ro;
GRANT SELECT ON order_payments TO nl2sql_ro;
GRANT SELECT ON order_reviews TO nl2sql_ro;
GRANT SELECT ON geolocation TO nl2sql_ro;

-- ============================================================================
-- 3. Create geolocation_by_zip materialized view
-- ============================================================================

-- Drop materialized view if exists
DROP MATERIALIZED VIEW IF EXISTS geolocation_by_zip CASCADE;

-- Create materialized view with aggregated geolocation data
CREATE MATERIALIZED VIEW geolocation_by_zip AS
SELECT 
    geolocation_zip_code_prefix,
    AVG(geolocation_lat) as geolocation_lat,
    AVG(geolocation_lng) as geolocation_lng,
    MODE() WITHIN GROUP (ORDER BY geolocation_city) as geolocation_city,
    MODE() WITHIN GROUP (ORDER BY geolocation_state) as geolocation_state
FROM geolocation
GROUP BY geolocation_zip_code_prefix;

-- Create unique index for refresh and joins
CREATE UNIQUE INDEX idx_geolocation_by_zip_prefix ON geolocation_by_zip(geolocation_zip_code_prefix);

-- Grant SELECT on the view
GRANT SELECT ON geolocation_by_zip TO nl2sql_ro;

-- ============================================================================
-- 4. Set default privileges for future tables
-- ============================================================================

-- Ensure future tables in public schema grant SELECT to nl2sql_ro
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO nl2sql_ro;

-- ============================================================================
-- 5. Verify setup
-- ============================================================================

-- Show role configuration
SELECT rolname, rolconfig 
FROM pg_roles 
WHERE rolname = 'nl2sql_ro';

-- Show granted tables
SELECT table_name, privilege_type
FROM information_schema.role_table_grants
WHERE grantee = 'nl2sql_ro'
ORDER BY table_name;

-- Verify materialized view
SELECT COUNT(*) as row_count FROM geolocation_by_zip;

-- ============================================================================
-- 6. Refresh instructions
-- ============================================================================

-- To refresh the materialized view (run periodically via cron):
-- REFRESH MATERIALIZED VIEW geolocation_by_zip;

-- Or concurrently (allows reads during refresh):
-- REFRESH MATERIALIZED VIEW CONCURRENTLY geolocation_by_zip;
