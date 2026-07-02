
# ga_monitor.py
from __future__ import annotations
from typing import Dict, Any, Optional
import os, json
import matplotlib.pyplot as plt

def _ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)

def save_histories_json(histories: Dict[str, Any], out_dir: str, timestamp: Optional[str] = None) -> str:
    _ensure_dir(out_dir)
    fname = f"ga_histories_{timestamp or 'run'}.json"
    path = os.path.join(out_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(histories, f, indent=2)
    return path

def _plot_lines(x, series_by_label: Dict[str, list], xlabel: str, ylabel: str, title: str, out_path: str) -> None:
    plt.figure()
    for label, y in series_by_label.items():
        if not y: 
            continue
        plt.plot(x, y, label=str(label))
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(title)
    if series_by_label:
        plt.legend()
    plt.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close()

def plot_partition_ga(histories_by_part: Dict[str, Dict[str, list]], out_dir: str, tag: str) -> Dict[str, str]:
    _ensure_dir(out_dir)
    saved = {}
    # Fitness
    series = {}
    x = None
    for p, H in histories_by_part.items():
        bf = H.get("fitness_evolution", [])
        if bf:
            series[p] = bf
            x = list(range(1, len(bf) + 1))
    if x:
        out = os.path.join(out_dir, f"{tag}__partition_best_fitness.png")
        _plot_lines(x, series, "Partition GA generation", "Best fitness", "Partition GA — Best fitness", out)
        saved["partition_best_fitness_png"] = out

    # Lateness
    series = {}
    x = None
    for p, H in histories_by_part.items():
        bl = H.get("lateness_evolution", [])
        if bl:
            series[p] = bl
            x = list(range(1, len(bl) + 1))
    if x:
        out = os.path.join(out_dir, f"{tag}__partition_best_lateness.png")
        _plot_lines(x, series, "Partition GA generation", "Best lateness", "Partition GA — Best lateness", out)
        saved["partition_best_lateness_png"] = out

    # Makespan
    series = {}
    x = None
    for p, H in histories_by_part.items():
        bm = H.get("makespan_evolution", [])
        if bm:
            series[p] = bm
            x = list(range(1, len(bm) + 1))
    if x:
        out = os.path.join(out_dir, f"{tag}__partition_best_makespan.png")
        _plot_lines(x, series, "Partition GA generation", "Best makespan", "Partition GA — Best makespan", out)
        saved["partition_best_makespan_png"] = out

    return saved

def plot_system_ga(sys_hist: Dict[str, Any], out_dir: str, tag: str) -> Dict[str, str]:
    _ensure_dir(out_dir)
    saved = {}
    gens = sys_hist.get("gen", [])
    if gens:
        # Global lateness
        out = os.path.join(out_dir, f"{tag}__system_global_lateness.png")
        _plot_lines(gens, {"global_lateness": sys_hist.get("global_lateness", [])},
                    "System GA generation", "Global lateness", "System GA — Global lateness", out)
        saved["system_global_lateness_png"] = out

        # Budgets per partition
        budgets = sys_hist.get("budgets", [])
        if budgets:
            parts = list(budgets[0].keys())
            series = {p: [b[p] for b in budgets] for p in parts}
            out = os.path.join(out_dir, f"{tag}__system_budgets.png")
            _plot_lines(gens, series, "System GA generation", "Budget", "System GA — Budgets per partition", out)
            saved["system_budgets_png"] = out

        # Makespans per partition
        makes = sys_hist.get("makespans", [])
        if makes:
            parts = list(makes[0].keys())
            series = {p: [m[p] for m in makes] for p in parts}
            out = os.path.join(out_dir, f"{tag}__system_makespans.png")
            _plot_lines(gens, series, "System GA generation", "Makespan", "System GA — Partition makespans", out)
            saved["system_makespans_png"] = out

    return saved

def save_and_plot_all(meta: Dict[str, Any], out_dir: str, timestamp: Optional[str] = None) -> Dict[str, str]:
    _ensure_dir(out_dir)
    artifacts = {}
    histories = meta.get("histories", {})
    artifacts["histories_json"] = save_histories_json(histories, out_dir, timestamp)

    P = histories.get("partition_ga_by_part", {})
    if isinstance(P, dict) and P:
        artifacts.update(plot_partition_ga(P, out_dir, tag=f"{timestamp or 'run'}"))
    S = histories.get("system_ga", {})
    if isinstance(S, dict) and S.get("gen"):
        artifacts.update(plot_system_ga(S, out_dir, tag=f"{timestamp or 'run'}"))
    return artifacts

def plot_system_time_budgets(meta, out_dir, timestamp="run"):
    """
    Creates one PNG in out_dir from meta['histories']['system_ga']['budgets']:
      - system_time_budgets_<timestamp>.png  (lines per partition vs. system generations)
    """
    import os
    import matplotlib.pyplot as plt

    Hsys = (meta or {}).get("histories", {}).get("system_ga", {})
    gens = Hsys.get("gen", [])
    budgets = Hsys.get("budgets", [])
    if not gens or not budgets:
        return {}

    parts = list(budgets[0].keys())
    os.makedirs(out_dir, exist_ok=True)

    fig = plt.figure(figsize=(10, 5))
    for p in parts:
        y = [b.get(p, None) for b in budgets]
        plt.plot(gens, y, marker="o", label=p)

    plt.title("System GA — Time budgets per partition")
    plt.xlabel("System GA generation")
    plt.ylabel("Time budget")
    plt.legend()
    out_path = os.path.join(out_dir, f"system_time_budgets_{timestamp}.png")
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return {"system_time_budgets_png": out_path}


# --- Simple system-level plots (PNG, no extra deps)
def plot_system_makespan_and_lateness(meta, out_dir, deadline, timestamp="run"):
    """
    Creates two PNGs in out_dir using meta['histories']['system_ga']:
      1) system_global_makespan_<timestamp>.png
      2) system_lateness_signed_<timestamp>.png  (makespan - deadline)
    """
    import os
    import matplotlib.pyplot as plt

    Hsys = (meta or {}).get("histories", {}).get("system_ga", {})
    gens = Hsys.get("gen", [])
    ms   = Hsys.get("global_makespan", [])
    if not gens or not ms:
        return {}

    os.makedirs(out_dir, exist_ok=True)
    arts = {}

    # 1) Global makespan with deadline
    fig = plt.figure(figsize=(10, 5))
    plt.plot(gens, ms, marker="o", label="Global makespan")
    plt.axhline(y=deadline, linestyle="--", label=f"Deadline = {deadline}")
    plt.title("System GA — Global makespan")
    plt.xlabel("System GA generation")
    plt.ylabel("Makespan")
    plt.legend()
    p1 = os.path.join(out_dir, f"system_global_makespan_{timestamp}.png")
    fig.savefig(p1, dpi=180, bbox_inches="tight")
    plt.close(fig)
    arts["system_global_makespan_png"] = p1

    # 2) Signed lateness = makespan - deadline
    lateness_raw = [int(m - deadline) for m in ms]
    fig = plt.figure(figsize=(10, 5))
    plt.plot(gens, lateness_raw, marker="o", label="lateness = makespan - deadline")
    plt.axhline(y=0, color="gray", linestyle="--")
    plt.title("System GA — Lateness (signed)")
    plt.xlabel("System GA generation")
    plt.ylabel("Lateness (ms - deadline)")
    plt.legend()
    p2 = os.path.join(out_dir, f"system_lateness_signed_{timestamp}.png")
    fig.savefig(p2, dpi=180, bbox_inches="tight")
    plt.close(fig)
    arts["system_lateness_signed_png"] = p2

    return arts


# def plot_system_budgets_and_makespans_all(meta, out_dir, timestamp="run"):
#     """
#     One PNG showing, for EACH partition, both its time budget (solid) and makespan (dashed)
#     over System-GA generations — all curves together in a single axes.

#     Expects in meta['histories']['system_ga']:
#       - gen:       [g1, g2, ...]
#       - budgets:   [ {P_FE:tb,...},  {..}, ... ]
#       - makespans: [ {P_FE:ms,...},  {..}, ... ]

#     Returns: {"system_budgets_and_makespans_all_png": "<path>"}
#     """
#     import os
#     import itertools
#     import matplotlib.pyplot as plt

#     Hsys = (meta or {}).get("histories", {}).get("system_ga", {})
#     gens = Hsys.get("gen", [])
#     budgets = Hsys.get("budgets", [])
#     makes   = Hsys.get("makespans", [])
#     if not gens or not budgets or not makes:
#         return {}

#     # Consistent partition order if present
#     parts = list(budgets[0].keys())
#     desired = ["P_FE", "P_C1", "P_C2", "P_C3"]
#     parts = [p for p in desired if p in parts] or parts

#     # Align lengths defensively
#     L = min(len(gens), len(budgets), len(makes))
#     x = gens[:L]

#     os.makedirs(out_dir, exist_ok=True)
#     fig = plt.figure(figsize=(12, 6))
#     ax = plt.gca()

#     # Assign one color per partition; solid = budget, dashed = makespan
#     colors = plt.rcParams.get("axes.prop_cycle", None)
#     palette = (colors.by_key().get("color", []) if colors else []) or \
#               ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd","#8c564b"]
#     color_cycle = itertools.cycle(palette)
#     color_map = {p: next(color_cycle) for p in parts}

#     for p in parts:
#         yb = [b.get(p, None) for b in budgets[:L]]
#         ym = [m.get(p, None) for m in makes[:L]]
#         c = color_map[p]
#         ax.plot(x, yb, linestyle="-", marker="o", label=f"{p} budget",   color=c)
#         ax.plot(x, ym, linestyle="--",          label=f"{p} makespan", color=c)

#     ax.set_title("System GA — Budgets (solid) and Makespans (dashed) for all partitions")
#     ax.set_xlabel("System GA generation")
#     ax.set_ylabel("Time")
#     ax.grid(True, alpha=0.3)
#     ax.legend(ncol=2, fontsize=9)

#     out_path = os.path.join(out_dir, f"system_budgets_and_makespans_all_{timestamp}.png")
#     fig.savefig(out_path, dpi=180, bbox_inches="tight")
#     plt.close(fig)
#     return {"system_budgets_and_makespans_all_png": out_path}


def plot_system_budgets_and_makespans_all(meta, out_dir, timestamp="run"):
    """
    One PNG with ALL partitions:
      - budget:  solid line with circle markers
      - makespan: dotted line
    Colors: P_FE=red, P_C1=green, P_C2=black, P_C3=blue
    Legend is placed outside the axes on the right.
    """
    import os
    import matplotlib.pyplot as plt

    Hsys = (meta or {}).get("histories", {}).get("system_ga", {})
    gens = Hsys.get("gen", [])
    budgets = Hsys.get("budgets", [])
    makes   = Hsys.get("makespans", [])
    if not gens or not budgets or not makes:
        return {}

    # Consistent partition order & fixed colors
    desired_order = ["P_FE", "P_C1", "P_C2", "P_C3"]
    parts = [p for p in desired_order if p in budgets[0]]
    color_map = {"P_FE": "red", "P_C1": "green", "P_C2": "black", "P_C3": "blue"}

    # Trim to common length just in case
    L = min(len(gens), len(budgets), len(makes))
    x = gens[:L]

    os.makedirs(out_dir, exist_ok=True)
    fig, ax = plt.subplots(figsize=(12, 6))

    for p in parts:
        c  = color_map.get(p, "gray")
        yb = [b.get(p, None) for b in budgets[:L]]
        ym = [m.get(p, None) for m in makes[:L]]

        # Budget: solid with markers
        ax.plot(
            x, yb, linestyle="-", marker="o", linewidth=2.0,
            markerfacecolor=c, markeredgecolor=c,
            color=c, label=f"{p} budget"
        )
        # Makespan: dotted, same color
        ax.plot(
            x, ym, linestyle=":", linewidth=2.0,
            color=c, label=f"{p} makespan"
        )

    ax.set_title("System GA — Budgets (solid) and Makespans (dotted) per partition")
    ax.set_xlabel("System GA generation")
    ax.set_ylabel("Time")
    ax.grid(True, alpha=0.3)

    # Legend outside on the right
    lg = ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False, ncol=1)
    # Make room for the outside legend
    plt.tight_layout(rect=[0.0, 0.0, 0.78, 1.0])

    out_path = os.path.join(out_dir, f"system_budgets_and_makespans_all_{timestamp}.png")
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return {"system_budgets_and_makespans_all_png": out_path}



