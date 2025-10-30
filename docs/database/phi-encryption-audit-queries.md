# Direct PostgreSQL Access for PHI Encryption Audits

## Quick Access Commands

### 1. Connect to Docker PostgreSQL
```bash
docker exec -it doc2db_2025_django-db-1 psql -U postgres -d meddocparser
```

### 2. Direct psql Connection (if needed)
```bash
psql -h localhost -p 5432 -U postgres -d meddocparser
# Password: postgres123
```

## Key SQL Commands for Auditors

### 3. Show Encrypted PHI Data (What's Actually Stored)
```sql
-- Show encrypted data lengths (should be 89 bytes for Fernet encryption)
SELECT mrn, 
       length(first_name) as name_bytes, 
       length(last_name) as lastname_bytes, 
       length(ssn) as ssn_bytes 
FROM patients LIMIT 3;

-- Show actual encrypted hex data 
SELECT mrn, 
       encode(first_name, 'hex') as encrypted_first_name
FROM patients LIMIT 2;

-- Show multiple encrypted fields
SELECT mrn,
       substring(encode(first_name, 'hex'), 1, 40) || '...' as encrypted_name,
       substring(encode(ssn, 'hex'), 1, 40) || '...' as encrypted_ssn
FROM patients LIMIT 3;
```

### 4. Security Tests (Should Return 0 Results)
```sql
-- Try to search for plaintext names (should find nothing)
SELECT COUNT(*) as found_patients FROM patients WHERE first_name = 'John';
SELECT COUNT(*) as found_patients FROM patients WHERE first_name = 'Jane';
SELECT COUNT(*) as found_patients FROM patients WHERE last_name = 'Smith';

-- Try to search for plaintext SSN (should find nothing)
SELECT COUNT(*) as found_ssn FROM patients WHERE ssn = '123456789';
```

### 5. Database Schema Verification
```sql
-- Show PHI field data types (should be 'bytea' for encrypted fields)
SELECT column_name, data_type, is_nullable
FROM information_schema.columns 
WHERE table_name = 'patients' 
AND column_name IN ('first_name', 'last_name', 'ssn', 'address', 'phone', 'email')
ORDER BY column_name;

-- Show table structure
\d patients
```

### 6. Audit Queries for Compliance
```sql
-- Count total patients with encrypted data
SELECT COUNT(*) as total_patients FROM patients WHERE deleted_at IS NULL;

-- Show creation dates of patient records
SELECT DATE(created_at) as date_created, COUNT(*) as patients_created
FROM patients 
GROUP BY DATE(created_at) 
ORDER BY date_created DESC;

-- Verify all PHI fields are present and encrypted
SELECT 
    COUNT(CASE WHEN first_name IS NOT NULL THEN 1 END) as has_first_name,
    COUNT(CASE WHEN last_name IS NOT NULL THEN 1 END) as has_last_name,
    COUNT(CASE WHEN ssn IS NOT NULL THEN 1 END) as has_ssn,
    COUNT(*) as total_patients
FROM patients 
WHERE deleted_at IS NULL;
```

## What Auditors Should See

### ✅ Expected Results (Encryption Working):
- **Encrypted Data**: PHI fields show as binary/hex data like `800000000068b6faec97516d4d...`
- **Data Length**: Encrypted fields are exactly 89 bytes (Fernet encryption overhead)
- **Search Failure**: Searching for plaintext values returns 0 results
- **Data Type**: PHI fields are stored as `bytea` (binary) type
- **No Plaintext**: No readable PHI visible in raw database queries

### ❌ Red Flags (Encryption NOT Working):
- PHI fields showing as readable text
- Successful searches for plaintext values
- PHI fields stored as `text` or `varchar` types
- Inconsistent field lengths
- Readable names/SSNs in database dumps

## Interactive Session Example

```bash
# Connect to database
docker exec -it doc2db_2025_django-db-1 psql -U postgres -d meddocparser

# Run audit commands
meddocparser=# SELECT mrn, encode(first_name, 'hex') FROM patients LIMIT 1;
meddocparser=# SELECT COUNT(*) FROM patients WHERE first_name = 'John';
meddocparser=# \d patients
meddocparser=# \q
```

## For Compliance Officers

This demonstrates:
- **HIPAA §164.312(a)(2)(iv)** - Encryption of PHI ✅
- **Data at Rest Protection** - Database stores only encrypted data ✅  
- **Breach Mitigation** - Stolen database would not expose readable PHI ✅
- **Access Controls** - Only application can decrypt data ✅
