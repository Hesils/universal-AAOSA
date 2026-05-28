# V2b Subtask 01 — Couche critères (registry + bibliothèque)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development ou superpowers:executing-plans. Steps en checkbox (`- [ ]`).

_Statut: TODO_
_Depends on: — (Task/Output existent déjà)_
_Blocking: 04 (SpecEvaluator), 08 (adaptive)_

## Objectif

Créer la couche de critères d'évaluation : un `CriterionOutcome` granulaire (score 0.0-1.0, pas un bool), un registry de critères indexé par nom, et une bibliothèque de 5 critères déterministes. Généralise les 3 critères de `BasicRuleEvaluator` (qui reste en place).

## Méthode

TDD strict : tests d'abord, vérifier le RED, puis implémenter.

## Fichiers

| Fichier | Action |
|---|---|
| `src/aaosa/qa/criteria.py` | CRÉER |
| `tests/qa/test_criteria.py` | CRÉER |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/qa/test_criteria.py -v
.venv\Scripts\python -m pytest tests/ -v
```

---

## Context — schemas existants

```python
# src/aaosa/schemas/task.py
class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    required_tags: dict[str, int]          # non vide
    acquirable_tags: dict[str, int] = {}
    metadata: dict = {}
    timestamp: datetime

# src/aaosa/schemas/output.py
class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    agent_id: str
    content: str
    llm_metadata: LLMMetadata
    timestamp: datetime

class LLMMetadata(BaseModel):
    model_config = ConfigDict(strict=True)
    model_name: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
```

---

## Étape 1 — Tests (RED)

Créer `tests/qa/test_criteria.py`.

```python
import pytest

from aaosa.qa.criteria import (
    CriterionOutcome,
    CRITERIA_REGISTRY,
    register_criterion,
    get_criterion,
    non_empty,
    min_length,
    references_tags,
    keyword_presence,
    format_check,
)
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.schemas.task import Task


def make_task(required_tags=None, description="Do the thing") -> Task:
    return Task(description=description, required_tags=required_tags or {"python": 80})


