# FHIR Merge Performance Benchmarks

This directory contains performance benchmark tests for the optimistic concurrency merge system.

## Purpose

These benchmarks measure the performance of:
- `add_fhir_resources()` - Merging FHIR resources into patient records
- `rollback_document_merge()` - Rolling back document merges

## Running Benchmarks

### Run All Benchmarks
```bash
pytest apps/patients/tests/test_fhir_merge_performance_benchmark.py --benchmark-only
```

### Run Specific Benchmark
```bash
pytest apps/patients/tests/test_fhir_merge_performance_benchmark.py::TestFHIRMergePerformanceBenchmarks::test_merge_large_dataset_100_resources --benchmark-only
```

### Run with Verbose Output
```bash
pytest apps/patients/tests/test_fhir_merge_performance_benchmark.py --benchmark-only -v
```

### Save Benchmark Results
```bash
pytest apps/patients/tests/test_fhir_merge_performance_benchmark.py --benchmark-only --benchmark-save=baseline
```

### Compare Against Saved Baseline
```bash
pytest apps/patients/tests/test_fhir_merge_performance_benchmark.py --benchmark-only --benchmark-compare=baseline
```

## Performance Targets

All operations must meet these targets:
- **Small datasets (10 resources)**: <50ms average
- **Medium datasets (50 resources)**: <200ms average
- **Large datasets (100 resources)**: <500ms average (SLA requirement)

## Benchmark Tests

### Merge Operations
1. `test_merge_small_dataset_10_resources` - 10 resources
2. `test_merge_medium_dataset_50_resources` - 50 resources
3. `test_merge_large_dataset_100_resources` - 100 resources
4. `test_merge_idempotent_update_performance` - Idempotent updates
5. `test_merge_with_complex_nested_resources` - Complex FHIR structures

### Rollback Operations
1. `test_rollback_small_dataset_10_resources` - 10 resources
2. `test_rollback_medium_dataset_50_resources` - 50 resources
3. `test_rollback_large_dataset_100_resources` - 100 resources
4. `test_rollback_selective_from_multi_document_bundle` - Selective rollback

### SLA Validation
1. `test_merge_100_resources_meets_500ms_target` - Validates merge SLA
2. `test_rollback_100_resources_meets_500ms_target` - Validates rollback SLA

## Interpreting Results

Benchmark output includes:
- **Min/Max**: Fastest and slowest execution times
- **Mean**: Average execution time (primary metric)
- **StdDev**: Standard deviation (consistency indicator)
- **Median**: Middle value (less affected by outliers)
- **IQR**: Interquartile range (variability measure)
- **OPS**: Operations per second

### Example Output
```
Name                                   Min        Max       Mean    StdDev   
test_merge_large_dataset_100_resources 1.01ms    1.47ms    1.06ms  46.27us  
```

This shows the merge of 100 resources averages 1.06ms, well under the 500ms target.

## Notes

- Benchmarks use `pytest-benchmark` for accurate timing
- Each test runs multiple iterations for statistical accuracy
- Rollback tests use setup functions to ensure clean state per iteration
- All tests validate functional correctness in addition to performance

