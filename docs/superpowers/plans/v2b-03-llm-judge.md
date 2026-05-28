# V2b Subtask 03 — LLM-judge (run_judge, 2 modes)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development ou superpowers:executing-plans.

_Statut: TODO_
_Depends on: 02 (JudgeSpec)_
_Blocking: 04 (SpecEvaluator)_

## Objectif

Implémenter le LLM-as-judge : `JudgeResult` + `run_judge`. Deux modes (`rubric` sans référence, `reference_based` avec référence injectée). Appel via structured output OpenAI (même pattern que `Agent.claim`), température portée par la spec. **Aucun appel LLM réel dans les tests** — client mocké.

## Méthode

TDD strict. Le judge n'est jamais le signal primaire (cf spec §1.5) ; ici on implémente seulement le scorer.

## Fichiers

| Fichier | Action |
|---|---|
| `src/aaosa/qa/judge.py` | CRÉER |
| `tests/qa/test_judge.py` | CRÉER |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/qa/test_judge.py -v
.venv\Scripts\python -m pytest tests/ -v
```

---

## Context — pattern d'appel LLM (depuis `Agent.claim`)

```python
response = client.beta.chat.completions.parse(
    model="gpt-4o-mini",
    messages=[{"role": "system", "content": ...}, {"role": "user", "content": ...}],
    response_format=Claim,            # un BaseModel Pydantic
)
parsed = response.choices[0].message.parsed   # instance du BaseModel ou None
```

On réutilise ce pattern avec `response_format=JudgeResult`. Le mock dans les tests reproduit cette forme.

---

## Étape 1 — Tests (RED)

Créer `tests/qa/test_judge.py`.

```python
import pytest

from aaosa.qa.judge import JudgeResult, run_judge
from aaosa.qa.spec import JudgeSpec
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.schemas.task import Task


def make_task() -> Task:
    return Task(description="Build a login form", required_tags={"frontend": 80})


