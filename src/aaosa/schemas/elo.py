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
