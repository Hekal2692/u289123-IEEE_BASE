Date/time: 2026-07-03T16:24:59# Benchmark AMS Run Preparation Report

Date/time: 2026-07-03T16:05:14

## Isolation
- Worktree path used: `/work/ws-tmp/u289123-IEEE_BASE/worktrees/benchmark_ams`
- Git branch: `benchmark/ams`
- Confirmation: all created/modified files for this preparation were kept inside `/work/ws-tmp/u289123-IEEE_BASE/worktrees/benchmark_ams`.
- Main repository, no_slack worktree, and static_budget worktree were not modified by this benchmark setup.

## Commands Executed
```bash
pwd
git status --short
git worktree list
mkdir -p experiments/benchmark_ams results/benchmark_ams logs/benchmark_ams
python -m py_compile experiments/benchmark_ams/validate_benchmark_ams.py experiments/benchmark_ams/run_benchmark_ams.py
bash -n experiments/benchmark_ams/run_benchmark_ams_medium_24h.sh
python experiments/benchmark_ams/validate_benchmark_ams.py > logs/benchmark_ams/validation.log 2>&1
python experiments/benchmark_ams/run_benchmark_ams.py --smoke
sbatch --test-only experiments/benchmark_ams/run_benchmark_ams_medium_24h.sh
```

## AM Files Used
Source files from `ModularFTcodes/BenchmarkAMs/`:
- `WATERS100_NewPM.json`
- `WATERS100_FogEdgePartitionedTasks_merged_strict.json`
- `WATERS100_Cloud1PartitionedData_merged.json`
- `WATERS100_Cloud2PartitionedData_merged.json`
- `WATERS100_Cloud3PartitionedData_merged.json`

The runner stages these into `experiments/benchmark_ams/runtime_platforms/100T/` using the filenames expected by the existing AM100 scheduler path. The unchanged platform files are copied from this worktree's `ModularFTcodes/Platforms/` into `experiments/benchmark_ams/runtime_platforms/`.

## Validation Summary
Validation log: `logs/benchmark_ams/validation.log`

Result: passed.

Validated counts:
- `WATERS100_NewPM.json`: 100 jobs, 212 messages, DAG acyclic.
- `WATERS100_FogEdgePartitionedTasks_merged_strict.json`: 72 jobs, 113 messages, DAG acyclic.
- `WATERS100_Cloud1PartitionedData_merged.json`: 3 jobs, 0 messages, DAG acyclic.
- `WATERS100_Cloud2PartitionedData_merged.json`: 20 jobs, 23 messages, DAG acyclic.
- `WATERS100_Cloud3PartitionedData_merged.json`: 5 jobs, 1 message, DAG acyclic.

## Scheduler Configuration Used
- Existing scheduler pipeline: `ModularFTcodes/codes/main.py` and existing HGA modules.
- No scheduling algorithm files were modified.
- AM slot used: existing `AM100`/`100T` path with staged WATERS100 inputs.
- Variant: `proposed` by default, unless another `--variant`/`VARIANT` is supplied intentionally.
- Baseline deadline: `2600`.
- Deadline ratios: `1.00 0.90 0.80 0.70`.
- Repeated-run seed list per deadline ratio: `1001 1002 1003 1004 1005 1006 1007 1008 1009 1010`.
- Full grid: 4 deadline ratios x 10 seeds = 40 benchmark runs.

## Smoke Test
Command:
```bash
python experiments/benchmark_ams/run_benchmark_ams.py --smoke
```

Result: passed after updating the benchmark-only runner to launch scheduler child processes with `ModularFTcodes/.venv/bin/python` when available. An initial smoke attempt using `/usr/bin/python` failed because that interpreter lacked `plotly`; no scheduler code was changed.

Smoke outputs:
- Log: `logs/benchmark_ams/smoke_test.log`
- Summary CSV: `results/benchmark_ams/smoke_test/smoke_summary.csv`
- Run summary: `results/benchmark_ams/smoke_test/runs/AM100/ratio1.00/seed1001/AM100__base2600__ratio1.00__deadline2600__seed1001__proposed__joblocal__tasklocal__WATERS100__seed1001__smoke/run_summary.json`

Smoke result metrics:
- Seed: `1001`
- Final global makespan: `2446`
- Deadline: `2600`
- Global lateness signed/clipped: `-154 / 0`
- Cumulative partition budget violation: `882.0`
- Runtime seconds: `256.1881631016731`
- Peak memory MB: `171.2578125`
- Selected partition allocation: unavailable in `run_summary.json`.
- Selected routes/path indices: unavailable in `run_summary.json`.