############## Monitoring function for the partition GA ##############

def plot_partition_ga_evolution(history, title="Partition GA: evolution", out_path=None):
    """
    Plots fitness, makespan, and lateness across generations.
    Note: in your current GA, fitness == lateness (by design).
    """
    import matplotlib.pyplot as plt

    gens = list(range(1, int(history["generations"]) + 1))
    fvals = history["fitness_evolution"]
    mspn  = history["makespan_evolution"]
    late  = history["lateness_evolution"]

    # Basic sanity (handles any off-by-one logging mishaps)
    m = min(len(gens), len(fvals), len(mspn), len(late))
    gens, fvals, mspn, late = gens[:m], fvals[:m], mspn[:m], late[:m]

    plt.figure(figsize=(9, 5.5))
    plt.plot(gens, fvals, label="Fitness (lateness)", linewidth=2)
    plt.plot(gens, mspn,  label="Makespan", linewidth=2)
    plt.plot(gens, late,  label="Lateness", linewidth=2, linestyle="--")

    plt.xlabel("Generation")
    plt.ylabel("Value (time units)")
    plt.title(title)
    plt.grid(True, alpha=0.3)
    # Put legend outside so it never hides details
    plt.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), borderaxespad=0.)
    plt.tight_layout()

    if out_path:
        plt.savefig(out_path, dpi=200, bbox_inches="tight")
        plt.close()
    else:
        plt.show()


