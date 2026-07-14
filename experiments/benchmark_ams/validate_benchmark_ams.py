#!/usr/bin/env python3
"""Validate the WATERS100 benchmark AM files without modifying them."""
import json
from pathlib import Path
import sys

import networkx as nx

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_DIR = WORKTREE_ROOT / "ModularFTcodes"
BENCHMARK_DIR = PROJECT_DIR / "BenchmarkAMs"

FILES = [
    "WATERS100_NewPM.json",
    "WATERS100_FogEdgePartitionedTasks_merged_strict.json",
    "WATERS100_Cloud1PartitionedData_merged.json",
    "WATERS100_Cloud2PartitionedData_merged.json",
    "WATERS100_Cloud3PartitionedData_merged.json",
]

REQUIRED_JOB_FIELDS = {"id", "can_run_on", "processing_times"}
REQUIRED_MESSAGE_FIELDS = {"id", "sender", "receiver", "size"}


def fail(errors, path, message):
    errors.append(f"{path}: {message}")


def load_json(path: Path, errors):
    if not path.exists():
        fail(errors, path, "missing file")
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        fail(errors, path, f"invalid JSON: {exc}")
        return None


def validate_file(path):
    errors = []
    warnings = []
    data = load_json(path, errors)
    if data is None:
        return 0, 0, False, errors, warnings

    if not isinstance(data, dict):
        fail(errors, path, "top-level JSON value is not an object")
        return 0, 0, False, errors, warnings

    app = data.get("application")
    if not isinstance(app, dict):
        fail(errors, path, "missing object: application")
        return 0, 0, False, errors, warnings

    jobs = app.get("jobs")
    messages = app.get("messages")
    if not isinstance(jobs, list) or not jobs:
        fail(errors, path, "application.jobs is missing, not a list, or empty")
        jobs = []
    if not isinstance(messages, list):
        fail(errors, path, "application.messages is missing or not a list")
        messages = []

    job_ids = set()
    for idx, job in enumerate(jobs):
        if not isinstance(job, dict):
            fail(errors, path, f"job[{idx}] is not an object")
            continue
        missing = REQUIRED_JOB_FIELDS - set(job)
        if missing:
            fail(errors, path, f"job[{idx}] missing fields: {sorted(missing)}")
        jid = job.get("id")
        if jid in job_ids:
            fail(errors, path, f"duplicate job id: {jid!r}")
        job_ids.add(jid)
        can_run_on = job.get("can_run_on")
        if can_run_on is not None and not isinstance(can_run_on, list):
            fail(errors, path, f"job {jid!r} can_run_on is not a list")
        processing_times = job.get("processing_times")
        if processing_times is not None and not isinstance(processing_times, (int, float, dict, list)):
            fail(errors, path, f"job {jid!r} processing_times is not numeric/dict/list")

    graph = nx.DiGraph()
    graph.add_nodes_from(job_ids)
    message_ids = set()
    for idx, message in enumerate(messages):
        if not isinstance(message, dict):
            fail(errors, path, f"message[{idx}] is not an object")
            continue
        missing = REQUIRED_MESSAGE_FIELDS - set(message)
        if missing:
            fail(errors, path, f"message[{idx}] missing fields: {sorted(missing)}")
        mid = message.get("id")
        if mid in message_ids:
            fail(errors, path, f"duplicate message id: {mid!r}")
        message_ids.add(mid)
        sender = message.get("sender")
        receiver = message.get("receiver")
        if sender not in job_ids:
            fail(errors, path, f"message {mid!r} sender {sender!r} is not an existing job")
        if receiver not in job_ids:
            fail(errors, path, f"message {mid!r} receiver {receiver!r} is not an existing job")
        if sender in job_ids and receiver in job_ids:
            graph.add_edge(sender, receiver)

    is_dag = nx.is_directed_acyclic_graph(graph)
    if not is_dag:
        fail(errors, path, "dependency graph is cyclic")

    return len(jobs), len(messages), is_dag, errors, warnings


def main():
    print(f"worktree_root={WORKTREE_ROOT}")
    print(f"benchmark_dir={BENCHMARK_DIR}")
    all_errors = []
    for name in FILES:
        path = BENCHMARK_DIR / name
        jobs, messages, is_dag, errors, warnings = validate_file(path)
        all_errors.extend(errors)
        status = "PASS" if not errors else "FAIL"
        print(f"{status}: {name}: jobs={jobs} messages={messages} dag_acyclic={is_dag}")
        for warning in warnings:
            print(f"WARNING: {warning}")
        for error in errors:
            print(f"ERROR: {error}")

    if all_errors:
        print(f"VALIDATION_FAILED errors={len(all_errors)}")
        return 1
    print("VALIDATION_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
