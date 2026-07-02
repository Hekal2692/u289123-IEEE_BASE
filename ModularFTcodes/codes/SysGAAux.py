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
from typing import Dict, Optional
import math, statistics as stats



"""
Extracts path IDs from the merged_paths_w_costs dictionary where the path includes
any of the routers: RID1, RID2, RID3, RID4, RID5, RID6.

Parameters:
    merged_paths_w_costs (dict): Dictionary of paths with their costs from compute_paths_cloud_costs().
    
Returns:
    list: A list of merged path IDs (keys) where the path includes one of the RID routers.
"""
def get_paths_with_rid_routers(merged_paths_w_costs):

    rid_routers = {"RID1", "RID2", "RID3", "RID4", "RID5", "RID6"}
    matching_ids = [
        path_id
        for path_id, data in merged_paths_w_costs.items()
        if any(node in rid_routers for node in data['path'])
    ]
    return matching_ids
####################################################################################################
"""
Extract message IDs that are defined in message_list but not used in any of the provided schedules.

Parameters:
    schedules (list of dict): List containing multiple schedules in the format {task_id: (processor_id, start_time, end_time, messages)}
    message_list (list of dict): List of messages with keys 'id', 'sender', 'receiver', 'size'

Returns:
    List[int]: Message IDs not present in any schedule
"""
def get_unused_message_ids(schedules, message_list):
    # Collect all used message IDs from all schedules
    used_message_ids = set()
    for schedule in schedules:
        for task_data in schedule.values():
            if len(task_data) >= 4:
                messages = task_data[3]
                for msg in messages:
                    if isinstance(msg, tuple) and len(msg) == 3:
                        used_message_ids.add(msg[2])

    # All defined message IDs
    all_message_ids = {msg["id"] for msg in message_list}

    # Return the ones not used
    unused_message_ids = sorted(list(all_message_ids - used_message_ids))
    return unused_message_ids
#####################################################################################################


# --- SysGAAux.py -------------------------------------------------------------


def _std_last_k(xs, k=10) -> float:
    if not xs:
        return 0.0
    tail = xs[-k:] if len(xs) > k else xs
    if len(tail) < 2:
        return 0.0
    try:
        return float(stats.pstdev(tail))
    except Exception:
        return 0.0

# def adjust_time_budgets_v2(
#     makespans: Dict[str, float],
#     prev_budgets: Dict[str, float],
#     partition_histories: Optional[Dict[str, dict]] = None,
#     # global coupling (optional, for gentle pressure tuning)
#     app_deadline: Optional[float] = None,
#     global_makespan: Optional[float] = None,
#     # margin & donation policy
#     min_margin_ratio: float = 0.03,   # ≥2% of MS as base cushion
#     k_sigma: float = 1.0,             # + 1σ of recent MS variability
#     donor_frac: float = 0.9,          # donors give up to 50% of surplus beyond margin
#     eta: float = 1.0,                  # use of the pooled bank (1.0 = full)
#     # stability & smoothing
#     cap_up: float = 0.35,             # ≤10% TB increase per gen
#     cap_down: float = 0.25,           # ≤10% TB decrease per gen
#     deadband_ratio: float = 0.02,     # ±2% MS dead-band ⇒ no changes
#     alpha_donor: float = 0.6,         # donors update slower (smoothing)
#     alpha_receiver: float = 0.4,      # receivers update faster
#     lateness_pressure_gain: float = 0.2,  # how strongly lateness boosts donor_frac
# ) -> Dict[str, int]:
#     """
#     Rebalances time budgets (TB) by moving slack from *donors* (surplus beyond
#     their target margin) to *receivers* (deficits vs target margin). Budgets
#     do NOT need to sum to the deadline; they are soft pressure targets.

#     Target margin per partition i:
#         m_i = max(min_margin_ratio * MS_i, k_sigma * std(last_K MS_i))
#     Surplus (donor):   s_i = max(0, (TB_i - MS_i) - m_i)
#     Deficit (receiver):d_i = max(0, m_i - (TB_i - MS_i))

#     Donor pool S = donor_frac_eff * sum_i s_i,
#     where donor_frac_eff grows mildly if the global schedule is late.

#     The pooled S is water-filled to receivers proportional to their deficit.
#     Per-generation change is capped and smoothed to avoid oscillations.
#     """
#     parts = list(makespans.keys())
#     TB0 = {p: float(prev_budgets[p]) for p in parts}
#     MS = {p: float(makespans[p]) for p in parts}

