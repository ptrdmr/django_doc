#!/usr/bin/env python
"""
Debug script to check environment variable reading
"""

from decouple import config

# Check what we're actually getting from the .env file
db_engine_raw = config('DB_ENGINE', default='NOT_SET')
print(f"Raw DB_ENGINE value: [{db_engine_raw}]")
print(f"Length: {len(db_engine_raw)}")
print(f"Type: {type(db_engine_raw)}")
print(f"Stripped: [{db_engine_raw.strip()}]")
print(f"Equals 'postgresql': {db_engine_raw == 'postgresql'}")
print(f"Stripped equals 'postgresql': {db_engine_raw.strip() == 'postgresql'}")

# Check other variables too
print(f"\nOther variables:")
print(f"DB_NAME: [{config('DB_NAME', default='NOT_SET')}]")
print(f"DB_PASSWORD: [{config('DB_PASSWORD', default='NOT_SET')}]")
print(f"DB_HOST: [{config('DB_HOST', default='NOT_SET')}]") 