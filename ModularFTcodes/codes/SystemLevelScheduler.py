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
from deap import tools
from deap.tools import cxPartialyMatched

import random
import time
import plotly.graph_objects as go
import plotly.express as px
import os
from datetime import datetime

import config as cfg
import GAAux as gax
import PartitionGA as pga
import SysGAAux as sgax
import ga_monitor as gamon
from collections import defaultdict, deque
import logging
log = logging.getLogger()






"""
Reconstructs a unified system-level schedule across all partitions (Fog Edge, Cloud 1/2/3),
resolving inter-partition dependencies by adjusting start and end times.

Parameters:
    PI (list): List of path indices (LSBs of path IDs).
    AML (list): Application message list (dicts with sender, receiver, size, id).
    IPM (list): List of inter-partition message IDs.
    SFE, S_C1, S_C2, S_C3 (dict): Partitioned schedules (task_id → (proc, start, end, deps)).
    IPI (dict): Inter-path information with path and cost.

Returns:
    dict: Unified system-level schedule with updated timings and dependencies.
"""

from typing import Dict, List, Tuple, Any, Optional, Set
from collections import defaultdict



from collections import defaultdict, deque
import logging
log = logging.getLogger(__name__)


class CheckpointCompatibilityError(RuntimeError):
    pass


class GracefulTermination(RuntimeError):
    def __init__(self, message, status_payload=None):
        super().__init__(message)
        self.status_payload = status_payload or {}


def SystemLevelReconstruction_2(PI, AML, IPM, SFE, S_C1, S_C2, S_C3, IPI, max_passes=20, eps=1e-9):
    """
    System-level reconstruction (IPC-only path handling, no duplicate messages).

    Key policy enforced:
      - Reconstruction assigns paths ONLY for inter-processor (IPC) messages derived from AML.
      - Dependencies are kept in triplet format [sender_task, path_id, msg_id] at the end.
      - No IPC message is duplicated due to reconstruction:
            uniqueness is enforced by (sender_task, msg_id) per receiver task,
        regardless of path_id.
      - If an IPC triplet already exists for the same (sender,msg_id), its path_id is
        overwritten to the reconstruction-selected path_id (reconstruction owns IPC paths).

    Timing constraint enforced:
      start(dst) >= max( end(src) + path_cost + msg_size ) for all IPC deps
      start(dst) >= end(src) for plain precedence deps (ints) that may exist
    """

    # ---- unify schedules
    all_schedules = {}
    task_to_proc = {}
    for sched in (SFE, S_C1, S_C2, S_C3):
        for tid, (proc, start, end, deps) in sched.items():
            all_schedules[int(tid)] = [str(proc), float(start), float(end), list(deps or [])]
            task_to_proc[int(tid)] = str(proc)

    # ---- msg size + PI-by-message-id (robust to IPM being a subset in any order)
    msg_size = {}
    for m in AML:
        try:
            msg_size[int(m["id"])] = float(m.get("size", 0.0))
        except Exception:
            pass

    if isinstance(PI, dict):
        pi_by_mid = {int(k): int(v) for k, v in PI.items()}
    else:
        # PI is a list aligned to AML order; build id->rank
        pi_by_mid = {}
        for i, m in enumerate(AML):
            try:
                pi_by_mid[int(m["id"])] = int(PI[i]) if i < len(PI) else 0
            except Exception:
                pi_by_mid[int(m.get("id", i))] = 0

    # ---- pre-index candidate paths per endpoint pair
    from collections import defaultdict

    by_endpoints = defaultdict(list)  # (src_proc, dst_proc) -> [(path_id, cost), ...] sorted by cost
    for pid, pdata in IPI.items():
        path = pdata.get("path", [])
        if not path:
            continue
        src, dst = str(path[0]), str(path[-1])
        cost = float(pdata.get("cost", 0.0))
        by_endpoints[(src, dst)].append((str(pid), cost))
        by_endpoints[(dst, src)].append((str(pid), cost))  # allow either direction

    for k in list(by_endpoints.keys()):
        by_endpoints[k].sort(key=lambda t: t[1])  # sort by cost

    # ---- build comm-edge descriptors per receiver using AML (IPC only)
    # receiver_tid -> list of (sender_tid, chosen_path_id, msg_size, msg_id)
    comm_edges = defaultdict(list)
    used_paths = 0
    for m in AML:
        try:
            mid = int(m["id"])
            s_tid = int(m["sender"])
            r_tid = int(m["receiver"])
        except Exception:
            continue
        if s_tid not in all_schedules or r_tid not in all_schedules:
            continue

        s_proc = task_to_proc[s_tid]
        r_proc = task_to_proc[r_tid]

        # only add an IPC edge if tasks are on different processors
        if s_proc == r_proc:
            continue

        cands = by_endpoints.get((s_proc, r_proc), [])
        if not cands:
            # no route known; skip adding comm latency (but keep any plain deps already present)
            continue

        rank = pi_by_mid.get(mid, 0)
        sel_id, _ = cands[rank % len(cands)]
        comm_edges[r_tid].append((s_tid, sel_id, float(msg_size.get(mid, 0.0)), mid))
        used_paths += 1

    # ---- helper: linearize a processor's whole timeline after a local shift
    def _linearize_processor(schedule, proc, t0: float = 0.0):
        tids = [tid for tid, (p, s, e, _) in schedule.items() if p == proc]
        tids.sort(key=lambda tid: (float(schedule[tid][1]), tid))
        prev_end = float(t0)
        shifted = 0

        for tid in tids:
            s, e = float(schedule[tid][1]), float(schedule[tid][2])
            dur = e - s
            if s < prev_end - eps:
                schedule[tid][1] = prev_end
                schedule[tid][2] = prev_end + dur
                shifted += 1
            prev_end = float(schedule[tid][2])

        return shifted

    # ---- helper: dedup IPC triplets in an existing deps list by (sender,msg_id),
    #              keep intra-proc triplets untouched, keep plain precedence deps untouched.
    def _dedup_existing_ipc_triplets(deps, r_tid):
        r_proc = task_to_proc.get(r_tid)
        if r_proc is None:
            return list(deps or [])

        new_deps = []
        seen_ipc = set()  # (sender,msg_id) for IPC only

        for d in deps or []:
            # keep plain precedence deps
            if isinstance(d, (int, float)) or (isinstance(d, str) and d.isdigit()):
                new_deps.append(int(d))
                continue

            # keep unknown formats as-is
            if not (isinstance(d, (list, tuple)) and len(d) == 3):
                new_deps.append(d)
                continue

            try:
                sid, pid, mid = int(d[0]), str(d[1]), int(d[2])
            except Exception:
                continue

            s_proc = task_to_proc.get(sid)
            if s_proc is None:
                # cannot classify; keep as-is
                new_deps.append([sid, pid, mid])
                continue

            if s_proc == r_proc:
                # intra-proc: keep exactly
                new_deps.append([sid, pid, mid])
            else:
                # IPC: dedup by (sid,mid) regardless of path id
                k = (sid, mid)
                if k in seen_ipc:
                    continue
                seen_ipc.add(k)
                new_deps.append([sid, pid, mid])

        return new_deps

    # ---- fixed-point relaxation: push starts to satisfy all arrivals
    shifts_total = 0
    for proc in sorted({rec[0] for rec in all_schedules.values()}):
        shifts_total += _linearize_processor(all_schedules, proc)

    for _pass in range(max_passes):
        moved = 0
        order = sorted(all_schedules.keys(), key=lambda t: (float(all_schedules[t][1]), t))

        for tid in order:
            proc, old_s, old_e, old_deps = all_schedules[tid]
            old_s = float(old_s)
            old_e = float(old_e)
            dur = old_e - old_s

            # 1) Start from deps and remove any pre-existing IPC duplicates by (sender,msg_id)
            deps = _dedup_existing_ipc_triplets(list(old_deps or []), tid)

            # 2) Build index of existing IPC triplets keyed by (sender,msg_id) so we can overwrite path_id
            r_proc = task_to_proc.get(tid)
            ipc_key_to_index = {}  # (snd, mid) -> index in deps
            if r_proc is not None:
                for i, d in enumerate(deps):
                    if isinstance(d, (list, tuple)) and len(d) == 3:
                        try:
                            snd0, pid0, mid0 = int(d[0]), str(d[1]), int(d[2])
                        except Exception:
                            continue
                        s_proc0 = task_to_proc.get(snd0)
                        if s_proc0 is not None and s_proc0 != r_proc:
                            ipc_key_to_index[(snd0, mid0)] = i

            arrivals = []

            # 3) Apply AML-derived IPC edges: compute arrivals using selected path cost,
            #    and ensure only one triplet per (sender,msg_id) by overwriting/adding.
            for (snd, pid_sel, msize, mid) in comm_edges.get(tid, []):
                if snd not in all_schedules:
                    continue

                src_end = float(all_schedules[snd][2])
                path_cost = float(IPI.get(str(pid_sel), {}).get("cost", 0.0))
                arrivals.append(src_end + path_cost + float(msize))

                k = (int(snd), int(mid))
                new_triplet = [int(snd), str(pid_sel), int(mid)]

                if k in ipc_key_to_index:
                    # overwrite path: reconstruction owns IPC paths
                    deps[ipc_key_to_index[k]] = new_triplet
                else:
                    deps.append(new_triplet)
                    ipc_key_to_index[k] = len(deps) - 1

            # 4) Arrivals from deps (after dedup+overwrite) for timing constraints
            for d in deps:
                if isinstance(d, (list, tuple)) and len(d) == 3:
                    try:
                        src_id, path_id, msg_id = int(d[0]), str(d[1]), int(d[2])
                    except Exception:
                        continue
                    if src_id in all_schedules:
                        src_end = float(all_schedules[src_id][2])
                        path_cost = float(IPI.get(path_id, {}).get("cost", 0.0))
                        msz = float(msg_size.get(msg_id, 0.0))
                        arrivals.append(src_end + path_cost + msz)
                elif isinstance(d, (int, float)) or (isinstance(d, str) and d.isdigit()):
                    src_id = int(d)
                    if src_id in all_schedules:
                        arrivals.append(float(all_schedules[src_id][2]))

            req_start = max([old_s] + arrivals) if arrivals else old_s
            if req_start > old_s + eps:
                new_s = req_start
                new_e = new_s + dur
                all_schedules[tid] = [proc, new_s, new_e, deps]
                moved += 1 + _linearize_processor(all_schedules, proc, t0=0.0)
            else:
                # persist deps if changed
                if deps != list(old_deps or []):
                    all_schedules[tid] = [proc, old_s, old_e, deps]

        shifts_total += moved
        if moved == 0:
            break

    log.info("[Reconstruction_2][IPC] paths_used=%d, tasks_shifted=%d, passes=%d",
             used_paths, shifts_total, _pass + 1)

    return all_schedules