#     # 1) Per-partition target margin m_i (data-driven)
#     margins = {}
#     for p in parts:
#         ms_series = None
#         if partition_histories and partition_histories.get(p):
#             ms_series = partition_histories[p].get("makespan_evolution")
#         sigma = _std_last_k(ms_series or [], k=10)
#         base = min_margin_ratio * MS[p]
#         margins[p] = max(base, k_sigma * sigma)

#     # 2) Errors vs margin: donors & receivers
#     surplus, deficit = {}, {}
#     need_sum = 0.0
#     for p in parts:
#         e = TB0[p] - MS[p]             # actual slack vs MS
#         m = margins[p]                 # desired margin
#         s = max(0.0, e - m)            # surplus beyond desired margin
#         d = max(0.0, m - e)            # deficit to reach desired margin
#         surplus[p] = s
#         deficit[p] = d
#         need_sum += d

#     # 3) Build the donor pool (with lateness-aware boost)
#     donor_frac_eff = donor_frac
#     if (app_deadline is not None) and (global_makespan is not None):
#         L = max(0.0, float(global_makespan) - float(app_deadline))
#         if app_deadline > 0 and L > 0:
#             donor_frac_eff = min(1.0, donor_frac * (1.0 + lateness_pressure_gain * (L / app_deadline)))

#     pool = donor_frac_eff * sum(surplus.values())
#     pool *= eta
#     # if no demand or no pool, changes remain zero
#     if pool <= 1e-9 or need_sum <= 1e-9:
#         # still apply small stabilizing nudges (dead-band + capping) by pulling donors toward margin
#         updated = {}
#         for p in parts:
#             e = TB0[p] - MS[p]
#             m = margins[p]
#             # within dead-band → no change
#             if abs(e - m) <= deadband_ratio * MS[p]:
#                 updated[p] = int(round(TB0[p]))
#                 continue
#             # otherwise, nudge toward margin
#             delta = 0.0
#             if e > m:   # donor → decrease
#                 to_reduce = e - m
#                 cap = cap_down * max(1.0, TB0[p])
#                 delta = -min(to_reduce, cap)
#                 alpha = alpha_donor
#             else:       # receiver → increase
#                 to_increase = (m - e)
#                 cap = cap_up * max(1.0, TB0[p])
#                 delta = +min(to_increase, cap)
#                 alpha = alpha_receiver
#             TB1 = TB0[p] + (1.0 - alpha) * delta
#             updated[p] = int(round(TB1))
#         return updated

#     # 4) Allocate the pool to receivers proportional to their need
#     updated: Dict[str, int] = {}
#     for p in parts:
#         e = TB0[p] - MS[p]
#         m = margins[p]
#         # default: no change
#         delta = 0.0

#         # dead-band (don’t churn around target)
#         if abs(e - m) <= deadband_ratio * MS[p]:
#             updated[p] = int(round(TB0[p]))
#             continue

#         if deficit[p] > 0:  # receiver: gets a share of the pool
#             share = pool * (deficit[p] / need_sum)
#             cap = cap_up * max(1.0, TB0[p])
#             delta = +min(share, cap)
#             alpha = alpha_receiver
#         elif surplus[p] > 0:  # donor: gives away (local contraction)
#             give = donor_frac_eff * surplus[p]
#             cap = cap_down * max(1.0, TB0[p])
#             delta = -min(give, cap)
#             alpha = alpha_donor
#         else:
#             alpha = 0.5  # neutral

#         TB1 = TB0[p] + (1.0 - alpha) * delta
#         updated[p] = int(round(TB1))

#     return updated
# # ---------------------------------------------------------------------------

import logging  # add this near the top of the module

