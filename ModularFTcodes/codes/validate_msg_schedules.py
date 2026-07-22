#!/usr/bin/env python3
"""Validate a directory of Multi-Schedule Graph schedule/event-calendar JSON files.

The validator checks each schedule alone, then checks each child against its parent
and triggering event. It writes a plain-text report intended for experiment audits.
"""
import argparse
import heapq
import hashlib
import json
import math
from collections import Counter, defaultdict, deque, namedtuple
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

EPS = 1e-6
MAX_EXAMPLES = 12
DEFAULT_PATH_K = 6


Issue = namedtuple("Issue", ["severity", "scope", "message"])


def add(issues: List[Issue], severity: str, scope: str, message: str) -> None:
    issues.append(Issue(severity.upper(), scope, message))


def fmt_num(x: Any) -> str:
    try:
        xf = float(x)
    except Exception:
        return str(x)
    if abs(xf - round(xf)) < EPS:
        return str(int(round(xf)))
    return f"{xf:.6g}"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def task_sort_key(value: Any) -> Tuple[int, Any]:
    try:
        return (0, int(value))
    except Exception:
        return (1, str(value))


def normalize_deps(deps: Any) -> List[List[Any]]:
    if not deps:
        return []
    out = []
    for dep in deps:
        if isinstance(dep, (list, tuple)) and len(dep) >= 3:
            try:
                out.append([int(dep[0]), str(dep[1]), int(dep[2])])
            except Exception:
                out.append(list(dep[:3]))
        else:
            out.append(dep)
    return out


def load_schedule(path: Path) -> Tuple[Dict[str, Any], Dict[int, List[Any]]]:
    data = load_json(path)
    if isinstance(data, dict) and "schedule" in data:
        meta = data.get("meta", {}) or {}
        raw = data.get("schedule", {}) or {}
    else:
        meta = {}
        raw = data or {}
    schedule: Dict[int, List[Any]] = {}
    for tid_raw, rec in raw.items():
        tid = int(tid_raw)
        if not isinstance(rec, (list, tuple)) or len(rec) < 3:
            schedule[tid] = [None, math.nan, math.nan, []]
            continue
        proc = str(rec[0])
        start = float(rec[1])
        end = float(rec[2])
        deps = normalize_deps(rec[3] if len(rec) >= 4 else [])
        schedule[tid] = [proc, start, end, deps]
    return meta, schedule


def schedule_fingerprint(schedule: Dict[int, List[Any]], digits: int = 6) -> str:
    items = []
    for tid in sorted(schedule):
        proc, start, end, deps = schedule[tid]
        norm_deps = []
        for dep in deps or []:
            if isinstance(dep, (list, tuple)) and len(dep) >= 3:
                norm_deps.append(("t", int(dep[0]), str(dep[1]), int(dep[2])))
            else:
                norm_deps.append(("i", str(dep)))
        items.append((tid, proc, round(float(start), digits), round(float(end), digits), tuple(norm_deps)))
    blob = json.dumps(items, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compute_makespan(schedule: Dict[int, List[Any]]) -> float:
    return max((float(rec[2]) for rec in schedule.values()), default=0.0)


def same_record(a: Sequence[Any], b: Sequence[Any]) -> bool:
    return (
        str(a[0]) == str(b[0])
        and abs(float(a[1]) - float(b[1])) <= EPS
        and abs(float(a[2]) - float(b[2])) <= EPS
        and normalize_deps(a[3] if len(a) > 3 else []) == normalize_deps(b[3] if len(b) > 3 else [])
    )


def changed_tasks(parent: Dict[int, List[Any]], child: Dict[int, List[Any]]) -> List[int]:
    tids = set(parent) | set(child)
    return sorted([tid for tid in tids if tid not in parent or tid not in child or not same_record(parent[tid], child[tid])])


def build_successors(messages: List[Dict[str, Any]]) -> Dict[int, List[int]]:
    succ = defaultdict(list)
    for msg in messages:
        succ[int(msg["sender"])].append(int(msg["receiver"]))
    return succ


def descendants(root: int, succ: Dict[int, List[int]]) -> Set[int]:
    seen: Set[int] = set()
    queue = deque([root])
    while queue:
        u = queue.popleft()
        for v in succ.get(u, []):
            if v not in seen:
                seen.add(v)
                queue.append(v)
    return seen


def schedule_deps(schedule: Dict[int, List[Any]]) -> Dict[Tuple[int, int, int], List[str]]:
    seen: Dict[Tuple[int, int, int], List[str]] = defaultdict(list)
    for receiver, rec in schedule.items():
        for dep in rec[3] or []:
            if isinstance(dep, (list, tuple)) and len(dep) >= 3:
                try:
                    sender = int(dep[0])
                    path_id = str(dep[1])
                    msg_id = int(dep[2])
                except Exception:
                    continue
                seen[(receiver, sender, msg_id)].append(path_id)
    return seen


def processor_level(pid: str) -> str:
    if pid.startswith(("E", "F")):
        return "FE"
    if pid.startswith("P1"):
        return "C1"
    if pid.startswith("P2"):
        return "C2"
    if pid.startswith("P3"):
        return "C3"
    return "UNKNOWN"


def allowed_by_current_policy(can_run_on: Any, processor_ids: Iterable[str]) -> Set[str]:
    cro = list(can_run_on or [])
    non_router = {pid for pid in processor_ids if not str(pid).startswith("R")}
    edge_only = {pid for pid in non_router if str(pid).startswith("E")}
    cloud_only = {pid for pid in non_router if str(pid).startswith("P")}
    if any(x in (1, 2) for x in cro):
        return non_router
    if any(x in (3, 4) for x in cro):
        return edge_only
    if any(x in (5, 6) for x in cro):
        return cloud_only
    return non_router


def build_platform_graph(app_model: Dict[str, Any]) -> Tuple[Dict[str, Set[str]], Set[str], Set[str]]:
    nodes = app_model.get("platform", {}).get("nodes", [])
    links = app_model.get("platform", {}).get("links", [])
    all_nodes = {str(n["id"]) for n in nodes}
    routers = {str(n["id"]) for n in nodes if n.get("is_router")}
    processors = all_nodes - routers
    graph: Dict[str, Set[str]] = {n: set() for n in all_nodes}
    for link in links:
        a, b = str(link["start"]), str(link["end"])
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set()).add(a)
    return graph, processors, routers



