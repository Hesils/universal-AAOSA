from aaosa.qa.adaptive import build_adaptive_spec, _build_prompt
from aaosa.qa.spec import EvaluatorSpec
from aaosa.schemas.task import Task


def task_with(required_tags) -> Task:
    return Task(description="x", required_tags=required_tags)


class TestBuildAdaptiveSpec:
    def test_returns_evaluator_spec(self):
        spec = build_adaptive_spec(task_with({"python": 50}))
        assert isinstance(spec, EvaluatorSpec)

    def test_always_has_non_empty_gate(self):
        spec = build_adaptive_spec(task_with({"python": 50}))
        gates = [c for c in spec.criteria if c.gate]
        assert any(c.name == "non_empty" for c in gates)

    def test_min_length_scaled_by_tag_count(self):
        spec = build_adaptive_spec(task_with({"python": 50, "testing": 40, "docker": 30}))
        ml = next(c for c in spec.criteria if c.name == "min_length")
        assert ml.params["min_chars"] == 150  # 50 * 3

    def test_no_judge_for_low_elo(self):
        spec = build_adaptive_spec(task_with({"python": 50, "css": 40}))
        assert spec.judge is None

    def test_judge_added_for_expert_tag(self):
        spec = build_adaptive_spec(task_with({"python": 90}))  # >= 85
        assert spec.judge is not None
        assert spec.judge.mode == "rubric"
        assert "correctness" in spec.judge.rubric

    def test_judge_threshold_boundary(self):
        # exactly 85 → judge présent (>=)
        assert build_adaptive_spec(task_with({"x": 85})).judge is not None
        # 84 → pas de judge
        assert build_adaptive_spec(task_with({"x": 84})).judge is None


def test_build_prompt_includes_context_when_present():
    task = Task(description="audit auth", required_tags={"security": 80},
                context="HIPAA, secrets en clair interdits")
    prompt = _build_prompt(task)
    assert "HIPAA" in prompt


def test_build_prompt_omits_context_section_when_absent():
    task = Task(description="audit auth", required_tags={"security": 80})
    prompt = _build_prompt(task)
    assert "# Contexte" not in prompt
