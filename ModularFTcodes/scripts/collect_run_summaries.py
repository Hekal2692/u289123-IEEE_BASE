#!/usr/bin/env python3
import csv
import json
from pathlib import Path


def _read_json(path):
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def _read_csv_rows(path):
    with path.open('r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        return list(reader)


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([])
        return
    fieldnames = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    repo_root = Path(__file__).resolve().parents[1]
    logs_root = repo_root / 'codes' / 'logs'
    run_summary_paths = sorted(logs_root.rglob('run_summary.json'))
    run_rows = [_read_json(path) for path in run_summary_paths]
    _write_csv(logs_root / 'all_runs_summary.csv', run_rows)

    generation_rows = []
    for summary_path in run_summary_paths:
        run_dir = summary_path.parent
        summary = _read_json(summary_path)
        csv_path = run_dir / 'system_ga_summary.csv'
        if not csv_path.exists():
            continue
        rows = _read_csv_rows(csv_path)
        for row in rows:
            row.setdefault('run_id', summary.get('run_id'))
            row.setdefault('am_id', summary.get('am_id'))
            row.setdefault('base_deadline', summary.get('base_deadline'))
            row.setdefault('deadline_ratio', summary.get('deadline_ratio'))
            row.setdefault('actual_deadline_value', summary.get('actual_deadline_value'))
            row.setdefault('seed', summary.get('seed'))
            row.setdefault('variant', summary.get('variant'))
            generation_rows.append(row)
    _write_csv(logs_root / 'all_generation_rows.csv', generation_rows)

    print(f'Collected {len(run_rows)} run summaries into {logs_root / "all_runs_summary.csv"}')
    print(f'Collected {len(generation_rows)} generation rows into {logs_root / "all_generation_rows.csv"}')


if __name__ == '__main__':
    main()