def _append_unique(graph: Dict[str, List[str]], src: str, dst: str) -> None:
    graph.setdefault(src, [])
    if dst not in graph[src]:
        graph[src].append(dst)


def build_ordered_platform_graph(app_model: Dict[str, Any]) -> Tuple[Dict[str, List[str]], Dict[str, bool]]:
    nodes = app_model.get("platform", {}).get("nodes", [])
    links = app_model.get("platform", {}).get("links", [])
    is_router = {str(node["id"]): bool(node.get("is_router")) for node in nodes}
    graph: Dict[str, List[str]] = {node_id: [] for node_id in is_router}
    for link in links:
        start, end = str(link["start"]), str(link["end"])
        _append_unique(graph, start, end)
        _append_unique(graph, end, start)
    return graph, is_router


def processor_type(processor_id: str) -> Optional[str]:
    if processor_id.startswith("F"):
        return "fog"
    if processor_id.startswith("E"):
        return "edge"
    if processor_id.startswith("P"):
        return "cloud"
    return None


def cloud_group(processor_id: str) -> Optional[str]:
    if processor_id.startswith("P") and len(processor_id) > 3:
        return processor_id[1]
    return None


def disallowed_path_nodes(source: str, target: str) -> Set[str]:
    disallowed: Set[str] = set()
    source_type = processor_type(source)
    target_type = processor_type(target)

    if source_type == "cloud" and target_type == "cloud" and cloud_group(source) == cloud_group(target):
        disallowed.update({"RID1", "RID2", "RID3", "RID4", "RID5", "RID6"})

    if source_type == "fog" and target_type == "fog":
        disallowed.update({"RID1", "RID2", "RID3", "RID4", "RID5", "RID6"})

    if source_type == "edge" and target_type == "edge":
        disallowed.add("RTSN1")

    if {source_type, target_type} == {"edge", "fog"}:
        disallowed.update({"RID1", "RID2", "RID3", "RID4", "RID5", "RID6"})

    return disallowed


def path_cost(path: Sequence[str], is_router: Dict[str, bool]) -> int:
    cost = 0
    expensive_routers = {"RID1", "RID2", "RID3", "RID4", "RID5", "RID6"}
    for node in path[1:]:
        if is_router.get(str(node), False):
            cost += 10 if str(node) in expensive_routers else 1
    return cost


