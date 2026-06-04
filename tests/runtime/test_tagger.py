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
