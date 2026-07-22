import numpy as np

import networkx as nx
from itertools import islice
import random

import networkx as nx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from decimal import Decimal
from copy import deepcopy
from collections import defaultdict
from functools import partial
from deap import base, creator, tools, algorithms
import random
import time
import plotly.graph_objects as go
import plotly.express as px


import ga_monitor as gam  # add near your other imports
import ga_plotly as gap   # NEW

import event_calendar as ea
import GAAux as gax
import HelperFunctions as hf
import PartitionGA as pga
import config as cfg
import SystemLevelScheduler as sls
import SysGAAux as sysgax

import event_calendar as ec
import event_handler as eh
import json, os, sys, socket, platform, shutil, hashlib, subprocess
from msg_builder import build_msg_from_dir
from msg_builder import build_msg_artifacts
from LoggerUtility import setup_logger

import argparse
from pathlib import Path
from datetime import datetime
from importlib import metadata as importlib_metadata

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PLATFORMS_DIR = PROJECT_DIR / "Platforms"

AM_FILE_LAYOUTS = {
    "100T": {
        "full": "TC100_NewPM.json",
        "fe": "FogEdgePartitionedTasks_merged_strict.json",
        "c1": "Cloud1PartitionedData_merged.json",
        "c2": "Cloud2PartitionedData_merged.json",
        "c3": "Cloud3PartitionedData_merged.json",
    },
    "250T": {
        "full": "TC250.json",
        "fe": "250_FETASKS.json",
        "c1": "250_C1TASKS.json",
        "c2": "250_C2TASKS.json",
        "c3": "250_C3TASKS.json",
    },
    "500T": {
        "full": "TC500.json",
        "fe": "500_FETASKS.json",
        "c1": "500_C1TASKS.json",
        "c2": "500_C2TASKS.json",
        "c3": "500_C3TASKS.json",
    },
}

# Baseline deadlines used in the paper's 100% deadline setting.
# Tightened experiments use 90%, 80%, and 70% of these values.
BASELINE_DEADLINES = {
    "100T": 2600,
    "250T": 2700,
    "500T": 4300,
}
DEADLINE_PERCENT_CHOICES = (100, 90, 80, 70)

AM_ID_ALIASES = {
    "AM100": "100T", "100": "100T", "100T": "100T",
    "AM250": "250T", "250": "250T", "250T": "250T",
    "AM500": "500T", "500": "500T", "500T": "500T",
}
AM_PUBLIC_IDS = {
    "100T": "AM100",
    "250T": "AM250",
    "500T": "AM500",
}
REQUIRED_ENV_CONFIG_KEYS = ("AM_ID", "BASE_DEADLINE", "DEADLINE_RATIO", "SEED")


def _env_flag(name):
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _using_env_config():
    return _env_flag("REQUIRE_ENV_CONFIG") or any(key in os.environ for key in REQUIRED_ENV_CONFIG_KEYS)


def _normalize_am_id(raw_am_id):
    key = str(raw_am_id).strip().upper().replace("-", "").replace("_", "")
    if key not in AM_ID_ALIASES:
        allowed = ", ".join(sorted(AM_ID_ALIASES))
        raise ValueError(f"Unsupported AM_ID={raw_am_id!r}. Use one of: {allowed}")
    am_size = AM_ID_ALIASES[key]
    return am_size, AM_PUBLIC_IDS[am_size]


def _require_env_config():
    missing = [key for key in REQUIRED_ENV_CONFIG_KEYS if not os.environ.get(key)]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): " + ", ".join(missing) +
            ". Export AM_ID, BASE_DEADLINE, DEADLINE_RATIO, and SEED before running main.py."
        )


def _nice_number(value):
    if value is None:
        return None
    value = float(value)
    return int(round(value)) if abs(value - round(value)) < 1e-9 else value


def _format_ratio(ratio):
    return f"{float(ratio):.2f}"


def _safe_name(value):
    text = str(value)
    for old, new in (("/", "-"), ("\\", "-"), (" ", "_"), (":", "-")):
        text = text.replace(old, new)
    return text


def _slurm_metadata():
    return {
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "slurm_array_job_id": os.environ.get("SLURM_ARRAY_JOB_ID"),
        "slurm_array_task_id": os.environ.get("SLURM_ARRAY_TASK_ID"),
        "slurm_cpus_per_task": os.environ.get("SLURM_CPUS_PER_TASK"),
        "slurm_mem_per_node": os.environ.get("SLURM_MEM_PER_NODE"),
    }


def _make_run_id(am_id, base_deadline, deadline_ratio, deadline_value, seed, variant, slurm_meta, run_timestamp):
    job_id = slurm_meta.get("slurm_job_id") or slurm_meta.get("slurm_array_job_id") or "local"
    task_id = slurm_meta.get("slurm_array_task_id")
    task_label = f"task{task_id}" if task_id is not None else "tasklocal"
    return "__".join([
        _safe_name(am_id),
        f"base{_safe_name(_nice_number(base_deadline))}",
        f"ratio{_format_ratio(deadline_ratio)}",
        f"deadline{_safe_name(_nice_number(deadline_value))}",
        f"seed{int(seed)}",
        _safe_name(variant),
        f"job{_safe_name(job_id)}",
        _safe_name(task_label),
        _safe_name(run_timestamp),
    ])


def _peak_memory_mb():
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except Exception:
        return None


def _package_versions():
    versions = {}
    for package_name in ("numpy", "networkx", "matplotlib", "deap", "plotly"):
        try:
            versions[package_name] = importlib_metadata.version(package_name)
        except Exception:
            versions[package_name] = None
    return versions


def _ga_config_values():
    names = [
        "APPLCATION_DEADLINE_FACTOR",
        "PartitionMakespanWeight", "PartitionLatenessWeight",
        "PartitionCrossoverProb", "PartitionMutationProb",
        "PartitionPopulationSize", "PartitionGenerations",
        "SystemLevelPopulationSize", "SystemLevelGenerations",
        "SystemLevelCrossOverProb", "SystemLevelMutationProb",
        "SystemLevelWeightViolationSum", "SystemLevelWeightGlobalLateness",
        "TBMinMarginRatio", "TBDeadbandRatio", "TBStepGainUp", "TBStepGainDown",
        "TBMinStepAbs", "TBMaxStepAbs", "TBMaxStepFrac",
        "TBHoldSlackRatioLo", "TBHoldSlackRatioHi",
        "TBMutNoiseFrac", "TBSlackPenaltyWeight",
    ]
    return {name: getattr(cfg, name, None) for name in names}


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def _atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp_path, path)


