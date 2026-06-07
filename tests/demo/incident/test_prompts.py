from aaosa.demo.incident.prompts import AGGREGATOR_PROMPT, DIVIDER_PROMPT, TAGGER_PROMPT


class TestDividerPromptTopologyDecision:
    """Verrous du ticket divider/topologie (2026-06-07) : le divider décide
    librement la topologie — aucune découpe hardcodée dans le prompt."""

    def test_no_forced_synthesis_subtask(self):
        # « include a final synthesis sub-task » garantissait un sink unique
        # → court-circuit D2 systématique, aggregator code mort
        assert "synthesis" not in DIVIDER_PROMPT.lower()

    def test_no_ordered_constraint(self):
        # « ordered » poussait vers le strictement séquentiel (chaîne pure = 1 sink)
        assert "ordered" not in DIVIDER_PROMPT.lower()

    def test_dependencies_only_when_genuinely_needed(self):
        assert "only when" in DIVIDER_PROMPT.lower()


def test_all_prompts_non_empty():
    for prompt in (DIVIDER_PROMPT, AGGREGATOR_PROMPT, TAGGER_PROMPT):
        assert prompt.strip()
