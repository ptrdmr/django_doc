import sqlite3
import sys

conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()

# Check for document tables
print("=== Checking for document/FHIR tables ===")
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%document%' OR name LIKE '%fhir%')")
tables = cursor.fetchall()
if tables:
    print("Found tables:")
    for t in tables:
        print(f"  - {t[0]}")
else:
    print("No document/FHIR tables found in SQLite")

# Check apps_documents_document
try:
    cursor.execute("SELECT id, status, uploaded_at, processed_at FROM apps_documents_document WHERE id = 88")
    result = cursor.fetchone()
    if result:
        print(f"\n=== Document 88 in apps_documents_document ===")
        print(f"ID: {result[0]}")
        print(f"Status: {result[1]}")
        print(f"Uploaded: {result[2]}")
        print(f"Processed: {result[3]}")
    else:
        print("\nDocument 88 not found in apps_documents_document")
except sqlite3.OperationalError as e:
    print(f"\nTable apps_documents_document doesn't exist: {e}")

# Check FHIR resources
try:
    cursor.execute("SELECT COUNT(*) FROM apps_fhir_fhirresource WHERE document_id = 88")
    count = cursor.fetchone()[0]
    print(f"\n=== FHIR Resources for Document 88 ===")
    print(f"Total resources: {count}")
    
    if count > 0:
        cursor.execute("SELECT resource_type, COUNT(*) FROM apps_fhir_fhirresource WHERE document_id = 88 GROUP BY resource_type ORDER BY COUNT(*) DESC")
        rows = cursor.fetchall()
        print("\nBreakdown by type:")
        for row in rows:
            print(f"  {row[0]}: {row[1]}")
except sqlite3.OperationalError as e:
    print(f"\nTable apps_fhir_fhirresource doesn't exist: {e}")

conn.close()


