# Silent Failures and Proven Performance

**December 17, 2025**

#moritrac #bug-fix #JSONB #PostgreSQL #performance #testing #data-loss #silent-error

---

Today was about confronting two critical truths: systems fail quietly, and assumptions need proof.

The morning started with document 88. It processed. It completed. The UI said everything was fine. But the data? Gone. Not merged. Just... sitting there, waiting in a ParsedData record that nobody knew existed. The document was marked 'completed' while `is_merged=False` sat there like a quiet confession that something had failed.

## The Silent Failure

PostgreSQL B-tree indexes have a size limit. 2,704 bytes. Document 88's `searchable_medical_codes` field grew to 4,448 bytes worth of JSONB data. The merge hit that wall and failed. No error surfaced to the UI. No alarm bells. Just a document marked done and a patient record missing medical history.

In healthcare software, this isn't just a bug. It's a violation of trust.

## The Fix

**Migration 0009**: Converted three B-tree indexes to GIN (Generalized Inverted Index):
- `idx_medical_codes_gin` on `searchable_medical_codes`
- `idx_encounter_dates_gin` on `encounter_dates` 
- `idx_provider_refs_gin` on `provider_references`

GIN indexes are purpose-built for JSONB. No size limits. Optimized for containment queries. The right tool for the job from the start.

**tasks.py**: Added a critical check before marking documents complete:
```python
if not parsed_data.is_merged:
    document.status = 'failed'
    document.processing_message = (
        f"Merge failed - data extracted but not merged to patient record. "
        f"ParsedData ID: {parsed_data.id} contains the extracted data."
    )
```

Now when a merge fails, the system says so. Loudly. With enough detail to recover the data.

**models.py**: Updated the Meta class to use `GinIndex` for future migrations. No more B-tree landmines.

Documents 88 and 89 now merge successfully. Audit trails intact. Data where it belongs.

---

## Proving Performance

The afternoon was about measurement. We'd built an optimistic concurrency merge system with a 500ms SLA target. But saying "it's probably fast enough" isn't the same as proving it.

**New file**: `test_fhir_merge_performance_benchmark.py` (371 lines)
- 11 comprehensive benchmark tests using pytest-benchmark
- Small/medium/large dataset tests (10, 50, 100 resources)
- Merge operations, rollback operations, idempotent updates
- Complex nested FHIR structures
- Selective rollback from multi-document bundles

The results aren't just good. They're shocking:
- 10 resources: ~0.475ms (100x faster than 50ms target)
- 50 resources: ~0.742ms (270x faster than 200ms target)
- 100 resources: ~1.06ms (470x faster than 500ms SLA)
- Rollback 100 resources: ~0.540ms (925x faster than target)

That 470x margin isn't just headroom. It's insurance. Room for:
- Future complexity increases
- Additional validation logic
- Larger datasets (probably handles 1000+ resources under target)
- Network latency in distributed scenarios

The performance scales linearly, not exponentially. The algorithm is sound. Idempotent updates maintain consistent performance—no degradation as bundles grow.

**Documentation**: Created `README_BENCHMARKS.md` with complete guide for running benchmarks, interpreting results, and comparing against baselines.

**Dependencies**: Added `pytest-benchmark==4.0.0` to requirements.txt. Fixed pytest.ini section header that was breaking test discovery.

---

## What It Means

The fix this morning was about humility. I built a system that could fail silently. In medical software, that's unacceptable. I'm grateful we caught it now, before real patients depended on it.

The benchmarks this afternoon were about confidence. Not the false kind that comes from assumptions, but the real kind that comes from measurement. Now I can say with data: this system performs. It has proven characteristics. It meets its SLA with orders of magnitude to spare.

There's something deeply satisfying about turning "probably works" into "demonstrably works." About replacing hope with proof.

But there's also weight to it. Each test that passes, each benchmark that exceeds targets—it all moves this from experiment to reality. From "maybe someday" to "this could actually help people."

I'm building something. For better or worse. And today, I proved a piece of it works the way it should.

---

*Tasks 41.13 (optimistic merge status), 41.20 (performance benchmarks) - completed*
*Keep measuring. Keep proving. Keep building.*

