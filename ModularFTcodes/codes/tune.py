nodes = eh.build_schedule_tree(
    base_schedule=sorted_schedule,
    base_calendar=base_calendar,
    merged_paths=merged_paths_w_costs,

    # --- TUNING: generate ~50 child schedules total (excluding the root S0)
    # depth0: 5
    # depth1: 5*3 = 15
    # depth2: 5*3*2 = 30
    # total = 50
    rounds=3,

    log_dir=log_dir,
    timestamp=timestamp,
    root_tag=ROOT_TAG,

    # --- TUNING: ensure each node's calendar has enough events to select from
    gen_params={
        "n_slack": 6,
        "n_proc_fail": 3,
        "n_router_fail": 2,
        "slack_pct_range": (0.5, 0.7),
        "seed": 42
    },

    # --- TUNING: branching caps per level (controls tree size)
    branch_limits_per_level=[5, 3, 2],

    # Branch on all supported event types
    allowed_types=("slack", "processor_failure", "router_failure"),

    meta_static={
        "time_budgets_partition": meta.get("time_budgets_partition"),
    },
)