def shortest_path_bfs(
    graph: Dict[str, List[str]],
    source: str,
    target: str,
    banned_nodes: Set[str],
    banned_edges: Set[Tuple[str, str]],
) -> Optional[List[str]]:
    if source in banned_nodes or target in banned_nodes:
        return None
    if source == target:
        return [source]

    queue = deque([source])
    parent: Dict[str, Optional[str]] = {source: None}
    while queue:
        node = queue.popleft()
        for neighbor in graph.get(node, []):
            edge = (node, neighbor)
            if neighbor in banned_nodes or edge in banned_edges or neighbor in parent:
                continue
            parent[neighbor] = node
            if neighbor == target:
                path = [target]
                cur = node
                while cur is not None:
                    path.append(cur)
                    cur = parent[cur]
                path.reverse()
                return path
            queue.append(neighbor)
    return None


def k_shortest_simple_paths(graph: Dict[str, List[str]], source: str, target: str, k: int) -> List[List[str]]:
    first_path = shortest_path_bfs(graph, source, target, set(), set())
    if not first_path:
        return []

    shortest_paths = [first_path]
    selected = {tuple(first_path)}
    candidates: List[Tuple[int, Tuple[str, ...], List[str]]] = []
    queued: Set[Tuple[str, ...]] = set()

    for kth_path in range(1, k):
        previous_path = shortest_paths[kth_path - 1]
        for spur_index in range(len(previous_path) - 1):
            root_path = previous_path[: spur_index + 1]
            spur_node = root_path[-1]
            banned_nodes = set(root_path[:-1])
            banned_edges: Set[Tuple[str, str]] = set()

            for selected_path in shortest_paths:
                if len(selected_path) > spur_index + 1 and selected_path[: spur_index + 1] == root_path:
                    u, v = selected_path[spur_index], selected_path[spur_index + 1]
                    banned_edges.add((u, v))
                    banned_edges.add((v, u))

            spur_path = shortest_path_bfs(graph, spur_node, target, banned_nodes, banned_edges)
            if not spur_path:
                continue
            total_path = root_path[:-1] + spur_path
            key = tuple(total_path)
            if key in selected or key in queued:
                continue
            queued.add(key)
            heapq.heappush(candidates, (len(total_path), key, total_path))

        while candidates:
            _length, key, path = heapq.heappop(candidates)
            queued.discard(key)
            if key not in selected:
                shortest_paths.append(path)
                selected.add(key)
                break
        else:
            break

    return shortest_paths


def compute_paths_cloud_costs_2(app_model: Dict[str, Any], k: int = DEFAULT_PATH_K) -> Dict[str, Dict[str, Any]]:
    graph, is_router = build_ordered_platform_graph(app_model)
    nodes = app_model.get("platform", {}).get("nodes", [])
    processor_nodes = [str(node["id"]) for node in nodes if not node.get("is_router")]

    merged_paths: Dict[str, Dict[str, Any]] = {}
    path_id = 1
    for i in range(len(processor_nodes)):
        for j in range(i + 1, len(processor_nodes)):
            source = processor_nodes[i]
            target = processor_nodes[j]
            disallowed = disallowed_path_nodes(source, target)
            restricted_graph = {
                node: [neighbor for neighbor in neighbors if neighbor not in disallowed]
                for node, neighbors in graph.items()
                if node not in disallowed
            }
            for sub_path_id, path in enumerate(k_shortest_simple_paths(restricted_graph, source, target, k)):
                merged_paths[f"{path_id}{sub_path_id}"] = {"path": path, "cost": path_cost(path, is_router)}
            path_id += 1

    for node in processor_nodes:
        merged_paths[f"{path_id}0"] = {"path": [node, node], "cost": 1}
        path_id += 1

    return merged_paths


def isolated_processors_after_router_failure(graph: Dict[str, Set[str]], processors: Set[str], router: str) -> Set[str]:
    nodes = set(graph) - {router}
    seen: Set[str] = set()
    isolated: Set[str] = set()
    for node in nodes:
        if node in seen:
            continue
        queue = deque([node])
        seen.add(node)
        comp = set()
        while queue:
            u = queue.popleft()
            comp.add(u)
            for v in graph.get(u, set()):
                if v == router or v not in nodes or v in seen:
                    continue
                seen.add(v)
                queue.append(v)
        comp_processors = comp & processors
        if len(comp_processors) <= 1:
            isolated.update(comp_processors)
    return isolated


def path_connects(path_info: Optional[Dict[str, Any]], src_proc: str, dst_proc: str) -> bool:
    if not path_info:
        return False
    path = [str(x) for x in path_info.get("path", [])]
    if not path:
        return False
    return (path[0] == src_proc and path[-1] == dst_proc) or (path[0] == dst_proc and path[-1] == src_proc)