# Commented on 24 feb 2026

# def SystemLevelReconstruction_2(PI, AML, IPM, SFE, S_C1, S_C2, S_C3, IPI, max_passes=20, eps=1e-9):
#     """
#     Generic system-level reconstruction.
#     - PI is interpreted as a dict: msg_id -> rank (if PI is a list, we build that dict from AML order)
#     - Path selection is per (src_proc, dst_proc), picking rank modulo available candidates.
#     - Enforces start(dst) >= max( end(src) + path_cost + msg_size ) for all comm deps,
#       and >= end(src) for plain precedence deps present in partition schedules.
#     """

#     # ---- unify schedules
#     all_schedules = {}
#     task_to_proc = {}
#     for sched in (SFE, S_C1, S_C2, S_C3):
#         for tid, (proc, start, end, deps) in sched.items():
#             all_schedules[int(tid)] = [str(proc), float(start), float(end), list(deps or [])]
#             task_to_proc[int(tid)] = str(proc)

#     # ---- msg size + PI-by-message-id (robust to IPM being a subset in any order)
#     msg_size = {}
#     for m in AML:
#         try:
#             msg_size[int(m["id"])] = float(m.get("size", 0.0))
#         except Exception:
#             pass

#     if isinstance(PI, dict):
#         pi_by_mid = {int(k): int(v) for k, v in PI.items()}
#     else:
#         # PI is a list aligned to AML order; build id->rank
#         pi_by_mid = {}
#         for i, m in enumerate(AML):
#             try:
#                 pi_by_mid[int(m["id"])] = int(PI[i]) if i < len(PI) else 0
#             except Exception:
#                 pi_by_mid[int(m.get("id", i))] = 0

#     # ---- pre-index candidate paths per endpoint pair
#     from collections import defaultdict, deque

#     by_endpoints = defaultdict(list)  # (src_proc, dst_proc) -> [(path_id, cost), ...] sorted by cost
#     for pid, pdata in IPI.items():
#         path = pdata.get("path", [])
#         if not path:
#             continue
#         src, dst = str(path[0]), str(path[-1])
#         cost = float(pdata.get("cost", 0.0))
#         by_endpoints[(src, dst)].append((str(pid), cost))
#         by_endpoints[(dst, src)].append((str(pid), cost))  # allow either direction

#     for k in list(by_endpoints.keys()):
#         by_endpoints[k].sort(key=lambda t: t[1])  # sort by cost

#     # ---- build comm-edge descriptors per receiver using AML (generic)
#     # receiver_tid -> list of (sender_tid, chosen_path_id, msg_size, msg_id)
#     comm_edges = defaultdict(list)
#     used_paths = 0
#     for m in AML:
#         try:
#             mid = int(m["id"])
#             s_tid = int(m["sender"])
#             r_tid = int(m["receiver"])
#         except Exception:
#             continue
#         if s_tid not in all_schedules or r_tid not in all_schedules:
#             continue

#         s_proc = task_to_proc[s_tid]
#         r_proc = task_to_proc[r_tid]

#         # only add an IPC edge if tasks are on different processors
#         if s_proc == r_proc:
#             continue

#         cands = by_endpoints.get((s_proc, r_proc), [])
#         if not cands:
#             # no route known; skip adding comm latency (but keep any plain deps already present)
#             continue

#         rank = pi_by_mid.get(mid, 0)
#         sel_id, _ = cands[rank % len(cands)]
#         comm_edges[r_tid].append((s_tid, sel_id, float(msg_size.get(mid, 0.0)), mid))
#         used_paths += 1

#     # ---- helper: linearize a processor's timeline from a given anchor
#     def _linearize_from(schedule, proc, anchor_tid, t0: float = 0.0):
#         tids = [tid for tid, (p, s, e, _) in schedule.items() if p == proc]
#         tids.sort(key=lambda tid: (float(schedule[tid][1]), tid))
#         if anchor_tid not in tids:
#             return
#         i = tids.index(anchor_tid)
#         prev_end = max(float(schedule[tids[i]][1]), t0)

#         # anchor
#         s0 = max(prev_end, float(schedule[tids[i]][1]))
#         dur0 = float(schedule[tids[i]][2]) - float(schedule[tids[i]][1])
#         schedule[tids[i]][1] = s0
#         schedule[tids[i]][2] = s0 + dur0
#         prev_end = schedule[tids[i]][2]

#         # followers
#         for j in range(i + 1, len(tids)):
#             tid = tids[j]
#             s, e = float(schedule[tid][1]), float(schedule[tid][2])
#             dur = e - s
#             if s < prev_end:
#                 s = prev_end
#                 schedule[tid][1] = s
#                 schedule[tid][2] = s + dur
#             prev_end = schedule[tid][2]

#     # ---- fixed-point relaxation: push starts to satisfy all arrivals
#     # use a stable order: sort by current start then task id; repeat until no movement
#     shifts_total = 0
#     for _pass in range(max_passes):
#         moved = 0
#         order = sorted(all_schedules.keys(), key=lambda t: (float(all_schedules[t][1]), t))
#         for tid in order:
#             proc, old_s, old_e, old_deps = all_schedules[tid]
#             old_s = float(old_s); old_e = float(old_e)
#             dur = old_e - old_s

#             # existing deps ⇒ include both triples (src, path, msg) and plain ints (predecessors)
#             deps = list(old_deps or [])
#             existing = set()
#             for d in deps:
#                 if isinstance(d, (list, tuple)) and len(d) == 3:
#                     try:
#                         existing.add((int(d[0]), str(d[1]), int(d[2])))
#                     except Exception:
#                         pass

#             # arrivals from NEW comm edges (build + append unique)
#             arrivals = []
#             for (snd, pid_sel, msize, mid) in comm_edges.get(tid, []):
#                 if snd in all_schedules:
#                     src_end = float(all_schedules[snd][2])
#                     path_cost = float(IPI.get(str(pid_sel), {}).get("cost", 0.0))
#                     arrivals.append(src_end + path_cost + float(msize))
#                     key = (int(snd), str(pid_sel), int(mid))
#                     if key not in existing:
#                         deps.append([int(snd), str(pid_sel), int(mid)])
#                         existing.add(key)