def save_partition_ga_history_csv(history, csv_path):
    import csv
    gens = list(range(1, int(history["generations"]) + 1))
    fvals = history["fitness_evolution"]
    mspn  = history["makespan_evolution"]
    late  = history["lateness_evolution"]
    m = min(len(gens), len(fvals), len(mspn), len(late))
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["generation", "fitness", "makespan", "lateness"])
        for i in range(m):
            w.writerow([gens[i], fvals[i], mspn[i], late[i]])




import os
import matplotlib.pyplot as plt

def _ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
    return path

def plot_makespan_vs_deadline(history, deadline, run_name="S_FE"):
    """
    Saves plot of makespan across generations + deadline line into
    PARTITION_PLOTS/<deadline>/makespan_<run_name>.png
    """
    gens  = list(range(1, int(history["generations"]) + 1))
    ms    = history["makespan_evolution"]
    m     = min(len(gens), len(ms))
    gens, ms = gens[:m], ms[:m]

    # Ensure folder exists
    folder = _ensure_dir(os.path.join("PARTITION_PLOTS", str(deadline)))
    out_path = os.path.join(folder, f"makespan_{run_name}.png")

    plt.figure(figsize=(9, 5.2))
    plt.plot(gens, ms, label="Makespan", linewidth=2)
    plt.hlines(deadline, gens[0], gens[-1], linestyles="--", label=f"Deadline={deadline}")
    plt.xlabel("Generation")
    plt.ylabel("Time (units)")
    plt.title(f"{run_name} • Makespan vs. Deadline")
    plt.grid(True, alpha=0.3)
    plt.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), borderaxespad=0.)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"[SAVED] {out_path}")


