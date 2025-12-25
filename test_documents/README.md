# Test Documents for Optimistic Merge System

This directory contains test documents for validating the optimistic concurrency merge system (Task 41).

## Test Documents

1. **mock_medical_document_test_patient.pdf** (3.5KB)
   - Small mock medical document
   - Good for quick testing

2. **mockedup_medical_document.pdf** (5.1KB)
   - Another mock medical document
   - Good for testing different formats

3. **Michael Sims BH 12_28_23.pdf** (643KB)
   - Real Banner Health medical document
   - Comprehensive test with actual medical data
   - Tests extraction quality and performance

## Testing Workflow

### Step 1: Upload Test Documents

Upload all PDF files to create Document records:

```bash
# In Docker
docker-compose exec web python scripts/upload_test_documents.py

# Or locally with venv
venv\Scripts\activate; python scripts/upload_test_documents.py
```

This will:
- Create a test patient (if needed)
- Upload all PDFs from this directory
- Create Document records with status='pending'
- Display document IDs for testing

### Step 2: Test Single Document Processing

Process one document to see detailed results:

```bash
# Process a specific document
docker-compose exec web python manage.py test_document_processing <document_id>

# Example
docker-compose exec web python manage.py test_document_processing 67

# With verbose output (shows FHIR resource breakdown)
docker-compose exec web python manage.py test_document_processing 67 --verbose
```

**Output includes:**
- Document info (file, patient, status)
- Quality check results (auto-approved vs flagged)
- Review status and confidence score
- Flag reason (if flagged)
- FHIR resources extracted (count and types)
- Merge status (merged to patient record or not)
- Patient bundle size (total resources)
- Processing time

### Step 3: Process All Pending Documents

Process all uploaded documents at once:

```bash
docker-compose exec web python manage.py test_document_processing --all
```

### Step 4: Run Batch Test with Metrics

Get comprehensive metrics and validation:

```bash
docker-compose exec web python scripts/test_optimistic_merge_batch.py
```

**Metrics collected:**
- Overall statistics (total, successful, failed)
- Approval rates (auto-approved vs flagged percentages)
- Flag reasons breakdown
- Confidence score statistics (avg, min, max)
- Resource extraction statistics
- Performance metrics (processing times)
- Detailed results table
- Recommendations for threshold tuning

**Target validation:**
- ✓ Flag rate should be 5-20%
- ✓ If < 5%: Thresholds too lenient
- ✓ If > 20%: Thresholds too strict

## Alternative: Upload and Process in One Step

Upload a new document and process it immediately:

```bash
docker-compose exec web python manage.py test_document_processing \
  --upload test_documents/mock_medical_document_test_patient.pdf \
  --patient-id 1 \
  --verbose
```

## Expected Results

### High-Quality Document (Should Auto-Approve)
- Confidence > 0.80
- Primary AI model (Claude)
- 3+ FHIR resources extracted
- No patient data conflicts

**Result:** `review_status='auto_approved'`, `auto_approved=True`, merged immediately

### Low-Quality Document (Should Flag)
- Confidence < 0.80, OR
- Fallback model (GPT) used, OR
- < 3 resources extracted, OR
- Patient data conflicts detected

**Result:** `review_status='flagged'`, `auto_approved=False`, but still merged (optimistic concurrency)

## Quality Check Criteria

The system flags documents based on these 5 checks:

1. **Low Confidence:** extraction_confidence < 0.80
2. **Fallback Model:** GPT model used instead of Claude
3. **Zero Resources:** No FHIR resources extracted
4. **Low Resource Count:** < 3 resources AND confidence < 0.95
5. **Patient Conflicts:** DOB or name mismatch with patient record

## Troubleshooting

### No Pending Documents
```bash
# Check document status
docker-compose exec web python manage.py shell
>>> from apps.documents.models import Document
>>> Document.objects.values('id', 'status').all()
```

### Document Already Processed
The system prevents duplicate processing. To reprocess:
```bash
# Reset document status
docker-compose exec web python manage.py shell
>>> from apps.documents.models import Document, ParsedData
>>> doc = Document.objects.get(id=67)
>>> doc.status = 'pending'
>>> doc.save()
>>> ParsedData.objects.filter(document=doc).delete()
```

### View Patient FHIR Bundle
```bash
docker-compose exec web python manage.py shell
>>> from apps.patients.models import Patient
>>> patient = Patient.objects.first()
>>> bundle = patient.encrypted_fhir_bundle
>>> len(bundle.get('entry', []))  # Total resources
>>> [e['resource']['resourceType'] for e in bundle['entry']]  # Resource types
```

## Performance Benchmarks

From Task 41.20 performance tests:
- 10 resources: ~0.5ms (100x faster than 50ms target)
- 50 resources: ~0.7ms (270x faster than 200ms target)
- 100 resources: ~1.1ms (470x faster than 500ms SLA)

Your test documents should process well under these targets.

## Next Steps After Testing

1. **Validate Flag Rates** (Task 41.22)
   - Run batch test on 10-20 documents
   - Check if flag rate is 5-20%
   - Adjust thresholds in `ParsedData.determine_review_status()` if needed

2. **Build Flagged Items UI** (Tasks 41.23-41.26)
   - Dashboard widget showing flagged count
   - List view for flagged documents
   - Detail view for verification
   - Action handlers (Mark Correct, Correct Data, Rollback)

3. **Deploy to Production** (Task 41.27)
   - Remove obsolete code
   - Update documentation
   - Deploy with confidence

## Files Created for Testing

- `apps/documents/management/commands/test_document_processing.py` - Single document testing
- `scripts/test_optimistic_merge_batch.py` - Batch testing with metrics
- `scripts/upload_test_documents.py` - Upload utility
- `test_documents/README.md` - This file

## Questions?

If you encounter issues:
1. Check Docker logs: `docker-compose logs web`
2. Check Celery logs: `docker-compose logs celery`
3. Check database: Documents should have `status='pending'` before processing
4. Verify AI API keys are configured in `.env` or `mcp.json`

