# Optimistic Merge System - Testing Quick Start

## 🚀 Quick Start (3 Steps)

### Step 1: Upload Your Test Documents (30 seconds)

```powershell
docker-compose exec web python scripts/upload_test_documents.py
```

**What this does:**
- Creates a test patient (if needed)
- Uploads all 3 PDFs from `test_documents/` folder
- Creates Document records with IDs

**Output:**
```
✓ Created test patient: Test Patient (MRN: TEST-0001)
📄 Uploading: mock_medical_document_test_patient.pdf
   ✓ Created Document 67
📄 Uploading: mockedup_medical_document.pdf
   ✓ Created Document 68
📄 Uploading: Michael Sims BH 12_28_23.pdf
   ✓ Created Document 69
```

---

### Step 2: Test Single Document (1-2 minutes)

```powershell
docker-compose exec web python manage.py test_document_processing 67 --verbose
```

**What this does:**
- Processes document 67
- Runs quality checks (5 criteria)
- Merges FHIR data immediately
- Shows detailed results

**Expected Output:**
```
🔄 Processing document 67...
✓ Processing complete! (45.23s)

==================================================
DOCUMENT 67 - PROCESSING RESULTS
==================================================

📄 Document Info:
   File: mock_medical_document_test_patient.pdf
   Patient: Test Patient (MRN: TEST-0001)
   Status: completed

🔍 Quality Check Results:
   ✓ AUTO-APPROVED
   Review Status: auto_approved
   Confidence: 92.5%
   AI Model: claude-3-sonnet

📊 FHIR Extraction:
   Resources Extracted: 5
   Resource Breakdown:
     - Condition: 2
     - Observation: 2
     - MedicationStatement: 1

🔄 Merge Status:
   ✓ MERGED to patient record
   Merged At: 2025-12-17 17:30:45

👤 Patient FHIR Bundle:
   Total Resources: 5
```

---

### Step 3: Run Batch Test with Metrics (2-5 minutes)

```powershell
docker-compose exec web python scripts/test_optimistic_merge_batch.py
```

**What this does:**
- Processes all pending documents
- Collects comprehensive metrics
- Validates flag rates (target: 5-20%)
- Provides recommendations

**Expected Output:**
```
==================================================
OPTIMISTIC CONCURRENCY MERGE SYSTEM - BATCH TEST
==================================================

[1/3] Processing Document 67
  ✓ AUTO-APPROVED
  Confidence: 92.5%
  Resources: 5

[2/3] Processing Document 68
  ⚠ FLAGGED
  Confidence: 72.3%
  Resources: 2
  Flag Reason: Low extraction confidence: 0.723

[3/3] Processing Document 69
  ✓ AUTO-APPROVED
  Confidence: 88.1%
  Resources: 12

==================================================
TEST SUMMARY
==================================================

📊 Overall Statistics:
  Total Documents: 3
  Successful: 3
  Failed: 0

✓ Approval Statistics:
  Auto-Approved: 2 (66.7%)
  Flagged: 1 (33.3%)
  ⚠ Flag rate is ABOVE target (> 20%) - thresholds may be too strict

⚠ Flag Reasons Breakdown:
  - Low extraction confidence: 1 (100.0%)

📈 Confidence Scores:
  Average: 84.3%
  Minimum: 72.3%
  Maximum: 92.5%

📊 Resource Extraction:
  Average Resources: 6.3
  Minimum Resources: 2
  Maximum Resources: 12

⏱ Performance Metrics:
  Average Processing Time: 48.52s
  Fastest: 42.11s
  Slowest: 56.34s

💡 RECOMMENDATIONS:
--------------------------------------------------
⚠ Flag rate is HIGH (> 20%):
  - Consider loosening quality thresholds
  - Decrease confidence threshold from 0.80 to 0.75
```

---

## 📋 What Gets Tested

### Quality Checks (5 Criteria)
1. ✅ **Confidence Check:** < 0.80 → Flag
2. ✅ **Fallback Model:** GPT used → Flag
3. ✅ **Zero Resources:** No FHIR → Flag
4. ✅ **Low Resource Count:** < 3 resources + < 0.95 confidence → Flag
5. ✅ **Patient Conflicts:** DOB/name mismatch → Flag

### Optimistic Merge Behavior
- ✅ **Auto-approved documents:** Merge immediately
- ✅ **Flagged documents:** ALSO merge immediately (optimistic!)
- ✅ **Rollback capability:** Can undo merges if needed
- ✅ **HIPAA audit trail:** All actions logged

---

## 🎯 Success Criteria

### For Task 41.21 (Staging Validation)
- ✅ Documents process without errors
- ✅ Quality checks run correctly
- ✅ Data merges to patient records
- ✅ Audit trails created
- ✅ Performance acceptable (< 60s per document)

### For Task 41.22 (Threshold Tuning)
- ✅ Flag rate between 5-20%
- ✅ High-quality docs auto-approve
- ✅ Low-quality docs get flagged
- ✅ No false negatives (bad data auto-approved)

---

## 🔧 Troubleshooting

### "No pending documents found"
```powershell
# Re-upload test documents
docker-compose exec web python scripts/upload_test_documents.py
```

### "Document already processed"
```powershell
# Reset a document to pending
docker-compose exec web python manage.py shell
>>> from apps.documents.models import Document, ParsedData
>>> doc = Document.objects.get(id=67)
>>> doc.status = 'pending'
>>> doc.save()
>>> ParsedData.objects.filter(document=doc).delete()
>>> exit()
```

### AI Processing Fails
Check API keys are configured:
```powershell
# Check .env file has ANTHROPIC_API_KEY
cat .env | grep ANTHROPIC

# Or check mcp.json for Cursor
cat .cursor/mcp.json | grep ANTHROPIC
```

---

## 📊 What's Next

After successful testing:

1. **Adjust Thresholds** (if needed)
   - Edit `apps/documents/models.py`
   - Modify `ParsedData.determine_review_status()`
   - Change confidence/resource thresholds
   - Re-test with batch script

2. **Build Flagged Items UI** (Tasks 41.23-41.26)
   - Dashboard widget
   - List view with filtering
   - Detail view for verification
   - Action handlers (Mark Correct, Correct Data, Rollback)

3. **Deploy to Production** (Task 41.27)
   - System is validated and ready
   - UI complete
   - Documentation updated

---

## 📁 Files Created

- `apps/documents/management/commands/test_document_processing.py` - Single doc testing
- `scripts/test_optimistic_merge_batch.py` - Batch testing with metrics
- `scripts/upload_test_documents.py` - Upload utility
- `test_documents/README.md` - Detailed testing guide
- `TESTING_QUICKSTART.md` - This file

---

## ✅ You're Ready!

Run the 3 steps above to validate the optimistic merge system with your test documents. The entire process takes about 5-10 minutes.

**Questions?** Check `test_documents/README.md` for detailed troubleshooting and advanced usage.