def plot_lateness_vs_generations(history, deadline, run_name="S_FE"):
    """
    Saves plot of lateness across generations into
    PARTITION_PLOTS/<deadline>/lateness_<run_name>.png
    """
    gens  = list(range(1, int(history["generations"]) + 1))
    late  = history["lateness_evolution"]
    m     = min(len(gens), len(late))
    gens, late = gens[:m], late[:m]

    # Ensure folder exists
    folder = _ensure_dir(os.path.join("PARTITION_PLOTS", str(deadline)))
    out_path = os.path.join(folder, f"lateness_{run_name}.png")

    plt.figure(figsize=(9, 5.2))
    plt.plot(gens, late, label="Lateness", linewidth=2)
    plt.xlabel("Generation")
    plt.ylabel("Time (units)")
    plt.title(f"{run_name} • Lateness vs. Generations")
    plt.grid(True, alpha=0.3)
    plt.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), borderaxespad=0.)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"[SAVED] {out_path}")


def _save_system_ga_plots(log_dir: str, sys_history: dict) -> None:
    """Save (1) per-partition violations across gens, (2) fitness evolution."""
    import os
    os.makedirs(log_dir, exist_ok=True)

    # Use non-interactive backend for headless runs
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    gens = sys_history.get("gen", [])
    if not gens:
        return

    # ------------------------------
    # Plot 1: Per-partition violations over generations
    # ------------------------------
    viol_list = sys_history.get("violations", [])  # list[dict{part: value}]
    if viol_list:
        parts = sorted(viol_list[0].keys())
        series = {p: [viol_list[i].get(p, 0) for i in range(len(gens))] for p in parts}

        # Distinct, fixed colors (as you like them)
        color_map = {"P_FE": "red", "P_C1": "green", "P_C2": "black", "P_C3": "blue"}
        default_colors = ["tab:red", "tab:green", "k", "tab:blue"]

        fig1, ax1 = plt.subplots(figsize=(8, 4.5), dpi=300)
        for idx, p in enumerate(parts):
            c = color_map.get(p, default_colors[idx % len(default_colors)])
            ax1.plot(gens, series[p], label=p, linewidth=2, linestyle="-", color=c)
        ax1.set_xlabel("Generation")
        ax1.set_ylabel("Violation (time units)")
        ax1.set_title("Per-Partition Violation vs. Generations")
        ax1.grid(True, alpha=0.3)
        # legend outside to avoid hiding details
        ax1.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), borderaxespad=0.0)
        fig1.tight_layout(rect=[0, 0, 0.82, 1])  # leave space for legend
        path1 = os.path.join(log_dir, "violations_per_partition_over_generations.png")
        fig1.savefig(path1)
        plt.close(fig1)

    # ------------------------------
    # Plot 2: Fitness evolution (best individual each generation)
    # ------------------------------
    best_fits = sys_history.get("best_fitness", [])
    if best_fits:
        # Convert tuples to columns
        k = len(best_fits[0])
        cols = list(zip(*best_fits))  # k series
        # Label by dimensionality
        if k == 3:
            labels = ["Max violation", "Sum violation", "Lateness"]
        elif k == 2:
            labels = ["Sum violation", "Lateness"]
        else:
            labels = [f"Obj{i+1}" for i in range(k)]

        fig2, ax2 = plt.subplots(figsize=(8, 4.5), dpi=300)
        for i in range(k):
            ax2.plot(gens, cols[i], linewidth=2, label=labels[i])
        ax2.set_xlabel("Generation")
        ax2.set_ylabel("Fitness value")
        ax2.set_title("Fitness Evolution (Best per Generation)")
        ax2.grid(True, alpha=0.3)
        ax2.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), borderaxespad=0.0)
        fig2.tight_layout(rect=[0, 0, 0.82, 1])
        path2 = os.path.join(log_dir, "fitness_evolution_over_generations.png")
        fig2.savefig(path2)
        plt.close(fig2)

