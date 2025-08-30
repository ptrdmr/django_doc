import os
import django
import json
from dotenv import load_dotenv
import pathlib

# Explicitly find and load the .env file from the project root
project_root = pathlib.Path(__file__).parent.resolve()
dotenv_path = project_root / '.env'
if dotenv_path.exists():
    print(f">>> Loading environment variables from: {dotenv_path}")
    load_dotenv(dotenv_path=dotenv_path)
else:
    print(f"--- WARNING: .env file not found at {dotenv_path} ---")

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings')
django.setup()

from apps.documents.models import Document, ParsedData

def check_last_parsed_data():
    """
    Fetches and prints the raw extraction_json from the most recently
    processed document's ParsedData record.
    """
    print(">>> Querying for the most recently processed document...")
    
    # Get the most recently processed document
    last_document = Document.objects.order_by('-processed_at').first()
    
    if not last_document:
        print("--- No processed documents found in the database. ---")
        return
        
    print(f">>> Found document ID: {last_document.id} (Processed at: {last_document.processed_at})")
    
    # Find the corresponding ParsedData record
    parsed_data_record = ParsedData.objects.filter(document=last_document).first()
    
    if parsed_data_record:
        print("\n--- ✅ PARSED DATA FOUND ---")
        print("Raw extraction_json from the AI:")
        
        # Pretty-print the JSON
        print(json.dumps(parsed_data_record.extraction_json, indent=2))
        
    else:
        print("\n--- ❌ NO PARSED DATA FOUND for the last processed document. ---")
        print("This indicates the AI analysis step failed to complete successfully.")

if __name__ == "__main__":
    check_last_parsed_data()
