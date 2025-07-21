#!/usr/bin/env python
"""
Database Query Script for Medical Document Parser

This script allows you to run raw SQL queries against your Django database.
Think of it as a direct connection to your database engine - no Django ORM middleman.

Usage:
    python db_query.py "SELECT * FROM patients LIMIT 5;"
    python db_query.py "SHOW TABLES;" (MySQL/MariaDB)
    python db_query.py "SELECT name FROM sqlite_master WHERE type='table';" (SQLite)
    python db_query.py "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';" (PostgreSQL)

Security Note: This is for development use only. Never use with untrusted input.
"""

import os
import sys
import django
from django.conf import settings
from django.db import connection


def setup_django():
    """
    Set up Django environment so we can use the database connection.
    """
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.development')
    django.setup()


def execute_query(sql_query):
    """
    Execute a raw SQL query and return the results.
    
    Args:
        sql_query (str): The SQL query to execute
        
    Returns:
        list: Query results
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql_query)
            
            # Check if this is a SELECT query (returns data)
            if sql_query.strip().upper().startswith('SELECT') or sql_query.strip().upper().startswith('SHOW'):
                # Fetch column names
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                # Fetch all rows
                rows = cursor.fetchall()
                return columns, rows
            else:
                # For INSERT, UPDATE, DELETE, etc.
                return None, f"Query executed successfully. Rows affected: {cursor.rowcount}"
                
    except Exception as e:
        return None, f"Error executing query: {str(e)}"


def format_results(columns, rows):
    """
    Format query results in a nice table format.
    
    Args:
        columns (list): Column names
        rows (list): Query result rows
    """
    if not columns:
        return "No results returned."
    
    # Calculate column widths
    col_widths = []
    for i, col in enumerate(columns):
        max_width = len(str(col))
        for row in rows:
            if i < len(row):
                max_width = max(max_width, len(str(row[i])))
        col_widths.append(min(max_width, 50))  # Cap at 50 chars
    
    # Create header
    header = " | ".join(str(col).ljust(width) for col, width in zip(columns, col_widths))
    separator = "-" * len(header)
    
    # Format rows
    formatted_rows = []
    for row in rows:
        formatted_row = " | ".join(
            str(row[i] if i < len(row) else "").ljust(width)[:width]
            for i, width in enumerate(col_widths)
        )
        formatted_rows.append(formatted_row)
    
    return f"\n{header}\n{separator}\n" + "\n".join(formatted_rows)


def show_help():
    """
    Show usage help and common queries.
    """
    help_text = """
Database Query Tool - Usage Examples:

BASIC QUERIES:
  python db_query.py "SELECT COUNT(*) FROM patients;"
  python db_query.py "SELECT * FROM providers LIMIT 5;"
  python db_query.py "SELECT mrn, first_name, last_name FROM patients;"

LIST TABLES (Database-specific):
  PostgreSQL: python db_query.py "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
  SQLite:     python db_query.py "SELECT name FROM sqlite_master WHERE type='table';"
  MySQL:      python db_query.py "SHOW TABLES;"

DESCRIBE TABLE STRUCTURE:
  PostgreSQL: python db_query.py "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'patients';"
  SQLite:     python db_query.py "PRAGMA table_info(patients);"
  MySQL:      python db_query.py "DESCRIBE patients;"

AUDIT QUERIES:
  python db_query.py "SELECT action, COUNT(*) FROM patient_history GROUP BY action;"
  python db_query.py "SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT 10;"

Remember: This is for development only. Always be careful with raw SQL!
"""
    print(help_text)


def main():
    """
    Main function to handle command line arguments and execute queries.
    """
    if len(sys.argv) < 2:
        print("Error: No SQL query provided.")
        show_help()
        sys.exit(1)
    
    if sys.argv[1] in ['-h', '--help', 'help']:
        show_help()
        sys.exit(0)
    
    # Set up Django
    try:
        setup_django()
    except Exception as e:
        print(f"Error setting up Django: {e}")
        sys.exit(1)
    
    # Get the SQL query from command line
    sql_query = " ".join(sys.argv[1:])
    
    print(f"Executing query: {sql_query}")
    print("=" * 60)
    
    # Execute the query
    columns, result = execute_query(sql_query)
    
    if columns:
        # This was a SELECT query with results
        if isinstance(result, list) and len(result) > 0:
            formatted = format_results(columns, result)
            print(formatted)
            print(f"\nRows returned: {len(result)}")
        else:
            print("Query executed successfully, but no rows returned.")
    else:
        # This was a non-SELECT query or an error
        print(result)


if __name__ == "__main__":
    main() 