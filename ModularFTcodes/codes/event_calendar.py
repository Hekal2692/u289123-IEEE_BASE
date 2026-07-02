import json, random, time
from datetime import datetime
import json, os
from typing import Dict, List, Any, Tuple, Optional, Set


def infer_level_from_proc(proc_id: str) -> str:
    if proc_id.startswith(('E','F')):  # Edge/Fog
        return 'FE'
    if proc_id.startswith('P1'):       # Cloud 1
        return 'C1'
    if proc_id.startswith('P2'):       # Cloud 2
        return 'C2'
    if proc_id.startswith('P3'):       # Cloud 3
        return 'C3'
    return 'FE'

def routers_only(nodes):
    # Keep anything that looks like a router (R..., RID..., RTSN...)
    return [n for n in nodes if n.startswith('R')]

def random_between(a, b):
    return random.randint(a, b)

# def build_meta(time_unit="ticks"):
#     return {
#         "version": "1.0",
#         "generated_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
#         "time_unit": time_unit,
#         "levels": ["FE", "C1", "C2", "C3"],
#         "event_types": ["slack", "processor_failure", "router_failure"],
#         "notes": "Times are taken from task start times. Router chosen from actual selected path."
#     }


def build_meta(time_unit="ticks", parent_schedule=None, schedule_tag=None):
    return {
        "version": "1.0",
        "generated_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        "time_unit": time_unit,
        "levels": ["FE", "C1", "C2", "C3"],
        "event_types": ["slack", "processor_failure", "router_failure"],
        "notes": "Times are taken from task start times. Router chosen from actual selected path.",
        "parent_schedule": parent_schedule,   # <-- NEW
        "schedule_tag": schedule_tag          # <-- NEW
    }


def pick_random_tasks(schedule_dict, k):
    task_ids = list(schedule_dict.keys())
    if k > len(task_ids):
        k = len(task_ids)
    return random.sample(task_ids, k)

def level_from_processor_id(proc_id):
    # For slack/processor events we use the processor running that task
    return infer_level_from_proc(proc_id)

def level_from_path(path_nodes):
    # Infer level from the LAST platform node in the path
    # (endpoints are processors/edge/fog nodes; routers start with 'R')
    end = next((n for n in reversed(path_nodes) if not n.startswith('R')), None)
    if end is None:
        return "FE"
    return infer_level_from_proc(end)

def build_slack_events(sorted_schedule, n_slack, slack_pct_range=(0.5, 0.7), rng=None):
    rng = rng or random
    events = []
    for idx, tid in enumerate(pick_random_tasks(sorted_schedule, n_slack), start=1):
        proc, start, end, _msgs = sorted_schedule[tid]
        level = level_from_processor_id(proc)
        pct = rng.uniform(slack_pct_range[0], slack_pct_range[1])
        events.append({
            "id": f"EVT-SL-{idx:04d}",
            "time": start,                       # from start_time
            "type": "slack",
            "level": level,
            "scope": "task",
            "target": proc,                      # Fxxx / Exx / P1xxx / P2xxx / P3xxx
            "slack_percent": round(pct * 100, 2) # 50–70%
            # no impact/action_hint/source/recovery/status
        })
    return events



def build_processor_failures(sorted_schedule, n_fail, rng=None):
    rng = rng or random
    events = []
    chosen = pick_random_tasks(sorted_schedule, n_fail)
    for idx, tid in enumerate(chosen, start=1):
        proc, start, end, _msgs = sorted_schedule[tid]
        level = level_from_processor_id(proc)

        # Always align to the schedule's START time
        fail_start = int(start)
        # Optional: short outage window anchored at start
        fail_end = fail_start + rng.randint(30, 180)
        if end is not None:
            fail_end = max(fail_start + 1, min(int(end), fail_end))

        events.append({
            "id": f"EVT-PF-{idx:04d}",
            "time": fail_start,                  # ← now equals task start time
            "type": "processor_failure",
            "level": level,
            "scope": "processor",
            "target": proc,
            "window": {"start": fail_start, "end": fail_end}
        })
    return events