# def adjust_time_budgets_v2(
#     makespans: Dict[str, float],
#     prev_budgets: Dict[str, float],
#     partition_histories: Optional[Dict[str, dict]] = None,
#     # global coupling (optional, for gentle pressure tuning)
#     app_deadline: Optional[float] = None,
#     global_makespan: Optional[float] = None,
#     # margin & donation policy
#     min_margin_ratio: float = 0.03,   # ≥2% of MS as base cushion
#     k_sigma: float = 1.0,             # + 1σ of recent MS variability
#     donor_frac: float = 0.9,          # donors give up to 50% of surplus beyond margin
#     eta: float = 1.0,                 # use of the pooled bank (1.0 = full)
#     # stability & smoothing
#     cap_up: float = 0.35,             # ≤10% TB increase per gen
#     cap_down: float = 0.25,           # ≤10% TB decrease per gen
#     deadband_ratio: float = 0.02,     # ±2% MS dead-band ⇒ no changes
#     alpha_donor: float = 0.6,         # donors update slower (smoothing)
#     alpha_receiver: float = 0.4,      # receivers update faster
#     lateness_pressure_gain: float = 0.2,  # how strongly lateness boosts donor_frac
#     *,
#     logger: Optional[logging.Logger] = None,  # NEW: optional logger
# ) -> Dict[str, int]:
#     """
#     Rebalances time budgets (TB) by moving slack from *donors* (surplus beyond
#     their target margin) to *receivers* (deficits vs target margin). Budgets
#     do NOT need to sum to the deadline; they are soft pressure targets.

#     Target margin per partition i:
#         m_i = max(min_margin_ratio * MS_i, k_sigma * std(last_K MS_i))
#     Surplus (donor):   s_i = max(0, (TB_i - MS_i) - m_i)
#     Deficit (receiver):d_i = max(0, m_i - (TB_i - MS_i))

#     Donor pool S = donor_frac_eff * sum_i s_i,
#     where donor_frac_eff grows mildly if the global schedule is late.

#     The pooled S is water-filled to receivers proportional to their deficit.
#     Per-generation change is capped and smoothed to avoid oscillations.
#     """
#     # --- log hyperparameters ONCE only ---
#     log = logger or logging.getLogger(__name__)
#     if not getattr(adjust_time_budgets_v2, "_logged_once", False):
#         log.info(
#             "[TBCTL] hyperparams: "
#             "min_margin_ratio=%.3f k_sigma=%.2f donor_frac=%.2f eta=%.2f "
#             "cap_up=%.2f cap_down=%.2f deadband_ratio=%.2f "
#             "alpha_donor=%.2f alpha_receiver=%.2f lateness_pressure_gain=%.2f",
#             min_margin_ratio, k_sigma, donor_frac, eta,
#             cap_up, cap_down, deadband_ratio,
#             alpha_donor, alpha_receiver, lateness_pressure_gain,
#         )
#         adjust_time_budgets_v2._logged_once = True
#     # -------------------------------------------------------

#     parts = list(makespans.keys())
#     TB0 = {p: float(prev_budgets[p]) for p in parts}
#     MS = {p: float(makespans[p]) for p in parts}

#     # 1) Per-partition target margin m_i (data-driven)
#     margins = {}
#     for p in parts:
#         ms_series = None
#         if partition_histories and partition_histories.get(p):
#             ms_series = partition_histories[p].get("makespan_evolution")
#         sigma = _std_last_k(ms_series or [], k=10)
#         base = min_margin_ratio * MS[p]
#         margins[p] = max(base, k_sigma * sigma)

#     # 2) Errors vs margin: donors & receivers
#     surplus, deficit = {}, {}
#     need_sum = 0.0
#     for p in parts:
#         e = TB0[p] - MS[p]             # actual slack vs MS
#         m = margins[p]                 # desired margin
#         s = max(0.0, e - m)            # surplus beyond desired margin
#         d = max(0.0, m - e)            # deficit to reach desired margin
#         surplus[p] = s
#         deficit[p] = d
#         need_sum += d

#     # 3) Build the donor pool (with lateness-aware boost)
#     donor_frac_eff = donor_frac
#     if (app_deadline is not None) and (global_makespan is not None):
#         L = max(0.0, float(global_makespan) - float(app_deadline))
#         if app_deadline > 0 and L > 0:
#             donor_frac_eff = min(1.0, donor_frac * (1.0 + lateness_pressure_gain * (L / app_deadline)))

#     pool = donor_frac_eff * sum(surplus.values())
#     pool *= eta
#     # if no demand or no pool, changes remain zero
#     if pool <= 1e-9 or need_sum <= 1e-9:
#         # still apply small stabilizing nudges (dead-band + capping) by pulling donors toward margin
#         updated = {}
#         for p in parts:
#             e = TB0[p] - MS[p]
#             m = margins[p]
#             # within dead-band → no change
#             if abs(e - m) <= deadband_ratio * MS[p]:
#                 updated[p] = int(round(TB0[p]))
#                 continue
#             # otherwise, nudge toward margin
#             delta = 0.0
#             if e > m:   # donor → decrease
#                 to_reduce = e - m
#                 cap = cap_down * max(1.0, TB0[p])
#                 delta = -min(to_reduce, cap)
#                 alpha = alpha_donor
#             else:       # receiver → increase
#                 to_increase = (m - e)
#                 cap = cap_up * max(1.0, TB0[p])
#                 delta = +min(to_increase, cap)
#                 alpha = alpha_receiver
#             TB1 = TB0[p] + (1.0 - alpha) * delta
#             updated[p] = int(round(TB1))
#         return updated

