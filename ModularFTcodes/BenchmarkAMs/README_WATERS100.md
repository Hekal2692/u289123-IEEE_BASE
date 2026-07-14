# WATERS-100 application models

These files are generated for direct use with the existing HGA scheduler. The scheduler-facing files intentionally keep the same schema as `TC100_NewPM.json` and the current partitioned AM files.

## Files to use in the code

- `WATERS100_NewPM.json` -> replace `TC100_NewPM.json` / `FullAMAddress` / `FullPMAddress`.
- `WATERS100_FogEdgePartitionedTasks_merged_strict.json` -> replace `FogEdgePartitionedTasks_merged_strict.json`.
- `WATERS100_Cloud1PartitionedData_merged.json` -> replace `Cloud1PartitionedData_merged.json`.
- `WATERS100_Cloud2PartitionedData_merged.json` -> replace `Cloud2PartitionedData_merged.json`.
- `WATERS100_Cloud3PartitionedData_merged.json` -> replace `Cloud3PartitionedData_merged.json`.

The platform graph in `WATERS100_NewPM.json` is copied from the original `TC100_NewPM.json`, so no platform parsing change is required.

## Generated workload summary

- Jobs: 100
- Messages: 212
- DAG acyclic: True
- Partition job counts: {'FE': 72, 'C1': 3, 'C2': 20, 'C3': 5}
- Partition message counts: {'FE': 113, 'C1': 0, 'C2': 23, 'C3': 1}
- Inter-partition messages in full AM: 75
- Intra-partition messages in full AM: 137
- Random seed: 20260703

## Important wording

This is a WATERS-derived scheduler-compatible application model, not a proprietary vehicle trace and not a TSN/DetNet testbed measurement. It preserves published WATERS workload characteristics while projecting them into the DAG-based AM expected by the scheduler.
