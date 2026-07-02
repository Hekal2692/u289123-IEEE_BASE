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
# import plotly.graph_objects as go
# import plotly.express as px



APPLCATION_DEADLINE_FACTOR = 0.9
################ PARTITION GA CONFIGURATION ##########################
PartitionMakespanWeight = -10
PartitionLatenessWeight = -1
PartitionCrossoverProb = 0.7
PartitionMutationProb = 0.7
PartitionPopulationSize = 16
PartitionGenerations = 20
#######################################################################





# =========================
# System-level GA (moderate convergence)
# =========================

# Population / evolution
SystemLevelPopulationSize       = 16
SystemLevelGenerations          = 60
SystemLevelCrossOverProb        = 0.80
SystemLevelMutationProb         = 0.70   

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
