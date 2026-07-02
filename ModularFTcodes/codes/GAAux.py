import numpy as np
import json
import networkx as nx
from itertools import islice
import random
import json
import networkx as nx
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


def compute_makespan(schedule):
    return max(info[2] for info in schedule.values()) if schedule else 0

def repair_task_order(order, valid_task_ids):
    seen = set()
    repaired = []
    for task in order:
        if task in valid_task_ids and task not in seen:
            repaired.append(task)
            seen.add(task)
    for task in valid_task_ids:
        if task not in seen:
            repaired.append(task)
    return repaired

def ComputeMappingsAndPaths(message_list, tasks, processors, message_orderings, path_indices):
    #print('message_orderings',message_orderings)
    # print('path_indices',path_indices)
    message_list_copy = deepcopy(message_list)
    
    # Create a dictionary that maps task ids to processor ids
    task_to_processor = {task: processors[i] for i, task in enumerate(tasks)}
    
    updated_message_list = []  # Container for mapping the messages between the processors
    
    # Create a mapping between message IDs (orderings) and path indices
    message_to_path_mapping = {message_orderings[i]: path_indices[i] for i in range(len(message_orderings))}
    
    for message in message_list_copy:
        # Find the corresponding path index using the message ID
        path_index = message_to_path_mapping.get(message['id'], None)
        # print('path_index', path_index)

        if task_to_processor[message['sender']] == task_to_processor[message['receiver']]:
            path_index = 0
        
        updated_message = {
            'id': message['id'],
            'sender': task_to_processor[message['sender']],
            'receiver': task_to_processor[message['receiver']],
            'size': message['size'],
            'path_index': path_index  # Add the path index to the updated message
        }
        updated_message_list.append(updated_message)
    
    return updated_message_list


def find_suitable_paths(updated_message_list, merged_paths_dict):
    selected_paths = []
    
    for message in updated_message_list:
        sender = message['sender']
        receiver = message['receiver']
        path_index_str = str(message['path_index'])

        # First collect all paths that connect sender↔receiver
        endpoint_matches = {
            pid: details['path']
            for pid, details in merged_paths_dict.items()
            if ((details['path'][0] == sender and details['path'][-1] == receiver) or
                (details['path'][0] == receiver and details['path'][-1] == sender))
        }

        # Of those, filter down to ones whose ID ends with the index
        index_matches = {pid for pid in endpoint_matches if pid.endswith(path_index_str)}

        # Use an index‐matching one if possible; otherwise fall back to any endpoint match
        if index_matches:
            chosen = next(iter(index_matches))
        elif endpoint_matches:
            chosen = next(iter(endpoint_matches))
        else:
            chosen = None

        selected_paths.append(chosen)
    
    return selected_paths

# def enforce_can_run_on_constraints(task_order, processor_allocation, processor_ids, job_data):
#     lsb_to_all = defaultdict(list)
#     lsb_edge_only = defaultdict(list)
#     lsb_fogcloud_only = defaultdict(list)
#     for pid in processor_ids:
#         if pid.startswith("R"):
#             continue
#         try:
#             lsb = int(pid[-1])
#         except ValueError:
#             continue
#         lsb_to_all[lsb].append(pid)
#         if pid.startswith("E"):
#             lsb_edge_only[lsb].append(pid)
#         elif pid.startswith("F") or pid.startswith("P"):
#             lsb_fogcloud_only[lsb].append(pid)
#     usage_index = defaultdict(int)
#     corrected_allocation = []
#     for i, task_id in enumerate(task_order):
#         assigned_pid = processor_allocation[i]
#         allowed_lsbs = job_data.get(task_id, [])
#         valid_processors = []
#         for lsb in allowed_lsbs:
#             if lsb in (1, 2):
#                 valid_processors.extend(lsb_to_all.get(lsb, []))
#             elif lsb in (3, 4):
#                 valid_processors.extend(lsb_edge_only.get(lsb, []))
#             elif lsb in (5, 6):
#                 valid_processors.extend(lsb_fogcloud_only.get(lsb, []))
#         if assigned_pid in valid_processors:
#             corrected_allocation.append(assigned_pid)
#             continue
#         if not valid_processors:
#             corrected_allocation.append(assigned_pid)
#             continue
#         rr_index = usage_index[task_id] % len(valid_processors)
#         selected = valid_processors[rr_index]
#         usage_index[task_id] += 1
#         corrected_allocation.append(selected)
#     return corrected_allocation

