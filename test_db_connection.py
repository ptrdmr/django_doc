#!/usr/bin/env python
"""
Test PostgreSQL connection outside of Django to isolate the issue
"""

import psycopg2
from decouple import config

# Get the same connection details Django would use
db_config = {
    'host': config('DB_HOST', default='127.0.0.1'),
    'port': config('DB_PORT', default='5432'),
    'user': config('DB_USER', default='postgres'),
    'password': config('DB_PASSWORD', default='password'),
}

print("Testing PostgreSQL connection with these settings:")
for key, value in db_config.items():
    print(f"  {key}: {value}")

print("\n" + "="*50)

# Test 1: Connect to postgres database (should always exist)
try:
    print("Test 1: Connecting to 'postgres' database...")
    conn = psycopg2.connect(database='postgres', **db_config)
    cursor = conn.cursor()
    cursor.execute("SELECT version();")
    version = cursor.fetchone()
    print(f"✅ SUCCESS! PostgreSQL version: {version[0]}")
    
    # List all databases
    cursor.execute("SELECT datname FROM pg_database ORDER BY datname;")
    databases = cursor.fetchall()
    print(f"✅ Available databases: {[db[0] for db in databases]}")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"❌ FAILED to connect to postgres database: {e}")

print("\n" + "-"*50)

# Test 2: Try to connect to meddocparser database
try:
    print("Test 2: Connecting to 'meddocparser' database...")
    conn = psycopg2.connect(database='meddocparser', **db_config)
    cursor = conn.cursor()
    cursor.execute("SELECT current_database();")
    current_db = cursor.fetchone()
    print(f"✅ SUCCESS! Connected to database: {current_db[0]}")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"❌ FAILED to connect to meddocparser database: {e}")

print("\n" + "="*50)
print("If Test 1 works but Test 2 fails, we have a database-specific issue.")
print("If both fail, we have a network/connection issue.") 