def validate_schedule(
    tag: str,
    meta: Dict[str, Any],
    schedule: Dict[int, List[Any]],
    schedule_path: Path,
    jobs: Dict[int, Dict[str, Any]],
    messages: List[Dict[str, Any]],
    paths: Dict[str, Dict[str, Any]],
    processor_ids: Set[str],
    issues: List[Issue],
) -> Dict[str, Any]:
    scope = tag
    expected_tasks = set(jobs)
    actual_tasks = set(schedule)
    missing = sorted(expected_tasks - actual_tasks)
    extra = sorted(actual_tasks - expected_tasks)
    if missing:
        add(issues, "FAIL", scope, f"missing {len(missing)} application tasks: {missing[:MAX_EXAMPLES]}")
    if extra:
        add(issues, "FAIL", scope, f"contains {len(extra)} unknown tasks: {extra[:MAX_EXAMPLES]}")
    if not missing and not extra:
        add(issues, "PASS", scope, f"task set matches application model ({len(actual_tasks)} tasks)")

    bad_shape = []
    unknown_processors = []
    bad_time = []
    duration_mismatch = []
    can_run_policy_warnings = []
    for tid, rec in schedule.items():
        proc, start, end, deps = rec
        if proc is None or math.isnan(start) or math.isnan(end):
            bad_shape.append(tid)
            continue
        if proc not in processor_ids:
            unknown_processors.append((tid, proc))
        if end < start - EPS or start < -EPS:
            bad_time.append((tid, start, end))
        job = jobs.get(tid)
        if job:
            expected_dur = float(job.get("processing_times", end - start))
            dur = end - start
            if abs(dur - expected_dur) > EPS:
                duration_mismatch.append((tid, dur, expected_dur))
            allowed = allowed_by_current_policy(job.get("can_run_on", []), processor_ids)
            if proc not in allowed:
                can_run_policy_warnings.append((tid, proc, job.get("can_run_on", [])))
    if bad_shape:
        add(issues, "FAIL", scope, f"{len(bad_shape)} malformed task records: {bad_shape[:MAX_EXAMPLES]}")
    if unknown_processors:
        add(issues, "FAIL", scope, f"{len(unknown_processors)} tasks use unknown processors: {unknown_processors[:MAX_EXAMPLES]}")
    if bad_time:
        add(issues, "FAIL", scope, f"{len(bad_time)} tasks have negative/invalid time intervals: {bad_time[:MAX_EXAMPLES]}")
    if duration_mismatch:
        add(issues, "WARN", scope, f"{len(duration_mismatch)} task durations differ from AM processing_times; expected for slack targets only. examples={duration_mismatch[:MAX_EXAMPLES]}")
    if can_run_policy_warnings:
        add(issues, "WARN", scope, f"{len(can_run_policy_warnings)} tasks violate current repo can_run_on policy. Verify policy matches older code. examples={can_run_policy_warnings[:MAX_EXAMPLES]}")

    overlaps = []
    by_proc = defaultdict(list)
    for tid, (proc, start, end, _deps) in schedule.items():
        by_proc[proc].append((float(start), float(end), tid))
    for proc, intervals in by_proc.items():
        intervals.sort()
        for prev, cur in zip(intervals, intervals[1:]):
            ps, pe, ptid = prev
            cs, ce, ctid = cur
            if cs < pe - EPS:
                overlaps.append((proc, ptid, ps, pe, ctid, cs, ce))
    if overlaps:
        add(issues, "FAIL", scope, f"{len(overlaps)} processor overlaps: {overlaps[:MAX_EXAMPLES]}")
    else:
        add(issues, "PASS", scope, "no processor overlaps")

    dep_map = schedule_deps(schedule)
    duplicate_deps = [(k, v) for k, v in dep_map.items() if len(v) > 1]
    if duplicate_deps:
        add(issues, "WARN", scope, f"{len(duplicate_deps)} duplicate dependency tuples by receiver/sender/message: {duplicate_deps[:MAX_EXAMPLES]}")

    explicit = implicit_same_proc = missing_msg = latency_bad = path_bad = path_missing = 0
    missing_examples = []
    path_missing_examples = []
    path_bad_examples = []
    latency_examples = []
    for msg in messages:
        mid = int(msg["id"])
        sender = int(msg["sender"])
        receiver = int(msg["receiver"])
        size = float(msg.get("size", 0))
        if sender not in schedule or receiver not in schedule:
            missing_msg += 1
            continue
        s_proc, _s0, s_end, _ = schedule[sender]
        r_proc, r_start, _r_end, _ = schedule[receiver]
        path_ids = dep_map.get((receiver, sender, mid), [])
        if path_ids:
            explicit += 1
            pid = str(path_ids[0])
            pinfo = paths.get(pid)
            if not pinfo:
                path_missing += 1
                path_missing_examples.append(("missing_path", receiver, sender, mid, pid))
                continue
            if not path_connects(pinfo, str(s_proc), str(r_proc)):
                path_bad += 1
                path_bad_examples.append(("bad_endpoint", receiver, sender, mid, pid, s_proc, r_proc, pinfo.get("path")))
                continue
            required = float(s_end) + float(pinfo.get("cost", 0)) + size
            if float(r_start) < required - EPS:
                latency_bad += 1
                latency_examples.append(("late", receiver, sender, mid, pid, fmt_num(r_start), fmt_num(required)))
        elif str(s_proc) == str(r_proc) and float(r_start) >= float(s_end) - EPS:
            implicit_same_proc += 1
        else:
            missing_msg += 1
            missing_examples.append(("missing_dep", receiver, sender, mid, s_proc, r_proc))

    represented = explicit + implicit_same_proc
    if missing_msg:
        add(issues, "FAIL", scope, f"{missing_msg}/{len(messages)} AM messages are not explicitly or implicitly enforced. examples={missing_examples[:MAX_EXAMPLES]}")
    else:
        add(issues, "PASS", scope, f"all {len(messages)} AM messages represented/enforced ({explicit} explicit deps, {implicit_same_proc} same-processor implicit)")
    if path_missing:
        add(issues, "FAIL", scope, f"{path_missing} dependency path IDs are absent from the path catalogue. examples={path_missing_examples[:MAX_EXAMPLES]}")
    if path_bad:
        add(issues, "FAIL", scope, f"{path_bad} dependency paths do not connect sender/receiver processors. examples={path_bad_examples[:MAX_EXAMPLES]}")
    if latency_bad:
        add(issues, "FAIL", scope, f"{latency_bad} message latency constraints violated. examples={latency_examples[:MAX_EXAMPLES]}")

    ms = compute_makespan(schedule)
    meta_ms = meta.get("global_makespan")
    if meta_ms is not None and abs(float(meta_ms) - ms) > EPS:
        add(issues, "WARN", scope, f"meta.global_makespan={meta_ms} but computed makespan={fmt_num(ms)}")
    meta_hash = meta.get("schedule_hash")
    if meta_hash:
        actual_hash = schedule_fingerprint(schedule)
        if meta_hash != actual_hash:
            add(issues, "WARN", scope, "meta.schedule_hash does not match schedule contents using current fingerprint logic")

    return {
        "tasks": len(schedule),
        "makespan": ms,
        "explicit_messages": explicit,
        "implicit_same_proc_messages": implicit_same_proc,
        "represented_messages": represented,
        "missing_messages": missing_msg,
        "overlaps": len(overlaps),
        "duration_mismatches": len(duration_mismatch),
    }


