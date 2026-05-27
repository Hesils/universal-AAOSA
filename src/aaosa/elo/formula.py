from aaosa.schemas.elo import ELO_K, ELO_MAX_DELTA


def compute_delta(agent_elo: int, required_elo: int, success: bool) -> int:
    if success:
        raw = ELO_K * (required_elo / agent_elo)
    else:
        raw = -ELO_K * (agent_elo / required_elo)
    return max(-ELO_MAX_DELTA, min(ELO_MAX_DELTA, round(raw)))