#             # arrivals from PRE-EXISTING deps
#             for d in deps:
#                 if isinstance(d, (list, tuple)) and len(d) == 3:
#                     try:
#                         src_id, path_id, msg_id = int(d[0]), str(d[1]), int(d[2])
#                     except Exception:
#                         continue
#                     if src_id in all_schedules:
#                         src_end = float(all_schedules[src_id][2])
#                         path_cost = float(IPI.get(path_id, {}).get("cost", 0.0))
#                         msz = float(msg_size.get(msg_id, 0.0))
#                         arrivals.append(src_end + path_cost + msz)
#                 elif isinstance(d, (int, float)) or (isinstance(d, str) and d.isdigit()):
#                     src_id = int(d)
#                     if src_id in all_schedules:
#                         arrivals.append(float(all_schedules[src_id][2]))

#             req_start = max([old_s] + arrivals) if arrivals else old_s
#             if req_start > old_s + eps:
#                 new_s = req_start
#                 new_e = new_s + dur
#                 all_schedules[tid] = [proc, new_s, new_e, deps]
#                 _linearize_from(all_schedules, proc, tid, t0=0.0)
#                 moved += 1
#             else:
#                 # still persist deps if augmented
#                 if len(deps) != len(old_deps or []):
#                     all_schedules[tid] = [proc, old_s, old_e, deps]

#         shifts_total += moved
#         if moved == 0:
#             break

#     log.info("[Reconstruction_2][IPC] paths_used=%d, tasks_shifted=%d, passes=%d",
#              used_paths, shifts_total, _pass + 1)

#     # Optional self-check (uncomment to assert zero IPC violations)
#     # try:
#     #     from GAAux import check_latency_violations
#     #     v = check_latency_violations(all_schedules, IPI, AML)
#     #     log.info("[Reconstruction_2][Validation] violations_after=%d", len(v))
#     # except Exception:
#     #     pass

#     return all_schedules




"""
PIDFE = processor IDs for Fog Edge partition
PIDC1 = processor IDs for Cloud 1 partition
PIDC2 = processor IDs for Cloud 2 partition
PIDC3 = processor IDs for Cloud 3 partition
PTFE = processing times for Fog Edge partition
PTC1 = processing times for Cloud 1 partition
PTC2 = processing times for Cloud 2 partition
PTC3 = processing times for Cloud 3 partition
MLFE = message list for Fog Edge partition
MLC1 = message list for Cloud 1 partition
MLC2 = message list for Cloud 2 partition
MLC3 = message list for Cloud 3 partition
PpathsFE = partition paths for Fog Edge partition
PpathsC1 = partition paths for Cloud 1 partition
PpathsC2 = partition paths for Cloud 2 partition
PpathsC3 = partition paths for Cloud 3 partition
JDFE = job data for Fog Edge partition
JDC1 = job data for Cloud 1 partition
JDC2 = job data for Cloud 2 partition
JDC3 = job data for Cloud 3 partition
TBvalues = time- budget parameters for scheduling  #removed
LSMS = list of scheduling makespan 
ML = message list for the entire application model
PI = Path information 
"""   