def make_output(content: str) -> Output:
    return Output(
        task_id="t1",
        agent_id="a1",
        content=content,
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


class TestCriterionOutcome:
    def test_valid(self):
        o = CriterionOutcome(name="x", passed=True, score=1.0, detail="ok")
        assert o.score == 1.0

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            CriterionOutcome(name="x", passed=True, score=1.0, detail="ok", bogus=1)


class TestRegistry:
    def test_library_registered(self):
        for name in ["non_empty", "min_length", "references_tags", "keyword_presence", "format_check"]:
            assert name in CRITERIA_REGISTRY

    def test_get_criterion_returns_callable(self):
        fn = get_criterion("non_empty")
        assert callable(fn)

    def test_get_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown criterion"):
            get_criterion("does_not_exist")

    def test_register_decorator(self):
        @register_criterion("tmp_test_criterion")
        def _crit(task, output, params):
            return CriterionOutcome(name="tmp_test_criterion", passed=True, score=1.0, detail="")
        assert "tmp_test_criterion" in CRITERIA_REGISTRY
        del CRITERIA_REGISTRY["tmp_test_criterion"]


class TestNonEmpty:
    def test_pass(self):
        o = non_empty(make_task(), make_output("hello"), {})
        assert o.passed is True and o.score == 1.0

    def test_fail_empty(self):
        o = non_empty(make_task(), make_output(""), {})
        assert o.passed is False and o.score == 0.0

    def test_fail_whitespace(self):
        o = non_empty(make_task(), make_output("   \n  "), {})
        assert o.passed is False


class TestMinLength:
    def test_pass_default(self):
        o = min_length(make_task(), make_output("x" * 60), {})
        assert o.passed is True and o.score == 1.0

    def test_fail_short(self):
        o = min_length(make_task(), make_output("x" * 25), {})
        assert o.passed is False
        assert o.score == pytest.approx(0.5)  # 25/50

    def test_custom_threshold(self):
        o = min_length(make_task(), make_output("x" * 10), {"min_chars": 10})
        assert o.passed is True and o.score == 1.0


class TestReferencesTags:
    def test_all_present(self):
        task = make_task({"python": 80, "testing": 50})
        o = references_tags(task, make_output("uses python and testing here"), {})
        assert o.passed is True and o.score == 1.0

    def test_partial(self):
        task = make_task({"python": 80, "docker": 50})
        o = references_tags(task, make_output("only python mentioned"), {})
        assert o.passed is False
        assert o.score == pytest.approx(0.5)

    def test_custom_tags_param(self):
        o = references_tags(make_task(), make_output("contains alpha"), {"tags": ["alpha"]})
        assert o.passed is True


class TestKeywordPresence:
    def test_all_present(self):
        o = keyword_presence(make_task(), make_output("def foo(): return"), {"keywords": ["def", "return"]})
        assert o.passed is True and o.score == 1.0

    def test_partial(self):
        o = keyword_presence(make_task(), make_output("def foo()"), {"keywords": ["def", "return"]})
        assert o.score == pytest.approx(0.5)

    def test_no_keywords_passes(self):
        o = keyword_presence(make_task(), make_output("anything"), {"keywords": []})
        assert o.passed is True and o.score == 1.0


class TestFormatCheck:
    def test_json_valid(self):
        o = format_check(make_task(), make_output('{"a": 1}'), {"kind": "json"})
        assert o.passed is True

    def test_json_invalid(self):
        o = format_check(make_task(), make_output("not json"), {"kind": "json"})
        assert o.passed is False

    def test_code_block(self):
        o = format_check(make_task(), make_output("text\n```py\nx=1\n```"), {"kind": "code_block"})
        assert o.passed is True

    def test_non_empty_lines_default(self):
        o = format_check(make_task(), make_output("line one\nline two"), {})
        assert o.passed is True

    def test_non_empty_lines_fail(self):
        o = format_check(make_task(), make_output("\n   \n"), {"kind": "non_empty_lines"})
        assert o.passed is False
```

- [ ] **Step 1: Écrire les tests ci-dessus**
- [ ] **Step 2: Vérifier le RED** — `.venv\Scripts\python -m pytest tests/qa/test_criteria.py -v` → ImportError / fail

---

## Étape 2 — Implementation (GREEN)

Créer `src/aaosa/qa/criteria.py`.

```python
import json
from typing import Callable

from pydantic import BaseModel, ConfigDict

from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class CriterionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    passed: bool
    score: float       # 0.0-1.0
    detail: str


Criterion = Callable[[Task, Output, dict], CriterionOutcome]

CRITERIA_REGISTRY: dict[str, Criterion] = {}


def register_criterion(name: str) -> Callable[[Criterion], Criterion]:
    def deco(fn: Criterion) -> Criterion:
        CRITERIA_REGISTRY[name] = fn
        return fn
    return deco


def get_criterion(name: str) -> Criterion:
    if name not in CRITERIA_REGISTRY:
        raise ValueError(f"unknown criterion: {name!r}")
    return CRITERIA_REGISTRY[name]


@register_criterion("non_empty")
def non_empty(task: Task, output: Output, params: dict) -> CriterionOutcome:
    passed = len(output.content.strip()) > 0
    return CriterionOutcome(
        name="non_empty", passed=passed, score=1.0 if passed else 0.0,
        detail=f"{len(output.content)} chars",
    )


@register_criterion("min_length")
def min_length(task: Task, output: Output, params: dict) -> CriterionOutcome:
    threshold = params.get("min_chars", 50)
    n = len(output.content)
    score = min(1.0, n / threshold) if threshold > 0 else 1.0
    return CriterionOutcome(
        name="min_length", passed=n >= threshold, score=score,
        detail=f"{n}/{threshold} chars",
    )


@register_criterion("references_tags")
def references_tags(task: Task, output: Output, params: dict) -> CriterionOutcome:
    tags = params.get("tags") or list(task.required_tags)
    content_lower = output.content.lower()
    present = [t for t in tags if t.lower() in content_lower]
    score = len(present) / len(tags) if tags else 1.0
    return CriterionOutcome(
        name="references_tags", passed=len(present) == len(tags), score=score,
        detail=f"{len(present)}/{len(tags)} tags referenced",
    )


@register_criterion("keyword_presence")
def keyword_presence(task: Task, output: Output, params: dict) -> CriterionOutcome:
    keywords = params.get("keywords", [])
    if not keywords:
        return CriterionOutcome(name="keyword_presence", passed=True, score=1.0, detail="no keywords")
    content_lower = output.content.lower()
    present = [k for k in keywords if k.lower() in content_lower]
    score = len(present) / len(keywords)
    return CriterionOutcome(
        name="keyword_presence", passed=len(present) == len(keywords), score=score,
        detail=f"{len(present)}/{len(keywords)} keywords present",
    )


@register_criterion("format_check")
def format_check(task: Task, output: Output, params: dict) -> CriterionOutcome:
    kind = params.get("kind", "non_empty_lines")
    content = output.content
    if kind == "json":
        try:
            json.loads(content)
            passed = True
        except (json.JSONDecodeError, ValueError):
            passed = False
    elif kind == "code_block":
        passed = "```" in content
    else:  # non_empty_lines
        passed = any(line.strip() for line in content.splitlines())
    return CriterionOutcome(
        name="format_check", passed=passed, score=1.0 if passed else 0.0,
        detail=f"kind={kind}",
    )
```

- [ ] **Step 3: Écrire `criteria.py`**
- [ ] **Step 4: GREEN** — `.venv\Scripts\python -m pytest tests/qa/test_criteria.py -v` → PASS
- [ ] **Step 5: Toute la suite** — `.venv\Scripts\python -m pytest tests/ -v`
- [ ] **Step 6: Commit** — `git add src/aaosa/qa/criteria.py tests/qa/test_criteria.py && git commit -m "feat(v2b): couche critères (registry + bibliothèque)"`

## Invariants

- Imports absolus uniquement (`from aaosa....`).
- `CriterionOutcome.score ∈ [0.0, 1.0]`.
- `get_criterion` raise `ValueError` (pas `KeyError`) sur nom inconnu.
- Les 5 critères sont enregistrés à l'import du module (via décorateur).
- `non_empty` teste `content.strip()` (whitespace = vide).