#     # 4) Allocate the pool to receivers proportional to their need
#     updated: Dict[str, int] = {}
#     for p in parts:
#         e = TB0[p] - MS[p]
#         m = margins[p]
#         # default: no change
#         delta = 0.0

#         # dead-band (don’t churn around target)
#         if abs(e - m) <= deadband_ratio * MS[p]:
#             updated[p] = int(round(TB0[p]))
#             continue

#         if deficit[p] > 0:  # receiver: gets a share of the pool
#             share = pool * (deficit[p] / need_sum)
#             cap = cap_up * max(1.0, TB0[p])
#             delta = +min(share, cap)
#             alpha = alpha_receiver
#         elif surplus[p] > 0:  # donor: gives away (local contraction)
#             give = donor_frac_eff * surplus[p]
#             cap = cap_down * max(1.0, TB0[p])
#             delta = -min(give, cap)
#             alpha = alpha_donor
#         else:
#             alpha = 0.5  # neutral

#         TB1 = TB0[p] + (1.0 - alpha) * delta
#         updated[p] = int(round(TB1))

#     return updated
# # ---------------------------------------------------------------------------


# Commented on 01.09.2025 , There is an overshoot as the deadline gets tighter

# def adjust_time_budgets_v2(
#     makespans: dict,
#     prev_budgets: dict,
#     partition_histories: dict | None = None,
#     app_deadline: float | None = None,
#     global_makespan: float | None = None,
#     # margin & donation policy
#     min_margin_ratio: float = 0.02,
#     k_sigma: float = 1.0,
#     donor_frac: float = 0.9,
#     eta: float = 1.0,
#     # stability & smoothing
#     cap_up: float = 0.35,
#     cap_down: float = 0.25,
#     deadband_ratio: float = 0.02,
#     alpha_donor: float = 0.70,
#     alpha_receiver: float = 0.30,
#     lateness_pressure_gain: float = 0.20,
#     # --- NEW automatic severity knobs (no manual weights) ---
#     severity_beta: float = 1.3,     # >=1: super-linear emphasis on big violators
#     margin_weight: float = 0.5,     # 0..1: include margin deficit in urgency
#     min_receiver_quota: float = 0.05,  # 0..1: % of pool split equally before severity
# ):
#     """
#     Reallocate TBs with explicit, automatic violation-driven feedback.

#     Severity_i = ( violation_i + margin_weight * deficit_to_margin_i ) ** severity_beta
#     Receivers get pool in proportion to Severity_i. Donors are limited by caps and smoothing.
#     """
#     from statistics import pstdev

#     parts = list(makespans.keys())
#     eps = 1e-9

#     # Global lateness → boost effective donor fraction slightly
#     late_ratio = 0.0
#     if app_deadline and global_makespan and global_makespan > app_deadline:
#         late_ratio = (global_makespan - app_deadline) / max(app_deadline, 1.0)
#     donor_frac_eff = min(1.0, donor_frac * (1.0 + lateness_pressure_gain * late_ratio))

#     # recent sigma for margins
#     def recent_sigma(p, K=5):
#         hist = (partition_histories or {}).get(p, {})
#         seq = (hist.get("makespan_evolution") or hist.get("ms_evolution") or [])[-K:]
#         return float(pstdev(seq)) if len(seq) >= 2 else 0.0

#     # Signals
#     margin, viol, deficit, slack, deadband_abs = {}, {}, {}, {}, {}
#     for p in parts:
#         ms = float(makespans[p]); tb = float(prev_budgets[p])
#         sigma = recent_sigma(p)
#         margin[p] = min_margin_ratio * ms + k_sigma * sigma
#         deadband_abs[p] = deadband_ratio * ms
#         viol[p] = max(0.0, ms - tb)
#         deficit[p] = max(0.0, (ms + margin[p]) - tb)
#         slack[p] = tb - (ms + margin[p])  # >0 => donor-ish

