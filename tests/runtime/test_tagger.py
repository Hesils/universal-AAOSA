from types import SimpleNamespace

from aaosa.core.agent import Agent
from aaosa.runtime.tagger import TagSet, Tagger


def make_agent(name="A", **tags) -> Agent:
    return Agent(name=name, tags_with_elo=tags or {"python": 80}, system_prompt="x")


def _client_returning(tagset):
    parsed = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=tagset))])
    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kw: parsed)))
    )


def test_tag_returns_set_of_tags():
    tagger = Tagger(system_prompt="tag it")
    client = _client_returning(TagSet(tags=["python", "sql"]))
    tags = tagger.tag("optimize a query", [make_agent()], client)
    assert tags == {"python", "sql"}


def test_tag_dedups_and_strips():
    tagger = Tagger(system_prompt="tag it")
    client = _client_returning(TagSet(tags=[" python ", "python", "sql"]))
    assert tagger.tag("x", [make_agent()], client) == {"python", "sql"}


def test_tag_returns_empty_set_when_parse_is_none():
    tagger = Tagger(system_prompt="tag it")
    client = _client_returning(None)
    assert tagger.tag("x", [make_agent()], client) == set()


def test_tag_returns_empty_set_when_llm_raises():
    tagger = Tagger(system_prompt="tag it")
    def boom(**kw):
        raise RuntimeError("network")
    client = SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=boom)))
    )
    assert tagger.tag("x", [make_agent()], client) == set()


def test_tagset_requires_at_least_one_tag():
    import pytest
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
