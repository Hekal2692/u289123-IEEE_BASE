# ga_plotly.py
from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple
import os, json

import plotly.graph_objects as go
from plotly.subplots import make_subplots

def _ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)

def save_histories_json(histories: Dict[str, Any], out_dir: str, timestamp: Optional[str] = None) -> str:
    _ensure_dir(out_dir)
    fname = f"ga_histories_{timestamp or 'run'}.json"
    path = os.path.join(out_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(histories, f, indent=2)
    return path

def _require_kaleido() -> None:
    """
    Plotly static image export requires 'kaleido'.
    Raises a clear error if PNG export isn't available.
    """
    try:
        # Try exporting a tiny figure to memory
        _ = go.Figure().to_image(format="png")
    except Exception as e:
        raise RuntimeError(
            "PNG export needs Plotly's Kaleido backend.\n"
            "Please install it in your environment:\n\n"
            "    pip install -U kaleido\n"
        ) from e

def _trace_runs_one_metric(
    runs_for_partition: List[Dict[str, Any]],
    metric_key: str,
    name_prefix: str
) -> List[go.Scatter]:
    traces = []
    for i, run in enumerate(runs_for_partition, start=1):
        H = run.get("history", {})
        series = H.get(metric_key, [])
        if not series:
            continue
        x = list(range(1, len(series) + 1))
        label = f"{name_prefix} run#{i} (TB={run.get('budget','?')})"
        traces.append(go.Scatter(
            x=x, y=series, mode="lines", name=label,
            hovertemplate="gen=%{x}<br>value=%{y}<extra>"+label+"</extra>"
        ))
    return traces

def plot_partition_runs_by_sysgen_png(
    part_runs_by_sysgen: Dict[str, Dict[str, List[Dict[str, Any]]]],
    out_dir: str,
    timestamp: Optional[str] = None,
    metrics: Tuple[str, ...] = ("makespan_evolution", "lateness_evolution", "fitness_evolution"),
) -> List[str]:
    """
    For each system generation g and each metric, save a PNG with a 2x2 grid (P_FE,P_C1,P_C2,P_C3).
    Each subplot shows all inner runs (lines) for that partition within that system gen.
    """
    _ensure_dir(out_dir)
    _require_kaleido()
    png_paths: List[str] = []

    def _key(x):
        try: return int(x)
        except: return x

    parts = ["P_FE", "P_C1", "P_C2", "P_C3"]
    rc = {(0,0):(1,1),(0,1):(1,2),(1,0):(2,1),(1,1):(2,2)}

    for g in sorted(part_runs_by_sysgen.keys(), key=_key):
        per_part = part_runs_by_sysgen[g]
        for metric in metrics:
            fig = make_subplots(rows=2, cols=2, subplot_titles=parts)
            for idx, p in enumerate(parts):
                r,c = rc[(idx//2, idx%2)]
                runs = per_part.get(p, [])
                traces = _trace_runs_one_metric(runs, metric, name_prefix=p)
                if not traces:
                    traces = [go.Scatter(x=[0], y=[0], mode="lines", name=f"{p} (no data)", showlegend=False)]
                for t in traces:
                    fig.add_trace(t, row=r, col=c)
                fig.update_xaxes(title_text="Partition-GA gen", row=r, col=c)
                fig.update_yaxes(title_text=metric.replace("_", " "), row=r, col=c)
            fig.update_layout(
                title_text=f"Partition GA runs (System Gen {g}) — {metric}",
                legend_title_text="Runs",
                height=800, width=1200
            )
            out = os.path.join(out_dir, f"partition_runs_G{g}_{metric}_{timestamp or 'run'}.png")
            fig.write_image(out, format="png", scale=2)
            png_paths.append(out)
    return png_paths

def plot_budgets_runs_by_sysgen_png(
    budgets_runs_by_sysgen: Dict[str, List[Dict[str, int]]],
    out_dir: str,
    timestamp: Optional[str] = None,
) -> List[str]:
    """
    For each system generation g, save a PNG with four subplots (P_FE,P_C1,P_C2,P_C3),
    showing budgets per evaluated individual (run#) within that system gen.
    """
    _ensure_dir(out_dir)
    _require_kaleido()
    png_paths: List[str] = []

    def _key(x):
        try: return int(x)
        except: return x

    parts = ["P_FE", "P_C1", "P_C2", "P_C3"]
    rc = {(0,0):(1,1),(0,1):(1,2),(1,0):(2,1),(1,1):(2,2)}

    for g in sorted(budgets_runs_by_sysgen.keys(), key=_key):
        lst = budgets_runs_by_sysgen[g]  # list of dicts per run
        fig = make_subplots(rows=2, cols=2, subplot_titles=parts)
        for idx, p in enumerate(parts):
            r,c = rc[(idx//2, idx%2)]
            y = [d.get(p, None) for d in lst]
            x = list(range(1, len(y) + 1))
            fig.add_trace(go.Scatter(
                x=x, y=y, mode="lines+markers", name=p,
                hovertemplate="run=%{x}<br>TB=%{y}<extra>"+p+"</extra>"
            ), row=r, col=c)
            fig.update_xaxes(title_text="Run # (within system gen)", row=r, col=c)
            fig.update_yaxes(title_text="Time budget", row=r, col=c)
        fig.update_layout(title_text=f"Budgets per run (System Gen {g})", height=800, width=1200)
        out = os.path.join(out_dir, f"budgets_runs_G{g}_{timestamp or 'run'}.png")
        fig.write_image(out, format="png", scale=2)
        png_paths.append(out)
    return png_paths

def plot_system_summary_png(
    sys_hist: Dict[str, Any],
    out_dir: str,
    timestamp: Optional[str] = None,
) -> List[str]:
    """
    Save three PNGs across system generations: global lateness line; budgets per partition; makespans per partition.
    """
    _ensure_dir(out_dir)
    _require_kaleido()
    png_paths: List[str] = []
    gens = sys_hist.get("gen", [])
    if not gens:
        return png_paths

    # Global lateness
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=gens, y=sys_hist.get("global_lateness", []),
                             mode="lines+markers", name="global_lateness"))
    fig.update_layout(title="System GA — Global lateness",
                      xaxis_title="System GA gen", yaxis_title="Global lateness")
    out = os.path.join(out_dir, f"system_global_lateness_{timestamp or 'run'}.png")
    fig.write_image(out, format="png", scale=2)
    png_paths.append(out)

    # Budgets per partition
    budgets = sys_hist.get("budgets", [])
    if budgets:
        parts = list(budgets[0].keys())
        fig = go.Figure()
        for p in parts:
            y = [b.get(p, None) for b in budgets]
            fig.add_trace(go.Scatter(x=gens, y=y, mode="lines+markers", name=p))
        fig.update_layout(title="System GA — Budgets per partition",
                          xaxis_title="System GA gen", yaxis_title="Budget")
        out = os.path.join(out_dir, f"system_budgets_{timestamp or 'run'}.png")
        fig.write_image(out, format="png", scale=2)
        png_paths.append(out)

    # Makespans per partition
    makes = sys_hist.get("makespans", [])
    if makes:
        parts = list(makes[0].keys())
        fig = go.Figure()
        for p in parts:
            y = [m.get(p, None) for m in makes]
            fig.add_trace(go.Scatter(x=gens, y=y, mode="lines+markers", name=p))
        fig.update_layout(title="System GA — Partition makespans",
                          xaxis_title="System GA gen", yaxis_title="Makespan")
        out = os.path.join(out_dir, f"system_makespans_{timestamp or 'run'}.png")
        fig.write_image(out, format="png", scale=2)
        png_paths.append(out)

    return png_paths

def save_and_plot_all_plotly_png(meta: Dict[str, Any], out_dir: str, timestamp: Optional[str] = None) -> Dict[str, List[str]]:
    """
    Expects meta like:
      meta["histories"]["partition_ga_runs_by_sysgen"][sys_gen][partition] -> list of {history, budget}
      meta["histories"]["budgets_per_run_by_sysgen"][sys_gen] -> list of {P_FE:tb, ...} per evaluated individual
      meta["histories"]["system_ga"] -> {gen, global_lateness, budgets, makespans}
    Produces multiple PNG files.
    """
    _ensure_dir(out_dir)
    H = meta.get("histories", {})
    out: Dict[str, List[str]] = {}

    # always write JSON snapshot too (handy for later)
    json_path = save_histories_json(H, out_dir, timestamp)
    out["json"] = [json_path]

    # part_runs = H.get("partition_ga_runs_by_sysgen", {})
    # if isinstance(part_runs, dict) and part_runs:
    #     out["partition_runs_png"] = plot_partition_runs_by_sysgen_png(part_runs, out_dir, timestamp)

    # budgets_runs = H.get("budgets_per_run_by_sysgen", {})
    # if isinstance(budgets_runs, dict) and budgets_runs:
    #     out["budgets_runs_png"] = plot_budgets_runs_by_sysgen_png(budgets_runs, out_dir, timestamp)

    sys_hist = H.get("system_ga", {})
    if isinstance(sys_hist, dict) and sys_hist.get("gen"):
        out["system_summary_png"] = plot_system_summary_png(sys_hist, out_dir, timestamp)

    return out