#     donors = [p for p in parts if slack[p] >  deadband_abs[p]]
#     recvs  = [p for p in parts if slack[p] < -deadband_abs[p]]
#     if not donors and not recvs:
#         return {p: float(prev_budgets[p]) for p in parts}

#     # Donor pool (after caps per donor)
#     donor_cap_unit = {}
#     for d in donors:
#         tb = float(prev_budgets[d])
#         surplus = max(0.0, slack[d])    # above (MS + margin)
#         give_potential = donor_frac_eff * surplus
#         cap_abs = cap_down * tb
#         donor_cap_unit[d] = max(0.0, min(give_potential, cap_abs))
#     total_donor_cap = sum(donor_cap_unit.values())
#     if total_donor_cap <= eps or not recvs:
#         return {p: float(prev_budgets[p]) for p in parts}

#     # --- Automatic severity (no weights to set) ---
#     # Use violation + a portion of the margin deficit (urgency), raised to beta
#     severity_raw = {r: (viol[r] + margin_weight * deficit[r]) for r in recvs}
#     # If everyone is near-zero, they’ll share the base quota equally
#     severity = {r: (max(severity_raw[r], 0.0) + eps) ** max(1.0, severity_beta) for r in recvs}
#     S = sum(severity.values())

#     # Split pool: small equal floor, remainder by severity
#     min_quota_total = max(0.0, min_receiver_quota) * total_donor_cap
#     base_q = (min_quota_total / len(recvs)) if recvs else 0.0
#     rem_pool = max(0.0, total_donor_cap - base_q * len(recvs))

#     desired_inc = {r: base_q for r in recvs}
#     if S > eps:
#         for r in recvs:
#             desired_inc[r] += rem_pool * (severity[r] / S)
#     else:
#         # fallback equal split
#         equal_add = rem_pool / len(recvs)
#         for r in recvs:
#             desired_inc[r] += equal_add

#     # Apply per-receiver cap_up and smoothing
#     inc = {}
#     for r in recvs:
#         tb = float(prev_budgets[r])
#         inc[r] = alpha_receiver * min(desired_inc[r], cap_up * tb)
#     inc_total = sum(inc.values())

#     # Match donors after smoothing (alpha_donor); scale receivers if needed
#     donor_total_after_alpha = alpha_donor * total_donor_cap
#     if donor_total_after_alpha + eps < inc_total:
#         scale = donor_total_after_alpha / max(inc_total, eps)
#         for r in recvs:
#             inc[r] *= scale
#         inc_total = donor_total_after_alpha

#     # Donor gives proportional to their capped potentials
#     denom = sum(donor_cap_unit.values()) or 1.0
#     give = {}
#     for d in donors:
#         share = donor_cap_unit[d] / denom
#         give_before_alpha = inc_total * share
#         give[d] = alpha_donor * min(give_before_alpha, donor_cap_unit[d])

#     # New budgets
#     new_tb = {p: float(prev_budgets[p]) for p in parts}
#     for r in recvs:
#         new_tb[r] = max(0.0, new_tb[r] + inc[r])
#     for d in donors:
#         new_tb[d] = max(0.0, new_tb[d] - give[d])

#     return new_tb

# Violations didn't converge to zero as there was a bug in the logic the code, it was regarding defining when to identify a partition as a donor and whe to identify it as a receiver.
# The logic has been fixed in the below code. 03.09.2025
# def adjust_time_budgets_v2(
#     makespans, prev_budgets, partition_histories=None,
#     app_deadline=None, global_makespan=None,
#     min_margin_ratio=0.02, k_sigma=1.0, donor_frac=0.9, eta=1.0,
#     cap_up=0.35, cap_down=0.25, deadband_ratio=0.02,
#     alpha_donor=0.70, alpha_receiver=0.30, lateness_pressure_gain=0.20,
#     severity_beta=1.3, margin_weight=0.5, min_receiver_quota=0.05,
# ):
#     from statistics import pstdev

#     parts = list(makespans.keys())
#     eps = 1e-9

#     late_ratio = 0.0
#     if app_deadline and global_makespan and global_makespan > app_deadline:
#         late_ratio = (global_makespan - app_deadline) / max(app_deadline, 1.0)
#     donor_frac_eff = min(1.0, donor_frac * (1.0 + lateness_pressure_gain * late_ratio))

#     def recent_sigma(p, K=5):
#         hist = (partition_histories or {}).get(p, {})
#         seq = (hist.get("makespan_evolution") or hist.get("ms_evolution") or [])[-K:]
#         return float(pstdev(seq)) if len(seq) >= 2 else 0.0

