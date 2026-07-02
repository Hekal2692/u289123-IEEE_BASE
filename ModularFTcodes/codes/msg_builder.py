# msg_builder.py
from __future__ import annotations
import os, glob, json, datetime
from typing import Dict, Any, Optional
import json, os, glob, datetime

def build_msg_from_dir(dir_path: str, out_path: str):
    """Scan <dir_path> for *__schedule_*.json files and write an MSG JSON to out_path."""
    def compute_makespan(sched): 
        return max(float(v[2]) for v in sched.values()) if sched else 0.0

    paths = sorted(glob.glob(os.path.join(dir_path, "*__schedule_*.json")))
    nodes, edges, root_tag = {}, [], None

    for p in paths:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        meta, sched = data.get("meta", {}), data.get("schedule", {})
        tag = meta.get("schedule_tag") or os.path.basename(p).split("__")[0]
        parent = meta.get("parent_schedule")
        if parent is None: root_tag = tag
        nodes[tag] = {
            "tag": tag,
            "file": os.path.basename(p),
            "saved_at": meta.get("saved_at"),
            "parent": parent,
            "calendar_path": meta.get("calendar_path"),
            "moved_count": meta.get("moved_count", 0),
            "schedule_hash": meta.get("schedule_hash"),
            "tasks": len(sched),
            "makespan": compute_makespan(sched),
        }

    for tag, nd in nodes.items():
        parent = nd.get("parent")
        if parent is None: continue
        with open(os.path.join(dir_path, nd["file"]), "r", encoding="utf-8") as f:
            cdata = json.load(f)
        edges.append({
            "from": parent,
            "to": tag,
            "event": cdata.get("meta", {}).get("event"),
            "moved_count": nd["moved_count"],
            "child_makespan": nd["makespan"],
        })

    msg = {
        "meta": {
            "version": "1.0",
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "root": root_tag,
            "notes": "Nodes are schedules; edges are triggering events."
        },
        "nodes": nodes,
        "edges": edges
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(msg, f, indent=2)





def build_msg_artifacts(log_dir: str, timestamp: str, make_png: bool = True) -> Dict[str, Any]:
    """
    Build a Multi-Schedule Graph (MSG) for a run.
    - Nodes are schedules found in <log_dir> matching "*__schedule_<timestamp>.json".
    - Edges are the events stored in each child's `meta.event`, linking parent->child.

    Writes:
      - MSG_<timestamp>.json  (graph data)
      - MSG_<timestamp>.dot   (GraphViz)
      - MSG_<timestamp>.png   (optional preview; skipped if matplotlib not available)

    Returns a dict with file paths and simple counts.

    Parameters
    ----------
    log_dir : str
        Directory for the current run (e.g., "logs/2025-08-19_13-38-18").
    timestamp : str
        Run timestamp string used in filenames (e.g., "2025-08-19_13-38-18").
    make_png : bool
        If True, try to render a simple PNG tree preview with matplotlib. If matplotlib
        is not installed, PNG is silently skipped.

    Notes
    -----
    - Root is inferred as the node with `parent_schedule is None`. If multiple candidates
      exist, S0 is preferred; else the first one by name.
    - Makespan is computed as max(end_time) across tasks in each schedule.
    """
    os.makedirs(log_dir, exist_ok=True)
    schedule_glob = os.path.join(log_dir, f"*__schedule_{timestamp}.json")

    def _compute_makespan(sched: Dict[str, Any]) -> float:
        ms = 0.0
        for v in (sched or {}).values():
            try:
                # v = [proc, start, end, deps]
                ms = max(ms, float(v[2]))
            except Exception:
                pass
        return ms

    # 1) Scan schedules -> nodes
    nodes: Dict[str, Dict[str, Any]] = {}
    edges = []
    for path in sorted(glob.glob(schedule_glob)):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        meta = data.get("meta", {})
        sched = data.get("schedule", {})

        tag = meta.get("schedule_tag") or os.path.basename(path).split("__")[0]
        parent = meta.get("parent_schedule")
        nodes[tag] = {
            "tag": tag,
            "file": os.path.basename(path),
            "saved_at": meta.get("saved_at"),
            "parent": parent,
            "calendar_path": meta.get("calendar_path"),
            "moved_count": meta.get("moved_count", 0),
            "schedule_hash": meta.get("schedule_hash"),
            "tasks": len(sched or {}),
            "makespan": _compute_makespan(sched),
        }

    # 2) Build edges by child -> parent using child's meta.event
    for tag, nd in nodes.items():
        parent = nd.get("parent")
        if not parent:
            continue
        child_path = os.path.join(log_dir, nd["file"])
        try:
            with open(child_path, "r", encoding="utf-8") as f:
                cdata = json.load(f)
            event = cdata.get("meta", {}).get("event")
        except Exception:
            event = None
        edges.append({
            "from": parent,
            "to": tag,
            "event": event,
            "moved_count": nd.get("moved_count", 0),
            "child_makespan": nd.get("makespan"),
        })

    # 3) Infer root
    roots = [t for t, nd in nodes.items() if not nd.get("parent")]
    root = None
    if "S0" in nodes and (not nodes["S0"].get("parent")):
        root = "S0"
    elif roots:
        root = sorted(roots)[0]
    elif nodes:
        root = sorted(nodes.keys())[0]

    # 4) JSON
    msg = {
        "meta": {
            "version": "1.0",
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "root": root,
            "notes": "Nodes are schedules; edges are triggering events parent->child."
        },
        "nodes": nodes,
        "edges": edges
    }
    json_path = os.path.join(log_dir, f"MSG_{timestamp}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(msg, f, indent=2)

    # 5) DOT
    def _esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    dot_lines = ["digraph MSG {", "  rankdir=LR;", "  node [shape=box];"]
    for tag, nd in nodes.items():
        ms = nd.get("makespan")
        tasks = nd.get("tasks")
        moved = nd.get("moved_count")
        label = f"{tag}"
        extras = []
        if ms is not None: extras.append(f"MS={int(ms)}")
        if tasks is not None: extras.append(f"Tasks={tasks}")
        if moved not in (None, 0): extras.append(f"Moved={moved}")
        if extras: label += "\\n" + "\\n".join(extras)
        dot_lines.append(f'  "{_esc(tag)}" [label="{_esc(label)}"];')
    for e in edges:
        p, c = e["from"], e["to"]
        ev = e.get("event") or {}
        typ = ev.get("type", "event")
        tme = ev.get("time", None)
        eid = ev.get("id", "")
        lbl = f"{typ}@{tme}" if tme is not None else typ
        if eid: lbl += f" ({eid})"
        dot_lines.append(f'  "{_esc(p)}" -> "{_esc(c)}" [label="{_esc(lbl)}"];')
    dot_lines.append("}")
    dot_path = os.path.join(log_dir, f"MSG_{timestamp}.dot")
    with open(dot_path, "w", encoding="utf-8") as f:
        f.write("\n".join(dot_lines))

    # 6) Optional PNG (pure matplotlib, simple layered layout)
    png_path: Optional[str] = None
    if make_png:
        try:
            import matplotlib.pyplot as plt
            # Build adjacency for layout
            children = {k: [] for k in nodes.keys()}
            for e in edges:
                children.setdefault(e["from"], []).append(e["to"])
            # BFS layering
            levels, visited = [], set()
            start = root or (sorted(nodes.keys())[0] if nodes else None)
            queue = [(start, 0)] if start else []
            while queue:
                cur, d = queue.pop(0)
                if cur in visited: continue
                visited.add(cur)
                while len(levels) <= d: levels.append([])
                levels[d].append(cur)
                for ch in children.get(cur, []): queue.append((ch, d + 1))
            # Orphans (if any)
            orphans = [n for n in nodes.keys() if n not in visited]
            if orphans: levels.append(orphans)

            # Positions
            pos = {}
            for depth, lvl_nodes in enumerate(levels):
                k = max(1, len(lvl_nodes))
                for i, tag in enumerate(lvl_nodes):
                    x = i / (k - 1) if k > 1 else 0.5
                    y = -depth
                    pos[tag] = (x, y)

            # Plot
            plt.figure(figsize=(10, 6))
            ax = plt.gca()

            # Edges with labels
            for e in edges:
                p, c = e["from"], e["to"]
                if p not in pos or c not in pos:
                    continue
                x1, y1 = pos[p]; x2, y2 = pos[c]
                ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                            arrowprops=dict(arrowstyle="->"))
                ev = e.get("event") or {}
                typ = ev.get("type", "event")
                tme = ev.get("time", None)
                eid = ev.get("id", "")
                lbl = f"{typ}@{tme}" if tme is not None else typ
                if eid: lbl += f" ({eid})"
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2 + 0.03
                ax.text(mx, my, lbl, fontsize=8, ha="center", va="bottom")

            # Nodes + labels
            for tag, (x, y) in pos.items():
                ax.scatter([x], [y])
                nd = nodes[tag]
                lab = f"{tag}"
                if nd.get("makespan") is not None:
                    lab += f"\nMS={int(nd['makespan'])}"
                if nd.get("moved_count", 0):
                    lab += f"\nMoved={nd['moved_count']}"
                ax.text(x, y - 0.05, lab, fontsize=9, ha="center", va="top")

            ax.set_axis_off()
            plt.tight_layout()
            png_path = os.path.join(log_dir, f"MSG_{timestamp}.png")
            plt.savefig(png_path, dpi=180)
            plt.close()
        except Exception:
            # matplotlib missing or other rendering issue; skip PNG
            png_path = None

    return {
        "json": json_path,
        "dot": dot_path,
        "png": png_path,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "root": root,
    }
