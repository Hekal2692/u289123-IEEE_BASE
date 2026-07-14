#!/usr/bin/env python3
"""Run the WATERS100 benchmark through the existing scheduler pipeline.

This script does not modify scheduler code. It stages the benchmark AM into an
isolated runtime Platforms tree with the filenames expected by the existing
AM100 baseline path, then executes codes/main.py in child Python processes.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
from datetime import datetime

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_DIR = WORKTREE_ROOT / "ModularFTcodes"
CODE_DIR = PROJECT_DIR / "codes"
BENCHMARK_DIR = PROJECT_DIR / "BenchmarkAMs"
EXPERIMENT_DIR = WORKTREE_ROOT / "experiments" / "benchmark_ams"
RESULTS_DIR = WORKTREE_ROOT / "results" / "benchmark_ams"
LOG_DIR = WORKTREE_ROOT / "logs" / "benchmark_ams"
RUNTIME_PLATFORMS_DIR = EXPERIMENT_DIR / "runtime_platforms"
RUNTIME_AM100_DIR = RUNTIME_PLATFORMS_DIR / "100T"
LOCAL_VENV_PYTHON = PROJECT_DIR / ".venv" / "bin" / "python"
HOME_VENV_PYTHON = Path.home() / "venvs" / "ftcodes311" / "bin" / "python"

SEEDS = [1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008, 1009, 1010]
BASE_DEADLINE = 2600
DEADLINE_RATIOS = ["1.00", "0.90", "0.80", "0.70"]

AM_STAGE_MAP = {
    "WATERS100_NewPM.json": "TC100_NewPM.json",
    "WATERS100_FogEdgePartitionedTasks_merged_strict.json": "FogEdgePartitionedTasks_merged_strict.json",
    "WATERS100_Cloud1PartitionedData_merged.json": "Cloud1PartitionedData_merged.json",
    "WATERS100_Cloud2PartitionedData_merged.json": "Cloud2PartitionedData_merged.json",
    "WATERS100_Cloud3PartitionedData_merged.json": "Cloud3PartitionedData_merged.json",
}
PLATFORM_FILES = ["FEPlatform.json", "CloudModel1.json", "CloudModel2.json", "CloudModel3.json"]

CSV_COLUMNS = [
    "run_id", "seed", "variant", "deadline", "base_deadline", "deadline_ratio",
    "final_global_makespan", "final_global_lateness_signed", "final_global_lateness_clipped",
    "final_viol_sum", "final_P_FE_makespan", "final_P_FE_budget", "final_P_FE_violation",
    "final_P_C1_makespan", "final_P_C1_budget", "final_P_C1_violation",
    "final_P_C2_makespan", "final_P_C2_budget", "final_P_C2_violation",
    "final_P_C3_makespan", "final_P_C3_budget", "final_P_C3_violation",
    "selected_partition_allocation", "selected_routes_path_indices",
    "total_runtime_s", "total_runtime_h", "peak_memory_mb", "run_summary_json",
]


def ensure_dirs():
    for directory in (EXPERIMENT_DIR, RESULTS_DIR, LOG_DIR, RUNTIME_AM100_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def stage_inputs():
    ensure_dirs()
    for src_name, dst_name in AM_STAGE_MAP.items():
        src = BENCHMARK_DIR / src_name
        dst = RUNTIME_AM100_DIR / dst_name
        if not src.exists():
            raise FileNotFoundError(f"Missing benchmark AM file: {src}")
        shutil.copy2(src, dst)
    platform_src_dir = PROJECT_DIR / "Platforms"
    for name in PLATFORM_FILES:
        src = platform_src_dir / name
        dst = RUNTIME_PLATFORMS_DIR / name
        if not src.exists():
            raise FileNotFoundError(f"Missing platform file: {src}")
        shutil.copy2(src, dst)


def shell_quote(parts):
    import shlex
    return " ".join(shlex.quote(str(p)) for p in parts)


def run_child(args):
    stage_inputs()
    sys.path.insert(0, str(CODE_DIR))
    import config as cfg

    if args.system_generations is not None:
        cfg.SystemLevelGenerations = int(args.system_generations)
    if args.partition_generations is not None:
        cfg.PartitionGenerations = int(args.partition_generations)

    run_tag = args.run_tag or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    os.environ.update({
        "MPLBACKEND": "Agg",
        "PYTHONPATH": f"{CODE_DIR}:{os.environ.get('PYTHONPATH', '')}",
        "PLATFORMS_DIR": str(RUNTIME_PLATFORMS_DIR),
        "OUTPUT_ROOT": str(Path(args.output_root).resolve()),
        "AM_ID": "AM100",
        "BASE_DEADLINE": str(BASE_DEADLINE),
        "DEADLINE_RATIO": str(args.deadline_ratio),
        "SEED": str(args.seed),
        "PYTHONHASHSEED": str(args.seed),
        "VARIANT": args.variant,
        "REQUIRE_ENV_CONFIG": "1",
        "AUTO_RESUME": "0",
        "RUN_TIMESTAMP": f"WATERS100__ratio{str(args.deadline_ratio).replace('.', '')}__seed{args.seed}__{run_tag}",
    })
    os.chdir(CODE_DIR)
    sys.argv = [str(CODE_DIR / "main.py")]
    runpy.run_path(str(CODE_DIR / "main.py"), run_name="__main__")
    return 0


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def collect_summaries(output_root, csv_path):
    rows = []
    for summary_path in sorted(output_root.rglob("run_summary.json")):
        summary = load_json(summary_path)
        row = {column: "unavailable" for column in CSV_COLUMNS}
        row.update({
            "run_id": summary.get("run_id", "unavailable"),
            "seed": summary.get("seed", "unavailable"),
            "variant": summary.get("variant", "unavailable"),
            "deadline": summary.get("actual_deadline_value", summary.get("deadline", "unavailable")),
            "base_deadline": summary.get("base_deadline", "unavailable"),
            "deadline_ratio": summary.get("deadline_ratio", "unavailable"),
            "final_global_makespan": summary.get("final_global_makespan", "unavailable"),
            "final_global_lateness_signed": summary.get("final_global_lateness_signed", "unavailable"),
            "final_global_lateness_clipped": summary.get("final_global_lateness_clipped", "unavailable"),
            "final_viol_sum": summary.get("final_viol_sum", "unavailable"),
            "total_runtime_s": summary.get("total_runtime_s", "unavailable"),
            "total_runtime_h": summary.get("total_runtime_h", "unavailable"),
            "peak_memory_mb": summary.get("peak_memory_mb", "unavailable"),
            "run_summary_json": str(summary_path),
        })
        for part in ("P_FE", "P_C1", "P_C2", "P_C3"):
            prefix = f"final_{part}"
            row[f"{prefix}_makespan"] = summary.get(f"{prefix}_makespan", "unavailable")
            row[f"{prefix}_budget"] = summary.get(f"{prefix}_budget", "unavailable")
            row[f"{prefix}_violation"] = summary.get(f"{prefix}_violation", "unavailable")
        rows.append(row)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def child_python_executable():
    for candidate in (HOME_VENV_PYTHON, LOCAL_VENV_PYTHON):
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return sys.executable


def run_parent(args):
    stage_inputs()
    seeds = args.seeds or SEEDS
    deadline_ratios = args.deadline_ratios or DEADLINE_RATIOS
    output_root = Path(args.output_root).resolve()
    log_file = Path(args.log_file).resolve()
    summary_csv = Path(args.summary_csv).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    summary_csv.parent.mkdir(parents=True, exist_ok=True)

    run_tag = args.run_tag or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    with log_file.open("a", encoding="utf-8") as log:
        log.write(f"\n=== benchmark_ams run {datetime.now().isoformat(timespec='seconds')} ===\n")
        log.write(f"worktree={WORKTREE_ROOT}\n")
        log.write(f"runtime_platforms={RUNTIME_PLATFORMS_DIR}\n")
        log.write(f"deadline_ratios={deadline_ratios}\n")
        log.write(f"seeds={seeds}\n")
        for deadline_ratio in deadline_ratios:
            for seed in seeds:
                cmd = [
                    child_python_executable(),
                    str(Path(__file__).resolve()),
                    "--child",
                    "--seed", str(seed),
                    "--deadline-ratio", str(deadline_ratio),
                    "--variant", args.variant,
                    "--output-root", str(output_root),
                    "--run-tag", run_tag,
                ]
                if args.system_generations is not None:
                    cmd += ["--system-generations", str(args.system_generations)]
                if args.partition_generations is not None:
                    cmd += ["--partition-generations", str(args.partition_generations)]

                exact = shell_quote(cmd)
                print(f"Executing: {exact}")
                log.write(f"Executing: {exact}\n")
                log.flush()
                result = subprocess.run(cmd, cwd=WORKTREE_ROOT, stdout=log, stderr=subprocess.STDOUT)
                if result.returncode != 0:
                    log.write(f"FAILED deadline_ratio={deadline_ratio} seed={seed} returncode={result.returncode}\n")
                    return result.returncode

        rows = collect_summaries(output_root, summary_csv)
        log.write(f"summary_csv={summary_csv}\n")
        log.write(f"summary_rows={len(rows)}\n")
    print(f"Summary CSV: {summary_csv}")
    return 0

def parse_args():
    parser = argparse.ArgumentParser(description="Run WATERS100 benchmark through existing scheduler")
    parser.add_argument("--child", action="store_true", help="Internal mode used by the parent runner")
    parser.add_argument("--seed", type=int, help="Seed for child mode")
    parser.add_argument("--seeds", nargs="+", type=int, help="Seeds to run in parent mode")
    parser.add_argument("--deadline-ratio", default="1.00", help="Deadline ratio for child mode")
    parser.add_argument("--deadline-ratios", nargs="+", help="Deadline ratios to run in parent mode")
    parser.add_argument("--collect-only", action="store_true", help="Only collect existing run_summary.json files into the summary CSV")
    parser.add_argument("--variant", default="proposed")
    parser.add_argument("--run-tag", default=None)
    parser.add_argument("--output-root", default=str(RESULTS_DIR / "runs"))
    parser.add_argument("--log-file", default=str(LOG_DIR / "run.log"))
    parser.add_argument("--summary-csv", default=str(RESULTS_DIR / "benchmark_ams_summary.csv"))
    parser.add_argument("--system-generations", type=int, default=None)
    parser.add_argument("--partition-generations", type=int, default=None)
    parser.add_argument("--smoke", action="store_true", help="Run seed 1001 with 1 system and 1 partition generation")
    args = parser.parse_args()

    if args.smoke:
        args.seeds = [1001]
        args.deadline_ratios = ["1.00"]
        args.output_root = str(RESULTS_DIR / "smoke_test" / "runs")
        args.log_file = str(LOG_DIR / "smoke_test.log")
        args.summary_csv = str(RESULTS_DIR / "smoke_test" / "smoke_summary.csv")
        args.system_generations = args.system_generations or 1
        args.partition_generations = args.partition_generations or 1
        args.run_tag = args.run_tag or "smoke"

    if args.child and args.seed is None:
        parser.error("--child requires --seed")
    return args


def main():
    args = parse_args()
    if args.collect_only:
        rows = collect_summaries(Path(args.output_root).resolve(), Path(args.summary_csv).resolve())
        print(f"Summary CSV: {Path(args.summary_csv).resolve()} ({len(rows)} rows)")
        return 0
    if args.child:
        return run_child(args)
    return run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