def build_router_failures(sorted_schedule, merged_paths_w_costs, n_router_fail, rng=None):
    """
    Build exactly n_router_fail events (if possible) by sampling from all eligible
    (receiver_task, router) pairs discovered in the schedule's recorded deps.
    Each dep already carries (sender, path_id, msg_id); we pull the path,
    extract routers, and anchor the failure time to the receiver task's start.
    """
    rng = rng or random

    # 1) Build an eligibility pool from schedule deps (no guessing)
    pool = []  # entries: (receiver_tid, start_time, router_id, level)
    for tid, (proc, start, _end, deps) in sorted_schedule.items():
        if not deps:
            continue
        for (_sender, path_id, _mid) in deps:
            pinfo = merged_paths_w_costs.get(str(path_id))
            if not pinfo:
                continue
            path_nodes = pinfo["path"]
            routers = [n for n in path_nodes if n.startswith("R")]
            if not routers:
                continue
            level = level_from_path(path_nodes)  # infer from path destination
            for r in routers:
                pool.append((tid, start, r, level))

    # 2) If pool is empty, nothing to do
    if not pool:
        return []

    # 3) Sample without replacement up to requested count
    k = min(n_router_fail, len(pool))
    chosen = rng.sample(pool, k=k)

    # 4) Build events (time anchored to receiver start)
    events = []
    for idx, (_tid, tstart, router_id, level) in enumerate(chosen, start=1):
        fail_start = int(tstart)
        fail_end = fail_start + rng.randint(40, 200)
        events.append({
            "id": f"EVT-RF-{idx:04d}",
            "time": fail_start,
            "type": "router_failure",
            "level": level,
            "scope": "router",
            "target": router_id,
            "window": {"start": fail_start, "end": fail_end}
        })
    return events



######## Commented on 13.08.2025 , missing attribute, will work in case I don't want to
####### automate the schedule tree generation
###### Need to uncomment the old build_meta function
# def generate_event_calendar(sorted_schedule,
#                             merged_paths_w_costs,
#                             n_slack=3,
#                             n_proc_fail=2,
#                             n_router_fail=2,
#                             slack_pct_range=(0.5, 0.7),
#                             seed=None):
#     """
#     sorted_schedule: dict[str_task_id] -> [processor_id, start, end, [(sender, path_id, msg_id), ...]]
#     merged_paths_w_costs: dict[str_path_id] -> {"path": [...], "cost": int}
#     """
#     if seed is not None:
#         random.seed(seed)

#     meta = build_meta(time_unit="ticks")

#     events = []
#     events += build_slack_events(sorted_schedule, n_slack, slack_pct_range)
#     events += build_processor_failures(sorted_schedule, n_proc_fail)
#     events += build_router_failures(sorted_schedule, merged_paths_w_costs, n_router_fail)

#     # Sort by time for readability
#     events.sort(key=lambda e: (e["time"], e["id"]))

#     return {"meta": meta, "events": events}


def generate_event_calendar(sorted_schedule,
                            merged_paths_w_costs,
                            n_slack=3,
                            n_proc_fail=2,
                            n_router_fail=2,
                            slack_pct_range=(0.5, 0.7),
                            seed=None,
                            parent_schedule=None,   # <-- NEW
                            schedule_tag=None):     # <-- NEW
    if seed is not None:
        random.seed(seed)

    meta = build_meta(time_unit="ticks",
                      parent_schedule=parent_schedule,
                      schedule_tag=schedule_tag)

    events = []
    events += build_slack_events(sorted_schedule, n_slack, slack_pct_range)
    events += build_processor_failures(sorted_schedule, n_proc_fail)
    events += build_router_failures(sorted_schedule, merged_paths_w_costs, n_router_fail)

    events.sort(key=lambda e: (e["time"], e["id"]))
    return {"meta": meta, "events": events}