import pytest
from aaosa.schemas.elo import (
    ELO_EXPERT_MIN,
    ELO_EXPERT_MAX,
    ELO_COMPETENT_MIN,
    ELO_COMPETENT_MAX,
    ELO_BASIC_MIN,
    ELO_BASIC_MAX,
    DEFAULT_REQUIRED_ELO,
)


def test_elo_expert_min_defined():
    """ELO_EXPERT_MIN should be defined and equal to 85."""
    assert ELO_EXPERT_MIN == 85


def test_elo_expert_max_defined():
    """ELO_EXPERT_MAX should be defined and equal to 95."""
    assert ELO_EXPERT_MAX == 95


def test_elo_competent_min_defined():
    """ELO_COMPETENT_MIN should be defined and equal to 30."""
    assert ELO_COMPETENT_MIN == 30


def test_elo_competent_max_defined():
    """ELO_COMPETENT_MAX should be defined and equal to 50."""
    assert ELO_COMPETENT_MAX == 50


def test_elo_basic_min_defined():
    """ELO_BASIC_MIN should be defined and equal to 10."""
    assert ELO_BASIC_MIN == 10


def test_elo_basic_max_defined():
    """ELO_BASIC_MAX should be defined and equal to 25."""
    assert ELO_BASIC_MAX == 25


def test_elo_constants_are_integers():
    """All ELO constants should be integers."""
    assert isinstance(ELO_EXPERT_MIN, int)
    assert isinstance(ELO_EXPERT_MAX, int)
    assert isinstance(ELO_COMPETENT_MIN, int)
    assert isinstance(ELO_COMPETENT_MAX, int)
    assert isinstance(ELO_BASIC_MIN, int)
    assert isinstance(ELO_BASIC_MAX, int)


def test_elo_hierarchy_holds():
    """ELO tiers should not overlap: Basic < Competent < Expert."""
    assert ELO_BASIC_MAX < ELO_COMPETENT_MIN
    assert ELO_COMPETENT_MAX < ELO_EXPERT_MIN


def test_default_required_elo_is_competent_floor():
    """DEFAULT_REQUIRED_ELO should equal ELO_COMPETENT_MIN."""
    assert DEFAULT_REQUIRED_ELO == ELO_COMPETENT_MIN == 30
