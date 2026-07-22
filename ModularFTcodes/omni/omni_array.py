#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

FIELDS = [
    "array_index",
    "run_key",
    "AM_ID",
    "workload",
    "BASE_DEADLINE",
    "DEADLINE_RATIO",
    "actual_deadline",
    "SEED",
    "VARIANT",
]
SEEDS = [str(seed) for seed in range(1001, 1011)]
WORKLOADS = [
    ("AM100", "2600", [("1.00", "2600"), ("0.90", "2340"), ("0.80", "2080"), ("0.70", "1820")]),
    ("AM250", "2700", [("1.00", "2700"), ("0.90", "2430"), ("0.80", "2160"), ("0.70", "1890")]),
    ("AM500", "4300", [("1.00", "4300"), ("0.90", "3870"), ("0.80", "3440"), ("0.70", "3010")]),
]
AM_SIZE_BY_ID = {"AM100": "100T", "AM250": "250T", "AM500": "500T"}
AM_FILES = {
    "AM100": [
        "Platforms/100T/TC100_NewPM.json",
        "Platforms/100T/FogEdgePartitionedTasks_merged_strict.json",
        "Platforms/100T/Cloud1PartitionedData_merged.json",
        "Platforms/100T/Cloud2PartitionedData_merged.json",
        "Platforms/100T/Cloud3PartitionedData_merged.json",
    ],
    "AM250": [
        "Platforms/250T/TC250.json",
        "Platforms/250T/250_FETASKS.json",
        "Platforms/250T/250_C1TASKS.json",
        "Platforms/250T/250_C2TASKS.json",
        "Platforms/250T/250_C3TASKS.json",
    ],
    "AM500": [
        "Platforms/500T/TC500.json",
        "Platforms/500T/500_FETASKS.json",
        "Platforms/500T/500_C1TASKS.json",
        "Platforms/500T/500_C2TASKS.json",
        "Platforms/500T/500_C3TASKS.json",
    ],
}
REQUIRED_PROJECT_FILES = [
    "requirements.txt",
    "codes/main.py",
    "codes/config.py",
    "codes/SystemLevelScheduler.py",
    "codes/PartitionGA.py",
    "codes/GAAux.py",
    "codes/SysGAAux.py",
    "Platforms/FEPlatform.json",
    "Platforms/CloudModel1.json",
    "Platforms/CloudModel2.json",
    "Platforms/CloudModel3.json",
]
RESUBMITTABLE = {
    "missing",
    "interrupted with checkpoint",
    "failed with checkpoint",
    "failed without checkpoint",
}
ACTIVE = {"pending", "running"}


def now_stamp():
    return datetime.now().isoformat(timespec="seconds")