## SLURM Settings
SLURM script: `experiments/benchmark_ams/run_benchmark_ams_medium_24h.sh`

Header settings:
- Partition: `medium`
- Time: `1-00:00:00`
- Job name: `benchmark_ams`
- Array: `0-39`
- stdout: `logs/benchmark_ams/%x_%A_%a.out`
- stderr: `logs/benchmark_ams/%x_%A_%a.err`

Array mapping:
- Deadline ratios: `1.00 0.90 0.80 0.70`
- Seeds per ratio: `1001 1002 1003 1004 1005 1006 1007 1008 1009 1010`
- Each Slurm array task runs exactly one `(deadline_ratio, seed)` pair.

Dry check command:
```bash
sbatch --test-only experiments/benchmark_ams/run_benchmark_ams_medium_24h.sh
```

Dry check result: passed.

Dry check output:
```text
sbatch: Job 11902930 to start at 2026-07-05T22:47:57 using 1 processors on nodes hpc-node127 in partition medium
```

Submit later with:
```bash
sbatch experiments/benchmark_ams/run_benchmark_ams_medium_24h.sh
```

## Full-Run Output Plan
The full batch script launches 40 independent Slurm array tasks: one task per deadline ratio and seed.

Per-task outputs:
- Slurm stdout/stderr: `logs/benchmark_ams/benchmark_ams_<job>_<task>.out/.err`
- Validation log: `logs/benchmark_ams/validation_ratioXXX_seedYYYY.log`
- Runner log: `logs/benchmark_ams/run_ratioXXX_seedYYYY.log`
- Task summary CSV: `results/benchmark_ams/summaries/benchmark_ams_ratioXXX_seedYYYY.csv`
- Nested scheduler outputs under: `results/benchmark_ams/runs/`

After all array tasks finish, collect one combined CSV with:
```bash
python experiments/benchmark_ams/run_benchmark_ams.py --collect-only --output-root results/benchmark_ams/runs --summary-csv results/benchmark_ams/benchmark_ams_summary.csv
```

## Files Created or Modified
- `experiments/benchmark_ams/validate_benchmark_ams.py`
- `experiments/benchmark_ams/run_benchmark_ams.py`
- `experiments/benchmark_ams/run_benchmark_ams_medium_24h.sh`
- `experiments/benchmark_ams/runtime_platforms/100T/TC100_NewPM.json`
- `experiments/benchmark_ams/runtime_platforms/100T/FogEdgePartitionedTasks_merged_strict.json`
- `experiments/benchmark_ams/runtime_platforms/100T/Cloud1PartitionedData_merged.json`
- `experiments/benchmark_ams/runtime_platforms/100T/Cloud2PartitionedData_merged.json`
- `experiments/benchmark_ams/runtime_platforms/100T/Cloud3PartitionedData_merged.json`
- `experiments/benchmark_ams/runtime_platforms/FEPlatform.json`
- `experiments/benchmark_ams/runtime_platforms/CloudModel1.json`
- `experiments/benchmark_ams/runtime_platforms/CloudModel2.json`
- `experiments/benchmark_ams/runtime_platforms/CloudModel3.json`
- `logs/benchmark_ams/validation.log`
- `logs/benchmark_ams/smoke_test.log`
- `results/benchmark_ams/smoke_test/smoke_summary.csv`
- `results/benchmark_ams/smoke_test/runs/...` scheduler smoke outputs
- `results/benchmark_ams/BENCHMARK_AMS_RUN_REPORT.md`

All listed files are inside the benchmark worktree.

## Errors and Assumptions
- Assumption: WATERS100 should use the existing AM100 baseline deadline setup (`BASE_DEADLINE=2600`) because the request asked to reuse the existing 100-task baseline experiment. The benchmark now sweeps deadline ratios `1.00`, `0.90`, `0.80`, and `0.70`.
- Assumption: The existing 10-seed repeated setup is `1001` through `1010`, as found in the local cluster scripts.
- The scheduler only supports built-in AM IDs in `main.py`; to avoid algorithm/code changes, the runner stages WATERS100 files into an isolated runtime `100T` layout and sets `PLATFORMS_DIR` to that runtime directory.
- Initial smoke attempt failed with `/usr/bin/python` missing `plotly`; the runner now uses the worktree `.venv` Python for scheduler child processes when available.
