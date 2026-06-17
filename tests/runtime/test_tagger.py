"""Tests for Tagger — uses provider.parse() (d6i migration)."""
import pytest
from unittest.mock import MagicMock

from aaosa.core.agent import Agent
from aaosa.runtime.providers import LLMProvider
from aaosa.runtime.tagger import TagSet, Tagger


def make_agent(name="A", **tags) -> Agent:
    return Agent(name=name, tags_with_elo=tags or {"python": 80}, system_prompt="x")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_tag_returns_set_of_tags():
    provider = MagicMock(spec=LLMProvider)
    provider.parse.return_value = TagSet(tags=["python", "sql"])
    tagger = Tagger(system_prompt="tag it")
    tags = tagger.tag("optimize a query", [make_agent()], provider)
    assert tags == {"python", "sql"}


def test_tag_dedups_and_strips():
    provider = MagicMock(spec=LLMProvider)
    provider.parse.return_value = TagSet(tags=[" python ", "python", "sql"])
    tagger = Tagger(system_prompt="tag it")
    assert tagger.tag("x", [make_agent()], provider) == {"python", "sql"}


def test_tag_returns_empty_set_when_parse_returns_none():
    provider = MagicMock(spec=LLMProvider)
    provider.parse.return_value = None
    tagger = Tagger(system_prompt="tag it")
    assert tagger.tag("x", [make_agent()], provider) == set()


def test_tag_calls_parse_with_correct_schema():
    provider = MagicMock(spec=LLMProvider)
    provider.parse.return_value = TagSet(tags=["python"])
    tagger = Tagger(system_prompt="tag it")
    tagger.tag("x", [make_agent()], provider)
    call_kwargs = provider.parse.call_args.kwargs
    assert call_kwargs["schema"] is TagSet
    assert call_kwargs["temperature"] == 0.0


def test_tag_passes_system_prompt_in_messages():
    provider = MagicMock(spec=LLMProvider)
    provider.parse.return_value = TagSet(tags=["python"])
    tagger = Tagger(system_prompt="custom-sys")
    tagger.tag("x", [make_agent()], provider)
    messages = provider.parse.call_args.kwargs["messages"]
    sys_content = next(m["content"] for m in messages if m["role"] == "system")
    assert sys_content == "custom-sys"


def test_tag_passes_description_in_user_message():
    provider = MagicMock(spec=LLMProvider)
    provider.parse.return_value = TagSet(tags=["python"])
    tagger = Tagger(system_prompt="tag it")
    tagger.tag("investigate the breach", [make_agent()], provider)
    messages = provider.parse.call_args.kwargs["messages"]
    user_content = next(m["content"] for m in messages if m["role"] == "user")
    assert "investigate the breach" in user_content


def test_tagset_requires_at_least_one_tag():
    with pytest.raises(Exception):
        TagSet(tags=[])


def test_build_prompt_states_and_filter_contract():
    """Les tags émis deviennent les required_tags d'un filtre AND (passes_filter) :
    le prompt doit communiquer ce contrat au LLM, sinon il émet l'union des
    capacités que la tâche touche → sous-tâches infaisables sur un roster de
    spécialistes étroits (bug découvert au DoD réel démo phase 3, 2026-06-07)."""
    tagger = Tagger(system_prompt="tag it")
    prompt = tagger._build_prompt("investigate the breach", [make_agent()])
    lower = prompt.lower()
    assert "single agent must hold all" in lower
    assert "not every capability the task touches" in lower
    assert "never mix tags from different lines" in lower
    # clause qui préserve la détection de roster gap : une capacité réellement
    # requise mais absente du roster doit quand même être nommée
    # (espaces normalisés : la phrase peut chevaucher un retour à la ligne)
    assert "name it even though it is absent" in " ".join(lower.split())


def test_build_prompt_groups_vocabulary_by_role_bundles():
    """Le vocabulaire est présenté par bundles de rôle (une ligne = les tags d'un
    rôle existant), pas à plat : sans les co-occurrences réelles, le LLM ne peut
    pas émettre un ensemble détenu par un seul agent (itération 2 du fix AND)."""
    agents = [
        make_agent("Sec", security=90, logs=72, investigation=75),
        make_agent("Data", data_analysis=88, database=70, reporting=75),
    ]
    prompt = Tagger(system_prompt="tag it")._build_prompt("x", agents)
    assert "- investigation, logs, security" in prompt
    assert "- data_analysis, database, reporting" in prompt
    # pas de ligne fusionnant les deux bundles
    assert "investigation, logs, reporting" not in prompt