def validate_child(
    tag: str,
    meta: Dict[str, Any],
    schedule: Dict[int, List[Any]],
    parent_meta: Dict[str, Any],
    parent_schedule: Dict[int, List[Any]],
    calendars: Dict[str, Dict[str, Any]],
    messages: List[Dict[str, Any]],
    paths: Dict[str, Dict[str, Any]],
    graph: Dict[str, Set[str]],
    processors: Set[str],
    issues: List[Issue],
) -> Dict[str, Any]:
    scope = f"edge {meta.get('parent_schedule')}->{tag}"
    event = meta.get("event") or {}
    etype = event.get("type")
    changed = changed_tasks(parent_schedule, schedule)
    moved_count = meta.get("moved_count")
    if moved_count is not None and int(moved_count) != len(changed):
        add(issues, "WARN", scope, f"meta.moved_count={moved_count}, but {len(changed)} task records differ from parent")
    add(issues, "INFO", scope, f"event={etype} id={event.get('id')} changed_tasks={len(changed)} examples={changed[:MAX_EXAMPLES]}")

    parent_tag = meta.get("parent_schedule")
    parent_calendar = calendars.get(str(parent_tag))
    if parent_calendar:
        event_ids = {e.get("id") for e in parent_calendar.get("events", [])}
        if event.get("id") not in event_ids:
            add(issues, "WARN", scope, f"child event id {event.get('id')} is not present in parent calendar {parent_tag}")
    else:
        add(issues, "WARN", scope, "parent calendar not found; cannot verify event came from parent calendar")

    event_time = float(event.get("time", 0.0))
    succ = build_successors(messages)

    if etype == "slack":
        target_proc = str(event.get("target"))
        target_candidates = [tid for tid, rec in parent_schedule.items() if str(rec[0]) == target_proc and abs(float(rec[1]) - event_time) <= EPS]
        if not target_candidates:
            target_candidates = [tid for tid, rec in parent_schedule.items() if str(rec[0]) == target_proc and float(rec[1]) >= event_time - EPS]
        if not target_candidates:
            add(issues, "FAIL", scope, f"slack target task not found on processor {target_proc} at/after time {fmt_num(event_time)}")
        else:
            target = sorted(target_candidates, key=lambda tid: parent_schedule[tid][1])[0]
            pct = float(event.get("slack_percent", 0.0))
            p_dur = parent_schedule[target][2] - parent_schedule[target][1]
            c_dur = schedule[target][2] - schedule[target][1]
            expected = p_dur * (1.0 - pct / 100.0)
            if abs(c_dur - expected) > 1e-4:
                add(issues, "FAIL", scope, f"slack target task {target} duration={fmt_num(c_dur)}, expected {fmt_num(expected)} from parent duration {fmt_num(p_dur)} and slack {pct}%")
            else:
                add(issues, "PASS", scope, f"slack target task {target} duration reduced as expected")
            allowed_changed = descendants(target, succ) | {target}
            unexpected = [tid for tid in changed if tid not in allowed_changed]
            if unexpected:
                add(issues, "WARN", scope, f"{len(unexpected)} changed tasks are not descendants of slack target {target}: {unexpected[:MAX_EXAMPLES]}")
            proc_changes = [tid for tid in changed if tid in parent_schedule and tid in schedule and parent_schedule[tid][0] != schedule[tid][0]]
            dep_changes = [tid for tid in changed if tid in parent_schedule and tid in schedule and normalize_deps(parent_schedule[tid][3]) != normalize_deps(schedule[tid][3])]
            if proc_changes:
                add(issues, "FAIL", scope, f"slack mitigation changed processors for tasks: {proc_changes[:MAX_EXAMPLES]}")
            if dep_changes:
                add(issues, "WARN", scope, f"slack mitigation changed dependency/path records for tasks: {dep_changes[:MAX_EXAMPLES]}")

    elif etype == "processor_failure":
        failed = str(event.get("target"))
        after = [tid for tid, rec in schedule.items() if str(rec[0]) == failed and float(rec[1]) >= event_time - EPS]
        overlapping = [tid for tid, rec in schedule.items() if str(rec[0]) == failed and float(rec[1]) < event_time < float(rec[2])]
        if after:
            add(issues, "FAIL", scope, f"failed processor {failed} is still used by {len(after)} tasks starting at/after failure time: {after[:MAX_EXAMPLES]}")
        else:
            add(issues, "PASS", scope, f"failed processor {failed} not used by tasks starting after failure time")
        if overlapping:
            add(issues, "WARN", scope, f"{len(overlapping)} tasks overlap the failure instant on processor {failed}: {overlapping[:MAX_EXAMPLES]}")
        pre_event_changes = [tid for tid in changed if tid in parent_schedule and parent_schedule[tid][1] < event_time - EPS]
        if pre_event_changes:
            add(issues, "WARN", scope, f"{len(pre_event_changes)} pre-event task records changed. This may be unrealistic unless full offline rescheduling is intended. examples={pre_event_changes[:MAX_EXAMPLES]}")

    elif etype == "router_failure":
        failed_router = str(event.get("target"))
        bad_paths = []
        dep_map = schedule_deps(schedule)
        for (receiver, sender, mid), path_ids in dep_map.items():
            rec = schedule.get(receiver)
            if not rec or float(rec[1]) < event_time - EPS:
                continue
            for pid in path_ids:
                pinfo = paths.get(str(pid))
                if pinfo and failed_router in [str(x) for x in pinfo.get("path", [])]:
                    bad_paths.append((receiver, sender, mid, pid))
        if bad_paths:
            add(issues, "FAIL", scope, f"{len(bad_paths)} post-router-failure dependencies still use router {failed_router}: {bad_paths[:MAX_EXAMPLES]}")
        else:
            add(issues, "PASS", scope, f"no post-failure dependency paths use failed router {failed_router}")
        isolated = isolated_processors_after_router_failure(graph, processors, failed_router)
        used_isolated = [tid for tid, rec in schedule.items() if rec[0] in isolated and float(rec[1]) >= event_time - EPS]
        if isolated:
            add(issues, "INFO", scope, f"processors isolated by removing {failed_router}: {sorted(isolated)[:MAX_EXAMPLES]}")
        if used_isolated:
            add(issues, "WARN", scope, f"{len(used_isolated)} tasks start after router failure on processors isolated by {failed_router}: {used_isolated[:MAX_EXAMPLES]}")
        pre_event_changes = [tid for tid in changed if tid in parent_schedule and parent_schedule[tid][1] < event_time - EPS]
        if pre_event_changes:
            add(issues, "WARN", scope, f"{len(pre_event_changes)} pre-event task records changed. This may be unrealistic unless full offline rescheduling is intended. examples={pre_event_changes[:MAX_EXAMPLES]}")
    else:
        add(issues, "WARN", scope, f"unknown or missing event type {etype!r}; child-specific mitigation checks skipped")

    return {"changed_tasks": len(changed), "event_type": etype}