def _git_commit_sha(repo_dir):
    env_sha = os.environ.get("GIT_COMMIT_SHA")
    if env_sha:
        return env_sha
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_dir), "rev-parse", "--verify", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def _fingerprint_file(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return {
        "path": str(path),
        "sha256": digest.hexdigest(),
        "size_bytes": stat.st_size,
    }


def _fingerprint_files(paths_by_name):
    return {name: _fingerprint_file(path) for name, path in paths_by_name.items()}


def _write_run_status(run_dir, state, run_metadata=None, message=None, **extra):
    payload = {
        "state": state,
        "message": message,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(Path(run_dir).resolve()),
    }
    if run_metadata:
        payload.update(run_metadata)
    payload.update(extra)
    _atomic_write_json(Path(run_dir) / "run_status.json", payload)


def _write_success_marker(run_dir, run_summary):
    payload = {
        "completed_successfully": True,
        "run_key": run_summary.get("run_key"),
        "run_id": run_summary.get("run_id"),
        "completed_at": run_summary.get("timestamp_end"),
        "final_generation": run_summary.get("final_generation"),
    }
    marker = Path(run_dir) / "_SUCCESS"
    tmp_path = marker.with_name(marker.name + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp_path, marker)


def _copy_requirements_snapshot(requirements_path, run_dir):
    src = Path(requirements_path)
    if not src.exists():
        return None
    dst = Path(run_dir) / "requirements_run.txt"
    shutil.copyfile(src, dst)
    return str(dst)


def _write_hardware_info(path, run_metadata):
    lines = [
        f"hostname: {socket.gethostname()}",
        f"platform: {platform.platform()}",
        f"python_version: {sys.version}",
        f"python_executable: {sys.executable}",
        f"cpu_count: {os.cpu_count()}",
        f"working_directory: {os.getcwd()}",
        f"output_dir: {run_metadata.get('output_dir')}",
        f"SLURM_JOB_ID: {run_metadata.get('slurm_job_id')}",
        f"SLURM_ARRAY_TASK_ID: {run_metadata.get('slurm_array_task_id')}",
        f"SLURM_CPUS_PER_TASK: {run_metadata.get('slurm_cpus_per_task')}",
        f"SLURM_MEM_PER_NODE: {run_metadata.get('slurm_mem_per_node')}",
        f"PYTHONHASHSEED: {os.environ.get('PYTHONHASHSEED')}",
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _collect_plot_files(value):
    files = []
    if value is None:
        return files
    if isinstance(value, dict):
        for item in value.values():
            files.extend(_collect_plot_files(item))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            files.extend(_collect_plot_files(item))
    elif isinstance(value, (str, os.PathLike)):
        text = os.fspath(value)
        if text.lower().endswith((".png", ".pdf", ".svg", ".jpg", ".jpeg")):
            files.append(text)
    return files


parser = argparse.ArgumentParser()
parser.add_argument('--timestamp', type=str, default=None)
parser.add_argument(
    '--am-size',
    choices=sorted(AM_FILE_LAYOUTS.keys()),
    default='100T',
    help='Application model size to run.',
)
parser.add_argument(
    '--platforms-dir',
    type=Path,
    default=DEFAULT_PLATFORMS_DIR,
    help='Directory containing the fixed platform JSON files and AM-size subdirectories.',
)
parser.add_argument(
    '--log-dir',
    type=str,
    default='logs',
    help='Directory where run logs and artifacts are written.',
)
parser.add_argument(
    '--deadline-percent',
    type=int,
    choices=DEADLINE_PERCENT_CHOICES,
    default=100,
    help='Deadline setting as a percentage of the AM baseline deadline.',
)
parser.add_argument(
    '--deadline-base',
    type=float,
    default=None,
    help='Override the AM baseline deadline before applying --deadline-percent.',
)
parser.add_argument(
    '--deadline',
    type=float,
    default=None,
    help='Use an exact application deadline and ignore --deadline-base/--deadline-percent.',
)
parser.add_argument(
    '--checkpoint-path',
    type=Path,
    default=None,
    help='Where to save the latest system-GA checkpoint. Defaults to <run-log-dir>/checkpoint_latest.pkl.',
)
parser.add_argument(
    '--resume-from',
    type=Path,
    default=None,
    help='Resume from a checkpoint file or from a run directory containing checkpoint_latest.pkl.',
)
parser.add_argument(
    '--auto-resume',
    action='store_true',
    help='If the default checkpoint exists in this run directory, resume from it automatically.',
)
args = parser.parse_args()

run_start_perf = time.perf_counter()
timestamp_start = datetime.now().isoformat(timespec="seconds")
slurm_meta = _slurm_metadata()
env_config_mode = _using_env_config()

if os.environ.get("RESUME_FROM") and args.resume_from is None:
    args.resume_from = Path(os.environ["RESUME_FROM"])
if os.environ.get("CHECKPOINT_PATH") and args.checkpoint_path is None:
    args.checkpoint_path = Path(os.environ["CHECKPOINT_PATH"])
if _env_flag("AUTO_RESUME") or _env_flag("RESUME_LATEST"):
    args.auto_resume = True

platforms_dir = Path(os.environ.get("PLATFORMS_DIR", args.platforms_dir)).expanduser()
if not platforms_dir.is_absolute():
    platforms_dir = (Path.cwd() / platforms_dir).resolve()

if env_config_mode:
    _require_env_config()
    args.am_size, am_id = _normalize_am_id(os.environ["AM_ID"])
    deadline_base = float(os.environ["BASE_DEADLINE"])
    deadline_ratio = float(os.environ["DEADLINE_RATIO"])
    seed = int(os.environ["SEED"])
    variant = os.environ.get("VARIANT", "proposed")
    workload = os.environ.get("WORKLOAD", am_id)
    output_root = Path(os.environ.get("OUTPUT_ROOT", "logs")).expanduser()
    if not output_root.is_absolute():
        output_root = (Path.cwd() / output_root).resolve()
    run_timestamp = os.environ.get("RUN_TIMESTAMP") or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    deadline_value = deadline_base * deadline_ratio
    run_key_env = os.environ.get("RUN_KEY")
    run_id = run_key_env or _make_run_id(am_id, deadline_base, deadline_ratio, deadline_value, seed, variant, slurm_meta, run_timestamp)
    if os.environ.get("RUN_DIR"):
        run_output_dir = Path(os.environ["RUN_DIR"]).expanduser()
        if not run_output_dir.is_absolute():
            run_output_dir = (Path.cwd() / run_output_dir).resolve()
    elif run_key_env:
        run_output_dir = output_root / "runs" / run_id
    else:
        run_output_dir = output_root / am_id / f"ratio{_format_ratio(deadline_ratio)}" / f"seed{seed}" / run_id
    args.log_dir = str(run_output_dir.parent)
    args.timestamp = run_output_dir.name
else:
    args.am_size, am_id = _normalize_am_id(args.am_size)
    deadline_base = float(args.deadline_base) if args.deadline_base is not None else float(BASELINE_DEADLINES[args.am_size])
    if args.deadline is not None:
        deadline_value = float(args.deadline)
        deadline_ratio = deadline_value / deadline_base if deadline_base else 1.0
    else:
        deadline_ratio = args.deadline_percent / 100.0
        deadline_value = deadline_base * deadline_ratio
    seed = int(os.environ["SEED"]) if os.environ.get("SEED") else None
    variant = os.environ.get("VARIANT", "proposed")
    workload = os.environ.get("WORKLOAD", am_id)
    run_id = args.timestamp or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    if args.timestamp is None:
        args.timestamp = run_id

if seed is not None:
    random.seed(seed)
    np.random.seed(seed)

resume_checkpoint = None
if args.resume_from is not None:
    resume_from = args.resume_from.expanduser()
    if not resume_from.is_absolute():
        resume_from = (Path.cwd() / resume_from).resolve()
    if resume_from.is_dir():
        resume_checkpoint = resume_from / "checkpoint_latest.pkl"
        args.timestamp = resume_from.name
        args.log_dir = str(resume_from.parent)
        run_id = resume_from.name
    else:
        resume_checkpoint = resume_from
        resume_run_dir = resume_from.parent
        args.timestamp = resume_run_dir.name
        args.log_dir = str(resume_run_dir.parent)
        run_id = resume_run_dir.name

run_key = os.environ.get("RUN_KEY") or run_id

log, log_dir, timestamp = setup_logger(base_log_dir=args.log_dir, timestamp=args.timestamp)
run_dir = Path(log_dir).resolve()

checkpoint_path = args.checkpoint_path
if checkpoint_path is None:
    checkpoint_path = run_dir / "checkpoint_latest.pkl"
else:
    checkpoint_path = checkpoint_path.expanduser()
    if not checkpoint_path.is_absolute():
        checkpoint_path = (Path.cwd() / checkpoint_path).resolve()

log.info("[RUN] run_id=%s", run_id)
log.info("[RUN] run_key=%s", run_key)
log.info("[RUN] seed=%s", seed)
log.info("[RUN] PYTHONHASHSEED=%s", os.environ.get("PYTHONHASHSEED"))
log.info("[RUN] am_id=%s", am_id)
log.info("[RUN] base_deadline=%s", _nice_number(deadline_base))
log.info("[RUN] deadline_ratio=%s", _format_ratio(deadline_ratio))
log.info("[RUN] actual_deadline_value=%s", _nice_number(deadline_value))
log.info("[RUN] variant=%s", variant)
log.info("[RUN] output_dir=%s", run_dir)
log.info("[RUN] hostname=%s", socket.gethostname())
log.info("[RUN] python_version=%s", sys.version.replace("\n", " "))
log.info("[RUN] working_directory=%s", os.getcwd())
log.info("[RUN] slurm_job_id=%s", slurm_meta.get("slurm_job_id"))
log.info("[RUN] slurm_array_task_id=%s", slurm_meta.get("slurm_array_task_id"))

def require_path(path):
    if not path.exists():
        raise FileNotFoundError(f"Required input file was not found: {path}")
    return path

def load_json(path):
    with require_path(path).open("r", encoding="utf-8") as f:
        return json.load(f)



############################################### AM & PM Paths #####################################################

am_dir = platforms_dir / args.am_size
am_layout = AM_FILE_LAYOUTS[args.am_size]

# AM-specific files: choose 100T, 250T, or 500T with --am-size.
AM_PATH = require_path(am_dir / am_layout["full"])
json_data = load_json(AM_PATH)

EdgeFogPartitionData = load_json(am_dir / am_layout["fe"])
Cloud1PartitionedData = load_json(am_dir / am_layout["c1"])
Cloud2PartitionedData = load_json(am_dir / am_layout["c2"])
Cloud3PartitionedData = load_json(am_dir / am_layout["c3"])

FullAMAddress = AM_PATH
FullPMAddress = AM_PATH

################## XXXXXXXXX THOSE ONES WON'T CHANGE FOR DIFFERNET EXPERIMENTS  XXXXXXXXXXX ##########################################
########################################## PLATFORM PATHS ##########################################################
PM_PATH_FE = require_path(platforms_dir / 'FEPlatform.json')
PM_PATH_C1 = require_path(platforms_dir / 'CloudModel1.json')
PM_PATH_C2 = require_path(platforms_dir / 'CloudModel2.json')
PM_PATH_C3 = require_path(platforms_dir / 'CloudModel3.json')
####################################################################################################################

log.info("[MAIN] AM size: %s", args.am_size)
log.info("[MAIN] Platforms directory: %s", platforms_dir)
log.info("[MAIN] Full AM/PM input: %s", AM_PATH)

PMx = hf.Read_Parent_PM(json_data)
PLATFORM_GRAPH_OBJECT = hf.construct_graph_from_json(PMx)

AMx = hf.Read_Parent_AM(json_data)

successors, processing_times = hf.construct_task_dag_from_json(AMx)
message_list = hf.extract_message_list(AMx)
n_tasks = len(processing_times)
processor_ids = hf.get_processor_ids(json_data)
job_data = {job["id"]: job["can_run_on"] for job in json_data["application"]["jobs"]}
merged_paths_w_costs = hf.compute_paths_cloud_costs_2(json_data, k=4) # same path function for all partitions



SR_Pair = hf.find_sender_receiver_pairs(hf.read_application_model(FullAMAddress))
SRPair_list = hf.find_sender_receiver_pairs_tuple(SR_Pair)
graph = hf.plot_graph(SRPair_list)
processing_time = hf.finding_ProcessTime(hf.read_application_model(FullAMAddress))
communication_costs = hf.communication_costs_task(hf.read_application_model(FullAMAddress))
processors = hf.find_processors(hf.read_platform_model(FullPMAddress))
EST = hf.calculate_earliest_start_time(graph, processing_time, communication_costs )

List_schedule, max_time = hf.list_scheduling(graph, processing_time, communication_costs, processors )

print('Time Maksepan of the list scheduling is ', max_time, ' seconds')

FEJobTimes, FogEdgePartitionTime= hf.calculate_partition_makespan(List_schedule, EdgeFogPartitionData)

Cloud1JobTimes , Cloud1PartitionTime = hf.calculate_partition_makespan(List_schedule, Cloud1PartitionedData)

Cloud2JobTimes, Cloud2PartitionTime = hf.calculate_partition_makespan(List_schedule, Cloud2PartitionedData)

Cloud3JobTimes, Cloud3PartitionTime= hf.calculate_partition_makespan(List_schedule, Cloud3PartitionedData)


####################################### FE Info ##########################################################


with open(PM_PATH_FE, 'r') as f:
    # Load the JSON data from the file
    json_data_FEPM = json.load(f)

PMxFE = hf.Read_Parent_PM(json_data_FEPM)
PLATFORM_GRAPH_OBJECT = hf.construct_graph_from_json(PMxFE)

processor_ids_FE = hf.get_processor_ids(json_data_FEPM)    # Getting the processor ids of the fog&edge 
################################################### C1 Info  ##########################################################

with open(PM_PATH_C1, 'r') as f:
    # Load the JSON data from the file
    json_data_C1 = json.load(f)

PMxC1 = hf.Read_Parent_PM(json_data_C1)
PLATFORM_GRAPH_OBJECT = hf.construct_graph_from_json(PMxC1)

processor_ids_C1 = hf.get_processor_ids(json_data_C1)    # Getting the processor ids of the Cloud1 
################################################## C2 Info ##########################################################


with open(PM_PATH_C2, 'r') as f:
    # Load the JSON data from the file
    json_data_C2 = json.load(f)

PMxC2 = hf.Read_Parent_PM(json_data_C2)
PLATFORM_GRAPH_OBJECT = hf.construct_graph_from_json(PMxC2)

processor_ids_C2 = hf.get_processor_ids(json_data_C2)    # Getting the processor ids of the Cloud2
################################################## C3 Info ##########################################################


with open(PM_PATH_C3, 'r') as f:
    # Load the JSON data from the file
    json_data_C3 = json.load(f)

PMxC3 = hf.Read_Parent_PM(json_data_C3)
PLATFORM_GRAPH_OBJECT = hf.construct_graph_from_json(PMxC3)

processor_ids_C3 = hf.get_processor_ids(json_data_C3)    # Getting the processor ids of the Cloud3

#############################################################################################################################

################################################## Partitioning FE ##########################################################

Partition_paths_FE = merged_paths_w_costs
AMxFE = hf.Read_Parent_AM(EdgeFogPartitionData)
processing_times_FE = hf.get_partition_processing_times(AMxFE)
message_list_FE = hf.extract_message_list(AMxFE)
job_data_FE = {job["id"]: job["can_run_on"] for job in EdgeFogPartitionData["application"]["jobs"]}
processing_times_FE = {job['id']: job['processing_times'] for job in AMxFE['jobs']}

# deadline = 2050
# start_time = time.time()
# S_FE, part_history   = pga.NEW_GA_V2(processor_ids_FE,processing_times_FE,message_list_FE , Partition_paths_FE ,job_data_FE,deadline)
# end_time = time.time()
# print("Partition FE Scheule is ",S_FE )
# print('time taken to compute Partition FE schedule is {} seconds'.format(end_time - start_time))
# print()



# run_name = "S_FE"

# gam.plot_makespan_vs_deadline(part_history, deadline, run_name)
# gam.plot_lateness_vs_generations(part_history, deadline, run_name)
################################################## Partitioning C1 ##########################################################

Partition_paths_C1 = merged_paths_w_costs
AMxC1 = hf.Read_Parent_AM(Cloud1PartitionedData)
processing_times_C1 = hf.get_partition_processing_times(AMxC1)
message_list_C1 = hf.extract_message_list(AMxC1)
job_data_C1 = {job["id"]: job["can_run_on"] for job in Cloud1PartitionedData["application"]["jobs"]}
processing_times_C1 = {job['id']: job['processing_times'] for job in AMxC1['jobs']}

################################################################
# deadlineC1 = 230
# start_time_c1 = time.time()
# S_0_C1, part_history_C1 = pga.NEW_GA_V2(processor_ids_C1,processing_times_C1,message_list_C1 , Partition_paths_C1 ,job_data_C1,deadline)
# end_time_c1 = time.time()
# print("Partition C1 Scheule is ",S_0_C1 )
# print('time taken to compute Partition C1 schedule is {} seconds'.format(end_time_c1 - start_time_c1) )
# print()
# run_name2 = "S_C1"
# gam.plot_makespan_vs_deadline(part_history_C1, deadlineC1, run_name2)
# gam.plot_lateness_vs_generations(part_history_C1, deadlineC1, run_name2)
################################################## Partitioning C2 ##########################################################

Partition_paths_C2 = merged_paths_w_costs
AMxC2 = hf.Read_Parent_AM(Cloud2PartitionedData)
processing_times_C2 = hf.get_partition_processing_times(AMxC2)
message_list_C2 = hf.extract_message_list(AMxC2)
job_data_C2 = {job["id"]: job["can_run_on"] for job in Cloud2PartitionedData["application"]["jobs"]}
processing_times_C2= {job['id']: job['processing_times'] for job in AMxC2['jobs']}

##############################################################
# deadlineC2 = 245
# # start_time_c2 = time.time()
# S_0_C2, part_history_C2  = pga.NEW_GA_V2(processor_ids_C2,processing_times_C2,message_list_C2 , Partition_paths_C2 ,job_data_C2, deadlineC2)
# # end_time_c2 = time.time()
# print("Partition C2 Scheule is ",S_0_C2 )
# # print('time taken to compute Partition C2 schedule is {} seconds '.format(end_time_c2 - start_time_c2))
# # print()
# run_name3 = "S_C2"
# gam.plot_makespan_vs_deadline(part_history_C2, deadlineC2, run_name3)
# gam.plot_lateness_vs_generations(part_history_C2, deadlineC2, run_name3)
################################################# Partitioning C3 ##########################################################

Partition_paths_C3 = merged_paths_w_costs
AMxC3 = hf.Read_Parent_AM(Cloud3PartitionedData)
processing_times_C3 = hf.get_partition_processing_times(AMxC3)
message_list_C3 = hf.extract_message_list(AMxC3)
job_data_C3 = {job["id"]: job["can_run_on"] for job in Cloud3PartitionedData["application"]["jobs"]}
processing_times_C3= {job['id']: job['processing_times'] for job in AMxC3['jobs']}

# #################################################################
# deadlineC3 = 950
# # start_time_c3 = time.time()
# S_0_C3, part_history_C3  = pga.NEW_GA_V2(processor_ids_C3,processing_times_C3,message_list_C3 , Partition_paths_C3 ,job_data_C3,deadlineC3)
# # end_time_c3 = time.time()                     
# print("Partition C3 Scheule is ",S_0_C3 )
# # print('time taken to compute Partition C3 schedule is  {} seconds' .format(end_time_c3 - start_time_c3) )
# run_name3 = "S_C3"
# gam.plot_makespan_vs_deadline(part_history_C3, deadlineC3, run_name3)
# gam.plot_lateness_vs_generations(part_history_C3, deadlineC3, run_name3)




######################################## System Level Scheduling ##########################################################

TimeBudget = [
    FogEdgePartitionTime,
    Cloud1PartitionTime,
    Cloud2PartitionTime,
    Cloud3PartitionTime
]
  # Time budget for each partition


deadline_setting = f"ratio{_format_ratio(deadline_ratio)}"
DEADLINE = _nice_number(deadline_value)
list_schedule_makespan = _nice_number(max_time)
print("List-scheduling makespan is ", max_time)
print("Baseline Deadline is ", _nice_number(deadline_base))
print("Deadline setting is ", deadline_setting)
print("Application Deadline is ", DEADLINE)
log.info("[RUN] list_schedule_makespan=%s", list_schedule_makespan)
log.info("[MAIN] List-scheduling makespan: %s", max_time)
log.info("[MAIN] Baseline deadline: %s", _nice_number(deadline_base))
log.info("[MAIN] Deadline setting: %s", deadline_setting)
log.info("[MAIN] Application deadline: %s", DEADLINE)

git_commit_sha = _git_commit_sha(PROJECT_DIR)
ga_configuration = _ga_config_values()
run_metadata = {
    "run_id": run_id,
    "run_key": run_key,
    "am_id": am_id,
    "workload": workload,
    "am_size": args.am_size,
    "base_deadline": _nice_number(deadline_base),
    "deadline_ratio": float(deadline_ratio),
    "actual_deadline": DEADLINE,
    "actual_deadline_value": DEADLINE,
    "seed": seed,
    "variant": variant,
    "timestamp_start": timestamp_start,
    "output_dir": str(run_dir),
    "working_directory": os.getcwd(),
    "hostname": socket.gethostname(),
    "python_version": sys.version,
    "python_executable": sys.executable,
    "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED"),
    "git_commit_sha": git_commit_sha,
    "ga_configuration": ga_configuration,
    **slurm_meta,
}
input_files = {
    "application_model": str(AM_PATH),
    "partition_fog_edge": str(am_dir / am_layout["fe"]),
    "partition_cloud1": str(am_dir / am_layout["c1"]),
    "partition_cloud2": str(am_dir / am_layout["c2"]),
    "partition_cloud3": str(am_dir / am_layout["c3"]),
    "platform_fog_edge": str(PM_PATH_FE),
    "platform_cloud1": str(PM_PATH_C1),
    "platform_cloud2": str(PM_PATH_C2),
    "platform_cloud3": str(PM_PATH_C3),
}
input_file_fingerprints = _fingerprint_files(input_files)
run_metadata["input_files"] = input_files
run_metadata["input_file_fingerprints"] = input_file_fingerprints
requirements_snapshot = _copy_requirements_snapshot(PROJECT_DIR / "requirements.txt", run_dir)
hardware_info_path = run_dir / "hardware_info.txt"
_write_hardware_info(hardware_info_path, run_metadata)
run_config = {
    **run_metadata,
    "timestamp": timestamp,
    "input_files": input_files,
    "input_file_fingerprints": input_file_fingerprints,
    "number_of_tasks": n_tasks,
    "number_of_messages": len(message_list),
    "number_of_partitions": 4,
    "partition_names": ["P_FE", "P_C1", "P_C2", "P_C3"],
    "list_schedule_makespan": list_schedule_makespan,
    "partition_list_schedule_makespans": {
        "P_FE": _nice_number(FogEdgePartitionTime),
        "P_C1": _nice_number(Cloud1PartitionTime),
        "P_C2": _nice_number(Cloud2PartitionTime),
        "P_C3": _nice_number(Cloud3PartitionTime),
    },
    "GA_parameters": ga_configuration,
    "time_budget_mutation_parameters": {
        key: getattr(cfg, key, None)
        for key in (
            "TBMinMarginRatio", "TBDeadbandRatio", "TBStepGainUp", "TBStepGainDown",
            "TBMinStepAbs", "TBMaxStepAbs", "TBMaxStepFrac",
            "TBHoldSlackRatioLo", "TBHoldSlackRatioHi", "TBMutNoiseFrac", "TBSlackPenaltyWeight",
        )
    },
    "population_size": getattr(cfg, "SystemLevelPopulationSize", None),
    "number_of_generations": getattr(cfg, "SystemLevelGenerations", None),
    "crossover_probability": getattr(cfg, "SystemLevelCrossOverProb", None),
    "mutation_probability": getattr(cfg, "SystemLevelMutationProb", None),
    "package_versions": _package_versions(),
    "requirements_run_path": requirements_snapshot,
    "hardware_info_path": str(hardware_info_path),
    "checkpoint_path": str(checkpoint_path),
    "auto_resume": bool(args.auto_resume),
    "resume_from": str(resume_checkpoint) if resume_checkpoint else None,
}
_write_json(run_dir / "run_config.json", run_config)
log.info("[RUN] run_config_json=%s", run_dir / "run_config.json")
_write_run_status(
    run_dir,
    "RUNNING",
    run_metadata,
    message="system-level GA starting",
    checkpoint_path=str(checkpoint_path),
    resume_from=str(resume_checkpoint) if resume_checkpoint else None,
)

start_sys_ga = time.perf_counter()
log.info("[MAIN] System-level scheduling launched")

try:
    SystemSchedule, meta = sls.SystemLevelGA(processor_ids_FE,processor_ids_C1,processor_ids_C2,processor_ids_C3,
                                          processing_times_FE,processing_times_C1,processing_times_C2,processing_times_C3,
                                          message_list_FE,message_list_C1,message_list_C2,message_list_C3,
                                          job_data_FE,job_data_C1,job_data_C2,job_data_C3,
                                          DEADLINE, message_list, merged_paths_w_costs,log_dir,
                                          checkpoint_path=checkpoint_path,
                                          resume_checkpoint=resume_checkpoint,
                                          auto_resume=args.auto_resume,
                                          run_metadata=run_metadata )
except sls.CheckpointCompatibilityError as exc:
    _write_run_status(
        run_dir,
        "CHECKPOINT_INCOMPATIBLE",
        run_metadata,
        message=str(exc),
        checkpoint_path=str(checkpoint_path),
    )
    log.error("[Checkpoint] Incompatible checkpoint: %s", exc)
    raise SystemExit(2)
except sls.GracefulTermination as exc:
    _write_run_status(
        run_dir,
        "INTERRUPTED",
        run_metadata,
        message=str(exc),
        checkpoint_path=str(checkpoint_path),
        **getattr(exc, "status_payload", {}),
    )
    log.warning("[RUN] Graceful termination requested: %s", exc)
    raise SystemExit(99)

end_sys_ga = time.perf_counter()
print("System Level Schedule is ", SystemSchedule)

schedule_path = os.path.join(log_dir, f"schedule_{timestamp}.json")
final_schedule_path = os.path.join(log_dir, "final_schedule.json")
plots_dir = os.path.join(log_dir, "plots")
os.makedirs(plots_dir, exist_ok=True)
generated_plot_files = []

########### Plotting 
# # Save JSON + emit plots into this run's private plots directory.


arts = gam.plot_system_makespan_and_lateness(meta, out_dir=plots_dir, deadline=DEADLINE, timestamp=timestamp)
generated_plot_files.extend(_collect_plot_files(arts))
print("[PLOT] Saved:", arts)


budg = gam.plot_system_time_budgets(meta, out_dir=plots_dir, timestamp=timestamp)
generated_plot_files.extend(_collect_plot_files(budg))
print("[PLOT] Time budgets:", budg)

arts = gam.plot_system_budgets_and_makespans_all(meta, out_dir=plots_dir, timestamp=timestamp)
generated_plot_files.extend(_collect_plot_files(arts))
print("[PLOT] Saved:", arts)

vf = gam.plot_system_violations_and_fitness(meta, out_dir=plots_dir, timestamp=timestamp)
generated_plot_files.extend(_collect_plot_files(vf))
print("[PLOT] Violations/Fitness:", vf)

# Choose scalar weights. If your DEAP weights are negative (minimization), take abs().
try:
    w1 = abs(cfg.SystemLevelWeightViolationSum)
    w2 = abs(cfg.SystemLevelWeightGlobalLateness)
except Exception:
    w1, w2 = 1.0, 1.0

arts = gam.plot_fitness_evolution(
    meta,
    out_dir=plots_dir,
    use_signed=True,               # show signed lateness curve
    deadline=DEADLINE,             # only used if signed series must be derived
    scalar_weights=(w1, w2),       # scalar = w1*viol + w2*lateness_clipped
    scalar_use_clipped=True,       # match GA objective definition
    timestamp=timestamp
)
generated_plot_files.extend(_collect_plot_files(arts))
print("[PLOT] Fitness (violation + lateness + scalar):", arts)

###########################################

# If you want it sorted by start time
sorted_schedule = dict(sorted(SystemSchedule.items(), key=lambda x: x[1][1]))

with open(schedule_path, "w", encoding="utf-8") as f:
    json.dump(sorted_schedule, f, indent=2)
with open(final_schedule_path, "w", encoding="utf-8") as f:
    json.dump(sorted_schedule, f, indent=2)

log.info(f"Final schedule saved as {schedule_path}")
log.info(f"Final schedule copy saved as {final_schedule_path}")
log.info(f"[SystemLevelGA] Total execution time: {end_sys_ga - start_sys_ga:.2f} seconds")

# --- NEW: save an enveloped, DAG-ready copy with parent & tag ---
ROOT_TAG = "S0"
root_enveloped_path = os.path.join(log_dir, f"{ROOT_TAG}__schedule_{timestamp}.json")
root_envelope = {
    "meta": {
        "version": "1.0",
        "saved_at": timestamp,            # reuse your run timestamp string
        "schedule_tag": ROOT_TAG,         # node id in the DAG
        "parent_schedule": None,          # root has no parent
        "event": None,                    # no incoming edge
        "calendar_path": None,            # will set after we save base calendar below
        "moved_count": 0,
        # optional: quick hash for dedup/debug (same format used in event_handler)
        "schedule_hash": ""               # filled below
    },
    "schedule": sorted_schedule
}

# quick fingerprint (same logic as _schedule_fingerprint but inline & simple)
import hashlib, json as _json
blob = _json.dumps(sorted(sorted_schedule.items(), key=lambda kv: kv[0]), default=str)
root_envelope["meta"]["schedule_hash"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()


root_envelope["meta"].update({
    "am_id": am_id,
    "am_size": args.am_size,
    "deadline": DEADLINE,
    "deadline_setting": deadline_setting,
    "deadline_ratio": float(deadline_ratio),
    "deadline_percent": int(round(float(deadline_ratio) * 100)),
    "deadline_base": deadline_base,
    "seed": seed,
    "variant": variant,
    "run_id": run_id,
    "checkpoint_path": str(checkpoint_path),
    "time_budgets_partition": meta.get("time_budgets_partition"),
    "global_makespan": int(meta.get("global_makespan",
                                    max(int(v[2]) for v in sorted_schedule.values())))
})

with open(root_enveloped_path, "w", encoding="utf-8") as f:
    json.dump(root_envelope, f, indent=2)
log.info(f"Enveloped root schedule saved as {root_enveloped_path}")

###################################### Latency Calculation ##########################################################

# violations = violations = gax.check_latency_violations(SystemSchedule, merged_paths_w_costs, message_list)

# for v in violations:
#     print(f"Violation: Task {v['task_id']} starts at {v['starts_at']} but depends on task {v['violated_dep']} "
#           f"which delivers via path {v['path_id']} arriving at {v['arrival_time']} "
#           f"(late by {v['violation_by']} units)")


# After you build SystemSchedule and merged_paths_w_costs
latency_violations = gax.check_latency_violations(SystemSchedule, merged_paths_w_costs, message_list)
processor_overlaps = gax.check_processor_overlaps(SystemSchedule)

# Use logging if available; otherwise fall back to print
try:
    logger = log  # your existing module logger
except NameError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("validation")

if not latency_violations:
    logger.info("[Validation] No IPC latency violations.")
else:
    logger.info("[Validation] Found %d IPC latency violations:", len(latency_violations))
    for v in latency_violations:
        logger.info(
            "IPC violation: Task %d starts at %.3f but depends on task %d "
            "which delivers via path %s arriving at %.3f (late by %.3f units)",
            v["task_id"], v["starts_at"], v["violated_dep"],
            str(v["path_id"]), v["arrival_time"], v["violation_by"]
        )

if not processor_overlaps:
    logger.info("[Validation] No processor overlaps.")
else:
    logger.info("[Validation] Found %d processor overlaps:", len(processor_overlaps))
    for v in processor_overlaps:
        logger.info(
            "Processor overlap: %s task %s [%.3f, %.3f] overlaps task %s "
            "[%.3f, %.3f] during [%.3f, %.3f] (%.3f units)",
            v["processor"], str(v["task_a"]), v["task_a_start"], v["task_a_end"],
            str(v["task_b"]), v["task_b_start"], v["task_b_end"],
            v["overlap_start"], v["overlap_end"], v["overlap_by"]
        )

if not latency_violations and not processor_overlaps:
    logger.info("[Validation] Schedule is consistent.")

run_stats = meta.get("run_stats", {}) or {}
final_budgets = meta.get("time_budgets_partition", {}) or {}
final_makespans = meta.get("partition_makespans_final", {}) or {}
final_violations = meta.get("partition_violations_final", {}) or {}
final_fitness = meta.get("final_fitness", {}) or {}
final_generation = meta.get("final_generation")
final_global_makespan = int(meta.get("global_makespan", max(int(v[2]) for v in sorted_schedule.values())))
final_global_lateness_signed = int(final_fitness.get("lateness_signed", final_global_makespan - int(DEADLINE)))
final_global_lateness_clipped = int(final_fitness.get("lateness_clipped", max(0, final_global_lateness_signed)))
final_viol_sum = float(final_fitness.get("viol_sum", sum(final_violations.values()) if final_violations else 0.0))
final_fitness_lateness = float(final_fitness.get("fitness_lateness", final_global_lateness_clipped))
total_runtime_s = time.perf_counter() - run_start_perf
total_runtime_h = total_runtime_s / 3600.0
peak_memory_mb = _peak_memory_mb()
partition_feasible = final_viol_sum == 0
deadline_feasible = final_global_lateness_clipped == 0
fully_feasible = deadline_feasible and partition_feasible

run_summary = {
    **run_metadata,
    "completed_successfully": True,
    "timestamp_end": datetime.now().isoformat(timespec="seconds"),
    "total_runtime_s": total_runtime_s,
    "total_runtime_h": total_runtime_h,
    "peak_memory_mb": peak_memory_mb,
    "final_generation": final_generation,
    "final_global_makespan": final_global_makespan,
    "final_global_lateness_signed": final_global_lateness_signed,
    "final_global_lateness_clipped": final_global_lateness_clipped,
    "final_viol_sum": final_viol_sum,
    "final_fitness_lateness": final_fitness_lateness,
    "deadline_feasible": deadline_feasible,
    "partition_feasible": partition_feasible,
    "fully_feasible": fully_feasible,
    "first_deadline_feasible_generation": run_stats.get("first_deadline_feasible_generation"),
    "first_partition_feasible_generation": run_stats.get("first_partition_feasible_generation"),
    "first_fully_feasible_generation": run_stats.get("first_fully_feasible_generation"),
    "best_global_makespan_so_far": run_stats.get("best_global_makespan_so_far"),
    "best_feasible_makespan_so_far": run_stats.get("best_feasible_makespan_so_far"),
    "best_feasible_generation": run_stats.get("best_feasible_generation"),
    "system_ga_summary_csv": str(run_dir / "system_ga_summary.csv"),
    "final_schedule_json": final_schedule_path,
    "schedule_json": schedule_path,
    "checkpoint_path": str(checkpoint_path),
    "attempt_count": meta.get("attempt_count"),
    "interruption_count": meta.get("interruption_count"),
    "resumed": meta.get("resumed"),
    "resume_generation": meta.get("resume_generation"),
    "final_attempt_system_ga_runtime_s": meta.get("final_attempt_system_ga_runtime_s"),
    "system_ga_runtime_s": meta.get("system_ga_runtime_s"),
    "generated_plot_files": sorted(set(generated_plot_files)),
}
for part in ("P_FE", "P_C1", "P_C2", "P_C3"):
    prefix = f"final_{part}"
    run_summary[f"{prefix}_budget"] = final_budgets.get(part)
    run_summary[f"{prefix}_makespan"] = final_makespans.get(part)
    run_summary[f"{prefix}_violation"] = final_violations.get(part)

_write_json(run_dir / "run_summary.json", run_summary)
_write_success_marker(run_dir, run_summary)
_write_run_status(
    run_dir,
    "COMPLETE",
    run_metadata,
    message="completed successfully",
    completed_successfully=True,
    final_generation=final_generation,
    checkpoint_path=str(checkpoint_path),
    system_ga_runtime_s=meta.get("system_ga_runtime_s"),
    attempt_count=meta.get("attempt_count"),
    interruption_count=meta.get("interruption_count"),
    resumed=meta.get("resumed"),
    resume_generation=meta.get("resume_generation"),
)
log.info("[RUN-SUMMARY] %s", json.dumps(run_summary, sort_keys=True, default=str))
log.info("[RUN-SUMMARY] total_runtime_s=%.3f total_runtime_h=%.6f peak_memory_mb=%s", total_runtime_s, total_runtime_h, peak_memory_mb)



################################################### MSG & Event Generation ###########################################################
#################################################### COMMENTED FOR NOW TO EVALUATE THE GA ##########################################################


# tb_part = meta.get("time_budgets_partition", {})  # e.g., {"P_FE":..,"P_C1":..,"P_C2":..,"P_C3":..}
# tb_level = {
#     "FE": tb_part.get("P_FE"),
#     "C1": tb_part.get("P_C1"),
#     "C2": tb_part.get("P_C2"),
#     "C3": tb_part.get("P_C3"),
# }

# eh.configure_replanner({
#     "pid_by_level": {"FE": processor_ids_FE, "C1": processor_ids_C1, "C2": processor_ids_C2, "C3": processor_ids_C3},
#     "paths": merged_paths_w_costs,
#     "job_data_all": job_data,
#     "message_list_all": message_list,   # <--- ADD THIS
#     "deadline": DEADLINE,
#     "time_budgets_level": tb_level,
#     "log_dir": log_dir,          # ← ADD THIS
#     "parent_tag": "S0",          # ← optional: improves CSV names
# })


# ########################### Event Calendar Processing ##########################################################

# #  These are for test parameters
# base_calendar = ec.generate_event_calendar(
#     sorted_schedule,
#     merged_paths_w_costs,
#     n_slack=2,                # tune as you like
#     n_proc_fail=2,            # placeholders for now
#     n_router_fail=0,          # placeholders for now
#     slack_pct_range=(0.5, 0.7),
#     seed=42,
#     parent_schedule=ROOT_TAG, # <- calendar belongs to S0
#     schedule_tag=ROOT_TAG
# )

# # base_calendar = ec.generate_event_calendar(
# #     sorted_schedule,
# #     merged_paths_w_costs,
# #     n_slack=1,
# #     n_proc_fail=1,
# #     n_router_fail=1,
# #     slack_pct_range=(0.5, 0.7),
# #     seed=42,
# #     parent_schedule=ROOT_TAG,
# #     schedule_tag=ROOT_TAG
# # )


# base_calendar_path = os.path.join(log_dir, f"{ROOT_TAG}__event_calendar_{timestamp}.json")
# with open(base_calendar_path, "w", encoding="utf-8") as f:
#     json.dump(base_calendar, f, indent=2)
# log.info(f"Base event calendar saved as {base_calendar_path}")

# # update calendar_path in the enveloped root file (so S0 points to its calendar)
# root_envelope["meta"]["calendar_path"] = base_calendar_path
# with open(root_enveloped_path, "w", encoding="utf-8") as f:
#     json.dump(root_envelope, f, indent=2)

# # # --- NEW: expand MSG for N rounds; every child schedule+calendar is saved ---

# ROOT_TAG = "S0"

# # Commenetd  24 Feb 2026

# # #  These are for test parameters
# # nodes = eh.build_schedule_tree(
# #     base_schedule=sorted_schedule,
# #     base_calendar=base_calendar,
# #     merged_paths=merged_paths_w_costs,
# #     rounds=1,
# #     log_dir=log_dir,
# #     timestamp=timestamp,
# #     root_tag=ROOT_TAG,
# #     gen_params={"n_slack": 1, "n_proc_fail": 1, "n_router_fail": 0, "slack_pct_range": (0.5, 0.7), "seed": 42},
# #     branch_limits_per_level=[{"processor_failure": 1, "slack": 2}],
# #     allowed_types=("slack","processor_failure"),              # only branch on slack for now
# #     meta_static={                          # <-- NEW
# #         "time_budgets_partition": meta.get("time_budgets_partition"),
# #     },
# # )

# # # --- MSG expansion with per-level calendar generation + per-level branch caps ---
# nodes = eh.build_schedule_tree(
#     base_schedule=sorted_schedule,
#     base_calendar=base_calendar,
#     merged_paths=merged_paths_w_costs,
#     rounds=3,                         # depth 0->1, 1->2, 2->3
#     log_dir=log_dir,
#     timestamp=timestamp,
#     root_tag=ROOT_TAG,

#     # Put INTO each child calendar (per level):
#     # depth 0 children (Round 1):   1+1+1
#     # depth 1 children (Round 2):   1+1+1
#     # depth 2 children (Round 3):   2 total (choose mix: 1 slack + 1 PF here)
#     gen_params_per_level=[
#         {"n_slack": 1, "n_proc_fail": 1, "n_router_fail": 1, "slack_pct_range": (0.5, 0.7), "seed": 42},
#         {"n_slack": 1, "n_proc_fail": 1, "n_router_fail": 1, "slack_pct_range": (0.5, 0.7), "seed": 42},
#         {"n_slack": 1, "n_proc_fail": 1, "n_router_fail": 0, "slack_pct_range": (0.5, 0.7), "seed": 42},
#     ],

#     # TAKE from each node’s calendar (per level):
#     branch_limits_per_level=[
#         {"slack": 1, "processor_failure": 1, "router_failure": 1},  # Round 1: 3 children from S0
#         {"slack": 1, "processor_failure": 1, "router_failure": 1},  # Round 2: 3 children per node
#         2,                                                          # Round 3: 2 children per node (any mix)
#     ],

#     allowed_types=("slack", "processor_failure", "router_failure"),
#     meta_static={"time_budgets_partition": meta.get("time_budgets_partition")},
# )



# build_msg_from_dir(log_dir, os.path.join(log_dir, f"MSG_{timestamp}.json"))






# #This will draw the MSG

# # artifacts = build_msg_artifacts(log_dir, timestamp, make_png=True)
# # log.info(
# #     f"[MSG] nodes={artifacts['node_count']} edges={artifacts['edge_count']} "
# #     f"root={artifacts['root']} | JSON={artifacts['json']} DOT={artifacts['dot']} "
# #     f"PNG={artifacts.get('png')}"
# # )
