"""ELO bootstrap ranges for skill levels."""

ELO_EXPERT_MIN = 85
ELO_EXPERT_MAX = 95

ELO_COMPETENT_MIN = 30
ELO_COMPETENT_MAX = 50

ELO_BASIC_MIN = 10
ELO_BASIC_MAX = 25

# Tags with required_elo <= this threshold are "acquirable" in Phase 1:
# agents can pass the filter without having them, and may gain them on task success (V2).
ELO_ACQUIRABLE_THRESHOLD = ELO_BASIC_MAX

# V2 — Dynamic ELO update constants
ELO_FLOOR = 1
ELO_CEILING = ELO_EXPERT_MAX  # 95
ELO_K = 5
ELO_MAX_DELTA = 10

# V3 — Tag loss mechanic (mirror of acquisition):
# on failure, if the raw post-delta ELO drops strictly below this threshold
# (the floor is deliberately ignored), the agent loses the tag entirely.
ELO_TAG_LOSS_THRESHOLD = 0