def plot_system_violations_and_fitness(meta, out_dir, timestamp="run"):
    """
    Renders two PNGs into out_dir using meta['histories']['system_ga']:
      - violations_per_partition_over_generations.png
      - fitness_evolution_over_generations.png

    This is a thin public wrapper around the existing _save_system_ga_plots.
    Returns a dict with the saved file paths.
    """
    import os
    Hsys = (meta or {}).get("histories", {}).get("system_ga", {})
    if not isinstance(Hsys, dict) or not Hsys.get("gen"):
        return {}

    # Reuse the existing painter (keeps styling consistent with your other figures)
    _save_system_ga_plots(out_dir, Hsys)

    # Return paths (stable names used inside _save_system_ga_plots)
    return {
        "violations_png": os.path.join(out_dir, "violations_per_partition_over_generations.png"),
        "fitness_evolution_png": os.path.join(out_dir, "fitness_evolution_over_generations.png"),
    }

def plot_fitness_evolution(
    meta,
    out_dir,
    use_signed=True,
    deadline=None,
    scalar_weights=(1.0, 1.0),
    scalar_use_clipped=True,
    timestamp="run",
):
    """
    Plot three curves over generations:
      - Total violation (sum over partitions)  -> from sys_history['fitness_vsum']
      - Lateness (signed if available/desired) -> from sys_history[...] or derived
      - Scalar fitness = w1*violation + w2*lateness_clipped

    Params
    ------
    use_signed : bool
        If True, plot signed lateness when available; else clipped.
    deadline : int or None
        Used only if signed series is missing and we need to derive signed lateness
        from global_makespan - deadline.
    scalar_weights : (float, float)
        (w1, w2) used for scalar fitness combining violation and lateness_clipped.
        Typically you want positive weights here; if your DEAP fitness weights are
        negative (for minimization), pass their absolute values from main.py.
    scalar_use_clipped : bool
        Always recommended True so the scalar mirrors the GA objective (non-negative lateness).
    """
    import os
    import matplotlib.pyplot as plt

    H = (meta or {}).get("histories", {}).get("system_ga", {})
    gens = H.get("gen", [])
    if not gens:
        return {}

    # 1) total violation (already summed per generation)
    viol = H.get("fitness_vsum", [])

    # 2) lateness series (pick signed if requested/available)
    if use_signed and "global_lateness_signed" in H:
        lat = H["global_lateness_signed"]
        lat_label = "Lateness (signed)"
        suffix_lat = "signed"
    elif "global_lateness" in H:
        lat = H["global_lateness"]
        lat_label = "Lateness (clipped)"
        suffix_lat = "clipped"
    elif deadline is not None and "global_makespan" in H:
        lat = [int(gm) - int(deadline) for gm in H["global_makespan"]]
        lat_label = "Lateness (signed, derived)"
        suffix_lat = "signed"
    else:
        lat = []
        lat_label = "Lateness"
        suffix_lat = "lateness"

    # 3) scalar fitness: w1 * violation + w2 * lateness_clipped
    #    (use clipped lateness here so it matches the GA's objective definition)
    if scalar_use_clipped:
        if "global_lateness" in H:
            lat_for_scalar = H["global_lateness"]
        else:
            # derive clipped if we only have signed + deadline
            if "global_lateness_signed" in H:
                lat_for_scalar = [max(0, int(x)) for x in H["global_lateness_signed"]]
            elif deadline is not None and "global_makespan" in H:
                lat_for_scalar = [max(0, int(gm) - int(deadline)) for gm in H["global_makespan"]]
            else:
                lat_for_scalar = []
    else:
        # (rare) allow scalar to use the same lateness series as plotted (may be signed)
        lat_for_scalar = lat

    # Align lengths defensively
    n = min(len(gens), len(viol), len(lat_for_scalar), len(lat) if lat else len(gens))
    gens = gens[:n]
    viol = viol[:n]
    lat = lat[:n] if lat else [0] * n
    lat_for_scalar = lat_for_scalar[:n]

    w1, w2 = scalar_weights
    scalar = [w1 * float(viol[i]) + w2 * float(lat_for_scalar[i]) for i in range(n)]

    # --- Plot
    plt.figure()
    plt.plot(gens, viol, label="Total violation")
    plt.plot(gens, lat, label=lat_label)
    plt.plot(gens, scalar, label=f"Scalar (w1·viol + w2·late_clipped) = {w1}·V + {w2}·L")
    plt.xlabel("Generation")
    plt.ylabel("Time units")
    ttl = "Fitness Evolution: Violation, Lateness, Scalar"
    plt.title(ttl)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()

    fname = f"fitness_evolution_with_scalar_{suffix_lat}_{timestamp}.png"
    path = os.path.join(out_dir, fname)
    try:
        plt.savefig(path)
    finally:
        plt.close()

    return {"fitness_evolution_with_scalar_png": path}