# Put this in GAAux.py (replacing the current version), or import here if you prefer.
# PATCH: GAAux.py — enforce can_run_on semantics and return (alloc, hard_violations)

# GAAux.py — robust can_run_on enforcement (handles list or dict job_data)


def enforce_can_run_on_constraints(task_order, processor_allocation, processor_ids, job_data, strict=True):
    """
    can_run_on semantics:
      1/2 -> any non-router in this cluster
      3/4 -> Edge only  (ids starting 'E')
      5/6 -> Cloud only (ids starting 'P')
    Returns: (corrected_allocation, hard_violations)
    """
    non_router = [pid for pid in processor_ids if not pid.startswith("R")]
    edge_only  = [pid for pid in non_router if pid.startswith("E")]
    cloud_only = [pid for pid in non_router if pid.startswith("P")]  # add 'F' if Fog should count as cloud

    corrected = []
    hard_violations = 0

    for i, task_id in enumerate(task_order):
        meta = job_data.get(task_id, [])

        # --- NEW: normalize cro whether job_data is a list or a dict
        if isinstance(meta, dict):
            cro = meta.get('can_run_on') or meta.get('canRunOn') or []
        elif isinstance(meta, (list, tuple, set)):
            cro = list(meta)
        else:
            cro = []

        # Decide allowed pool
        if any(x in (1, 2) for x in cro):
            allowed = non_router
        elif any(x in (3, 4) for x in cro):
            allowed = edge_only
        elif any(x in (5, 6) for x in cro):
            allowed = cloud_only
        else:
            allowed = non_router  # permissive fallback

        current = processor_allocation[i]
        if allowed:
            if current in allowed:
                corrected.append(current)
            else:
                corrected.append(random.choice(allowed))  # soft fix inside feasible cluster
                # This is still a violation of the original assignment; treat as soft ⇒ no hard_viol increment
        else:
            # Impossible on this cluster (e.g., Edge-only task but no E* here)
            corrected.append(current)
            hard_violations += 1

    return corrected, hard_violations




##################################################################

# def check_latency_violations(schedule, path_dict):
#     violations = []

#     for task_id, (proc, start, end, deps) in schedule.items():
#         for src_id, path_id, msg_id in deps:
#             if src_id not in schedule:
#                 continue  # source task not found

#             # Get end time of the source task
#             src_end = schedule[src_id][2]

#             # Get path cost from path dictionary
#             path_info = path_dict.get(path_id)
#             if not path_info:
#                 continue  # skip if path is missing

#             path_cost = path_info['cost']
#             arrival_time = src_end + path_cost

#             # Violation if message arrives after task start
#             if arrival_time > start:
#                 violations.append({
#                     'task_id': task_id,
#                     'starts_at': start,
#                     'violated_dep': src_id,
#                     'path_id': path_id,
#                     'message_id': msg_id,
#                     'src_end': src_end,
#                     'path_cost': path_cost,
#                     'arrival_time': arrival_time,
#                     'violation_by': arrival_time - start
#                 })

#     return violations


def check_latency_violations(schedule, paths, messages=None):
    """
    Validate start(dst) >= end(src) + path_cost [+ msg_size if available].

    schedule: {tid: [proc, start, end, deps]}
    paths   : {path_id: {"cost": float, ...}}
    messages: optional list[dict] with 'id' and 'size' to account for msg_size.
    """
    # Build size lookup if messages are provided
    msg_size = {}
    if messages is not None:
        for m in messages:
            try:
                msg_size[int(m["id"])] = float(m.get("size", 0.0))
            except Exception:
                # ignore malformed entries
                pass

    violations = []
    for tid, rec in schedule.items():
        start = float(rec[1])
        deps = rec[3] if len(rec) >= 4 else []
        for d in deps or []:
            if isinstance(d, (list, tuple)) and len(d) >= 3:
                try:
                    src_id, path_id, msg_id = int(d[0]), str(d[1]), int(d[2])
                except Exception:
                    continue
                if path_id not in paths or src_id not in schedule:
                    continue
                src_end = float(schedule[src_id][2])
                path_cost = float(paths[path_id].get("cost", 0.0))
                size = msg_size.get(msg_id, 0.0)
                arrival = src_end + path_cost + size
                if arrival > start + 1e-9:
                    violations.append({
                        "task_id": int(tid),
                        "violated_dep": int(src_id),
                        "path_id": path_id,
                        "message_id": int(msg_id),
                        "arrival_time": float(arrival),
                        "starts_at": float(start),
                        "violation_by": float(arrival - start),
                    })
    return violations
