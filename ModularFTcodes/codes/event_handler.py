
####################################### New functions for event handling #######################################

# event_handler.py
from typing import Dict, List, Any, Tuple, Optional, Set
import json, os, copy, hashlib
from typing import Dict, List, Any, Tuple, Optional, Union
from collections import defaultdict
import copy, os, json

# ---------------- Public API ----------------
def _save_calendar(calendar_obj: Dict[str, Any], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(calendar_obj, f, indent=2)

def process_events(calendar_path: str,
                   schedule: Dict[int, List[Any]],
                   parent_tag: str = "S0",
                   log_dir: Optional[str] = None,
                   timestamp: Optional[str] = None):
    """
    Read events from JSON file, apply them sequentially on `schedule`.
    Returns list of (new_schedule_dict, node_meta). Saves each new schedule as .json if log_dir is given.
    """
    with open(calendar_path, "r", encoding="utf-8") as f:
        cal = json.load(f)
    return process_events_obj(cal, schedule, parent_tag=parent_tag, log_dir=log_dir, timestamp=timestamp)


def process_events_obj(calendar_obj: Dict[str, Any],
                       schedule: Dict[int, List[Any]],
                       parent_tag: str = "S0",
                       log_dir: Optional[str] = None,
                       timestamp: Optional[str] = None):
    _ensure_int_keys(schedule)
    events = sorted(calendar_obj.get("events", []), key=lambda e: float(e["time"]))
    out = []
    cur = copy.deepcopy(schedule)
    cur_parent = parent_tag

    for ev in events:
        etype, level, t = ev["type"], ev["level"], float(ev["time"])

        if etype == "slack":
            new_sched, node = _apply_slack_successors_only(cur, ev, level, t, cur_parent)
        elif etype == "processor_failure":
            new_sched, node = _placeholder_processor_failure(cur, ev, level, t, cur_parent)
        elif etype == "router_failure":
            new_sched, node = _placeholder_router_failure(cur, ev, level, t, cur_parent)
        else:
            # unknown -> skip
            continue

        # Save child schedule as JSON (with the node tag)
        if log_dir and timestamp:
            path = os.path.join(log_dir, f"{node['node_tag']}__schedule_{timestamp}.json")
            _save_schedule(new_sched, path)

        out.append((new_sched, node))
        cur, cur_parent = new_sched, node["node_tag"]

    return out

from datetime import datetime

# def _save_schedule_enveloped(schedule: Dict[int, List[Any]],
#                              path: str,
#                              schedule_tag: str,
#                              parent_schedule: Optional[str],
#                              event: Optional[Dict[str, Any]],
#                              schedule_hash: str,
#                              calendar_path: Optional[str],
#                              moved: List[Any],
#                              version: str = "1.0") -> None:
#     """
#     Write a schedule file that contains both the task map and a meta block.
#     This makes reconstructing the DAG trivial (nodes=schedules, edges=events).
#     """
#     os.makedirs(os.path.dirname(path), exist_ok=True)
#     envelope = {
#         "meta": {
#             "version": version,
#             "saved_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
#             "schedule_tag": schedule_tag,
#             "parent_schedule": parent_schedule,    # <-- parent reference
#             "event": event,                        # <-- edge that produced this schedule
#             "calendar_path": calendar_path,        # calendar to expand from this node
#             "moved_count": len(moved),
#             "schedule_hash": schedule_hash
#         },
#         "schedule": _to_json_keys(schedule)         # original format preserved under "schedule"
#     }
#     with open(path, "w", encoding="utf-8") as f:
#         json.dump(envelope, f, indent=2)

from datetime import datetime

def _compute_makespan(schedule: Dict[int, List[Any]]) -> int:
    if not schedule:
        return 0
    try:
        return int(max(float(v[2]) for v in schedule.values()))
    except Exception:
        ms = 0.0
        for v in schedule.values():
            try:
                ms = max(ms, float(v[2]))
            except Exception:
                pass
        return int(ms)

def _save_schedule_enveloped(schedule: Dict[int, List[Any]],
                             path: str,
                             schedule_tag: str,
                             parent_schedule: Optional[str],
                             event: Optional[Dict[str, Any]],
                             schedule_hash: str,
                             calendar_path: Optional[str],
                             moved: List[Any],
                             version: str = "1.0",
                             meta_extra: Optional[Dict[str, Any]] = None) -> None:
    """
    Write a schedule file that contains both the task map and a meta block.
    - Always records global_makespan computed from this schedule.
    - Optionally merges 'meta_extra' (e.g., budgets, PIgenes) into meta.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    envelope = {
        "meta": {
            "version": version,
            "saved_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "schedule_tag": schedule_tag,
            "parent_schedule": parent_schedule,    # <-- parent reference
            "event": event,                        # <-- edge that produced this schedule
            "calendar_path": calendar_path,        # calendar to expand from this node
            "moved_count": len(moved),
            "schedule_hash": schedule_hash,
            "global_makespan": _compute_makespan(schedule)  # <-- NEW
        },
        "schedule": _to_json_keys(schedule)
    }
    if meta_extra:
        envelope["meta"].update(meta_extra)        # <-- NEW (budgets, PIgenes)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2)




# def build_schedule_tree(
#     base_schedule: Dict[int, List[Any]],
#     base_calendar: Dict[str, Any],
#     merged_paths: Dict[str, Any] = None,
#     rounds: int = 2,
#     log_dir: Optional[str] = None,
#     timestamp: Optional[str] = None,
#     root_tag: str = "S0",
#     # how many events to PUT into each newly generated child calendar:
#     gen_params: Optional[Dict[str, Any]] = None,   # e.g. {"n_slack":2,"n_proc_fail":0,"n_router_fail":0,"slack_pct_range":(0.5,0.7),"seed":42}
#     # how many events to TAKE (branch) from each node’s calendar:
#     # - single int -> cap total children per node
#     # - dict per type -> e.g. {"slack":4} means up to 4 slack children per node
#     # - list per level -> e.g. [{"slack":4}, {"slack":2}] for level 0 and level 1
#     branch_limits_per_level: Optional[List[Union[int, Dict[str, int]]]] = None,
#     allowed_types: Tuple[str, ...] = ("slack", "processor_failure", "router_failure"),
# ):

def _clone_replanner_context(ctx: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if ctx is None:
        return None
    out = copy.copy(ctx)
    out["pid_by_level"] = {
        level: list(pids or [])
        for level, pids in (ctx.get("pid_by_level", {}) or {}).items()
    }
    out["failed_processors"] = list(ctx.get("failed_processors", []) or [])
    out["failed_routers"] = list(ctx.get("failed_routers", []) or [])
    return out


def _context_summary(ctx: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not ctx:
        return {}
    return {
        "failed_processors": list(ctx.get("failed_processors", []) or []),
        "failed_routers": list(ctx.get("failed_routers", []) or []),
    }


def _paths_without_failed_routers(paths: Optional[Dict[str, Any]],
                                  failed_routers: List[str]) -> Optional[Dict[str, Any]]:
    if not paths or not failed_routers:
        return paths
    failed = set(str(r) for r in failed_routers)
    filtered = {}
    for pid, details in paths.items():
        path_nodes = details.get("path", []) if isinstance(details, dict) else []
        if not any(str(node) in failed for node in path_nodes):
            filtered[pid] = details
    return filtered


def build_schedule_tree(
    base_schedule: Dict[int, List[Any]],
    base_calendar: Dict[str, Any],
    merged_paths: Dict[str, Any] = None,
    rounds: int = 2,
    log_dir: Optional[str] = None,
    timestamp: Optional[str] = None,
    root_tag: str = "S0",
    gen_params: Optional[Dict[str, Any]] = None,
    gen_params_per_level: Optional[List[Dict[str, Any]]] = None,
    branch_limits_per_level: Optional[List[Union[int, Dict[str, int]]]] = None,
    allowed_types: Tuple[str, ...] = ("slack", "processor_failure", "router_failure"),
    meta_static: Optional[Dict[str, Any]] = None,
    branch_context: Optional[Dict[str, Any]] = None,
):

    """
    Independent-branching MSG expansion:
      - For each node, EACH SELECTED EVENT creates ONE child from the SAME parent schedule.
      - Each child inherits a branch-local failure context from its parent.
      - gen_params applies to every generated child calendar unless gen_params_per_level is set.
      - gen_params_per_level[depth] controls the calendar generated for children created at that depth.
      - branch_limits_per_level controls how many events are taken from each node's calendar.

    Returns: flat list of node metadata dicts (one per child).
    """
    import event_calendar as ec  # local import to avoid cycles

    _ensure_int_keys(base_schedule)
    nodes: List[Dict[str, Any]] = []

    next_tag = make_schedule_tagger(start=int(root_tag[1:]) if root_tag.startswith("S") else 0)

    def _limits_for_level(depth: int) -> Optional[Union[int, Dict[str, int]]]:
        if not branch_limits_per_level:
            return None
        if depth < len(branch_limits_per_level):
            return branch_limits_per_level[depth]
        return branch_limits_per_level[-1]

    def _gen_params_for_level(depth: int) -> Dict[str, Any]:
        if gen_params_per_level:
            if depth < len(gen_params_per_level):
                return dict(gen_params_per_level[depth] or {})
            return dict(gen_params_per_level[-1] or {})
        return dict(gen_params or {})

    root_ctx = _clone_replanner_context(branch_context)
    if root_ctx is None:
        root_ctx = _clone_replanner_context(_REPLAN_CTX)
    if root_ctx is not None and merged_paths is not None and root_ctx.get("paths") is None:
        root_ctx["paths"] = merged_paths

    frontier: List[Tuple[str, Dict[int, List[Any]], Dict[str, Any], Optional[Dict[str, Any]]]] = [
        (root_tag, copy.deepcopy(base_schedule), base_calendar, root_ctx)
    ]

    for depth in range(rounds):
        next_frontier: List[Tuple[str, Dict[int, List[Any]], Dict[str, Any], Optional[Dict[str, Any]]]] = []
        limits = _limits_for_level(depth)

        for parent_tag, sched, cal, parent_ctx in frontier:
            events = list(cal.get("events", []))
            events = [e for e in events if e.get("type") in allowed_types]
            events.sort(key=lambda e: (e.get("time", 0.0), e.get("id", "")))
            selected = _select_events_for_branching(events, limits)

            for ev in selected:
                etype, level, t = ev.get("type"), ev.get("level"), float(ev.get("time", 0.0))
                parent_sched_copy = copy.deepcopy(sched)
                child_ctx = _clone_replanner_context(parent_ctx)

                if etype == "slack":
                    child_sched, node = _apply_slack_successors_only(parent_sched_copy, ev, level, t, parent_tag)
                elif etype == "processor_failure":
                    child_sched, node = _placeholder_processor_failure(
                        parent_sched_copy, ev, level, t, parent_tag, branch_context=child_ctx
                    )
                    child_ctx = node.pop("_branch_context", child_ctx)
                elif etype == "router_failure":
                    child_sched, node = _placeholder_router_failure(
                        parent_sched_copy, ev, level, t, parent_tag, branch_context=child_ctx
                    )
                    child_ctx = node.pop("_branch_context", child_ctx)
                else:
                    continue

                child_tag = next_tag()
                node["schedule_tag"] = child_tag
                node["parent_schedule"] = parent_tag
                node.update(_context_summary(child_ctx))

                gp = _gen_params_for_level(depth)
                paths_for_calendar = merged_paths
                if child_ctx is not None and child_ctx.get("paths") is not None:
                    paths_for_calendar = child_ctx.get("paths")

                child_calendar = ec.generate_event_calendar(
                    _to_json_keys(child_sched),
                    paths_for_calendar,
                    n_slack=gp.get("n_slack", 0),
                    n_proc_fail=gp.get("n_proc_fail", 0),
                    n_router_fail=gp.get("n_router_fail", 0),
                    slack_pct_range=gp.get("slack_pct_range", (0.5, 0.7)),
                    seed=gp.get("seed", 42),
                    parent_schedule=child_tag,
                    schedule_tag=child_tag
                )

                if log_dir and timestamp:
                    cal_path = os.path.join(log_dir, f"{child_tag}__event_calendar_{timestamp}.json")
                    _save_calendar(child_calendar, cal_path)
                    sch_path = os.path.join(log_dir, f"{child_tag}__schedule_{timestamp}.json")
                    meta_extra = dict(meta_static or {})
                    meta_extra.update(_context_summary(child_ctx))
                    _save_schedule_enveloped(
                        schedule=child_sched,
                        path=sch_path,
                        schedule_tag=child_tag,
                        parent_schedule=parent_tag,
                        event=ev,
                        schedule_hash=_schedule_fingerprint(child_sched),
                        calendar_path=cal_path,
                        moved=node.get("moved", []),
                        meta_extra=meta_extra,
                    )
                    node["event_calendar_path"] = cal_path
                    node["schedule_path"] = sch_path

                nodes.append(node)
                next_frontier.append((child_tag, child_sched, child_calendar, child_ctx))

        frontier = next_frontier

    return nodes


# --- helpers for selection ---
def _path_connects(paths_dict, path_id, src_proc, dst_proc):
    d = paths_dict.get(str(path_id))
    if not d: 
        return False, 0.0
    path = d.get("path", [])
    if not path:
        return False, float(d.get("cost", 0.0))
    ok = (path[0] == src_proc and path[-1] == dst_proc) or (path[0] == dst_proc and path[-1] == src_proc)
    return ok, float(d.get("cost", 0.0))

def _normalize_receiver_deps(schedule, paths_dict) -> int:
    """
    For each task, keep only ONE dep per (sender,msg_id).
    If multiple paths exist for the same (sender,msg), keep the cheapest valid one.
    Returns the number of duplicates removed.
    """
    removed = 0
    for rid, (rproc, _s, _e, deps) in schedule.items():
        deps = deps or []
        if not deps:
            continue
        best = {}
        for (sid, pid, mid) in deps:
            sid_i, mid_i = int(sid), int(mid)
            sproc = schedule.get(sid_i, [None])[0]
            # pick cost; if current path doesn't connect, we'll treat its cost as +inf
            valid, cost = _path_connects(paths_dict, pid, sproc, rproc)
            if not valid:
                cost = float("inf")
            key = (sid_i, mid_i)
            if key not in best or cost < best[key][1]:
                best[key] = ([sid_i, str(pid), mid_i], cost)
        new_deps = [v[0] for v in best.values()]
        removed += max(0, len(deps) - len(new_deps))
        schedule[rid][3] = new_deps
    return removed



def _select_events_for_branching(
    events: List[Dict[str, Any]],
    limits: Optional[Union[int, Dict[str, int]]],
) -> List[Dict[str, Any]]:
    """
    Choose which events from a node's calendar will spawn children.
    - limits=None  -> use ALL events.
    - limits=int   -> cap total #events.
    - limits=dict  -> cap per type, e.g. {"slack":4, "processor_failure":1}.
    """
    if limits is None:
        return events

    if isinstance(limits, int):
        return events[:limits]

    # dict per type
    out: List[Dict[str, Any]] = []
    used = defaultdict(int)
    # maintain original ordering by time/id
    for e in events:
        et = e.get("type")
        if et not in limits:
            continue
        if used[et] < limits[et]:
            out.append(e)
            used[et] += 1
        # optional early stop if all type limits are met
        if all(used.get(k, 0) >= v for k, v in limits.items()):
            break
    return out



# --- helper to save calendars (place near _save_schedule) ---
def _save_calendar(calendar_obj: Dict[str, Any], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(calendar_obj, f, indent=2)




# ----------------- Helpers -----------------

def _infer_task_for_slack(event: Dict[str, Any], schedule: Dict[int, List[Any]]) -> Optional[int]:
    # Prefer explicit id if provided
    if "target_task" in event:
        tid = int(event["target_task"])
        return tid if tid in schedule else None
    # Else map by (processor, start==time)
    proc = event.get("target")
    t = float(event.get("time", 0))
    exact = [k for k, (p, s, _e, _d) in schedule.items() if p == proc and float(s) == t]
    if exact:
        return min(exact)
    later = [k for k, (p, s, _e, _d) in schedule.items() if p == proc and float(s) >= t]
    return min(later, key=lambda x: schedule[x][1]) if later else None

def _ensure_int_keys(s: Dict[Any, Any]) -> None:
    for k in list(s.keys()):
        if isinstance(k, str):
            s[int(k)] = s.pop(k)

def _norm_copy(s: Dict[int, Any]) -> Dict[int, Any]:
    out = copy.deepcopy(s)
    _ensure_int_keys(out)
    return out

def _to_json_keys(s: Dict[int, Any]) -> Dict[str, Any]:
    return {str(k): v for k, v in s.items()}

def _save_schedule(schedule: Dict[int, List[Any]], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_to_json_keys(schedule), f, indent=2)

def _build_preds_map(schedule: Dict[int, List[Any]]) -> Dict[int, List[Tuple[int, Optional[float]]]]:
    preds = {}
    for tid, rec in schedule.items():
        deps = rec[3] if len(rec) >= 4 else []
        L = []
        for d in deps or []:
            if isinstance(d, (list, tuple)) and len(d) >= 3:
                pred_id, _msg, arrival = d
                L.append((int(pred_id), float(arrival)))
            else:
                L.append((int(d), None))
        preds[tid] = L
    return preds

def _build_succs_map(schedule: Dict[int, List[Any]]) -> Dict[int, List[int]]:
    succs = {}
    for tid, rec in schedule.items():
        for d in (rec[3] if len(rec) >= 4 else []):
            pid = int(d[0]) if isinstance(d, (list, tuple)) else int(d)
            succs.setdefault(pid, []).append(tid)
    return succs

def _collect_successors(root: int, succs_map: Dict[int, List[int]]) -> Set[int]:
    out: Set[int] = set()
    stack = [root]
    while stack:
        u = stack.pop()
        for v in succs_map.get(u, []):
            if v not in out:
                out.add(v)
                stack.append(v)
    return out

def _preds_ready_time(tid: int,
                      preds_map: Dict[int, List[Tuple[int, Optional[float]]]],
                      schedule: Dict[int, List[Any]]) -> float:
    if tid not in preds_map or not preds_map[tid]:
        return 0.0
    xs = []
    for pid, arr in preds_map[tid]:
        pend = schedule.get(pid, [None, None, 0.0])[2]
        xs.append(max(pend, arr) if arr is not None else pend)
    return max(xs) if xs else 0.0

def _proc_orders(schedule: Dict[int, List[Any]]) -> Dict[str, List[int]]:
    byp = {}
    for tid, (p, s, e, *_r) in schedule.items():
        byp.setdefault(p, []).append((s, e, tid))
    return {p: [tid for s, e, tid in sorted(v)] for p, v in byp.items()}

def _prev_on_proc_end(tid: int,
                      schedule: Dict[int, List[Any]],
                      order_on_proc: Dict[str, List[int]]) -> float:
    p = schedule[tid][0]
    order = order_on_proc.get(p, [])
    prev_end = 0.0
    for x in order:
        if x == tid:
            break
        prev_end = schedule[x][2]
    return prev_end

def _schedule_fingerprint(schedule: Dict[int, List[Any]], digits: int = 6) -> str:
    items = []
    for tid in sorted(schedule.keys()):
        proc, s, e, deps = schedule[tid]
        norm_deps = []
        for d in deps or []:
            if isinstance(d, (list, tuple)) and len(d) >= 3:
                norm_deps.append(("t", int(d[0]), str(d[1]), float(d[2])))
            else:
                norm_deps.append(("i", int(d)))
        items.append((tid, proc, round(float(s), digits), round(float(e), digits), tuple(norm_deps)))
    blob = json.dumps(items, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()

def _mk_node(prefix: str, parent_tag: str, event: Dict[str, Any], level: str, t: float,
             schedule: Dict[int, List[Any]], moved, **extras):
    raw = f"{parent_tag}|{prefix}|{level}|{event.get('target')}|{event.get('time')}|{event.get('slack_percent')}"
    tag = f"{prefix}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:8]}"
    node = {
        "node_tag": tag,
        "parent_tag": parent_tag,
        "event": event,
        "level": level,
        "time": t,
        "moved": moved,
        "schedule_hash": _schedule_fingerprint(schedule),
    }
    node.update(extras)
    return node


# --- Tag manager (global monotonic S0, S1, ...) ---
def make_schedule_tagger(start=0):
    counter = {"i": start}
    def next_tag():
        counter["i"] += 1
        return f"S{counter['i']}"
    return next_tag


def _rnd(x: float, d: int) -> float:
    return round(float(x), d)


###################################################################

# --------------- Slack handling (implemented) ---------------

def _apply_slack_successors_only(schedule_in: Dict[int, List[Any]],
                                 event: Dict[str, Any], level: str, t: float,
                                 parent_tag: str, round_digits: int = 6):
    """
    Shorten target task by slack%, then advance ONLY its transitive successors
    (respecting predecessor readiness and processor order). No compaction/backfilling.
    """
    s = _norm_copy(schedule_in)
    tid = _infer_task_for_slack(event, s)
    if tid is None or tid not in s:
        # if we can't map it, just return unchanged with a tag
        return s, _mk_node("SLK", parent_tag, event, level, t, s, moved=[])

    proc, s0, e0, deps = s[tid]
    dur0 = e0 - s0
    sp = max(0.0, min(100.0, float(event.get("slack_percent", 0.0))))
    new_end = s0 + max(1e-9, dur0 * (1.0 - sp / 100.0))
    s[tid][2] = _rnd(new_end, round_digits)   # <-- use _rnd (or keep rnd alias)

    preds_map = _build_preds_map(s)
    succs_map = _build_succs_map(s)
    affected  = _collect_successors(tid, succs_map)
    order_on_proc = _proc_orders(s)
    orig_dur = {k: s[k][2] - s[k][1] for k in s}

    moved: List[Tuple[int, Tuple[float,float], Tuple[float,float]]] = []
    frontier = list(succs_map.get(tid, []))
    visited: Set[int] = set()

    while frontier:
        u = frontier.pop(0)
        if u in visited:
            continue
        visited.add(u)

        if u in affected:
            old_s, old_e = s[u][1], s[u][2]
            pred_ready = _preds_ready_time(u, preds_map, s)
            prev_end   = _prev_on_proc_end(u, s, order_on_proc)
            earliest   = max(pred_ready, prev_end, t)  # never before event time
            if earliest < old_s:
                dur_u = orig_dur[u]
                new_s = _rnd(earliest, round_digits)   # <-- use _rnd (or rnd alias)
                new_e = _rnd(new_s + dur_u, round_digits)
                s[u][1], s[u][2] = new_s, new_e

                moved.append((u, (old_s, old_e), (new_s, new_e)))

        for v in succs_map.get(u, []):
            if v not in visited:
                frontier.append(v)


    node = _mk_node("SLK", parent_tag, event, level, t, s, moved,
                    target_old_end=_rnd(e0, round_digits), target_new_end=_rnd(new_end, round_digits))
    return s, node


########### FAILURE HANDLERS  ###########
# --- NEW: context + imports for fault handling ---
import logging
import PartitionGA as pga  # uses NEW_GA_V2(processor_ids, processing_times, message_list, paths, job_data, time_budget)
log = logging.getLogger(__name__)

# Global replanning context set by your main
_REPLAN_CTX = None

def configure_replanner(ctx: Dict[str, Any]) -> None:
    """
    Set once from main with:
        configure_replanner({
            "pid_by_level": {"FE": [...], "C1": [...], "C2": [...], "C3": [...]},
            "paths": merged_paths_w_costs,
            "job_data_all": {task_id: can_run_on, ...},
            "deadline": DEADLINE,
            # optional but helpful:
            "time_budgets_level": {"FE": <int>, "C1": <int>, "C2": <int>, "C3": <int>}
        })
    """
    global _REPLAN_CTX
    _REPLAN_CTX = _clone_replanner_context(ctx)
    log.info("[PF] Replanning context configured: keys=%s", list((_REPLAN_CTX or {}).keys()))

# ---------- small helpers ----------
def _level_from_proc(pid: str) -> str:
    if pid.startswith(("E", "F")):  # Fog/Edge
        return "FE"
    if pid.startswith("P1"): return "C1"
    if pid.startswith("P2"): return "C2"
    if pid.startswith("P3"): return "C3"
    # fallback: try digit after 'P'
    return {"1":"C1","2":"C2","3":"C3"}.get(pid[1:2], "FE")

def _tasks_before_after(schedule: Dict[int, List[Any]], t: float):
    before, after = {}, {}
    for tid, (proc, s, e, deps) in schedule.items():
        (before if float(s) < t else after)[tid] = [proc, float(s), float(e), deps or []]
    return before, after

def _group_by_level(tasks: Dict[int, List[Any]]) -> Dict[str, List[int]]:
    g = defaultdict(list)
    for tid, (proc, s, e, deps) in tasks.items():
        g[_level_from_proc(proc)].append(tid)
    return g

def _durations_from_parent(schedule: Dict[int, List[Any]], tids: List[int]) -> Dict[int, float]:
    return {tid: float(schedule[tid][2]) - float(schedule[tid][1]) for tid in tids}

def _messages_among(tasks: Dict[int, List[Any]], tids: List[int]) -> List[Dict[str, Any]]:
    """
    Build a light message_list subset from recorded deps inside the schedule:
      dep tuple format: (sender_id, path_id, message_id)
    Only keep edges where both sender and receiver are in 'tids'.
    Size is set to 0; reconstruct step will add path cost anyway.
    """
    tids_set = set(tids)
    out, seen = [], set()
    for rid, (_p, _s, _e, deps) in tasks.items():
        if rid not in tids_set: 
            continue
        for d in deps or []:
            if not (isinstance(d, (list, tuple)) and len(d) >= 3):
                continue
            src, path_id, msg_id = int(d[0]), d[1], d[2]
            if src in tids_set:
                key = (src, rid, msg_id)
                if key in seen: 
                    continue
                seen.add(key)
                out.append({"id": int(msg_id), "sender": src, "receiver": rid, "size": 0})
    return out

def _job_data_subset(job_data_all: Dict[int, Any], tids: List[int]) -> Dict[int, Any]:
    return {int(t): job_data_all.get(int(t), []) for t in tids}

def _healthy_pids_for_level(level: str, faulty_pid: str, ctx: Dict[str, Any]) -> List[str]:
    pids = list(ctx["pid_by_level"].get(level, []))
    if faulty_pid in pids:
        pids.remove(faulty_pid)
    return pids


# Newly added on 13-10-2025

def _level_of(p):
    """Map processor → level using ctx['pid_by_level'] (strings compared)."""
    for L, plist in _REPLAN_CTX.get("pid_by_level", {}).items():
        if str(p) in map(str, plist):
            return L
    return None

def _level_makespan_until(schedule: Dict[int, List[Any]], level: str, t_cut: float) -> int:
    """Max end-time among tasks on processors of `level` with end <= t_cut."""
    pids = set(map(str, _REPLAN_CTX["pid_by_level"].get(level, [])))
    mx = 0
    for _tid, (p, s, e, _d) in schedule.items():
        if str(p) in pids and e <= t_cut and e > mx:
            mx = e
    return int(mx)

def _relative_makespan(rel_sched: Dict[int, List[Any]]) -> int:
    """Max end in a relative schedule (values like (p, s, e, d) with s/e relative)."""
    return max((e for (_p, _s, e, _d) in rel_sched.values()), default=0)



def _shift_and_pack_no_overlap(
    partial_sched: Dict[int, List[Any]],
    base_sched: Dict[int, List[Any]],
    t0: float
) -> Dict[int, List[Any]]:
    """
    Shift the freshly built partial schedule so *no processor* overlaps with tasks already in base_sched.
    - First shift to start at >= t0.
    - Then, for each processor, push to at least the last end-time already present.
    """
    # Gather last occupied time per processor from base
    last_end = defaultdict(float)
    for _tid, (p, s, e, _d) in base_sched.items():
        last_end[p] = max(last_end[p], float(e) if float(e) >= t0 else float(e))

    out = {}
    for tid, (p, s, e, deps) in partial_sched.items():
        # Initial shift: align to t0
        ds = float(s)
        de = float(e)
        span = de - ds
        start = max(t0, last_end[p])
        end = start + span
        out[tid] = [p, start, end, deps or []]
        last_end[p] = end
    return out

def _rebuild_partition(
    level: str,
    tids: List[int],
    parent_after: Dict[int, List[Any]],
    faulty_pid: str,
    ctx: Dict[str, Any],
    t0: float,
) -> Tuple[Dict[int, List[Any]], Dict[str, Any]]:
    """
    Run partition GA on the subset (tids) of this level; start anchoring at t0.
    Returns (new_partial_schedule, stats).
    """
    if not tids:
        return {}, {"hard_violations": 0, "pids": [], "time_budget": 0}

    pids = _healthy_pids_for_level(level, faulty_pid, ctx)
    if not pids:
        log.warning("[PF][%s] No healthy processors after removing %s; skipping.", level, faulty_pid)
        return {}, {"hard_violations": 0, "pids": [], "time_budget": 0}

    ptimes = _durations_from_parent(parent_after, tids)                                     # THIS MIGHT BE A A LOGIC ERROR 
    msgs   = _messages_among(parent_after, tids)
    jobdat = _job_data_subset(ctx.get("job_data_all", {}), tids)

    # ---- Use time budgets from the parent schedule when available ----
    def _extract_numeric_budget(x):
        if isinstance(x, (int, float)):
            return int(x)
        if isinstance(x, dict):
            for key in ("current", "value", "next", "budget", "tb", "TB"):
                v = x.get(key)
                if isinstance(v, (int, float)):
                    return int(v)
        try:
            return int(float(x))
        except Exception:
            return None

    tb_level = None
    raw_tb = None
    if ctx.get("time_budgets_level") and level in ctx["time_budgets_level"]:
        raw_tb = ctx["time_budgets_level"][level]
        tb_level = _extract_numeric_budget(raw_tb)

    if tb_level is None:
        tb_level = int(sum(ptimes.values()) * 1.05)  # fallback

    try:
        log.debug("[PF][%s] Using time budget %s (raw=%r)", level, tb_level, raw_tb)
    except Exception:
        pass

    # ---- Run the partition GA (returns schedule + history dict) ----
    sched_rel, part_hist = pga.NEW_GA_V2(
        processor_ids=pids,
        processing_times=ptimes,
        message_list=msgs,
        all_path_indexes_with_costs=ctx["paths"],
        job_data=jobdat,
        time_budget=tb_level
    )

    # Shift & de-overlap against already-frozen content at t0
    stats_hist_hviol = 0
    if isinstance(part_hist, dict):
        # if someday you add {"hard_violations": ...} to the history, we’ll pick it up
        stats_hist_hviol = int(part_hist.get("hard_violations", 0))
    # Build stats
    stats = {"hard_violations": stats_hist_hviol, "pids": pids, "time_budget": int(tb_level)}
    return sched_rel, stats


# --------------- REAL processor failure handler ---------------

# --- Communication-aware reconstruction helpers ---

def _select_best_path_between(paths_dict: Dict[str, Dict[str, Any]], src_proc: str, dst_proc: str):
    """
    Pick the cheapest path whose endpoints match (src_proc -> dst_proc) (order-insensitive).
    Returns (path_id, cost). If none found, returns (None, 0).
    """
    best = (None, 0)
    best_cost = float("inf")
    for pid, details in paths_dict.items():
        path = details.get("path", [])
        if not path:
            continue
        if (path[0] == src_proc and path[-1] == dst_proc) or (path[0] == dst_proc and path[-1] == src_proc):
            cost = float(details.get("cost", 0))
            if cost < best_cost:
                best_cost = cost
                best = (str(pid), cost)
    return best

def _linearize_from(schedule: Dict[int, List[Any]], proc: str, anchor_tid: int, t0: float):
    """
    Re-pack the timeline on `proc` starting from `anchor_tid` to remove overlaps.
    Keeps tasks with start < t0 frozen.
    """
    # Get tasks of this processor sorted by (start, task_id) for stability
    tids = [tid for tid, (p, s, e, _) in schedule.items() if p == proc]
    tids.sort(key=lambda tid: (float(schedule[tid][1]), tid))

    # Walk forward from anchor tid
    if anchor_tid not in tids:
        return
    i = tids.index(anchor_tid)
    prev_end = max(float(schedule[tids[i]][1]), t0)

    # Anchor the first one
    s0 = max(prev_end, float(schedule[tids[i]][1]))
    dur0 = float(schedule[tids[i]][2]) - float(schedule[tids[i]][1])
    schedule[tids[i]][1] = s0
    schedule[tids[i]][2] = s0 + dur0
    prev_end = schedule[tids[i]][2]

    # Push followers if they overlap
    for j in range(i + 1, len(tids)):
        tid = tids[j]
        s, e = float(schedule[tid][1]), float(schedule[tid][2])
        dur = e - s
        if s < prev_end:
            s = prev_end
            schedule[tid][1] = s
            schedule[tid][2] = s + dur
        prev_end = schedule[tid][2]

# def _enforce_inter_partition_comm(
#     schedule: Dict[int, List[Any]],
#     all_messages: List[Dict[str, Any]],
#     paths_dict: Dict[str, Dict[str, Any]],
#     t0: float,
#     frozen_ids: Optional[Set[int]] = None,
#     max_iters: int = 50,
# ) -> Tuple[Dict[str, List[Any]], Dict[str, Any]]:
#     """
#     Enforce message precedence across the WHOLE (frozen + repaired) schedule.
#     For each message (sender->receiver), ensure:
#         start(receiver) >= end(sender) + size + path_cost(sender.proc, receiver.proc)
#     Shifts the receiver and re-linearizes the processor timeline from that receiver onward.
#     Only adjusts tasks with start >= t0 (keeps frozen region intact).
#     """
#     frozen_ids = frozen_ids or set()
#     # Build incoming edges by receiver: receiver -> list[(sender, msg_id, size)]
#     incoming = defaultdict(list)
#     for m in all_messages or []:
#         rid = int(m["receiver"])
#         sid = int(m["sender"])
#         incoming[rid].append((sid, int(m["id"]), float(m.get("size", 0))))

#     # Fixed-point iteration
#     changed = 0
#     iters = 0
#     while iters < max_iters:
#         iters += 1
#         bumped_this_round = 0

#         for rid, incs in incoming.items():
#             if rid not in schedule:
#                 continue  # receiver not present
#             r_proc, r_s, r_e, r_deps = schedule[rid]
#             r_s = float(r_s); r_e = float(r_e)

#             # Skip tasks in the frozen region
#             if r_s < t0:
#                 continue

#             # Compute the required start given all incoming messages whose senders exist in the schedule
#             required = r_s
#             chosen_deps = []
#             for sid, mid, msize in incs:
#                 if sid not in schedule:
#                     continue
#                 s_proc, _s, s_e, _d = schedule[sid]
#                 # pick cheapest path between processors
#                 path_id, cost = _select_best_path_between(paths_dict, s_proc, r_proc)
#                 arrival = float(s_e) + float(msize) + float(cost)
#                 required = max(required, arrival)
#                 if path_id is not None:
#                     chosen_deps.append((sid, path_id, mid))

#             # If we need to delay the receiver
#             if required > r_s + 1e-9:
#                 # update start/end
#                 dur = r_e - r_s
#                 schedule[rid][1] = required
#                 schedule[rid][2] = required + dur

#                 # de-overlap on the receiver's processor
#                 _linearize_from(schedule, r_proc, rid, t0)

#                 # merge dependency records; avoid duplicates
#                 deps = schedule[rid][3] or []
#                 existing = set((int(a), str(b), int(c)) for (a, b, c) in deps if isinstance(deps, list))
#                 for (a, b, c) in chosen_deps:
#                     key = (int(a), str(b), int(c))
#                     if key not in existing:
#                         deps.append([int(a), str(b), int(c)])
#                         existing.add(key)
#                 schedule[rid][3] = deps

#                 changed += 1
#                 bumped_this_round += 1

#         if bumped_this_round == 0:
#             break

#     stats = {"iterations": iters, "tasks_shifted": changed}
#     return schedule, stats

def _enforce_inter_partition_comm(
    schedule: Dict[int, List[Any]],
    all_messages: List[Dict[str, Any]],
    paths_dict: Dict[str, Dict[str, Any]],
    t0: float,
    frozen_ids: Optional[Set[int]] = None,
    max_iters: int = 50,
) -> Tuple[Dict[int, List[Any]], Dict[str, Any]]:
    """
    Enforce message precedence across the WHOLE (frozen + repaired) schedule.
    Always materializes a single dependency tuple per (sender,msg_id), picking the cheapest valid path.
    Only adjusts times for tasks with start >= t0 (frozen part unchanged).
    """
    frozen_ids = frozen_ids or set()

    # receiver -> list[(sender, msg_id, size)]
    incoming = defaultdict(list)
    for m in all_messages or []:
        incoming[int(m["receiver"])].append((int(m["sender"]), int(m["id"]), float(m.get("size", 0))))

    def _path_cost_if_connects(pid: str, s_proc: str, r_proc: str) -> float:
        d = paths_dict.get(str(pid), {})
        path = d.get("path", [])
        if not path:
            return float("inf")
        if (path[0] == s_proc and path[-1] == r_proc) or (path[0] == r_proc and path[-1] == s_proc):
            return float(d.get("cost", 0.0))
        return float("inf")

    changed = 0
    iters = 0
    while iters < max_iters:
        iters += 1
        bumped_this_round = 0

        for rid, incs in incoming.items():
            if rid not in schedule:
                continue
            r_proc, r_s, r_e, _ = schedule[rid]
            r_s = float(r_s); r_e = float(r_e)

            # Build candidate deps & required start regardless of bump
            required = r_s
            chosen_deps = []  # (sender, path_id, msg_id)
            for sid, mid, msize in incs:
                if sid not in schedule:
                    continue
                s_proc, _s, s_e, _d = schedule[sid]
                path_id, cost = _select_best_path_between(paths_dict, s_proc, r_proc)
                if path_id is not None:
                    chosen_deps.append((sid, path_id, mid))
                arrival = float(s_e) + float(msize) + float(cost)
                if arrival > required:
                    required = arrival

            # If receiver is frozen, we still **write deps** but don't move times
            if r_s < t0:
                # merge/replace deps by (sender,msg_id) using cheapest valid path
                deps = schedule[rid][3] or []
                depmap: Dict[Tuple[int, int], Tuple[str, float]] = {}
                for d in deps:
                    sa, pb, sc = int(d[0]), str(d[1]), int(d[2])
                    sproc0 = schedule.get(sa, [None])[0]
                    depmap[(sa, sc)] = (pb, _path_cost_if_connects(pb, sproc0, r_proc))
                for (a, b, c) in chosen_deps:
                    sa, sb, sc = int(a), str(b), int(c)
                    sproc1 = schedule.get(sa, [None])[0]
                    cand_cost = _path_cost_if_connects(sb, sproc1, r_proc)
                    if (sa, sc) not in depmap or cand_cost < depmap[(sa, sc)][1]:
                        depmap[(sa, sc)] = (sb, cand_cost)
                schedule[rid][3] = [[sa, depmap[(sa, sc)][0], sc] for (sa, sc) in depmap]
                continue  # no timing changes in frozen region

            # Move if needed
            if required > r_s + 1e-9:
                dur = r_e - r_s
                schedule[rid][1] = required
                schedule[rid][2] = required + dur
                _linearize_from(schedule, r_proc, rid, t0)
                changed += 1
                bumped_this_round += 1

            # Always merge/replace deps by (sender,msg_id), even if no bump
            deps = schedule[rid][3] or []
            depmap: Dict[Tuple[int, int], Tuple[str, float]] = {}
            for d in deps:
                sa, pb, sc = int(d[0]), str(d[1]), int(d[2])
                sproc0 = schedule.get(sa, [None])[0]
                depmap[(sa, sc)] = (pb, _path_cost_if_connects(pb, sproc0, r_proc))
            for (a, b, c) in chosen_deps:
                sa, sb, sc = int(a), str(b), int(c)
                sproc1 = schedule.get(sa, [None])[0]
                cand_cost = _path_cost_if_connects(sb, sproc1, r_proc)
                if (sa, sc) not in depmap or cand_cost < depmap[(sa, sc)][1]:
                    depmap[(sa, sc)] = (sb, cand_cost)
            schedule[rid][3] = [[sa, depmap[(sa, sc)][0], sc] for (sa, sc) in depmap]

        if bumped_this_round == 0:
            break

    # Final sweep: keep one dep per (sender,msg_id), cheapest valid path
    dups_removed = 0
    for r_id, (r_proc, _s, _e, deps) in schedule.items():
        deps = deps or []
        if not deps:
            continue
        best: Dict[Tuple[int, int], Tuple[List[Any], float]] = {}
        for (sid, pid, mid) in deps:
            sa, pb, sc = int(sid), str(pid), int(mid)
            sproc = schedule.get(sa, [None])[0]
            cost = _path_cost_if_connects(pb, sproc, r_proc)
            key = (sa, sc)
            if key not in best or cost < best[key][1]:
                best[key] = ([sa, pb, sc], cost)
        new_deps = [v[0] for v in best.values()]
        dups_removed += max(0, len(deps) - len(new_deps))
        schedule[r_id][3] = new_deps

    stats = {"iterations": iters, "tasks_shifted": changed, "dups_removed": dups_removed}
    return schedule, stats

# Woeking version missing 13-10-2025 changes:
# def _handle_processor_failure(schedule_in: Dict[int, List[Any]],
#                               event: Dict[str, Any], level: str, t: float,
#                               parent_tag: str):

#     if _REPLAN_CTX is None:
#         log.warning("[PF] Replanner context is not configured; returning parent schedule unchanged.")
#         s = _norm_copy(schedule_in)
#         node = _mk_node("PF", parent_tag, event, level, t, s, moved=[], note="no replanner context")
#         return s, node

#     ctx = _REPLAN_CTX
#     faulty = str(event.get("target"))
#     t0     = float(t)
#     log.info("[PF] Handling processor failure: target=%s level=%s t_fault=%.3f", faulty, level, t0)

#     # 1) Freeze
#     parent = _norm_copy(schedule_in)
#     before, after = _tasks_before_after(parent, t0)
#     log.info("[PF] Freeze: %d tasks kept (start < %.3f), %d tasks to replan (start >= %.3f)",
#              len(before), t0, len(after), t0)

#     # 2) Group replanning tasks by their current level
#     by_lvl = _group_by_level(after)
#     log.info("[PF] Replan groups: " + ", ".join(f"{k}:{len(v)}" for k, v in by_lvl.items()) or "none")

#     # 3+4+5) Rebuild each affected level using its healthy processors
#     merged = dict(before)  # start from frozen part
#     moved_ids = []
#     part_stats = {}

#     for lvl, tids in by_lvl.items():
#         log.info("[PF][%s] Rebuilding %d tasks; removing faulty=%s if present.", lvl, len(tids), faulty if lvl == level else "n/a")
#         sched_rel, stats = _rebuild_partition(
#             level=lvl,
#             tids=tids,
#             parent_after=after,
#             faulty_pid=faulty if lvl == level else "__none__",  # only remove in the failed level
#             ctx=ctx,
#             t0=t0
#         )
#         # Shift and avoid overlap w/ current merged content
#         sched_abs = _shift_and_pack_no_overlap(sched_rel, merged, t0)
#         merged.update(sched_abs)
#         moved_ids.extend(list(sched_abs.keys()))
#         part_stats[lvl] = stats

#     # 6) Check deadline; if violated, allow ONLY tasks that previously ran on the faulty processor to move across any level
#     def _global_deadline(msched: Dict[int, List[Any]]) -> int:
#         return _compute_makespan(msched)

#     violates = False
#     if "deadline" in ctx:
#         ms = _global_deadline(merged)
#         violates = ms > float(ctx["deadline"])
#         log.info("[PF] Rebuild makespan=%d vs deadline=%s => violates=%s", ms, ctx["deadline"], violates)

#     if violates:
#         # pick only tasks that were on the failed processor in the parent and start >= t0
#         cross_tids = [tid for tid, (p, s, e, d) in after.items() if str(p) == faulty]
#         if cross_tids:
#             log.info("[PF][XFER] Deadline miss → rescheduling %d failed-proc tasks on ANY healthy level.", len(cross_tids))
#             # Build 'any' processor pool
#             all_pids = []
#             for L, plist in ctx.get("pid_by_level", {}).items():
#                 all_pids.extend(plist)
#             all_pids = [p for p in all_pids if p != faulty]

#             ptimes = _durations_from_parent(parent, cross_tids)
#             msgs   = _messages_among(after, cross_tids)
#             jobdat = _job_data_subset(ctx.get("job_data_all", {}), cross_tids)
#             tb_any = int(sum(ptimes.values()) * 1.10)

#             # sched_rel, hard_viol = pga.NEW_GA_V2(
#             #     processor_ids=all_pids, processing_times=ptimes, message_list=msgs,
#             #     all_path_indexes_with_costs=ctx["paths"], job_data=jobdat, time_budget=tb_any
#             # )
#             sched_rel, xfer_hist = pga.NEW_GA_V2(
#             processor_ids=all_pids, processing_times=ptimes, message_list=msgs,
#             all_path_indexes_with_costs=ctx["paths"], job_data=jobdat, time_budget=tb_any
#             )
#             # Remove previous instances of these tids, then pack the new ones
#             for tid in cross_tids:
#                 if tid in merged:
#                     del merged[tid]
#             sched_abs = _shift_and_pack_no_overlap(sched_rel, merged, t0)
#             merged.update(sched_abs)
#             moved_ids.extend(list(sched_abs.keys()))
#             xfer_hviol = int(xfer_hist.get("hard_violations", 0)) if isinstance(xfer_hist, dict) else 0
#             part_stats["XFER"] = {"hard_violations": xfer_hviol, "pids": f"{len(all_pids)} any", "time_budget": int(tb_any)}
#             # part_stats["XFER"] = {"hard_violations": int(hard_viol), "pids": f"{len(all_pids)} any", "time_budget": tb_any}

#             ms2 = _global_deadline(merged)
#             log.info("[PF][XFER] New makespan after cross-level repair = %d (deadline=%s)", ms2, ctx["deadline"])
#             violates = ms2 > float(ctx["deadline"])
#         else:
#             log.info("[PF][XFER] No tasks on the failed processor after t_fault; skipping cross-level repair.")
            
#     # --- NEW: enforce inter-partition communications (frozen→repaired and across levels)
#     frozen_ids = set(before.keys())
#     merged, comm_stats = _enforce_inter_partition_comm(
#         schedule=merged,
#         all_messages=ctx.get("message_list_all", []),  # you pass this via configure_replanner(...)
#         paths_dict=ctx["paths"],
#         t0=t0,
#         frozen_ids=frozen_ids,
#     )
#     log.info("[PF][IPC] Applied inter-partition deps: %s", comm_stats)

#     # Re-evaluate makespan & deadline after IPC shifts
#     ms_final = _compute_makespan(merged)
#     if "deadline" in ctx:
#         violates = ms_final > float(ctx["deadline"])
#     log.info("[PF][IPC] Final makespan after IPC enforcement = %d (deadline=%s, violates=%s)",
#              ms_final, ctx.get("deadline"), violates)

#     # Build node envelope + tag
#     s_out = merged
#     node = _mk_node(
#         "PF", parent_tag, event, level, t0, s_out, moved=moved_ids,
#         violates_deadline=bool(violates),
#         part_stats=part_stats
#     )
#     return s_out, node



# Commenetd on 19.02.2026 OMAR
# def _handle_processor_failure(schedule_in: Dict[int, List[Any]],
#                               event: Dict[str, Any], level: str, t: float,
#                               parent_tag: str):

#     if _REPLAN_CTX is None:
#         log.warning("[PF] Replanner context is not configured; returning parent schedule unchanged.")
#         s = _norm_copy(schedule_in)
#         node = _mk_node("PF", parent_tag, event, level, t, s, moved=[], note="no replanner context")
#         return s, node

#     ctx = _REPLAN_CTX
#     faulty = str(event.get("target"))
#     t0     = float(t)
#     log.info("[PF] Handling processor failure: target=%s level=%s t_fault=%.3f", faulty, level, t0)

#     # 1) Freeze
#     parent = _norm_copy(schedule_in)
#     before, after = _tasks_before_after(parent, t0)
#     log.info("[PF] Freeze: %d tasks kept (start < %.3f), %d tasks to replan (start >= %.3f)",
#              len(before), t0, len(after), t0)

#     # 2) Group replanning tasks by their current level
#     by_lvl = _group_by_level(after)
#     log.info("[PF] Replan groups: " + ", ".join(f"{k}:{len(v)}" for k, v in by_lvl.items()) or "none")

#     # 3+4+5) Rebuild each affected level using its healthy processors
#     merged = dict(before)  # start from frozen part
#     moved_ids = []
#     part_stats = {}

#     # NEW: per-level TB tracking
#     level_budget_viol: Dict[str, bool] = {}
#     level_remain: Dict[str, int] = {}

#     for lvl, tids in by_lvl.items():
#         log.info("[PF][%s] Rebuilding %d tasks; removing faulty=%s if present.",
#                  lvl, len(tids), faulty if lvl == level else "n/a")

#         sched_rel, stats = _rebuild_partition(
#             level=lvl,
#             tids=tids,
#             parent_after=after,
#             faulty_pid=faulty if lvl == level else "__none__",  # only remove in the failed level
#             ctx=ctx,
#             t0=t0
#         )

#         # --- NEW: per-level time-budget check BEFORE packing this rebuilt chunk ---
#         # rel_ms: how long this rebuilt piece needs (relative times)
#         rel_ms = _relative_makespan(sched_rel)

#         # remaining TB for this level AFTER the freeze barrier t0:
#         tb_lvl = int(ctx.get("time_budgets_level", {}).get(lvl, 1 << 30))
#         used_before = _level_makespan_until(before, lvl, t0)  # how much of TB already consumed ≤ t0
#         remain_after_t0 = max(0, tb_lvl - used_before)

#         level_remain[lvl] = remain_after_t0
#         level_budget_viol[lvl] = rel_ms > remain_after_t0

#         log.info("[PF][%s] Rebuild rel_ms=%d, remain_after_t0=%d, tb=%d, used_before=%d, viol=%s",
#                  lvl, rel_ms, remain_after_t0, tb_lvl, used_before, level_budget_viol[lvl])

#         # Shift and avoid overlap w/ current merged content
#         sched_abs = _shift_and_pack_no_overlap(sched_rel, merged, t0)
#         merged.update(sched_abs)
#         moved_ids.extend(list(sched_abs.keys()))
#         part_stats[lvl] = stats

#     # 6) Check budgets/deadline; trigger XFER if any per-level TB is violated (or if global deadline already missed)
#     def _global_deadline(msched: Dict[int, List[Any]]) -> int:
#         return _compute_makespan(msched)

#     level_violation = any(level_budget_viol.values())

#     violates = False
#     if "deadline" in ctx:
#         ms_merged = _global_deadline(merged)
#         violates = ms_merged > float(ctx["deadline"])
#         log.info("[PF] Post-rebuild global makespan=%d vs deadline=%s => violates=%s",
#                  ms_merged, ctx["deadline"], violates)

#     # --- NEW: Escalate to cross-level repair (XFER) if per-level TB violated OR global deadline missed ---
#     if level_violation or violates:
#         # pick only tasks that were on the failed processor in the parent and start >= t0
#         cross_tids = [tid for tid, (p, s, e, d) in after.items() if str(p) == faulty]
#         if cross_tids:
#             log.info("[PF][XFER] TB/deadline miss → rescheduling %d failed-proc tasks on ANY healthy level.", len(cross_tids))

#             # Build 'any' processor pool = union of all levels, excluding the faulty
#             all_pids = []
#             for L, plist in ctx.get("pid_by_level", {}).items():
#                 all_pids.extend(plist)
#             all_pids = [p for p in all_pids if str(p) != faulty]

#             ptimes = _durations_from_parent(parent, cross_tids)
#             msgs   = _messages_among(after, cross_tids)
#             jobdat = _job_data_subset(ctx.get("job_data_all", {}), cross_tids)
#             tb_any = int(sum(ptimes.values()) * 1.10)  # 10% headroom

#             # GA with history (your existing variant)
#             sched_rel, xfer_hist = pga.NEW_GA_V2(
#                 processor_ids=all_pids, processing_times=ptimes, message_list=msgs,
#                 all_path_indexes_with_costs=ctx["paths"], job_data=jobdat, time_budget=tb_any
#             )

#             # Remove previous instances of these tids, then pack the new ones
#             for tid in cross_tids:
#                 if tid in merged:
#                     del merged[tid]
#             sched_abs = _shift_and_pack_no_overlap(sched_rel, merged, t0)
#             merged.update(sched_abs)
#             moved_ids.extend(list(sched_abs.keys()))
#             xfer_hviol = int(xfer_hist.get("hard_violations", 0)) if isinstance(xfer_hist, dict) else 0
#             part_stats["XFER"] = {"hard_violations": xfer_hviol, "pids": f"{len(all_pids)} any", "time_budget": int(tb_any)}

#             ms2 = _global_deadline(merged)
#             log.info("[PF][XFER] New makespan after cross-level repair = %d (deadline=%s)", ms2, ctx.get("deadline"))
#             violates = ms2 > float(ctx["deadline"]) if "deadline" in ctx else False
#         else:
#             log.info("[PF][XFER] No tasks on the failed processor after t_fault; skipping cross-level repair.")

#     # --- Enforce inter-partition communications (frozen→repaired and across levels)
#     frozen_ids = set(before.keys())
#     merged, comm_stats = _enforce_inter_partition_comm(
#         schedule=merged,
#         all_messages=ctx.get("message_list_all", []),
#         paths_dict=ctx["paths"],
#         t0=t0,
#         frozen_ids=frozen_ids,
#     )
#     log.info("[PF][IPC] Applied inter-partition deps: %s", comm_stats)

#     # Re-evaluate makespan & deadline after IPC shifts
#     ms_final = _compute_makespan(merged)
#     if "deadline" in ctx:
#         violates = ms_final > float(ctx["deadline"])
#     log.info("[PF][IPC] Final makespan after IPC enforcement = %d (deadline=%s, violates=%s)",
#              ms_final, ctx.get("deadline"), violates)

#     # NEW: Per-level TB audit after IPC (informational; hook a bounded second-XFER here if desired)
#     final_level_viol = {}
#     for lvl in by_lvl.keys():
#         pids = set(map(str, ctx["pid_by_level"].get(lvl, [])))
#         lvl_ms_final = max((e for (_tid, (p, _s, e, _d)) in merged.items() if str(p) in pids), default=0)
#         tb_lvl = int(ctx.get("time_budgets_level", {}).get(lvl, 1 << 30))
#         final_level_viol[lvl] = lvl_ms_final > tb_lvl
#     log.info("[PF][IPC] Per-level TB after IPC: " + ", ".join(f"{L}:{final_level_viol[L]}" for L in final_level_viol))

#     # Build node envelope + tag
#     s_out = merged
#     node = _mk_node(
#         "PF", parent_tag, event, level, t0, s_out, moved=moved_ids,
#         violates_deadline=bool(violates),
#         part_stats=part_stats
#     )
#     return s_out, node



# NAJIB FUNCTIONS 
def _pf_check_constraints(
    sched: Dict[int, List[Any]],
    deadline: float,
    time_budgets_level: Dict[str, Any],
) -> Dict[str, Any]:
    ms = _compute_makespan(sched)
    out: Dict[str, Any] = {
        "global_makespan": int(ms),
        "deadline": float(deadline),
        "deadline_violation": bool(ms > float(deadline)),
    }

    TB = time_budgets_level or {}
    per_level: Dict[str, Any] = {}
    any_tb = False

    for L, tb in TB.items():
        lvl_ms = 0.0
        for _tid, (p, _s, e, _d) in sched.items():
            if _level_from_proc(str(p)) == L:
                ee = float(e)
                if ee > lvl_ms:
                    lvl_ms = ee

        viol = bool(lvl_ms > float(tb))
        per_level[L] = {"makespan": int(lvl_ms), "TB": int(tb), "violation": viol}
        any_tb = any_tb or viol

    out["per_level"] = per_level
    out["tb_violation_any"] = bool(any_tb)
    out["any_violation"] = bool(out["deadline_violation"] or any_tb)
    return out


def _handle_processor_failure(schedule_in: Dict[int, List[Any]],
                              event: Dict[str, Any], level: str, t: float,
                              parent_tag: str,
                              branch_context: Optional[Dict[str, Any]] = None):

    ctx_base = branch_context if branch_context is not None else _REPLAN_CTX
    if ctx_base is None:
        log.warning("[PF] Replanner context is not configured; returning parent schedule unchanged.")
        s = _norm_copy(schedule_in)
        node = _mk_node("PF", parent_tag, event, level, float(t), s, moved=[],
                        note="no replanner context")
        return s, node

    parent = _norm_copy(schedule_in)

    faulty = str(event.get("target"))
    t0     = float(t)

    fault_level = _level_from_proc(faulty)
    log.info("[PF] START: faulty=%s (derived_level=%s) t_fault=%.3f", faulty, fault_level, t0)

    # ---- Mandatory platform update: exclude faulty FIRST ----
    ctx_local = _clone_replanner_context(ctx_base)
    pid_by_level_new = copy.deepcopy(ctx_local.get("pid_by_level", {}))
    for L in pid_by_level_new:
        pid_by_level_new[L] = [p for p in pid_by_level_new[L] if str(p) != faulty]
    ctx_local["pid_by_level"] = pid_by_level_new
    failed_processors = list(ctx_local.get("failed_processors", []) or [])
    if faulty not in failed_processors:
        failed_processors.append(faulty)
    ctx_local["failed_processors"] = failed_processors
    log.info("[PF] Catalogue updated: removed faulty=%s from pid_by_level.", faulty)

    deadline = float(ctx_local.get("deadline", float("inf")))
    TB = ctx_local.get("time_budgets_level", {}) or {}

    # ============================================================
    # STRATEGY 1: Freeze + rebuild only AFTER tasks
    # ============================================================
    before, after = _tasks_before_after(parent, t0)
    by_lvl = _group_by_level(after)

    log.info("[PF][STRAT1] Freeze: before=%d after=%d; groups=%s",
             len(before), len(after), {k: len(v) for k, v in by_lvl.items()})

    merged = dict(before)
    moved_ids: List[int] = []
    part_stats: Dict[str, Any] = {}

    for lvl2, tids in by_lvl.items():
        log.info("[PF][STRAT1][%s] Rebuilding %d tasks on healthy processors.", lvl2, len(tids))

        sched_rel, stats = _rebuild_partition(
            level=lvl2,
            tids=tids,
            parent_after=after,
            faulty_pid=faulty,
            ctx=ctx_local,
            t0=t0
        )
        sched_abs = _shift_and_pack_no_overlap(sched_rel, merged, t0)
        merged.update(sched_abs)
        moved_ids.extend(list(sched_abs.keys()))
        part_stats[f"STRAT1_{lvl2}"] = stats

    # Connect frozen + rebuilt sets via IPC enforcement BEFORE checks
    merged, comm_stats1 = _enforce_inter_partition_comm(
        schedule=merged,
        all_messages=ctx_local.get("message_list_all", []),
        paths_dict=ctx_local["paths"],
        t0=t0,
        frozen_ids=set(before.keys()),
    )
    log.info("[PF][STRAT1][IPC] comm_stats=%s", comm_stats1)

    checks1 = _pf_check_constraints(merged, deadline, TB)
    log.info("[PF][STRAT1][CHECK] any_violation=%s details=%s", checks1["any_violation"], checks1)

    if not checks1["any_violation"]:
        log.info("[PF] END: Strategy 1 succeeded (no violations).")
        node = _mk_node(
            "PF", parent_tag, event, fault_level, t0, merged, moved=moved_ids,
            strategy_used="STRAT1_FREEZE_REBUILD",
            checks=checks1,
            comm_stats=comm_stats1,
            part_stats=part_stats,
            failed_processors=list(ctx_local.get("failed_processors", []) or []),
            failed_routers=list(ctx_local.get("failed_routers", []) or [])
        )
        node["_branch_context"] = ctx_local
        return merged, node

    # ============================================================
    # STRATEGY 2: Full reschedule (no freezing)
    # ============================================================
    log.info("[PF][STRAT2] Triggered: Strategy 1 violations detected. Starting FULL reschedule (no freeze).")
    import SystemLevelScheduler as sls

    all_tids = list(parent.keys())
    ptimes_all = _durations_from_parent(parent, all_tids)

    all_by_lvl = _group_by_level(parent)
    processing_times_FE = {tid: ptimes_all[tid] for tid in all_by_lvl.get("FE", [])}
    processing_times_C1 = {tid: ptimes_all[tid] for tid in all_by_lvl.get("C1", [])}
    processing_times_C2 = {tid: ptimes_all[tid] for tid in all_by_lvl.get("C2", [])}
    processing_times_C3 = {tid: ptimes_all[tid] for tid in all_by_lvl.get("C3", [])}

    job_all = ctx_local.get("job_data_all", {}) or {}
    job_data_FE = _job_data_subset(job_all, list(processing_times_FE.keys()))
    job_data_C1 = _job_data_subset(job_all, list(processing_times_C1.keys()))
    job_data_C2 = _job_data_subset(job_all, list(processing_times_C2.keys()))
    job_data_C3 = _job_data_subset(job_all, list(processing_times_C3.keys()))

    message_list = ctx_local.get("message_list_all", []) or []
    message_list_FE = [m for m in message_list if int(m["receiver"]) in processing_times_FE]
    message_list_C1 = [m for m in message_list if int(m["receiver"]) in processing_times_C1]
    message_list_C2 = [m for m in message_list if int(m["receiver"]) in processing_times_C2]
    message_list_C3 = [m for m in message_list if int(m["receiver"]) in processing_times_C3]

    processor_ids_FE = ctx_local.get("pid_by_level", {}).get("FE", [])
    processor_ids_C1 = ctx_local.get("pid_by_level", {}).get("C1", [])
    processor_ids_C2 = ctx_local.get("pid_by_level", {}).get("C2", [])
    processor_ids_C3 = ctx_local.get("pid_by_level", {}).get("C3", [])

    SystemSchedule2, meta2 = sls.SystemLevelGA(
        processor_ids_FE, processor_ids_C1, processor_ids_C2, processor_ids_C3,
        processing_times_FE, processing_times_C1, processing_times_C2, processing_times_C3,
        message_list_FE, message_list_C1, message_list_C2, message_list_C3,
        job_data_FE, job_data_C1, job_data_C2, job_data_C3,
        ctx_local.get("deadline"),
        message_list,
        ctx_local["paths"],
        ctx_local.get("log_dir"),
    )

    _ensure_int_keys(SystemSchedule2)

    merged2, comm_stats2 = _enforce_inter_partition_comm(
        schedule=SystemSchedule2,
        all_messages=ctx_local.get("message_list_all", []),
        paths_dict=ctx_local["paths"],
        t0=0.0,
        frozen_ids=set(),
    )
    log.info("[PF][STRAT2][IPC] comm_stats=%s", comm_stats2)

    checks2 = _pf_check_constraints(merged2, deadline, TB)
    log.info("[PF][STRAT2][CHECK] any_violation=%s details=%s", checks2["any_violation"], checks2)

    node = _mk_node(
        "PF", parent_tag, event, fault_level, t0, merged2, moved=list(merged2.keys()),
        strategy_used="STRAT2_FULL_RESCHEDULE",
        checks=checks2,
        comm_stats=comm_stats2,
        part_stats={
            "STRAT1": part_stats,
            "STRAT2": {
                "global_makespan": meta2.get("global_makespan") if isinstance(meta2, dict) else None,
                "final_generation": meta2.get("final_generation") if isinstance(meta2, dict) else None,
            },
        },
        failed_processors=list(ctx_local.get("failed_processors", []) or []),
        failed_routers=list(ctx_local.get("failed_routers", []) or [])
    )
    node["_branch_context"] = ctx_local
    return merged2, node

# ---------- wire the new handler into the existing switch ----------
def _placeholder_processor_failure(schedule_in: Dict[int, List[Any]],
                                   event: Dict[str, Any], level: str, t: float,
                                   parent_tag: str,
                                   branch_context: Optional[Dict[str, Any]] = None):
    # redirect to real handler
    return _handle_processor_failure(schedule_in, event, level, t, parent_tag, branch_context=branch_context)

# --------------- Placeholders (no logic yet) --------------


####################################################################################################################
########################################### TO BE IMPLEMENTED LATER ##############################################

def _placeholder_router_failure(schedule_in: Dict[int, List[Any]],
                                event: Dict[str, Any], level: str, t: float,
                                parent_tag: str,
                                branch_context: Optional[Dict[str, Any]] = None):
    """
    PLACEHOLDER ONLY. Router failure handling to be provided later.
    The branch context still records the failed router and filters it from future path sets.
    """
    s = _norm_copy(schedule_in)
    ctx_base = branch_context if branch_context is not None else _REPLAN_CTX
    ctx_local = _clone_replanner_context(ctx_base)
    failed_router = str(event.get("target"))
    if ctx_local is not None:
        failed_routers = list(ctx_local.get("failed_routers", []) or [])
        if failed_router not in failed_routers:
            failed_routers.append(failed_router)
        ctx_local["failed_routers"] = failed_routers
        ctx_local["paths"] = _paths_without_failed_routers(ctx_local.get("paths"), failed_routers)

    node = _mk_node(
        "RF", parent_tag, event, level, t, s, moved=[],
        note="router failure handler TBD",
        failed_processors=list((ctx_local or {}).get("failed_processors", []) or []),
        failed_routers=list((ctx_local or {}).get("failed_routers", []) or [])
    )
    if ctx_local is not None:
        node["_branch_context"] = ctx_local
    return s, node
