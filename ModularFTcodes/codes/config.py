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
import os
# import plotly.graph_objects as go
# import plotly.express as px



def _env_int(name, default):
    raw = os.environ.get(name)
    return default if raw in (None, "") else int(raw)


def _env_float(name, default):
    raw = os.environ.get(name)
    return default if raw in (None, "") else float(raw)


APPLCATION_DEADLINE_FACTOR = 0.9
################ PARTITION GA CONFIGURATION ##########################
PartitionMakespanWeight = -10
PartitionLatenessWeight = -1
PartitionCrossoverProb = _env_float("PARTITION_CROSSOVER_PROB", 0.7)
PartitionMutationProb = _env_float("PARTITION_MUTATION_PROB", 0.7)
PartitionPopulationSize = _env_int("PARTITION_POPULATION_SIZE", 16)
PartitionGenerations = _env_int("PARTITION_GENERATIONS", 20)
#######################################################################





# =========================
# System-level GA (moderate convergence)
# =========================

# Population / evolution
SystemLevelPopulationSize       = _env_int("SYSTEM_LEVEL_POPULATION_SIZE", 16)
SystemLevelGenerations          = _env_int("SYSTEM_LEVEL_GENERATIONS", 60)
SystemLevelCrossOverProb        = _env_float("SYSTEM_LEVEL_CROSSOVER_PROB", 0.80)
SystemLevelMutationProb         = _env_float("SYSTEM_LEVEL_MUTATION_PROB", 0.70)

# Fitness weights (minimize both)
SystemLevelWeightViolationSum   = -1.0
SystemLevelWeightGlobalLateness = -1.0

# =========================
# Time-Budget (TB) mutation & stability (moderate)
# =========================

# Safety floor and near-target deadband
TBMinMarginRatio   = 0.03     # keep TB >= ms * (1 + 3%)
TBDeadbandRatio    = 0.02

# Gradual step sizing (proportional to deficit/surplus)
TBStepGainUp       = 0.33     # ~1/3 of deficit corrected per gen
TBStepGainDown     = 0.22     # a bit gentler shaving of surplus

# Per-generation rate limits (avoid jumps)
TBMinStepAbs       = 6        # min absolute movement when adjusting
TBMaxStepAbs       = 60       # hard per-gen cap
TBMaxStepFrac      = 0.06     # and also cap to 6% of current TB

# Stabilization band once violation == 0 (hold TB steady here)
TBHoldSlackRatioLo = 0.006    # 0.6% of ms above target (lower edge)
TBHoldSlackRatioHi = 0.018    # 1.8% of ms above target (upper edge)

# Tiny noise only when far from the stability band
TBMutNoiseFrac     = 0.007    # disabled inside hold band

# Weak regularizer to discourage unnecessary TB inflation
TBSlackPenaltyWeight = 0.01
