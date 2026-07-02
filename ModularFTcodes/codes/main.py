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
import json, os
from msg_builder import build_msg_from_dir
from msg_builder import build_msg_artifacts
from LoggerUtility import setup_logger

import argparse
from pathlib import Path

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

platforms_dir = args.platforms_dir.expanduser()
if not platforms_dir.is_absolute():
    platforms_dir = (Path.cwd() / platforms_dir).resolve()

resume_checkpoint = None
if args.resume_from is not None:
    resume_from = args.resume_from.expanduser()
    if not resume_from.is_absolute():
        resume_from = (Path.cwd() / resume_from).resolve()
    if resume_from.is_dir():
        resume_checkpoint = resume_from / "checkpoint_latest.pkl"
        args.timestamp = resume_from.name
        args.log_dir = str(resume_from.parent)
    else:
        resume_checkpoint = resume_from
        run_dir = resume_from.parent
        args.timestamp = run_dir.name
        args.log_dir = str(run_dir.parent)

log, log_dir, timestamp = setup_logger(base_log_dir=args.log_dir, timestamp=args.timestamp)

checkpoint_path = args.checkpoint_path
if checkpoint_path is None:
    checkpoint_path = Path(log_dir) / "checkpoint_latest.pkl"
else:
    checkpoint_path = checkpoint_path.expanduser()
    if not checkpoint_path.is_absolute():
        checkpoint_path = (Path.cwd() / checkpoint_path).resolve()

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


deadline_base = float(args.deadline_base) if args.deadline_base is not None else float(BASELINE_DEADLINES[args.am_size])
if args.deadline is not None:
    deadline_value = float(args.deadline)
    deadline_setting = "custom"
else:
    deadline_value = deadline_base * (args.deadline_percent / 100.0)
    deadline_setting = f"{args.deadline_percent}%"

DEADLINE = int(round(deadline_value)) if abs(deadline_value - round(deadline_value)) < 1e-9 else deadline_value
print("List-scheduling makespan is ", max_time)
print("Baseline Deadline is ", int(deadline_base) if deadline_base.is_integer() else deadline_base)
print("Deadline setting is ", deadline_setting)
print("Application Deadline is ", DEADLINE)
log.info("[MAIN] List-scheduling makespan: %s", max_time)
log.info("[MAIN] Baseline deadline: %s", int(deadline_base) if deadline_base.is_integer() else deadline_base)
log.info("[MAIN] Deadline setting: %s", deadline_setting)
log.info("[MAIN] Application deadline: %s", DEADLINE)
start_sys_ga = time.time()
log.info("[MAIN] System-level scheduling launched")


SystemSchedule, meta = sls.SystemLevelGA(processor_ids_FE,processor_ids_C1,processor_ids_C2,processor_ids_C3,
                                      processing_times_FE,processing_times_C1,processing_times_C2,processing_times_C3,
                                      message_list_FE,message_list_C1,message_list_C2,message_list_C3,
                                      job_data_FE,job_data_C1,job_data_C2,job_data_C3,
                                      DEADLINE, message_list, merged_paths_w_costs,log_dir,
                                      checkpoint_path=checkpoint_path,
                                      resume_checkpoint=resume_checkpoint,
                                      auto_resume=args.auto_resume )

end_sys_ga = time.time()
print("System Level Schedule is ", SystemSchedule)

schedule_path = os.path.join(log_dir, f"schedule_{timestamp}.json")

########### Plotting 
# # Save JSON + emit plots into your existing log_dir/timestamp


arts = gam.plot_system_makespan_and_lateness(meta, out_dir=log_dir, deadline=DEADLINE, timestamp=timestamp)
print("[PLOT] Saved:", arts)


budg = gam.plot_system_time_budgets(meta, out_dir=log_dir, timestamp=timestamp)
print("[PLOT] Time budgets:", budg)

arts = gam.plot_system_budgets_and_makespans_all(meta, out_dir=log_dir, timestamp=timestamp)
print("[PLOT] Saved:", arts)

vf = gam.plot_system_violations_and_fitness(meta, out_dir=log_dir, timestamp=timestamp)
print("[PLOT] Violations/Fitness:", vf)

# Choose scalar weights. If your DEAP weights are negative (minimization), take abs().
try:
    w1 = abs(cfg.SystemLevelWeightViolationSum)
    w2 = abs(cfg.SystemLevelWeightGlobalLateness)
except Exception:
    w1, w2 = 1.0, 1.0

arts = gam.plot_fitness_evolution(
    meta,
    out_dir=log_dir,
    use_signed=True,               # show signed lateness curve
    deadline=DEADLINE,             # only used if signed series must be derived
    scalar_weights=(w1, w2),       # scalar = w1*viol + w2*lateness_clipped
    scalar_use_clipped=True,       # match GA objective definition
    timestamp=timestamp
)
print("[PLOT] Fitness (violation + lateness + scalar):", arts)

###########################################

# If you want it sorted by start time
sorted_schedule = dict(sorted(SystemSchedule.items(), key=lambda x: x[1][1]))

with open(schedule_path, "w", encoding="utf-8") as f:
    json.dump(sorted_schedule, f, indent=2)

log.info(f"Final schedule saved as {schedule_path}")
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
    "am_size": args.am_size,
    "deadline": DEADLINE,
    "deadline_setting": deadline_setting,
    "deadline_percent": None if args.deadline is not None else args.deadline_percent,
    "deadline_base": deadline_base,
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
violations = gax.check_latency_violations(SystemSchedule, merged_paths_w_costs, message_list)

# Use logging if available; otherwise fall back to print
try:
    logger = log  # your existing module logger
except NameError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("validation")

if not violations:
    logger.info("[Validation] ✅ No IPC latency violations — schedule is consistent.")
else:
    logger.info("[Validation] Found %d IPC latency violations:", len(violations))
    for v in violations:
        logger.info(
            "Violation: Task %d starts at %.3f but depends on task %d "
            "which delivers via path %s arriving at %.3f (late by %.3f units)",
            v["task_id"], v["starts_at"], v["violated_dep"],
            str(v["path_id"]), v["arrival_time"], v["violation_by"]
        )



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