#     margin, viol, deficit, slack, deadband_abs, target = {}, {}, {}, {}, {}, {}
#     for p in parts:
#         ms = float(makespans[p]); tb = float(prev_budgets[p])
#         sigma = recent_sigma(p)
#         m = min_margin_ratio * ms + k_sigma * sigma
#         margin[p] = m
#         target[p] = ms + m                           # FIX: explicit target
#         deadband_abs[p] = deadband_ratio * ms
#         viol[p] = max(0.0, ms - tb)
#         deficit[p] = max(0.0, target[p] - tb)
#         slack[p] = tb - target[p]                    # >0 => donor-ish

#     donors = [p for p in parts if slack[p] >  deadband_abs[p]]
#     recvs  = [p for p in parts if slack[p] < -deadband_abs[p]]

#     # --- FIX B: if no receivers, decay donors toward their target (anti-hang) ---
#     if donors and not recvs:
#         new_tb = {p: float(prev_budgets[p]) for p in parts}
#         for d in donors:
#             tb = float(prev_budgets[d])
#             # reduce by a smoothed, capped amount but never below target - deadband
#             reduce = min(slack[d], cap_down * tb)
#             new_tb[d] = max(target[d] - deadband_abs[d], tb - alpha_donor * reduce)
#         return new_tb

#     # If nobody can give or there’s nobody to receive, keep as is.
#     if not donors or not recvs:
#         return {p: float(prev_budgets[p]) for p in parts}

#     # Donor pool (after caps per donor)
#     donor_cap_unit = {}
#     for d in donors:
#         tb = float(prev_budgets[d])
#         surplus = max(0.0, slack[d])
#         give_potential = donor_frac_eff * surplus
#         cap_abs = cap_down * tb
#         donor_cap_unit[d] = max(0.0, min(give_potential, cap_abs))
#     total_donor_cap = sum(donor_cap_unit.values())
#     if total_donor_cap <= eps:
#         return {p: float(prev_budgets[p]) for p in parts}

#     # Severity weighting
#     severity_raw = {r: (viol[r] + margin_weight * deficit[r]) for r in recvs}
#     severity = {r: (max(severity_raw[r], 0.0) + eps) ** max(1.0, severity_beta) for r in recvs}
#     S = sum(severity.values())

#     min_quota_total = max(0.0, min_receiver_quota) * total_donor_cap
#     base_q = (min_quota_total / len(recvs)) if recvs else 0.0
#     rem_pool = max(0.0, total_donor_cap - base_q * len(recvs))

#     desired_inc = {r: base_q for r in recvs}
#     if S > eps:
#         for r in recvs:
#             desired_inc[r] += rem_pool * (severity[r] / S)
#     else:
#         equal_add = rem_pool / len(recvs)
#         for r in recvs:
#             desired_inc[r] += equal_add

#     # --- FIX A: anti-windup: never request more than the deficit to the target ---
#     inc = {}
#     for r in recvs:
#         tb = float(prev_budgets[r])
#         want = min(desired_inc[r], cap_up * tb, deficit[r])  # clip to deficit
#         inc[r] = alpha_receiver * want

#     inc_total = sum(inc.values())

#     # Match donors after smoothing
#     donor_total_after_alpha = alpha_donor * total_donor_cap
#     if donor_total_after_alpha + eps < inc_total:
#         scale = donor_total_after_alpha / max(inc_total, eps)
#         for r in recvs:
#             inc[r] *= scale
#         inc_total = donor_total_after_alpha

#     denom = sum(donor_cap_unit.values()) or 1.0
#     give = {}
#     for d in donors:
#         share = donor_cap_unit[d] / denom
#         give_before_alpha = inc_total * share
#         give[d] = alpha_donor * min(give_before_alpha, donor_cap_unit[d])

#     new_tb = {p: float(prev_budgets[p]) for p in parts}
#     for r in recvs:
#         # FINAL CLAMP: don’t cross target + deadband
#         new_tb[r] = min(target[r] + deadband_abs[r], new_tb[r] + inc[r])
#     for d in donors:
#         # FINAL CLAMP: don’t drop below target - deadband
#         new_tb[d] = max(target[d] - deadband_abs[d], new_tb[d] - give[d])

#     return new_tb