def sha256_file(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_sha(project_dir):
    try:
        return subprocess.check_output(
            ["git", "-C", str(project_dir), "rev-parse", "--verify", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def expected_rows():
    rows = []
    index = 0
    for am_id, base_deadline, ratios in WORKLOADS:
        for ratio, actual_deadline in ratios:
            for seed in SEEDS:
                rows.append({
                    "array_index": str(index),
                    "run_key": f"{am_id}__ratio{ratio}__seed{seed}__proposed",
                    "AM_ID": am_id,
                    "workload": am_id,
                    "BASE_DEADLINE": base_deadline,
                    "DEADLINE_RATIO": ratio,
                    "actual_deadline": actual_deadline,
                    "SEED": seed,
                    "VARIANT": "proposed",
                })
                index += 1
    return rows


EXPECTED_BY_INDEX = {row["array_index"]: row for row in expected_rows()}


def read_manifest(path):
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"ERROR: manifest does not exist: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames != FIELDS:
            raise SystemExit(
                "ERROR: manifest header mismatch. Expected: " + "\t".join(FIELDS)
            )
        rows = [{key: (row.get(key) or "").strip() for key in FIELDS} for row in reader]
    return rows


def required_files(project_dir):
    project_dir = Path(project_dir)
    files = [project_dir / rel for rel in REQUIRED_PROJECT_FILES]
    for am_id in AM_FILES:
        files.extend(project_dir / rel for rel in AM_FILES[am_id])
    return files


def validate_manifest(path, project_dir):
    rows = read_manifest(path)
    errors = []
    if len(rows) != 120:
        errors.append(f"expected exactly 120 data rows, found {len(rows)}")
    indices = [row["array_index"] for row in rows]
    if sorted(indices, key=lambda value: int(value) if value.isdigit() else -1) != [str(i) for i in range(120)]:
        errors.append("array indices are not exactly 0 through 119")
    if len(indices) != len(set(indices)):
        errors.append("array indices are not unique")
    run_keys = [row["run_key"] for row in rows]
    if len(run_keys) != len(set(run_keys)):
        errors.append("run keys are not unique")

    for row in rows:
        index = row["array_index"]
        expected = EXPECTED_BY_INDEX.get(index)
        if expected is None:
            errors.append(f"row has unexpected array_index={index!r}")
            continue
        for field in FIELDS:
            if row[field] != expected[field]:
                errors.append(
                    f"row {index} field {field} expected {expected[field]!r}, found {row[field]!r}"
                )
        try:
            calculated = int(round(float(row["BASE_DEADLINE"]) * float(row["DEADLINE_RATIO"])))
            if calculated != int(row["actual_deadline"]):
                errors.append(
                    f"row {index} calculated deadline {calculated} != actual_deadline {row['actual_deadline']}"
                )
        except Exception as exc:
            errors.append(f"row {index} has invalid numeric deadline fields: {exc}")

    groups = defaultdict(set)
    for row in rows:
        groups[(row["workload"], row["DEADLINE_RATIO"], row["actual_deadline"])].add(row["SEED"])
        if row["VARIANT"] != "proposed":
            errors.append(f"row {row['array_index']} has VARIANT={row['VARIANT']!r}, expected 'proposed'")
    if len(groups) != 12:
        errors.append(f"expected 12 workload-deadline groups, found {len(groups)}")
    for group, seeds in sorted(groups.items()):
        if seeds != set(SEEDS):
            missing = sorted(set(SEEDS) - seeds)
            extra = sorted(seeds - set(SEEDS))
            errors.append(f"group {group} has missing seeds {missing} and extra seeds {extra}")

    missing_files = [str(path) for path in required_files(project_dir) if not Path(path).exists()]
    if missing_files:
        errors.append("required application/platform files are missing: " + ", ".join(missing_files))

    if errors:
        raise SystemExit("ERROR: manifest validation failed:\n- " + "\n- ".join(errors))
    return rows


def row_by_index(manifest_path, array_index, project_dir=None, validate=False):
    rows = validate_manifest(manifest_path, project_dir) if validate and project_dir else read_manifest(manifest_path)
    wanted = str(array_index)
    matches = [row for row in rows if row["array_index"] == wanted]
    if len(matches) != 1:
        raise SystemExit(f"ERROR: expected one manifest row for array_index={wanted}, found {len(matches)}")
    row = matches[0]
    expected = EXPECTED_BY_INDEX.get(wanted)
    if expected is None or any(row[field] != expected[field] for field in FIELDS):
        raise SystemExit(f"ERROR: manifest row {wanted} does not match the validated expected grid")
    return row


def run_dir_for(output_root, row):
    return Path(output_root).expanduser().resolve() / "runs" / row["run_key"]


def checkpoint_path_for(run_dir):
    return Path(run_dir) / "checkpoint_latest.pkl"


def checkpoint_sidecar_path(checkpoint_path):
    checkpoint_path = Path(checkpoint_path)
    return checkpoint_path.with_suffix(".json") if checkpoint_path.suffix else Path(str(checkpoint_path) + ".json")


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    os.replace(tmp_path, path)


def is_complete(run_dir, row=None):
    run_dir = Path(run_dir)
    if not (run_dir / "_SUCCESS").exists():
        return False
    summary_path = run_dir / "run_summary.json"
    if not summary_path.exists():
        return False
    try:
        summary = load_json(summary_path)
    except Exception:
        return False
    if summary.get("completed_successfully") is not True:
        return False
    if row:
        checks = {
            "run_key": row["run_key"],
            "am_id": row["AM_ID"],
            "workload": row["workload"],
            "seed": int(row["SEED"]),
            "variant": row["VARIANT"],
        }
        for key, expected in checks.items():
            actual = summary.get(key)
            if key == "seed" and actual is not None:
                actual = int(actual)
            if actual != expected:
                return False
        if round(float(summary.get("deadline_ratio")), 10) != round(float(row["DEADLINE_RATIO"]), 10):
            return False
        if int(summary.get("actual_deadline_value")) != int(row["actual_deadline"]):
            return False
    return True


def normalize(value):
    if isinstance(value, float):
        return round(value, 10)
    if isinstance(value, str):
        try:
            if re.fullmatch(r"-?\d+", value):
                return int(value)
            if re.fullmatch(r"-?\d+\.\d+", value):
                return round(float(value), 10)
        except Exception:
            return value
    if isinstance(value, dict):
        return {str(key): normalize(val) for key, val in sorted(value.items())}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return value


def checkpoint_matches_row(row, checkpoint_path):
    sidecar = checkpoint_sidecar_path(checkpoint_path)
    if not Path(checkpoint_path).exists():
        return False, "checkpoint does not exist"
    if not sidecar.exists():
        return False, f"checkpoint sidecar is missing: {sidecar}"
    try:
        payload = load_json(sidecar)
    except Exception as exc:
        return False, f"checkpoint sidecar is invalid JSON: {exc}"
    identity = payload.get("checkpoint_identity") or payload
    expected = {
        "run_key": row["run_key"],
        "workload": row["workload"],
        "am_id": row["AM_ID"],
        "base_deadline": int(row["BASE_DEADLINE"]),
        "deadline_ratio": float(row["DEADLINE_RATIO"]),
        "actual_deadline_value": int(row["actual_deadline"]),
        "seed": int(row["SEED"]),
        "variant": row["VARIANT"],
    }
    mismatches = []
    for key, expected_value in expected.items():
        if normalize(identity.get(key)) != normalize(expected_value):
            mismatches.append(key)
    if mismatches:
        return False, "mismatched checkpoint field(s): " + ", ".join(mismatches)
    return True, "checkpoint is compatible with manifest row"


def parse_index_expression(expr):
    expr = (expr or "").strip()
    if not expr:
        return []
    expr = expr.split("%", 1)[0]
    indices = []
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            indices.extend(range(int(start), int(end) + 1))
        else:
            indices.append(int(part))
    return sorted(set(indices))


def compact_indices(indices):
    values = sorted(set(int(index) for index in indices))
    if not values:
        return ""
    chunks = []
    start = prev = values[0]
    for value in values[1:]:
        if value == prev + 1:
            prev = value
            continue
        chunks.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = value
    chunks.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(chunks)


def indices_from_slurm_job_token(token, array_job_id):
    token = token.split(".", 1)[0]
    root = str(array_job_id).split(";", 1)[0]
    prefix = root + "_"
    if not token.startswith(prefix):
        return []
    suffix = token[len(prefix):]
    if suffix.startswith("[") and suffix.endswith("]"):
        suffix = suffix[1:-1]
    return parse_index_expression(suffix)


def read_squeue_states(array_job_id):
    if not array_job_id or not shutil.which("squeue"):
        return {}, False
    try:
        proc = subprocess.run(
            ["squeue", "-h", "-j", str(array_job_id).split(";", 1)[0], "-o", "%i|%T"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        return {}, False
    states = {}
    for line in proc.stdout.splitlines():
        if "|" not in line:
            continue
        token, state = line.split("|", 1)
        for index in indices_from_slurm_job_token(token.strip(), array_job_id):
            states[index] = state.strip().upper()
    return states, True


def read_sacct_states(array_job_id):
    if not array_job_id or not shutil.which("sacct"):
        return {}, False
    try:
        proc = subprocess.run(
            [
                "sacct", "-n", "-P", "-j", str(array_job_id).split(";", 1)[0],
                "--format=JobID,State,ExitCode",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        return {}, False
    states = {}
    for line in proc.stdout.splitlines():
        parts = line.split("|")
        if len(parts) < 2 or "." in parts[0]:
            continue
        token, state = parts[0].strip(), parts[1].strip().upper()
        for index in indices_from_slurm_job_token(token, array_job_id):
            states[index] = state
    return states, True


def load_array_job_id(output_root):
    path = Path(output_root) / "array_submission.json"
    if not path.exists():
        return None
    try:
        payload = load_json(path)
        return payload.get("array_job_id") or payload.get("raw_sbatch_id")
    except Exception:
        return None


def load_status(run_dir):
    path = Path(run_dir) / "run_status.json"
    if not path.exists():
        return None
    try:
        return load_json(path)
    except Exception:
        return {"state": "INVALID_STATUS"}


def classify_one(row, output_root, queue_states=None, sacct_states=None, queue_checked=False):
    index = int(row["array_index"])
    run_dir = run_dir_for(output_root, row)
    checkpoint_path = checkpoint_path_for(run_dir)
    status = load_status(run_dir)

    if is_complete(run_dir, row):
        return "complete"

    if status and str(status.get("state", "")).upper() == "CHECKPOINT_INCOMPATIBLE":
        return "checkpoint incompatible"

    if checkpoint_path.exists():
        compatible, _message = checkpoint_matches_row(row, checkpoint_path)
        if not compatible:
            return "checkpoint incompatible"

    qstate = (queue_states or {}).get(index)
    if qstate:
        if qstate in {"PENDING", "CONFIGURING", "COMPLETING"}:
            return "pending"
        if qstate in {"RUNNING", "SUSPENDED"}:
            return "running"

    acct_state = (sacct_states or {}).get(index, "")
    acct_base = acct_state.split()[0] if acct_state else ""
    if acct_base in {"FAILED", "TIMEOUT", "CANCELLED", "NODE_FAIL", "OUT_OF_MEMORY", "PREEMPTED", "BOOT_FAIL"}:
        return "failed with checkpoint" if checkpoint_path.exists() else "failed without checkpoint"

    if not run_dir.exists():
        return "missing"

    state = str((status or {}).get("state", "")).upper()
    if state in {"INTERRUPTED", "REQUEUED", "STOPPING"}:
        return "interrupted with checkpoint" if checkpoint_path.exists() else "failed without checkpoint"
    if state in {"FAILED", "ERROR"}:
        return "failed with checkpoint" if checkpoint_path.exists() else "failed without checkpoint"
    if state == "RUNNING":
        if queue_checked:
            return "failed with checkpoint" if checkpoint_path.exists() else "failed without checkpoint"
        return "running"

    if checkpoint_path.exists():
        return "interrupted with checkpoint"
    if status:
        return "failed without checkpoint"
    return "missing"


def classification_table(manifest_path, output_root, array_job_id=None):
    rows = read_manifest(manifest_path)
    array_job_id = array_job_id or load_array_job_id(output_root)
    queue_states, queue_checked = read_squeue_states(array_job_id)
    sacct_states, sacct_checked = read_sacct_states(array_job_id)
    table = []
    for row in rows:
        classification = classify_one(
            row,
            output_root,
            queue_states=queue_states,
            sacct_states=sacct_states,
            queue_checked=queue_checked,
        )
        table.append({"row": row, "classification": classification})
    return table, array_job_id, queue_checked, sacct_checked, queue_states, sacct_states


def cmd_validate(args):
    validate_manifest(args.manifest, args.project_dir)
    print(f"OK: validated 120-row manifest: {args.manifest}")


def cmd_export_row(args):
    row = row_by_index(args.manifest, args.array_index, args.project_dir, validate=True)
    exports = {
        "ARRAY_INDEX": row["array_index"],
        "RUN_KEY": row["run_key"],
        "AM_ID": row["AM_ID"],
        "WORKLOAD": row["workload"],
        "BASE_DEADLINE": row["BASE_DEADLINE"],
        "DEADLINE_RATIO": row["DEADLINE_RATIO"],
        "ACTUAL_DEADLINE": row["actual_deadline"],
        "SEED": row["SEED"],
        "VARIANT": row["VARIANT"],
    }
    for key, value in exports.items():
        print(f"export {key}={shlex.quote(str(value))}")


def cmd_check_complete(args):
    row = row_by_index(args.manifest, args.array_index) if args.manifest and args.array_index is not None else None
    run_dir = args.run_dir or run_dir_for(args.output_root, row)
    raise SystemExit(0 if is_complete(run_dir, row) else 1)


def cmd_check_checkpoint(args):
    row = row_by_index(args.manifest, args.array_index)
    ok, message = checkpoint_matches_row(row, args.checkpoint_path)
    print(message)
    raise SystemExit(0 if ok else 1)


def cmd_write_status(args):
    row = None
    if args.manifest and args.array_index is not None:
        row = row_by_index(args.manifest, args.array_index)
        run_dir = run_dir_for(args.output_root, row)
    elif args.run_dir:
        run_dir = Path(args.run_dir)
    else:
        raise SystemExit("ERROR: write-status needs --run-dir or --manifest/--array-index/--output-root")
    payload = {
        "state": args.state,
        "message": args.message,
        "updated_at": now_stamp(),
        "run_dir": str(Path(run_dir).resolve()),
        "exit_code": args.exit_code,
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "slurm_array_job_id": os.environ.get("SLURM_ARRAY_JOB_ID"),
        "slurm_array_task_id": os.environ.get("SLURM_ARRAY_TASK_ID"),
    }
    if row:
        payload.update(row)
        payload["checkpoint_path"] = str(checkpoint_path_for(run_dir))
    atomic_write_json(Path(run_dir) / "run_status.json", payload)


def cmd_status(args):
    validate_manifest(args.manifest, args.project_dir)
    table, array_job_id, queue_checked, sacct_checked, _q, sacct_states = classification_table(
        args.manifest, args.output_root, args.array_job_id
    )
    counts = Counter(item["classification"] for item in table)
    sacct_bases = Counter((state.split()[0] if state else "") for state in sacct_states.values())
    failed = counts["failed with checkpoint"] + counts["failed without checkpoint"]
    groups = defaultdict(list)
    for item in table:
        row = item["row"]
        groups[(row["workload"], row["DEADLINE_RATIO"], row["actual_deadline"])].append(item)
    complete_groups = 0
    groups_with_missing = []
    for group, items in sorted(groups.items()):
        incomplete = [item for item in items if item["classification"] != "complete"]
        if not incomplete:
            complete_groups += 1
        else:
            groups_with_missing.append((group, incomplete))

    print(f"SLURM array job ID: {array_job_id or 'unknown'}")
    print("total expected tasks: 120")
    print(f"completed tasks: {counts['complete']}")
    print(f"pending tasks: {counts['pending']}")
    print(f"running tasks: {counts['running']}")
    print(f"failed tasks: {failed}")
    print(f"timed-out tasks: {sacct_bases['TIMEOUT']}")
    print(f"cancelled tasks: {sacct_bases['CANCELLED']}")
    print(f"interrupted tasks with checkpoints: {counts['interrupted with checkpoint']}")
    print(f"missing tasks: {counts['missing']}")
    print(f"incompatible checkpoints: {counts['checkpoint incompatible']}")
    print(f"complete workload-deadline groups: {complete_groups}/12")
    print(f"squeue checked: {str(queue_checked).lower()}")
    print(f"sacct checked: {str(sacct_checked).lower()}")
    if groups_with_missing:
        print("groups with missing seeds:")
        for (workload, ratio, deadline), items in groups_with_missing:
            missing = ",".join(f"{item['row']['SEED']}:{item['classification']}" for item in items)
            print(f"  {workload} ratio{ratio} deadline{deadline}: {missing}")
    else:
        print("groups with missing seeds: none")


def cmd_incomplete_expression(args):
    validate_manifest(args.manifest, args.project_dir)
    table, array_job_id, queue_checked, sacct_checked, _q, _s = classification_table(
        args.manifest, args.output_root, args.array_job_id
    )
    selected = [int(item["row"]["array_index"]) for item in table if item["classification"] in RESUBMITTABLE]
    incompatible = [int(item["row"]["array_index"]) for item in table if item["classification"] == "checkpoint incompatible"]
    expr = compact_indices(selected)
    if args.plain:
        print(expr)
        return
    payload = {
        "array_job_id": array_job_id,
        "selected_indices": selected,
        "array_expression": expr,
        "selected_count": len(selected),
        "incompatible_indices_excluded": incompatible,
        "squeue_checked": queue_checked,
        "sacct_checked": sacct_checked,
        "counts": Counter(item["classification"] for item in table),
    }
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(f"array job ID: {array_job_id or 'unknown'}")
        print(f"selected incomplete indices: {expr or 'none'}")
        print(f"selected count: {len(selected)}")
        if incompatible:
            print(f"checkpoint-incompatible indices excluded: {compact_indices(incompatible)}")


def cmd_write_submission(args):
    raw = args.array_job_id.strip()
    payload = {
        "array_job_id": raw.split(";", 1)[0],
        "raw_sbatch_id": raw,
        "submitted_at": now_stamp(),
        "manifest": str(Path(args.manifest).resolve()),
        "manifest_sha256": sha256_file(args.manifest),
        "output_root": str(Path(args.output_root).expanduser().resolve()),
        "max_concurrent": int(args.max_concurrent),
        "git_commit_sha": args.git_commit_sha,
        "array_expression": args.array_expression,
    }
    atomic_write_json(Path(args.output_root) / "array_submission.json", payload)
    print(Path(args.output_root) / "array_submission.json")


def cmd_write_environment_marker(args):
    payload = {
        "state": "READY",
        "written_at": now_stamp(),
        "project_dir": str(Path(args.project_dir).resolve()),
        "venv": str(Path(args.venv).expanduser()),
        "python_bin": args.python_bin,
        "requirements_sha256": sha256_file(Path(args.project_dir) / "requirements.txt"),
    }
    atomic_write_json(args.marker, payload)
    print(f"OK: wrote environment marker {args.marker}")


def cmd_check_environment(args):
    marker = Path(args.marker)
    if not marker.exists():
        raise SystemExit(f"ERROR: environment-ready marker not found: {marker}")
    payload = load_json(marker)
    venv = Path(payload.get("venv", "")).expanduser()
    if not venv.exists():
        raise SystemExit(f"ERROR: venv recorded in marker does not exist: {venv}")
    if args.project_dir:
        req_path = Path(args.project_dir) / "requirements.txt"
        if req_path.exists() and payload.get("requirements_sha256") != sha256_file(req_path):
            raise SystemExit("ERROR: requirements.txt changed after environment preparation")
    print(f"OK: environment marker is ready: {marker}")


def cmd_write_preflight_marker(args):
    payload = {
        "state": "PASSED",
        "written_at": now_stamp(),
        "project_dir": str(Path(args.project_dir).resolve()),
        "manifest": str(Path(args.manifest).resolve()),
        "manifest_sha256": sha256_file(args.manifest),
        "git_commit_sha": git_sha(args.project_dir),
    }
    atomic_write_json(args.marker, payload)
    print(f"OK: wrote preflight marker {args.marker}")


def cmd_marker_value(args):
    payload = load_json(args.marker)
    value = payload
    for part in args.key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise SystemExit(f"ERROR: marker key not found: {args.key}")
        value = value[part]
    print(value)


def build_parser():
    parser = argparse.ArgumentParser(description="Omni SLURM array manifest/status helper")
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    p = sub.add_parser("validate-manifest")
    p.add_argument("--manifest", required=True)
    p.add_argument("--project-dir", required=True)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("export-row")
    p.add_argument("--manifest", required=True)
    p.add_argument("--array-index", required=True)
    p.add_argument("--project-dir", required=True)
    p.set_defaults(func=cmd_export_row)

    p = sub.add_parser("check-complete")
    p.add_argument("--run-dir")
    p.add_argument("--manifest")
    p.add_argument("--array-index")
    p.add_argument("--output-root")
    p.set_defaults(func=cmd_check_complete)

    p = sub.add_parser("check-checkpoint")
    p.add_argument("--manifest", required=True)
    p.add_argument("--array-index", required=True)
    p.add_argument("--checkpoint-path", required=True)
    p.set_defaults(func=cmd_check_checkpoint)

    p = sub.add_parser("write-status")
    p.add_argument("--state", required=True)
    p.add_argument("--message")
    p.add_argument("--exit-code", type=int)
    p.add_argument("--run-dir")
    p.add_argument("--manifest")
    p.add_argument("--array-index")
    p.add_argument("--output-root")
    p.set_defaults(func=cmd_write_status)

    p = sub.add_parser("status")
    p.add_argument("--manifest", required=True)
    p.add_argument("--project-dir", required=True)
    p.add_argument("--output-root", required=True)
    p.add_argument("--array-job-id")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("incomplete-expression")
    p.add_argument("--manifest", required=True)
    p.add_argument("--project-dir", required=True)
    p.add_argument("--output-root", required=True)
    p.add_argument("--array-job-id")
    p.add_argument("--plain", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_incomplete_expression)

    p = sub.add_parser("write-submission")
    p.add_argument("--output-root", required=True)
    p.add_argument("--array-job-id", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--max-concurrent", required=True)
    p.add_argument("--git-commit-sha")
    p.add_argument("--array-expression", required=True)
    p.set_defaults(func=cmd_write_submission)

    p = sub.add_parser("write-environment-marker")
    p.add_argument("--marker", required=True)
    p.add_argument("--project-dir", required=True)
    p.add_argument("--venv", required=True)
    p.add_argument("--python-bin", required=True)
    p.set_defaults(func=cmd_write_environment_marker)

    p = sub.add_parser("check-environment")
    p.add_argument("--marker", required=True)
    p.add_argument("--project-dir")
    p.set_defaults(func=cmd_check_environment)

    p = sub.add_parser("write-preflight-marker")
    p.add_argument("--marker", required=True)
    p.add_argument("--project-dir", required=True)
    p.add_argument("--manifest", required=True)
    p.set_defaults(func=cmd_write_preflight_marker)

    p = sub.add_parser("marker-value")
    p.add_argument("--marker", required=True)
    p.add_argument("--key", required=True)
    p.set_defaults(func=cmd_marker_value)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