def make_output(content="<form>login</form>") -> Output:
    return Output(
        task_id="t1", agent_id="a1", content=content,
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


# --- Fake OpenAI client reproduisant client.beta.chat.completions.parse ---

class _FakeMessage:
    def __init__(self, parsed):
        self.parsed = parsed

class _FakeChoice:
    def __init__(self, parsed):
        self.message = _FakeMessage(parsed)

class _FakeParseResponse:
    def __init__(self, parsed):
        self.choices = [_FakeChoice(parsed)]

class FakeParseClient:
    """Capture les kwargs et retourne un JudgeResult pré-calculé."""
    def __init__(self, parsed: JudgeResult):
        self._parsed = parsed
        self.captured_kwargs = None
        self.beta = self
        self.chat = self
        self.completions = self

    def parse(self, **kwargs):
        self.captured_kwargs = kwargs
        return _FakeParseResponse(self._parsed)


class TestJudgeResult:
    def test_valid(self):
        r = JudgeResult(dimension_scores={"correctness": 0.9}, overall=0.9, reason="good")
        assert r.overall == 0.9

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            JudgeResult(dimension_scores={}, overall=1.0, reason="", bogus=1)


class TestRunJudge:
    def test_returns_judge_result(self):
        expected = JudgeResult(dimension_scores={"correctness": 0.8}, overall=0.8, reason="ok")
        client = FakeParseClient(expected)
        result = run_judge(make_task(), make_output(), JudgeSpec(rubric=["correctness"]), client)
        assert result.overall == 0.8

    def test_uses_spec_model_and_temperature(self):
        client = FakeParseClient(JudgeResult(dimension_scores={"x": 1.0}, overall=1.0, reason=""))
        spec = JudgeSpec(rubric=["x"], model="gpt-4o-mini", temperature=0.0)
        run_judge(make_task(), make_output(), spec, client)
        assert client.captured_kwargs["model"] == "gpt-4o-mini"
        assert client.captured_kwargs["temperature"] == 0.0
        assert client.captured_kwargs["response_format"] is JudgeResult

    def test_rubric_mode_no_reference_in_prompt(self):
        client = FakeParseClient(JudgeResult(dimension_scores={"x": 1.0}, overall=1.0, reason=""))
        run_judge(make_task(), make_output(), JudgeSpec(mode="rubric", rubric=["x"]), client)
        user_msg = client.captured_kwargs["messages"][-1]["content"]
        assert "Reference" not in user_msg and "référence" not in user_msg.lower()

    def test_reference_based_injects_reference(self):
        client = FakeParseClient(JudgeResult(dimension_scores={"x": 1.0}, overall=1.0, reason=""))
        spec = JudgeSpec(mode="reference_based", rubric=["x"])
        run_judge(make_task(), make_output(), spec, client, reference="THE IDEAL ANSWER")
        user_msg = client.captured_kwargs["messages"][-1]["content"]
        assert "THE IDEAL ANSWER" in user_msg

    def test_rubric_dimensions_in_prompt(self):
        client = FakeParseClient(JudgeResult(dimension_scores={}, overall=0.5, reason=""))
        run_judge(make_task(), make_output(), JudgeSpec(rubric=["correctness", "completeness"]), client)
        user_msg = client.captured_kwargs["messages"][-1]["content"]
        assert "correctness" in user_msg and "completeness" in user_msg

    def test_instructions_injected(self):
        client = FakeParseClient(JudgeResult(dimension_scores={}, overall=0.5, reason=""))
        spec = JudgeSpec(rubric=["x"], instructions="Be strict about accessibility.")
        run_judge(make_task(), make_output(), spec, client)
        user_msg = client.captured_kwargs["messages"][-1]["content"]
        assert "accessibility" in user_msg
```

- [ ] **Step 1: Écrire les tests**
- [ ] **Step 2: RED** — `.venv\Scripts\python -m pytest tests/qa/test_judge.py -v`

---

## Étape 2 — Implementation (GREEN)

Créer `src/aaosa/qa/judge.py`.

```python
from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from aaosa.qa.spec import JudgeSpec
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class JudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimension_scores: dict[str, float]
    overall: float
    reason: str


_SYSTEM = (
    "You are a strict QA judge. Score the agent output against the task on each "
    "rubric dimension from 0.0 to 1.0, then give an overall score (0.0-1.0) and a short reason. "
    "Be conservative: reward only what is actually present in the output."
)


def _build_user_message(
    task: Task, output: Output, spec: JudgeSpec, reference: str | None
) -> str:
    parts = [
        f"# Task\n{task.description}",
        f"# Required tags\n{', '.join(task.required_tags)}",
        f"# Rubric dimensions\n{', '.join(spec.rubric)}",
        f"# Agent output\n{output.content}",
    ]
    if spec.instructions:
        parts.append(f"# Extra instructions\n{spec.instructions}")
    if spec.mode == "reference_based" and reference is not None:
        parts.append(f"# Reference (ideal answer)\n{reference}")
    return "\n\n".join(parts)


def run_judge(
    task: Task,
    output: Output,
    spec: JudgeSpec,
    client: OpenAI,
    reference: str | None = None,
) -> JudgeResult:
    user_message = _build_user_message(task, output, spec, reference)
    response = client.beta.chat.completions.parse(
        model=spec.model,
        temperature=spec.temperature,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_message},
        ],
        response_format=JudgeResult,
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        raise ValueError("judge returned no parsed result")
    return parsed
```

- [ ] **Step 3: Écrire `judge.py`**
- [ ] **Step 4: GREEN** — `.venv\Scripts\python -m pytest tests/qa/test_judge.py -v`
- [ ] **Step 5: Suite complète** — `.venv\Scripts\python -m pytest tests/ -v`
- [ ] **Step 6: Commit** — `git add src/aaosa/qa/judge.py tests/qa/test_judge.py && git commit -m "feat(v2b): LLM-judge run_judge (modes rubric/reference_based)"`

## Invariants

- Imports absolus.
- `mode="reference_based"` injecte la référence dans le prompt ; `mode="rubric"` ne le fait pas.
- `temperature` et `model` viennent de la `JudgeSpec` (pas hardcodés).
- `response_format=JudgeResult` (structured output, pas de parsing manuel).
- Aucun appel LLM réel dans les tests (client mocké).
- La validation LLM réelle se fera via la démo (v2b-09), comme V2a.