###############################################################################################################################
# SysGAAux.py
# SysGAAux.py
def adaptive_timebudget_knobs(global_ms, deadline, makespans, prev_budgets, base):
    # lateness ratio (0 if on-time)
    L = 0.0
    if deadline and global_ms and global_ms > deadline:
        L = max(0.0, (global_ms - deadline) / max(float(deadline), 1.0))

    # simple density of violations vs TB_prev (same metric your GA optimizes)
    Vsum = sum(max(0.0, float(makespans[p]) - float(prev_budgets[p])) for p in makespans)
    TBsum = sum(float(prev_budgets[p]) for p in prev_budgets) or 1.0
    dens = Vsum / TBsum

    k = dict(base)  # copy

    # keep deadband modest (≤ margin) to avoid donor starvation
    k['deadband_ratio'] = min(k.get('deadband_ratio', 0.02),
                              0.5 * k.get('min_margin_ratio', 0.02))

    # let lateness & density increase throughput a bit (safe nudges)
    k['donor_frac']      = min(1.0, max(k.get('donor_frac', 0.9), 0.95 + 0.05*L))
    k['alpha_donor']     = min(1.00, max(k.get('alpha_donor', 0.9), 0.90 + 0.05*L))
    k['alpha_receiver']  = min(0.45, max(k.get('alpha_receiver', 0.35), 0.35 + 0.10*dens))
    k['cap_up']          = min(0.40, max(k.get('cap_up', 0.30), 0.30 + 0.10*dens))
    if k['alpha_receiver'] * k['cap_up'] > 0.15:
        k['cap_up'] = 0.15 / max(k['alpha_receiver'], 1e-9)

    k['min_receiver_quota'] = min(0.30, max(k.get('min_receiver_quota', 0.20), 0.20 + 0.15*L))
    # keep these unchanged unless you want global throttling:
    # k['eta'], k['lateness_pressure_gain'], k['severity_beta'], k['margin_weight'], k['k_sigma'], etc.
    return k


