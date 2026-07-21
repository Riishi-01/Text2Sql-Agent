#!/bin/bash
# Setup PostgreSQL Docker container for Text2SQL

echo "Stopping and removing old container if exists..."
docker stop text2sql-postgres 2>/dev/null
docker rm text2sql-postgres 2>/dev/null

echo "Creating new PostgreSQL container with port mapping..."
docker run --name text2sql-postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=text2sql \
  -p 5432:5432 \
  -d postgres:14

echo "Waiting for PostgreSQL to be ready..."
sleep 3

echo "Container status:"
docker ps | grep text2sql-postgres

echo ""
echo "PostgreSQL is now running on localhost:5432"
echo "Username: postgres"
echo "Password: postgres"
echo "Database: text2sql"