def SystemLevelGA(PIDFE, PIDC1, PIDC2, PIDC3,
                  PTFE, PTC1, PTC2, PTC3,
                  MLFE, MLC1, MLC2, MLC3,
                  JDFE, JDC1, JDC2, JDC3,
                  LSMS, ML, PI,
                  log_dir,
                  checkpoint_path=None,
                  resume_checkpoint=None,
                  auto_resume=False,
                  run_metadata=None):
    """
    System-level GA with budget mutation (no global per-gen overwrite).
    - Keeps your logging & plotting schema (tb_knobs_base/used, budgets/budgets_prev, etc.)
    - Updates TBs INSIDE mutation, guided by parent's MS/violation signals
    - TB mutation is applied to EVERY offspring, EVERY generation (per partition)
    - Restores CSV logging:
      generation,global_makespan,global_lateness,fitness_vsum,fitness_lateness,
      P_FE_budget,P_FE_makespan,P_FE_violation,
      P_C1_budget,P_C1_makespan,P_C1_violation,
      P_C2_budget,P_C2_makespan,P_C2_violation,
      P_C3_budget,P_C3_makespan,P_C3_violation
    """
    from deap import base, creator, tools
    import random, os, csv, logging, pickle, signal
    from collections import defaultdict

    log = logging.getLogger(__name__)
    run_metadata = dict(run_metadata or {})
    ga_start_perf = time.perf_counter()
    eval_counter = {"total": 0}
    termination_requested = {"requested": False, "signal": None, "generation": None}

    def _handle_termination_signal(signum, _frame):
        try:
            signal_name = signal.Signals(signum).name
        except Exception:
            signal_name = str(signum)
        termination_requested["requested"] = True
        termination_requested["signal"] = signal_name
        log.warning(
            "[Signal] Received %s; will checkpoint and stop at the next completed system generation.",
            signal_name,
        )

    for _sig_name in ("SIGUSR1", "SIGTERM", "SIGINT"):
        _sig = getattr(signal, _sig_name, None)
        if _sig is not None:
            try:
                signal.signal(_sig, _handle_termination_signal)
            except Exception as exc:
                log.warning("[Signal] Could not install handler for %s: %s", _sig_name, exc)

    def _peak_memory_mb():
        try:
            import resource
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        except Exception:
            return None

    # Expect cfg/gax/pga/sgax/SystemLevelReconstruction_2 available at module scope:
    # import config as cfg, GAAux as gax, PartitionGA as pga, SysGAAux as sgax
    # from SystemLevelScheduler import SystemLevelReconstruction_2

    message_ids = [m['id'] for m in ML]
    partitions = ['P_FE', 'P_C1', 'P_C2', 'P_C3']
    num_parts = len(partitions)

    # --- TB-mutation knobs (pull from cfg; provide sane defaults) ---
    TBMinMarginRatio   = getattr(cfg, 'TBMinMarginRatio',
                           getattr(cfg, 'Timebudgetmin_margin_ratio', 0.02))
    TBDeadbandRatio    = getattr(cfg, 'TBDeadbandRatio',
                           getattr(cfg, 'Timebudgetdeadband_ratio', 0.02))

    # Gradual step sizing based on delta, with rate limiters
    TBStepGainUp       = getattr(cfg, 'TBStepGainUp', 0.35)   # fraction of deficit corrected per gen
    TBStepGainDown     = getattr(cfg, 'TBStepGainDown', 0.25) # fraction of surplus shaved per gen
    TBMinStepAbs       = getattr(cfg, 'TBMinStepAbs', 3)      # absolute lower bound per-step
    TBMaxStepAbs       = getattr(cfg, 'TBMaxStepAbs', 100)    # absolute upper bound per-step
    TBMaxStepFrac      = getattr(cfg, 'TBMaxStepFrac', 0.08)  # relative upper bound per-step

    # Stabilization (hysteresis) once violation is zero
    # Hold TB inside [target + lo*ms, target + hi*ms] without changing it.
    TBHoldSlackRatioLo = getattr(cfg, 'TBHoldSlackRatioLo', 0.005)   # 0.5% of ms
    TBHoldSlackRatioHi = getattr(cfg, 'TBHoldSlackRatioHi', 0.015)   # 1.5% of ms

    # Keep regularizer so TBs don’t inflate when unnecessary
    TBSlackPenaltyWeight = getattr(cfg, 'TBSlackPenaltyWeight', 0.01)

    # Optional tiny jitter when far from target; automatically disabled in the stability band
    TBMutNoiseFrac     = getattr(cfg, 'TBMutNoiseFrac', 0.01)

    # -------------------
    # Helpers
    # -------------------
    def _repair_po_alignment(ind, partitions, num_parts, msg_len):
        """Ensure PO is a proper permutation of partitions."""
        PO = ind[:num_parts]
        missing = [p for p in partitions if p not in PO]
        seen, dup_idx = set(), []
        for k, label in enumerate(PO):
            if label in seen:
                dup_idx.append(k)
            else:
                seen.add(label)
        for k, lbl in zip(dup_idx, missing):
            PO[k] = lbl
        ind[:num_parts] = PO
        assert set(ind[:num_parts]) == set(partitions), f"PO still invalid: {ind[:num_parts]}"

    def _repair_pa_unique(ind, num_parts):
        """Ensure PA is a proper permutation of ['FE','C1','C2','C3'][:num_parts]."""
        start, end = num_parts, 2 * num_parts
        PA = ind[start:end]
        clusters = ['FE', 'C1', 'C2', 'C3'][:num_parts]
        missing = [c for c in clusters if c not in PA]
        seen, dup_idx = set(), []
        for k, c in enumerate(PA):
            if c in seen:
                dup_idx.append(k)
            else:
                seen.add(c)
        for k, c in zip(dup_idx, missing):
            PA[k] = c
        ind[start:end] = PA
        assert set(ind[start:end]) == set(clusters), f"PA not unique: {ind[start:end]}"

    def _pmx_hashable_inplace(a, b, lo, hi):
        """PMX that works with arbitrary hashable genes; crossover on [lo:hi) in place."""
        if hi - lo < 2:
            return a, b
        A = a[lo:hi]; B = b[lo:hi]
        AB = {A[i]: B[i] for i in range(len(A))}
        BA = {B[i]: A[i] for i in range(len(A))}
        for i in list(range(0, lo)) + list(range(hi, len(a))):
            v = a[i]
            while v in BA:
                v = BA[v]
            a[i] = v
        for i in list(range(0, lo)) + list(range(hi, len(b))):
            v = b[i]
            while v in AB:
                v = AB[v]
            b[i] = v
        a[lo:hi] = B; b[lo:hi] = A
        return a, b

    def _two_point_on_segment(a, b, start, end):
        """Two-point crossover on [start:end) that mutates the ORIGINAL lists (not slices)."""
        if end - start < 2:
            return a, b
        i, j = sorted(random.sample(range(start, end), 2))
        a[i:j], b[i:j] = b[i:j], a[i:j]
        return a, b

    def _tb_by_partition(PO, TB_list, partitions):
        """Map partition -> TB using ordering in PO & TB_list (aligned)."""
        return {p: int(TB_list[PO.index(p)]) for p in partitions}

    def _inner_runs_defaultdict(saved=None):
        d = defaultdict(lambda: {p: [] for p in partitions})
        if saved:
            for k, v in saved.items():
                d[k] = v
        return d

    attempt_count = 1
    interruption_count = 0
    resumed = False
    resume_generation = None
    accumulated_runtime_before_attempt = 0.0
    checkpoint_path = os.fspath(checkpoint_path) if checkpoint_path else None
    resume_checkpoint = os.fspath(resume_checkpoint) if resume_checkpoint else None

    def _normalize_identity_value(value):
        if isinstance(value, float):
            return round(value, 10)
        if isinstance(value, dict):
            return {str(k): _normalize_identity_value(v) for k, v in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [_normalize_identity_value(v) for v in value]
        return value

    def _checkpoint_identity(metadata):
        return {
            "run_key": metadata.get("run_key") or metadata.get("run_id"),
            "workload": metadata.get("workload") or metadata.get("am_id"),
            "am_id": metadata.get("am_id"),
            "am_size": metadata.get("am_size"),
            "base_deadline": _normalize_identity_value(metadata.get("base_deadline")),
            "deadline_ratio": _normalize_identity_value(metadata.get("deadline_ratio")),
            "actual_deadline_value": _normalize_identity_value(metadata.get("actual_deadline_value")),
            "seed": metadata.get("seed"),
            "variant": metadata.get("variant"),
            "ga_configuration": _normalize_identity_value(metadata.get("ga_configuration")),
            "git_commit_sha": metadata.get("git_commit_sha"),
            "input_file_fingerprints": _normalize_identity_value(metadata.get("input_file_fingerprints")),
        }

    checkpoint_identity = _checkpoint_identity(run_metadata)

    def _identity_mismatches(saved_identity):
        mismatches = []
        for key, expected in checkpoint_identity.items():
            actual = (saved_identity or {}).get(key)
            if _normalize_identity_value(actual) != _normalize_identity_value(expected):
                mismatches.append(key)
        return mismatches

    def _checkpoint_sidecar_path(path):
        root, ext = os.path.splitext(path)
        return f"{root}.json" if ext else f"{path}.json"

    def _attempt_runtime_s():
        return time.perf_counter() - ga_start_perf

    def _accumulated_runtime_s():
        return accumulated_runtime_before_attempt + _attempt_runtime_s()

    def _json_safe_checkpoint_summary(state):
        keys = (
            "version", "completed_generation", "run_key", "workload", "am_id", "am_size",
            "base_deadline", "deadline_ratio", "actual_deadline", "actual_deadline_value",
            "seed", "variant", "ga_configuration", "git_commit_sha", "input_file_fingerprints",
            "attempt_count", "interruption_count", "resumed", "resume_generation",
            "final_attempt_system_ga_runtime_s", "accumulated_system_ga_runtime_s",
            "checkpoint_identity",
        )
        return {key: state.get(key) for key in keys}

    def _save_checkpoint(completed_generation, population, history):
        if not checkpoint_path:
            return
        attempt_runtime = _attempt_runtime_s()
        accumulated_runtime = accumulated_runtime_before_attempt + attempt_runtime
        state = {
            "version": 2,
            "completed_generation": int(completed_generation),
            "population": population,
            "sys_history": history,
            "system_level_history": history,
            "inner_runs_by_sysgen": dict(inner_runs_by_sysgen),
            "required_partition_histories": dict(inner_runs_by_sysgen),
            "budgets_per_run_by_sysgen": dict(budgets_per_run_by_sysgen),
            "budget_histories": dict(budgets_per_run_by_sysgen),
            "random_state": random.getstate(),
            "python_random_state": random.getstate(),
            "numpy_random_state": np.random.get_state(),
            "run_metadata": run_metadata,
            "checkpoint_identity": checkpoint_identity,
            "run_key": checkpoint_identity.get("run_key"),
            "workload": checkpoint_identity.get("workload"),
            "am_id": checkpoint_identity.get("am_id"),
            "am_size": checkpoint_identity.get("am_size"),
            "base_deadline": checkpoint_identity.get("base_deadline"),
            "deadline_ratio": checkpoint_identity.get("deadline_ratio"),
            "actual_deadline": checkpoint_identity.get("actual_deadline_value"),
            "actual_deadline_value": checkpoint_identity.get("actual_deadline_value"),
            "seed": checkpoint_identity.get("seed"),
            "variant": checkpoint_identity.get("variant"),
            "ga_configuration": checkpoint_identity.get("ga_configuration"),
            "git_commit_sha": checkpoint_identity.get("git_commit_sha"),
            "input_file_fingerprints": checkpoint_identity.get("input_file_fingerprints"),
            "attempt_count": int(attempt_count),
            "interruption_count": int(interruption_count),
            "resumed": bool(resumed),
            "resume_generation": resume_generation,
            "final_attempt_system_ga_runtime_s": float(attempt_runtime),
            "accumulated_system_ga_runtime_s": float(accumulated_runtime),
        }
        checkpoint_dir = os.path.dirname(checkpoint_path)
        if checkpoint_dir:
            os.makedirs(checkpoint_dir, exist_ok=True)
        tmp_path = f"{checkpoint_path}.tmp"
        with open(tmp_path, "wb") as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp_path, checkpoint_path)
        sidecar_path = _checkpoint_sidecar_path(checkpoint_path)
        tmp_sidecar_path = f"{sidecar_path}.tmp"
        with open(tmp_sidecar_path, "w", encoding="utf-8") as f:
            json.dump(_json_safe_checkpoint_summary(state), f, indent=2, default=str)
        os.replace(tmp_sidecar_path, sidecar_path)
        log.info("[Checkpoint] Saved generation %s to %s", completed_generation, checkpoint_path)

    def _trim_history_to_generation(history, completed_generation):
        completed_generation = int(completed_generation)
        if completed_generation <= 0:
            for key, value in list(history.items()):
                if isinstance(value, list):
                    history[key] = []
            return history
        gens = [int(g) for g in history.get("gen", [])]
        index_by_generation = {}
        for idx, generation in enumerate(gens):
            if 1 <= generation <= completed_generation:
                index_by_generation[generation] = idx
        missing = [g for g in range(1, completed_generation + 1) if g not in index_by_generation]
        if missing:
            raise CheckpointCompatibilityError(
                "Checkpoint history is missing completed generation row(s): " +
                ", ".join(str(g) for g in missing)
            )
        keep_indices = [index_by_generation[g] for g in range(1, completed_generation + 1)]
        original_len = len(gens)
        for key, value in list(history.items()):
            if isinstance(value, list) and len(value) == original_len:
                history[key] = [value[idx] for idx in keep_indices]
        history["gen"] = list(range(1, completed_generation + 1))
        return history

    def _trim_generation_mapping(mapping, completed_generation):
        trimmed = {}
        for key, value in dict(mapping or {}).items():
            try:
                gen = int(key)
            except Exception:
                continue
            if 0 <= gen <= int(completed_generation):
                trimmed[str(gen)] = value
        return trimmed

    def _rewrite_csv_to_completed_generation(csv_path, csv_columns, completed_generation):
        completed_generation = int(completed_generation)
        rows_by_generation = {}
        if os.path.exists(csv_path):
            with open(csv_path, "r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        generation = int(row.get("generation", ""))
                    except Exception:
                        continue
                    if 1 <= generation <= completed_generation:
                        rows_by_generation[generation] = row
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=csv_columns)
            writer.writeheader()
            for generation in range(1, completed_generation + 1):
                row = rows_by_generation.get(generation)
                if row:
                    writer.writerow({col: row.get(col) for col in csv_columns})

    def _load_checkpoint(path):
        if os.path.isdir(path):
            path = os.path.join(path, "checkpoint_latest.pkl")
        with open(path, "rb") as f:
            state = pickle.load(f)
        if state.get("version") != 2:
            raise CheckpointCompatibilityError(
                f"Unsupported or metadata-incomplete checkpoint version in {path}: {state.get('version')}"
            )
        mismatches = _identity_mismatches(state.get("checkpoint_identity"))
        if mismatches:
            raise CheckpointCompatibilityError(
                "Checkpoint does not match this manifest/configuration; mismatched field(s): " +
                ", ".join(mismatches)
            )
        if "python_random_state" in state:
            random.setstate(state["python_random_state"])
        elif "random_state" in state:
            random.setstate(state["random_state"])
        if "numpy_random_state" in state:
            np.random.set_state(state["numpy_random_state"])
        log.info("[Checkpoint] Loaded generation %s from %s", state.get("completed_generation", 0), path)
        return state

    # -------------------
    # Deep histories collectors
    # -------------------
    inner_runs_by_sysgen = defaultdict(lambda: {p: [] for p in partitions})
    budgets_per_run_by_sysgen = defaultdict(list)
    _current_sys_gen = {"g": 0}

    # -------------------
    # GA Setup (2D fitness)
    # -------------------
    if 'SysFitness2D' not in creator.__dict__:
        creator.create('SysFitness2D', base.Fitness,
                       weights=(getattr(cfg, 'SystemLevelWeightViolationSum', -1.0),
                                getattr(cfg, 'SystemLevelWeightGlobalLateness', -1.0)))
    if 'SysIndividual' not in creator.__dict__:
        creator.create('SysIndividual', list, fitness=creator.SysFitness2D)

    toolbox = base.Toolbox()

    def create_aligned_individual():
        PO = partitions.copy(); random.shuffle(PO)
        PA = random.sample(['FE', 'C1', 'C2', 'C3'][:num_parts], num_parts)
        equal_budget = LSMS // num_parts
        TB = [equal_budget for _ in range(num_parts)]
        PIgenes = [random.choice([0, 1, 2, 3]) for _ in range(len(message_ids))]
        ind = creator.SysIndividual(PO + PA + PIgenes + TB)
        _repair_po_alignment(ind, partitions, num_parts, len(message_ids))
        _repair_pa_unique(ind, num_parts)
        return ind

    toolbox.register("individual", create_aligned_individual)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)

    # -------------------
    # Evaluate → (viol_sum_eff, lateness_clipped)
    # -------------------
    def evaluate(ind, gen_context="Init"):
        eval_counter["total"] += 1
        _repair_po_alignment(ind, partitions, num_parts, len(message_ids))
        _repair_pa_unique(ind, num_parts)

        PO = ind[:num_parts]
        PA = ind[num_parts:2 * num_parts]
        PIgenes = ind[2 * num_parts:2 * num_parts + len(message_ids)]
        TB = ind[2 * num_parts + len(message_ids):]
        triple_map = {PO[i]: (PA[i], TB[i]) for i in range(num_parts)}

        pd_map = {
            'P_FE': (PTFE, MLFE, JDFE),
            'P_C1': (PTC1, MLC1, JDC1),
            'P_C2': (PTC2, MLC2, JDC2),
            'P_C3': (PTC3, MLC3, JDC3)
        }
        cr_map = {'FE': (PIDFE, PI), 'C1': (PIDC1, PI), 'C2': (PIDC2, PI), 'C3': (PIDC3, PI)}

        results, makespans = {}, {}
        part_viol = {}
        part_histories = {}
        gkey = str(_current_sys_gen["g"])

        for p in partitions:
            if p not in triple_map:
                _repair_po_alignment(ind, partitions, num_parts, len(message_ids))
                _repair_pa_unique(ind, num_parts)
                PO = ind[:num_parts]
                PA = ind[num_parts:2 * num_parts]
                TB = ind[2 * num_parts + len(message_ids):]
                triple_map = {PO[i]: (PA[i], TB[i]) for i in range(num_parts)}

            cluster, tb = triple_map[p]
            proc_ids, paths = cr_map[cluster]
            ptimes, msgs, jdat = pd_map[p]

            sched, phist = pga.NEW_GA_V2(proc_ids, ptimes, msgs, paths, jdat, time_budget=round(tb))
            ms = round(gax.compute_makespan(sched))

            log.info(f"[Eval] (Context: {gen_context}) {p} -> {cluster} | Budget={round(tb)} | MS={ms}")
            makespans[p] = ms
            results[p] = sched
            part_viol[p] = max(0, ms - tb)
            part_histories[p] = phist or {}

            inner_runs_by_sysgen[gkey][p].append({
                "history": phist or {},
                "budget": int(round(tb))
            })

        budgets_this_run = {pp: int(round(triple_map[pp][1])) for pp in partitions}
        budgets_per_run_by_sysgen[gkey].append(budgets_this_run)

        # Global schedule
        Saux = [results[p] for p in partitions]
        IPM = sgax.get_unused_message_ids(Saux, ML)
        gglob = SystemLevelReconstruction_2(
            PIgenes, ML, IPM,
            results['P_FE'], results['P_C1'],
            results['P_C2'], results['P_C3'], PI
        )
        gms = round(gax.compute_makespan(gglob))
        lateness_signed = gms - LSMS
        lateness_clipped = max(0, lateness_signed)
        log.info(f"[Eval-Global] (gen={_current_sys_gen['g']}, ctx={gen_context}) "
                 f"GlobalMS={gms} SignedLate={lateness_signed} Deadline={LSMS}")

        # Attach artifacts for reuse after selection + TB mutation guidance
        ind.eval_PO = PO[:]; ind.eval_PA = PA[:]; ind.eval_PI = PIgenes[:]; ind.eval_TB = TB[:]
        ind.triple_map = triple_map.copy()
        ind.partition_schedules = results.copy()
        ind.makespans = makespans.copy()
        ind.partition_ga_histories = part_histories.copy()
        ind.global_schedule = gglob
        ind.global_makespan = gms
        ind.lateness_signed = lateness_signed
        ind.partition_violations = part_viol.copy()

        # Slack regularizer to avoid TB inflation
        extra_slack = {}
        for p in partitions:
            ms = float(makespans[p]); tb = float(triple_map[p][1])
            target_p = ms * (1.0 + TBMinMarginRatio)
            extra_slack[p] = max(0.0, tb - target_p)
        ind.extra_slack = extra_slack

        viol_sum = sum(part_viol.values())
        # viol_sum_eff = viol_sum + TBSlackPenaltyWeight * sum(extra_slack.values())

        return (viol_sum, lateness_clipped)

    toolbox.register('evaluate', evaluate)

    # -------------------
    # GA Operators
    # -------------------
    toolbox.register("select_parents", tools.selTournamentDCD)

    def _assert_tb_alignment_with_parent_map(child, parent_map, num_parts, msg_len, label="child"):
        """Ensure child's TB[i] equals parent's TB for partition label child[i]."""
        po = child[:num_parts]
        tb_st = 2 * num_parts + msg_len
        for i, p in enumerate(po):
            expected = parent_map.get(p, None)
            if expected is None:
                raise AssertionError(f"[{label}] Unknown partition label {p}")
            got = child[tb_st + i]
            assert got == expected, (
                f"[{label}] TB misaligned for {p} at idx {i}: got {got}, expected {expected}"
            )

    def _assert_tb_alignment_basic(ind, num_parts, msg_len, label="ind"):
        tb_st = 2 * num_parts + msg_len
        tb_ed = tb_st + num_parts
        TB = ind[tb_st:tb_ed]
        assert len(TB) == num_parts, f"[{label}] TB segment length mismatch"
        for i, v in enumerate(TB):
            assert isinstance(v, (int, float)), f"[{label}] TB[{i}] not numeric: {v}"

    def mate_sys(a, b):
        num_parts_local = num_parts
        po_lo, po_hi  = 0, num_parts_local
        pa_lo, pa_hi  = num_parts_local, 2 * num_parts_local
        pi_lo, pi_hi  = 2 * num_parts_local, 2 * num_parts_local + len(message_ids)
        tb_lo, tb_hi  = pi_hi, pi_hi + num_parts_local

        a_map = {a[i]: a[tb_lo + i] for i in range(num_parts_local)}
        b_map = {b[i]: b[tb_lo + i] for i in range(num_parts_local)}

        _pmx_hashable_inplace(a, b, po_lo, po_hi)
        _pmx_hashable_inplace(a, b, pa_lo, pa_hi)
        _repair_po_alignment(a, partitions, num_parts_local, len(message_ids))
        _repair_po_alignment(b, partitions, num_parts_local, len(message_ids))
        _repair_pa_unique(a, num_parts_local)
        _repair_pa_unique(b, num_parts_local)

        POa2 = a[po_lo:po_hi]; POb2 = b[po_lo:po_hi]
        for i, p in enumerate(POa2):
            a[tb_lo + i] = a_map[p]
        for i, p in enumerate(POb2):
            b[tb_lo + i] = b_map[p]

        if getattr(cfg, "DebugAssertTB", True):
            _assert_tb_alignment_with_parent_map(a, a_map, num_parts_local, len(message_ids), "child A")
            _assert_tb_alignment_with_parent_map(b, b_map, num_parts_local, len(message_ids), "child B")

        _two_point_on_segment(a, b, pi_lo, pi_hi)
        _repair_po_alignment(a, partitions, num_parts_local, len(message_ids))
        _repair_po_alignment(b, partitions, num_parts_local, len(message_ids))
        _repair_pa_unique(a, num_parts_local)
        _repair_pa_unique(b, num_parts_local)
        return a, b

    toolbox.register("mate", mate_sys)

    # Structural mutation (probabilistic)
    def mutate_struct(ind):
        nparts = num_parts
        po_st, pa_st = 0, nparts
        tb_st = 2 * nparts + len(message_ids)

        # Triple swap keeps alignment PO/PA/TB
        i, j = random.sample(range(nparts), 2)
        ind[po_st + i], ind[po_st + j] = ind[po_st + j], ind[po_st + i]
        ind[pa_st + i], ind[pa_st + j] = ind[pa_st + j], ind[pa_st + i]
        ind[tb_st + i], ind[tb_st + j] = ind[tb_st + j], ind[tb_st + i]

        # Occasionally explore PA only
        if random.random() < 0.25:
            i2, j2 = random.sample(range(nparts), 2)
            ind[pa_st + i2], ind[pa_st + j2] = ind[pa_st + j2], ind[pa_st + i2]

        # Mutate PI with small probability
        pi_st, pi_ed = 2 * nparts, 2 * nparts + len(message_ids)
        for idx in range(pi_st, pi_ed):
            if random.random() < 0.05:
                ind[idx] = random.choice([0, 1, 2, 3])

        _repair_po_alignment(ind, partitions, nparts, len(message_ids))
        _repair_pa_unique(ind, nparts)
        if getattr(cfg, "DebugAssertTB", True):
            _assert_tb_alignment_basic(ind, nparts, len(message_ids), "mutant")
        return ind,

    toolbox.register('mutate', mutate_struct)

    # TB-only mutation (APPLIED EVERY GENERATION, per partition)
    def mutate_tb(ind):
        nparts = num_parts
        po = ind[:nparts]
        tb_st = 2 * nparts + len(message_ids)

        # Parent signals from last evaluation (cloned over in _clone_with_attrs)
        parent_ms   = getattr(ind, "makespans", {}) or {}
        parent_viol = getattr(ind, "partition_violations", {}) or {}

        for k, p in enumerate(po):
            tb     = float(ind[tb_st + k])
            ms     = float(parent_ms.get(p, tb))          # fallback: tb
            viol   = int(parent_viol.get(p, 0))

            # Safety target and stability band
            target = ms * (1.0 + TBMinMarginRatio)
            band_lo = target + TBHoldSlackRatioLo * ms
            band_hi = target + TBHoldSlackRatioHi * ms

            # Rate limiters
            rel_cap = TBMaxStepFrac * max(1.0, tb)
            abs_cap = TBMaxStepAbs
            step_cap = max(TBMinStepAbs, min(rel_cap, abs_cap))

            # --- Cases ---
            if viol > 0 or tb < ms:
                # Need to increase: correct a fraction of the deficit (to ms or to target, whichever is larger)
                deficit = max(ms - tb, target - tb)
                step = min(step_cap, max(TBMinStepAbs, int(round(TBStepGainUp * deficit))))
                new_tb = tb + step
                # Don’t overshoot too far; stop at the upper edge of the stability band
                new_tb = min(new_tb, band_hi)
            elif tb >= band_hi:
                # Clear surplus well above the stability band → shave gradually toward band_lo
                surplus = tb - band_lo
                step = min(step_cap, max(TBMinStepAbs, int(round(TBStepGainDown * surplus))))
                new_tb = max(band_lo, tb - step)
            elif tb < target:
                # No violation but below safety target: gently nudge up toward band_lo
                deficit = band_lo - tb
                step = min(step_cap, max(TBMinStepAbs, int(round(0.5 * TBStepGainUp * deficit))))
                new_tb = min(band_lo, tb + step)
            else:
                # Inside stability band [band_lo, band_hi] with zero violation → HOLD (no noise)
                new_tb = tb

            # Far from band? allow tiny unbiased jitter; otherwise none
            if new_tb == tb and (tb >= band_hi or tb <= target):
                jitter = int(round(random.gauss(0.0, TBMutNoiseFrac * max(1.0, tb))))
                # keep within [target, ∞) and don’t jump out of band if we’re already stable
                if tb < target:
                    new_tb = max(target, tb + jitter)
                elif tb > band_hi:
                    new_tb = max(band_lo, tb + jitter)   # ensure not below band_lo
                # else: in band → still no jitter

            ind[tb_st + k] = int(round(new_tb))

        return ind,

    toolbox.register('mutate_tb', mutate_tb)

    # Clone that preserves parent's signals (needed for mutate_tb guidance)
    def _clone_with_attrs(src):
        c = creator.SysIndividual(src)
        for attr in ("makespans", "partition_violations"):
            if hasattr(src, attr):
                setattr(c, attr, getattr(src, attr))
        return c

    # per-generation history (kept same keys for your plots)
    sys_history = {
        "gen": [],
        "global_makespan": [],
        "global_lateness": [],          # clipped (>=0)
        "global_lateness_signed": [],   # signed (can be <0)
        "budgets": [],                  # BEST's TBs that produced MS (compat: previously TB_next)
        "budgets_prev": [],             # identical to budgets (no global overwrite path)
        "makespans": [],
        "violations": [],
        "best_fitness": [],
        "fitness_vsum": [],
        "fitness_lateness": [],
        "tb_knobs_base": [],            # kept for plotting compatibility
        "tb_knobs_used": [],
        "elapsed_generation_s": [],
        "cumulative_runtime_s": [],
        "evaluated_individuals_this_generation": [],
        "total_evaluated_individuals": [],
        "deadline_feasible": [],
        "partition_feasible": [],
        "fully_feasible": [],
        "best_global_makespan_so_far": [],
        "best_feasible_makespan_so_far": [],
        "best_feasible_generation": [],
        "peak_memory_mb": [],
    }

    def _empty_run_stats():
        return {
            "first_deadline_feasible_generation": None,
            "first_partition_feasible_generation": None,
            "first_fully_feasible_generation": None,
            "best_global_makespan_so_far": None,
            "best_feasible_makespan_so_far": None,
            "best_feasible_generation": None,
        }

    def _update_run_stats(stats, generation, global_makespan, lateness_clipped, viol_sum):
        generation = int(generation)
        global_makespan = int(global_makespan)
        lateness_clipped = int(lateness_clipped)
        viol_sum = float(viol_sum)
        deadline_feasible = lateness_clipped == 0
        partition_feasible = viol_sum == 0
        fully_feasible = deadline_feasible and partition_feasible

        if stats["best_global_makespan_so_far"] is None or global_makespan < stats["best_global_makespan_so_far"]:
            stats["best_global_makespan_so_far"] = global_makespan
        if deadline_feasible and stats["first_deadline_feasible_generation"] is None:
            stats["first_deadline_feasible_generation"] = generation
        if partition_feasible and stats["first_partition_feasible_generation"] is None:
            stats["first_partition_feasible_generation"] = generation
        if fully_feasible:
            if stats["first_fully_feasible_generation"] is None:
                stats["first_fully_feasible_generation"] = generation
            if stats["best_feasible_makespan_so_far"] is None or global_makespan < stats["best_feasible_makespan_so_far"]:
                stats["best_feasible_makespan_so_far"] = global_makespan
                stats["best_feasible_generation"] = generation
        return deadline_feasible, partition_feasible, fully_feasible

    def _derive_run_stats_from_history(history):
        stats = _empty_run_stats()
        gens = history.get("gen", []) or []
        gms = history.get("global_makespan", []) or []
        lates = history.get("global_lateness", []) or []
        viols = history.get("fitness_vsum", []) or []
        for idx, generation in enumerate(gens):
            if idx < len(gms) and idx < len(lates) and idx < len(viols):
                _update_run_stats(stats, generation, gms[idx], lates[idx], viols[idx])
        return stats

    # -------------------
    # Init / Resume Population
    # -------------------
    resume_path = resume_checkpoint
    if auto_resume and checkpoint_path and os.path.exists(checkpoint_path):
        resume_path = checkpoint_path

    if resume_path:
        if os.path.isdir(resume_path):
            resume_path = os.path.join(resume_path, "checkpoint_latest.pkl")
        if os.path.exists(resume_path):
            state = _load_checkpoint(resume_path)
            pop = state["population"]
            start_gen = int(state.get("completed_generation", 0))
            sys_history = _trim_history_to_generation(state.get("sys_history", sys_history), start_gen)
            inner_runs_by_sysgen = _inner_runs_defaultdict(
                _trim_generation_mapping(state.get("inner_runs_by_sysgen"), start_gen)
            )
            budgets_per_run_by_sysgen = defaultdict(
                list,
                _trim_generation_mapping(state.get("budgets_per_run_by_sysgen", {}), start_gen),
            )
            accumulated_runtime_before_attempt = float(state.get("accumulated_system_ga_runtime_s", 0.0) or 0.0)
            attempt_count = int(state.get("attempt_count", 1) or 1) + 1
            interruption_count = int(state.get("interruption_count", 0) or 0)
            resumed = True
            resume_generation = start_gen
        else:
            raise FileNotFoundError(f"Resume checkpoint was not found: {resume_path}")
    else:
        pop = toolbox.population(n=getattr(cfg, "SystemLevelPopulationSize", 64))
        for ind in pop:
            _repair_po_alignment(ind, partitions, num_parts, len(message_ids))
            _repair_pa_unique(ind, num_parts)
            if not ind.fitness.valid:
                ind.fitness.values = toolbox.evaluate(ind, gen_context="Init")

        pop[:] = tools.selNSGA2(pop, len(pop))
        start_gen = 0
        _save_checkpoint(0, pop, sys_history)

    run_stats = _derive_run_stats_from_history(sys_history)

    # --- CSV summary: keep the legacy columns and add run metadata for aggregation. ---
    os.makedirs(log_dir, exist_ok=True)
    csv_path = os.path.join(log_dir, "system_ga_summary.csv")
    csv_columns = [
        "run_id", "am_id", "am_size", "base_deadline", "deadline_ratio", "actual_deadline_value",
        "seed", "variant", "slurm_job_id", "slurm_array_job_id", "slurm_array_task_id",
        "attempt_count", "interruption_count", "resumed", "resume_generation",
        "generation", "elapsed_generation_s", "cumulative_runtime_s", "attempt_runtime_s",
        "evaluated_individuals_this_generation", "total_evaluated_individuals",
        "global_makespan", "global_lateness", "global_lateness_signed", "global_lateness_clipped",
        "fitness_vsum", "fitness_lateness",
        "deadline_feasible", "partition_feasible", "fully_feasible",
        "first_deadline_feasible_generation", "first_partition_feasible_generation", "first_fully_feasible_generation",
        "best_global_makespan_so_far", "best_feasible_makespan_so_far", "best_feasible_generation",
        "P_FE_budget", "P_FE_makespan", "P_FE_violation",
        "P_C1_budget", "P_C1_makespan", "P_C1_violation",
        "P_C2_budget", "P_C2_makespan", "P_C2_violation",
        "P_C3_budget", "P_C3_makespan", "P_C3_violation",
        "peak_memory_mb",
    ]
    write_header = True
    if os.path.exists(csv_path):
        try:
            with open(csv_path, "r", newline="") as f:
                header_line = f.readline().strip()
            write_header = header_line != ",".join(csv_columns)
        except Exception:
            write_header = True
    if write_header:
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=csv_columns)
            w.writeheader()
    if start_gen > 0:
        _rewrite_csv_to_completed_generation(csv_path, csv_columns, start_gen)

    ngen = getattr(cfg, "SystemLevelGenerations", 80)
    for gen in range(start_gen, ngen):
        log.info(f"[SystemLevelGA] Generation {gen + 1}/{ngen}")
        _current_sys_gen["g"] = gen + 1
        gen_start_perf = time.perf_counter()
        gen_eval_start = eval_counter["total"]

        # Selection & cloning (preserve parent's signals for TB mutation guidance)
        parents = toolbox.select_parents(pop, len(pop))
        offspring = [_clone_with_attrs(ind) for ind in parents]

        # Crossover
        for c1, c2 in zip(offspring[::2], offspring[1::2]):
            if random.random() < getattr(cfg, "SystemLevelCrossOverProb", 0.8):
                toolbox.mate(c1, c2)
                if hasattr(c1.fitness, 'values'): del c1.fitness.values
                if hasattr(c2.fitness, 'values'): del c2.fitness.values

        # Structural mutation (probabilistic) + TB mutation (ALWAYS)
        for mutant in offspring:
            if random.random() < getattr(cfg, "SystemLevelMutationProb", 0.7):
                toolbox.mutate(mutant)
                if hasattr(mutant.fitness, 'values'):
                    del mutant.fitness.values
            # ALWAYS mutate TBs per partition, every generation
            toolbox.mutate_tb(mutant)
            if hasattr(mutant.fitness, 'values'):
                del mutant.fitness.values

        # Evaluate newborns
        for ind in offspring:
            if not ind.fitness.valid:
                ind.fitness.values = toolbox.evaluate(ind, gen_context=f"Gen-{gen + 1}")

        # Environmental selection
        pop[:] = tools.selNSGA2(pop + offspring, len(pop))

        # Best (lexicographic by fitness tuple)
        best = min(pop, key=lambda ind: ind.fitness.values)
        bf0, bf1 = best.fitness.values

        # Reuse artifacts
        PO        = best.eval_PO
        TB_used   = best.eval_TB
        makespans = best.makespans
        global_makespan = best.global_makespan
        lateness_signed = best.lateness_signed
        lateness_clipped = max(0, lateness_signed)
        violations_current = {p: int(best.partition_violations.get(p, 0)) for p in partitions}

        # Log TB knobs (compat with your plots) — reflect TB-mutation parameters
        tb_base = {
            "min_margin_ratio": TBMinMarginRatio,
            "deadband_ratio":   TBDeadbandRatio,
            "step_gain_up":     TBStepGainUp,
            "step_gain_down":   TBStepGainDown,
            "min_step_abs":     TBMinStepAbs,
            "max_step_abs":     TBMaxStepAbs,
            "max_step_frac":    TBMaxStepFrac,
            "hold_lo_ratio":    TBHoldSlackRatioLo,
            "hold_hi_ratio":    TBHoldSlackRatioHi,
            "noise_frac":       TBMutNoiseFrac,
            "slack_penalty_weight": TBSlackPenaltyWeight,
        }
        sys_history["tb_knobs_base"].append(tb_base.copy())
        sys_history["tb_knobs_used"].append(tb_base.copy())

        # History (kept same keys)
        sys_history["gen"].append(gen + 1)
        sys_history["global_makespan"].append(int(global_makespan))
        sys_history["global_lateness"].append(int(lateness_clipped))
        sys_history["global_lateness_signed"].append(int(lateness_signed))
        sys_history["budgets_prev"].append({p: int(TB_used[PO.index(p)]) for p in partitions})
        sys_history["budgets"].append({p: int(TB_used[PO.index(p)]) for p in partitions})
        sys_history["makespans"].append({p: int(makespans[p]) for p in partitions})
        sys_history["violations"].append(violations_current)
        sys_history["best_fitness"].append((float(bf0), float(bf1)))
        sys_history["fitness_vsum"].append(float(bf0))
        sys_history["fitness_lateness"].append(float(bf1))

        elapsed_generation_s = time.perf_counter() - gen_start_perf
        attempt_runtime_s = _attempt_runtime_s()
        cumulative_runtime_s = accumulated_runtime_before_attempt + attempt_runtime_s
        evaluated_this_generation = eval_counter["total"] - gen_eval_start
        total_evaluated_individuals = eval_counter["total"]
        peak_memory_mb = _peak_memory_mb()
        viol_sum_current = int(sum(violations_current.values()))
        deadline_feasible, partition_feasible, fully_feasible = _update_run_stats(
            run_stats, gen + 1, global_makespan, lateness_clipped, viol_sum_current
        )
        sys_history["elapsed_generation_s"].append(float(elapsed_generation_s))
        sys_history["cumulative_runtime_s"].append(float(cumulative_runtime_s))
        sys_history["evaluated_individuals_this_generation"].append(int(evaluated_this_generation))
        sys_history["total_evaluated_individuals"].append(int(total_evaluated_individuals))
        sys_history["deadline_feasible"].append(bool(deadline_feasible))
        sys_history["partition_feasible"].append(bool(partition_feasible))
        sys_history["fully_feasible"].append(bool(fully_feasible))
        sys_history["best_global_makespan_so_far"].append(run_stats["best_global_makespan_so_far"])
        sys_history["best_feasible_makespan_so_far"].append(run_stats["best_feasible_makespan_so_far"])
        sys_history["best_feasible_generation"].append(run_stats["best_feasible_generation"])
        sys_history["peak_memory_mb"].append(peak_memory_mb)

        # --- CSV: write this generation’s summary ---
        tb_row = _tb_by_partition(PO, TB_used, partitions)
        csv_row = {
            "run_id": run_metadata.get("run_id"),
            "am_id": run_metadata.get("am_id"),
            "am_size": run_metadata.get("am_size"),
            "base_deadline": run_metadata.get("base_deadline"),
            "deadline_ratio": run_metadata.get("deadline_ratio"),
            "actual_deadline_value": run_metadata.get("actual_deadline_value"),
            "seed": run_metadata.get("seed"),
            "variant": run_metadata.get("variant"),
            "slurm_job_id": run_metadata.get("slurm_job_id"),
            "slurm_array_job_id": run_metadata.get("slurm_array_job_id"),
            "slurm_array_task_id": run_metadata.get("slurm_array_task_id"),
            "attempt_count": int(attempt_count),
            "interruption_count": int(interruption_count),
            "resumed": bool(resumed),
            "resume_generation": resume_generation,
            "generation": gen + 1,
            "elapsed_generation_s": elapsed_generation_s,
            "cumulative_runtime_s": cumulative_runtime_s,
            "attempt_runtime_s": attempt_runtime_s,
            "evaluated_individuals_this_generation": evaluated_this_generation,
            "total_evaluated_individuals": total_evaluated_individuals,
            "global_makespan": int(global_makespan),
            "global_lateness": int(lateness_clipped),
            "global_lateness_signed": int(lateness_signed),
            "global_lateness_clipped": int(lateness_clipped),
            "fitness_vsum": float(bf0),
            "fitness_lateness": float(bf1),
            "deadline_feasible": bool(deadline_feasible),
            "partition_feasible": bool(partition_feasible),
            "fully_feasible": bool(fully_feasible),
            "first_deadline_feasible_generation": run_stats["first_deadline_feasible_generation"],
            "first_partition_feasible_generation": run_stats["first_partition_feasible_generation"],
            "first_fully_feasible_generation": run_stats["first_fully_feasible_generation"],
            "best_global_makespan_so_far": run_stats["best_global_makespan_so_far"],
            "best_feasible_makespan_so_far": run_stats["best_feasible_makespan_so_far"],
            "best_feasible_generation": run_stats["best_feasible_generation"],
            "P_FE_budget": int(tb_row["P_FE"]),
            "P_FE_makespan": int(makespans["P_FE"]),
            "P_FE_violation": int(violations_current["P_FE"]),
            "P_C1_budget": int(tb_row["P_C1"]),
            "P_C1_makespan": int(makespans["P_C1"]),
            "P_C1_violation": int(violations_current["P_C1"]),
            "P_C2_budget": int(tb_row["P_C2"]),
            "P_C2_makespan": int(makespans["P_C2"]),
            "P_C2_violation": int(violations_current["P_C2"]),
            "P_C3_budget": int(tb_row["P_C3"]),
            "P_C3_makespan": int(makespans["P_C3"]),
            "P_C3_violation": int(violations_current["P_C3"]),
            "peak_memory_mb": peak_memory_mb,
        }
        with open(csv_path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=csv_columns)
            w.writerow(csv_row)

        log.info(f"[Generation {gen + 1}] GlobalMS={global_makespan} "
                 f"Late={lateness_signed} TB={sys_history['budgets'][-1]} "
                 f"ViolSum={viol_sum_current} GenTime={elapsed_generation_s:.2f}s "
                 f"TotalTime={cumulative_runtime_s:.2f}s PeakMemMB={peak_memory_mb}")

        _save_checkpoint(gen + 1, pop, sys_history)
        if termination_requested["requested"]:
            termination_requested["generation"] = gen + 1
            interruption_count += 1
            _save_checkpoint(gen + 1, pop, sys_history)
            raise GracefulTermination(
                f"Termination requested by {termination_requested['signal']} after generation {gen + 1}",
                {
                    "signal": termination_requested["signal"],
                    "completed_generation": gen + 1,
                    "resume_generation": gen + 1,
                    "attempt_count": int(attempt_count),
                    "interruption_count": int(interruption_count),
                    "system_ga_runtime_s": _accumulated_runtime_s(),
                },
            )

    # Final artifacts
    final_best = min(pop, key=lambda ind: ind.fitness.values)
    final_partition_schedules = final_best.partition_schedules
    final_makespans_eval      = {p: int(final_best.makespans[p]) for p in partitions}
    gglob_final               = final_best.global_schedule
    global_makespan_final     = int(final_best.global_makespan)
    lateness_final_signed     = int(final_best.lateness_signed)
    lateness_final_clipped    = max(0, lateness_final_signed)

    final_budgets = {p: int(final_best.triple_map[p][1]) for p in partitions}
    final_violations = {p: int(max(0, final_makespans_eval[p] - final_budgets[p])) for p in partitions}
    final_generation = int(sys_history["gen"][-1]) if sys_history.get("gen") else int(start_gen)
    final_attempt_runtime_s = _attempt_runtime_s()
    accumulated_system_ga_runtime_s = accumulated_runtime_before_attempt + final_attempt_runtime_s
    total_runtime_s = final_attempt_runtime_s
    peak_memory_mb = _peak_memory_mb()
    cluster_for = {final_best.eval_PO[i]: final_best.eval_PA[i] for i in range(num_parts)}

    for p in partitions:
        tb_used = final_budgets[p]; ms_eval = final_makespans_eval[p]
        log.info(f"  {p} -> {cluster_for[p]} | TB_used={tb_used} | MS(eval)={ms_eval} "
                 f"| Violation={max(0, ms_eval - tb_used)}")
    log.info(f"  Final Global Makespan (eval) = {global_makespan_final}, "
             f"Lateness (signed/clipped) = {lateness_final_signed}/{lateness_final_clipped}")
    log.info("  Total runtime = %.2fs (%.4fh), peak memory = %s MB, total evaluations = %s",
             total_runtime_s, total_runtime_s / 3600.0, peak_memory_mb, eval_counter["total"])

    tb_by_partition = final_budgets
    tb_by_level = {"FE": tb_by_partition["P_FE"], "C1": tb_by_partition["P_C1"],
                   "C2": tb_by_partition["P_C2"], "C3": tb_by_partition["P_C3"]}

    return gglob_final, {
        "time_budgets_partition": tb_by_partition,
        "time_budgets_level": tb_by_level,
        "global_makespan": int(global_makespan_final),
        "partition_makespans_final": final_makespans_eval,
        "partition_violations_final": final_violations,
        "final_generation": final_generation,
        "final_fitness": {
            "viol_sum": float(final_best.fitness.values[0]),
            "fitness_lateness": float(final_best.fitness.values[1]),
            "lateness_signed": int(lateness_final_signed),
            "lateness_clipped": int(lateness_final_clipped),
        },
        "run_stats": run_stats,
        "run_metadata": run_metadata,
        "total_runtime_s": total_runtime_s,
        "total_runtime_h": total_runtime_s / 3600.0,
        "final_attempt_system_ga_runtime_s": final_attempt_runtime_s,
        "system_ga_runtime_s": accumulated_system_ga_runtime_s,
        "attempt_count": int(attempt_count),
        "interruption_count": int(interruption_count),
        "resumed": bool(resumed),
        "resume_generation": resume_generation,
        "peak_memory_mb": peak_memory_mb,
        "total_evaluated_individuals": eval_counter["total"],
        "histories": {
            "system_ga": sys_history,
            "partition_ga_by_part": getattr(final_best, "partition_ga_histories", {}) or {},
            "partition_ga_runs_by_sysgen": dict(inner_runs_by_sysgen),
            "budgets_per_run_by_sysgen": dict(budgets_per_run_by_sysgen),
            "system_ga_generations": int(getattr(cfg, "SystemLevelGenerations", 80)),
            "partition_ga_generations": {
                p: int((getattr(final_best, "partition_ga_histories", {}) or {}).get(p, {}).get("generations", 0))
                for p in partitions
            }
        },
        "returned_schedule_kind": "evaluation_best",
        "checkpoint_path": checkpoint_path,
    }
