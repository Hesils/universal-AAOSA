from aaosa.runtime import default_prompts


def test_prompts_are_nonempty_strings():
    for p in (default_prompts.DIVIDER_PROMPT, default_prompts.AGGREGATOR_PROMPT, default_prompts.TAGGER_PROMPT):
        assert isinstance(p, str) and p.strip()


def test_aggregator_prompt_is_domain_agnostic():
    # « incident » est le seul terme domaine de la version démo : il ne doit pas fuiter ici.
    assert "incident" not in default_prompts.AGGREGATOR_PROMPT.lower()
    assert "task" in default_prompts.AGGREGATOR_PROMPT.lower()