def read_schedules(schedule_dir: Path) -> Dict[str, Tuple[Path, Dict[str, Any], Dict[int, List[Any]]]]:
    out = {}
    for path in sorted(schedule_dir.glob("*__schedule_*.json")):
        meta, schedule = load_schedule(path)
        tag = str(meta.get("schedule_tag") or path.name.split("__")[0])
        out[tag] = (path, meta, schedule)
    return out


def read_calendars(schedule_dir: Path) -> Dict[str, Dict[str, Any]]:
    out = {}
    for path in sorted(schedule_dir.glob("*__event_calendar_*.json")):
        data = load_json(path)
        tag = str((data.get("meta") or {}).get("schedule_tag") or path.name.split("__")[0])
        out[tag] = data
    return out


def issue_counts(issues: List[Issue], scope_prefix: Optional[str] = None) -> Counter:
    c = Counter()
    for issue in issues:
        if scope_prefix is None or issue.scope == scope_prefix or issue.scope.startswith(scope_prefix):
            c[issue.severity] += 1
    return c


def write_report(
    out_path: Path,
    schedule_dir: Path,
    app_model_path: Path,
    path_k: int,
    schedules: Dict[str, Tuple[Path, Dict[str, Any], Dict[int, List[Any]]]],
    schedule_stats: Dict[str, Dict[str, Any]],
    child_stats: Dict[str, Dict[str, Any]],
    issues: List[Issue],
) -> None:
    lines: List[str] = []
    counts = issue_counts(issues)
    lines.append("MSG Schedule Validation Report")
    lines.append("=" * 30)
    lines.append(f"generated_at: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"schedule_dir: {schedule_dir}")
    lines.append(f"application_model: {app_model_path}")
    lines.append(f"path_k: {path_k}")
    lines.append("path_catalogue: generated internally from application_model")
    lines.append(f"schedules: {', '.join(sorted(schedules, key=task_sort_key))}")
    lines.append(f"overall_counts: PASS={counts['PASS']} WARN={counts['WARN']} FAIL={counts['FAIL']} INFO={counts['INFO']}")
    lines.append("")

    lines.append("Checklist Implemented")
    lines.append("- envelope/lineage metadata: tag, parent, event, hash, makespan")
    lines.append("- task-set equality with AM jobs")
    lines.append("- valid task records, nonnegative intervals, known processors")
    lines.append("- processor overlap detection")
    lines.append("- message enforcement for every AM message: explicit dep or same-processor implicit order")
    lines.append("- path catalogue presence, path endpoint compatibility, and latency feasibility")
    lines.append("- duplicate dependency tuple detection")
    lines.append("- current-code can_run_on policy warnings")
    lines.append("- parent-child changed-task audit")
    lines.append("- slack-specific target duration and affected-descendant checks")
    lines.append("- processor-failure post-event processor exclusion checks")
    lines.append("- router-failure post-event failed-router path checks and isolation warnings")
    lines.append("")

    lines.append("Additional Failure Modes To Watch")
    lines.append("- child schedules that rewrite pre-event history, which may be invalid for online mitigation")
    lines.append("- same-processor dependencies omitted but receiver starts before sender finishes")
    lines.append("- path IDs valid in one path catalogue version but not another k/path-generation version")
    lines.append("- stale metadata: moved_count/hash/makespan not matching actual schedule")
    lines.append("- full reschedules that satisfy timing but violate fault persistence in descendants")
    lines.append("- can_run_on semantics drift between older code and current code")
    lines.append("- router failures that should invalidate processor reachability, not only path choice")
    lines.append("- duplicate AM message IDs or duplicate dependency tuples masking missing messages")
    lines.append("- deadline/time-budget metadata passing while individual partition constraints fail")
    lines.append("- nondeterministic path fallback or RNG state causing non-reproducible schedule variants")
    lines.append("")

    lines.append("Schedule Summary")
    lines.append("tag  tasks  makespan  explicit_msg  implicit_msg  missing_msg  overlaps  dur_mismatch")
    for tag in sorted(schedules, key=task_sort_key):
        st = schedule_stats[tag]
        lines.append(
            f"{tag:>3}  {st['tasks']:>5}  {fmt_num(st['makespan']):>8}  "
            f"{st['explicit_messages']:>12}  {st['implicit_same_proc_messages']:>12}  "
            f"{st['missing_messages']:>11}  {st['overlaps']:>8}  {st['duration_mismatches']:>12}"
        )
    lines.append("")

    if child_stats:
        lines.append("Parent-Child Summary")
        lines.append("child  parent  event_type           changed_tasks")
        for tag in sorted(child_stats, key=task_sort_key):
            path, meta, _schedule = schedules[tag]
            st = child_stats[tag]
            lines.append(f"{tag:>5}  {str(meta.get('parent_schedule')):>6}  {str(st.get('event_type')):<18} {st.get('changed_tasks'):>5}")
        lines.append("")

    lines.append("Issues")
    severity_order = {"FAIL": 0, "WARN": 1, "INFO": 2, "PASS": 3}
    for issue in sorted(issues, key=lambda x: (severity_order.get(x.severity, 9), x.scope, x.message)):
        lines.append(f"[{issue.severity}] {issue.scope}: {issue.message}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve_report_path(report_out: Path) -> Path:
    resolved = report_out.resolve()
    if report_out.exists() and report_out.is_dir():
        return resolved / "validation_report.txt"
    if report_out.suffix:
        return resolved
    return resolved / "validation_report.txt"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate MSG schedule/event-calendar JSON files. The script is self-contained: "
            "it builds the path catalogue from the application model internally."
        )
    )
    parser.add_argument("app_model", type=Path, help="Application/platform JSON model used to generate the schedules.")
    parser.add_argument("schedule_dir", type=Path, help="Directory containing *__schedule_*.json and *__event_calendar_*.json files.")
    parser.add_argument("report_out", type=Path, help="Report file path, or a directory where validation_report.txt should be written.")
    args = parser.parse_args()

    app_model_path = args.app_model.resolve()
    schedule_dir = args.schedule_dir.resolve()
    out_path = resolve_report_path(args.report_out)

    app_model = load_json(app_model_path)
    jobs = {int(job["id"]): job for job in app_model["application"]["jobs"]}
    messages = list(app_model["application"].get("messages", []))
    graph, processors, routers = build_platform_graph(app_model)
    processor_ids = processors
    paths = {str(k): v for k, v in compute_paths_cloud_costs_2(app_model, k=DEFAULT_PATH_K).items()}

    schedules = read_schedules(schedule_dir)
    calendars = read_calendars(schedule_dir)
    issues: List[Issue] = []
    schedule_stats: Dict[str, Dict[str, Any]] = {}
    child_stats: Dict[str, Dict[str, Any]] = {}

    if not schedules:
        raise SystemExit(f"No schedule files found in {schedule_dir}")

    for tag, (path, meta, schedule) in sorted(schedules.items(), key=lambda kv: task_sort_key(kv[0])):
        filename_tag = path.name.split("__")[0]
        if tag != filename_tag:
            add(issues, "WARN", tag, f"meta schedule_tag={tag} differs from filename tag={filename_tag}")
        schedule_stats[tag] = validate_schedule(tag, meta, schedule, path, jobs, messages, paths, processor_ids, issues)

    for tag, (path, meta, schedule) in sorted(schedules.items(), key=lambda kv: task_sort_key(kv[0])):
        parent_tag = meta.get("parent_schedule")
        if parent_tag is None:
            continue
        if str(parent_tag) not in schedules:
            add(issues, "FAIL", tag, f"parent schedule {parent_tag} not found")
            continue
        _ppath, pmeta, pschedule = schedules[str(parent_tag)]
        child_stats[tag] = validate_child(tag, meta, schedule, pmeta, pschedule, calendars, messages, paths, graph, processors, issues)

    write_report(out_path, schedule_dir, app_model_path, DEFAULT_PATH_K, schedules, schedule_stats, child_stats, issues)
    counts = issue_counts(issues)
    print(f"Wrote {out_path}")
    print(f"PASS={counts['PASS']} WARN={counts['WARN']} FAIL={counts['FAIL']} INFO={counts['INFO']}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