def adjust_time_budgets_v2(
    makespans, prev_budgets, partition_histories=None,
    app_deadline=None, global_makespan=None,
    min_margin_ratio=0.02, k_sigma=1.0, donor_frac=0.9, eta=1.0,
    cap_up=0.35, cap_down=0.25, deadband_ratio=0.02,
    alpha_donor=0.70, alpha_receiver=0.30, lateness_pressure_gain=0.20,
    severity_beta=1.3, margin_weight=0.5, min_receiver_quota=0.05,
    # optional leak knob for “near-donors” used only when real violations exist
    near_donor_leak=True,
):
    """
    TB reallocation with:
      - Anti-overshoot (receiver increments clipped to deficit; final band clamps)
      - Donor contraction fallback
      - NEW: 'Hard' classification so real violations cannot stall:
            * Any MS > TB ⇒ receiver (even if within deadband around target)
            * If any receiver exists ⇒ any TB > MS ⇒ donor (near-donor leak)
    """
    from statistics import pstdev

    parts = list(makespans.keys())
    eps = 1e-9

    # Global lateness → boost effective donor fraction slightly
    late_ratio = 0.0
    if app_deadline and global_makespan and global_makespan > app_deadline:
        late_ratio = (global_makespan - app_deadline) / max(app_deadline, 1.0)
    donor_frac_eff = min(1.0, donor_frac * (1.0 + lateness_pressure_gain * late_ratio))

    # recent sigma for margins
    def recent_sigma(p, K=5):
        hist = (partition_histories or {}).get(p, {})
        seq = (hist.get("makespan_evolution") or hist.get("ms_evolution") or [])[-K:]
        return float(pstdev(seq)) if len(seq) >= 2 else 0.0

    # Signals
    margin, viol, deficit, slack, deadband_abs, target = {}, {}, {}, {}, {}, {}
    for p in parts:
        ms = float(makespans[p]); tb = float(prev_budgets[p])
        sigma = recent_sigma(p)
        m = min_margin_ratio * ms + k_sigma * sigma
        margin[p] = m
        target[p] = ms + m
        deadband_abs[p] = deadband_ratio * ms
        viol[p] = max(0.0, ms - tb)            # "hard" violation vs TB
        deficit[p] = max(0.0, target[p] - tb)  # deficit to target
        slack[p] = tb - target[p]              # >0 => donor-ish relative to target

    # --- NEW: hard gating to prevent stalls ---
    has_hard_recv = any(viol[p] > 0 for p in parts)

    # Soft (target-band) classification
    donors_soft = [p for p in parts if slack[p] >  deadband_abs[p]]
    recvs_soft  = [p for p in parts if slack[p] < -deadband_abs[p]]

    # Hard rules layered on top:
    recvs_hard  = [p for p in parts if viol[p] > 0.0] if has_hard_recv else []
    # If there is any real violation, allow "near-donors" with TB > MS (even if inside deadband)
    if has_hard_recv and near_donor_leak:
        donors_hard = [p for p in parts if (float(prev_budgets[p]) > float(makespans[p]))]
    else:
        donors_hard = []

    # Union of soft+hard
    donors = sorted(set(donors_soft) | set(donors_hard))
    recvs  = sorted(set(recvs_soft)  | set(recvs_hard))

    # --- Donor-only fallback (no receivers) ---
    if donors and not recvs:
        new_tb = {p: float(prev_budgets[p]) for p in parts}
        for d in donors:
            tb = float(prev_budgets[d])
            reduce = min(max(0.0, slack[d]), cap_down * tb)
            new_tb[d] = max(target[d] - deadband_abs[d], tb - alpha_donor * reduce)
        return new_tb

    # If nobody can give OR nobody to receive, keep as is.
    if not donors or not recvs:
        return {p: float(prev_budgets[p]) for p in parts}

    # Donor pool (after caps per donor)
    donor_cap_unit = {}
    total_donor_cap = 0.0
    for d in donors:
        tb = float(prev_budgets[d])
        # Available above target; if near-donor, surplus might be small — that's fine.
        surplus = max(0.0, slack[d])
        give_potential = donor_frac_eff * surplus
        cap_abs = cap_down * tb
        cap_d = max(0.0, min(give_potential, cap_abs))
        donor_cap_unit[d] = cap_d
        total_donor_cap += cap_d

    # Global pool throttle (eta)
    total_donor_cap *= max(0.0, float(eta))
    if total_donor_cap <= eps:
        return {p: float(prev_budgets[p]) for p in parts}

    # Automatic severity (unchanged)
    severity_raw = {r: (viol[r] + margin_weight * deficit[r]) for r in recvs}
    severity = {r: (max(severity_raw[r], 0.0) + eps) ** max(1.0, severity_beta) for r in recvs}
    S = sum(severity.values())

    # Split pool: small equal floor, remainder by severity
    min_quota_total = max(0.0, min_receiver_quota) * total_donor_cap
    base_q = (min_quota_total / len(recvs)) if recvs else 0.0
    rem_pool = max(0.0, total_donor_cap - base_q * len(recvs))

    desired_inc = {r: base_q for r in recvs}
    if S > eps:
        for r in recvs:
            desired_inc[r] += rem_pool * (severity[r] / S)
    else:
        equal_add = (rem_pool / len(recvs)) if recvs else 0.0
        for r in recvs:
            desired_inc[r] += equal_add

    inc = {}
    # NEW: absolute rate limiter vs current makespan
    rate_limit_rho = 0.10   # <= you can move this to cfg if you want

    for r in recvs:
        tb = float(prev_budgets[r])

        # base request (your anti-windup + per-step cap)
        # if you didn’t add deficit clamp yet, include it here
        want = min(desired_inc[r], cap_up * tb, deficit[r])

        # NEW: limit the *absolute* change by a fraction of the plant size (MS)
        # catches the corner case: TB_prev is big -> % step still looks huge
        ms_now = float(makespans.get(r, 0.0))
        abs_cap = rate_limit_rho * max(1.0, ms_now)
        want = min(want, abs_cap)

        # smoothing
        inc[r] = alpha_receiver * want

    # keep the rest (scaling by donor availability, apportioning, final clamps)
    inc_total = sum(inc.values())

    # Donor gives proportional to their capped potentials (unchanged)
    denom = sum(donor_cap_unit.values()) or 1.0
    give = {}
    for d in donors:
        share = donor_cap_unit[d] / denom
        give_before_alpha = inc_total * share
        give[d] = alpha_donor * min(give_before_alpha, donor_cap_unit[d])

    # New budgets + final clamps (unchanged)
    new_tb = {p: float(prev_budgets[p]) for p in parts}
    for r in recvs:
        new_tb[r] = min(target[r] + deadband_abs[r], new_tb[r] + inc[r])
    for d in donors:
        new_tb[d] = max(target[d] - deadband_abs[d], new_tb[d] - give[d])

    return new_tb
