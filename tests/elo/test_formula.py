from aaosa.elo.formula import compute_delta


def test_success_easy_task():
    # agent_elo=80, required=20 -> K * (20/80) = 5 * 0.25 = 1.25 -> round = 1
    assert compute_delta(agent_elo=80, required_elo=20, success=True) == 1


def test_success_same_level():
    # agent_elo=50, required=50 -> K * (50/50) = 5 * 1.0 = 5
    assert compute_delta(agent_elo=50, required_elo=50, success=True) == 5


def test_success_hard_task():
    # agent_elo=20, required=80 -> K * (80/20) = 5 * 4.0 = 20 -> clamp = 10
    assert compute_delta(agent_elo=20, required_elo=80, success=True) == 10


def test_success_moderate_hard():
    # agent_elo=30, required=50 -> K * (50/30) = 5 * 1.667 = 8.33 -> round = 8
    assert compute_delta(agent_elo=30, required_elo=50, success=True) == 8


def test_failure_hard_task():
    # agent_elo=20, required=80 -> -K * (20/80) = -5 * 0.25 = -1.25 -> round = -1
    assert compute_delta(agent_elo=20, required_elo=80, success=False) == -1


def test_failure_same_level():
    # agent_elo=50, required=50 -> -K * (50/50) = -5
    assert compute_delta(agent_elo=50, required_elo=50, success=False) == -5


def test_failure_easy_task():
    # agent_elo=80, required=20 -> -K * (80/20) = -5 * 4.0 = -20 -> clamp = -10
    assert compute_delta(agent_elo=80, required_elo=20, success=False) == -10


def test_failure_moderate_easy():
    # agent_elo=50, required=30 -> -K * (50/30) = -5 * 1.667 = -8.33 -> round = -8
    assert compute_delta(agent_elo=50, required_elo=30, success=False) == -8


def test_clamp_positive():
    # agent_elo=1, required=95 -> K * (95/1) = 475 -> clamp = 10
    assert compute_delta(agent_elo=1, required_elo=95, success=True) == 10


def test_clamp_negative():
    # agent_elo=95, required=1 -> -K * (95/1) = -475 -> clamp = -10
    assert compute_delta(agent_elo=95, required_elo=1, success=False) == -10


def test_floor_agent_elo():
    # agent_elo=1 (floor), required=50 -> K * (50/1) = 250 -> clamp = 10
    assert compute_delta(agent_elo=1, required_elo=50, success=True) == 10


def test_ceiling_agent_elo():
    # agent_elo=95 (ceiling), required=50 -> K * (50/95) = 2.63 -> round = 3
    assert compute_delta(agent_elo=95, required_elo=50, success=True) == 3


def test_both_at_floor():
    # agent_elo=1, required=1 -> K * (1/1) = 5
    assert compute_delta(agent_elo=1, required_elo=1, success=True) == 5


def test_both_at_ceiling():
    # agent_elo=95, required=95 -> K * (95/95) = 5
    assert compute_delta(agent_elo=95, required_elo=95, success=True) == 5


def test_rounding_half():
    # agent_elo=40, required=20 -> K * (20/40) = 2.5 -> round = 2 (banker's rounding)
    assert compute_delta(agent_elo=40, required_elo=20, success=True) == 2


def test_returns_int():
    result = compute_delta(agent_elo=50, required_elo=50, success=True)
    assert isinstance(result, int)
