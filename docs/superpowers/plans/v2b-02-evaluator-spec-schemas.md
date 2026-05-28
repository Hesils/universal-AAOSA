# V2b Subtask 02 — Schemas de spec (CriterionSpec, JudgeSpec, EvaluatorSpec)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development ou superpowers:executing-plans.

_Statut: TODO_
_Depends on: —_
_Blocking: 03 (judge), 04 (SpecEvaluator), 05 (test_set), 08 (adaptive)_

## Objectif

Définir la spec déclarative de l'evaluator : `CriterionSpec`, `JudgeSpec`, `EvaluatorSpec`. Schemas Pydantic purs, entièrement sérialisables JSON (c'est le pont vers la génération par agent en V3).

## Méthode

TDD strict.

## Fichiers

| Fichier | Action |
|---|---|
| `src/aaosa/qa/spec.py` | CRÉER |
| `tests/qa/test_spec.py` | CRÉER |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/qa/test_spec.py -v
.venv\Scripts\python -m pytest tests/ -v
```

---

## Étape 1 — Tests (RED)

Créer `tests/qa/test_spec.py`.

```python
import pytest

from aaosa.qa.spec import CriterionSpec, JudgeSpec, EvaluatorSpec


class TestCriterionSpec:
    def test_defaults(self):
        c = CriterionSpec(name="non_empty")
        assert c.params == {}
        assert c.weight == 1.0
        assert c.gate is False

    def test_full(self):
        c = CriterionSpec(name="min_length", params={"min_chars": 100}, weight=2.0, gate=True)
        assert c.params["min_chars"] == 100
        assert c.gate is True

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            CriterionSpec(name="x", bogus=1)


class TestJudgeSpec:
    def test_defaults(self):
        j = JudgeSpec(rubric=["correctness"])
        assert j.mode == "rubric"
        assert j.model == "gpt-4o-mini"
        assert j.weight == 0.3
        assert j.temperature == 0.0
        assert j.instructions == ""

    def test_reference_based(self):
        j = JudgeSpec(mode="reference_based", rubric=["correctness", "completeness"], weight=0.5)
        assert j.mode == "reference_based"
        assert len(j.rubric) == 2

    def test_invalid_mode(self):
        with pytest.raises(Exception):
            JudgeSpec(mode="bogus", rubric=["x"])

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            JudgeSpec(rubric=["x"], bogus=1)


class TestEvaluatorSpec:
    def test_minimal(self):
        s = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        assert s.judge is None
        assert s.success_threshold == 0.7

    def test_with_judge(self):
        s = EvaluatorSpec(
            criteria=[CriterionSpec(name="non_empty", gate=True)],
            judge=JudgeSpec(rubric=["correctness"]),
            success_threshold=0.8,
        )
        assert s.judge is not None
        assert s.success_threshold == 0.8

    def test_json_roundtrip(self):
        s = EvaluatorSpec(
            criteria=[
                CriterionSpec(name="non_empty", gate=True),
                CriterionSpec(name="min_length", params={"min_chars": 80}, weight=2.0),
            ],
            judge=JudgeSpec(mode="reference_based", rubric=["a", "b"], weight=0.4),
            success_threshold=0.75,
        )
        data = s.model_dump_json()
        s2 = EvaluatorSpec.model_validate_json(data)
        assert s2 == s

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            EvaluatorSpec(criteria=[], bogus=1)
```

- [ ] **Step 1: Écrire les tests**
- [ ] **Step 2: RED** — `.venv\Scripts\python -m pytest tests/qa/test_spec.py -v`

---

## Étape 2 — Implementation (GREEN)

Créer `src/aaosa/qa/spec.py`.

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict


class CriterionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    params: dict = {}
    weight: float = 1.0
    gate: bool = False


class JudgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["rubric", "reference_based"] = "rubric"
    model: str = "gpt-4o-mini"
    rubric: list[str]
    weight: float = 0.3
    temperature: float = 0.0
    instructions: str = ""


class EvaluatorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criteria: list[CriterionSpec]
    judge: JudgeSpec | None = None
    success_threshold: float = 0.7
```

- [ ] **Step 3: Écrire `spec.py`**
- [ ] **Step 4: GREEN** — `.venv\Scripts\python -m pytest tests/qa/test_spec.py -v`
- [ ] **Step 5: Suite complète** — `.venv\Scripts\python -m pytest tests/ -v`
- [ ] **Step 6: Commit** — `git add src/aaosa/qa/spec.py tests/qa/test_spec.py && git commit -m "feat(v2b): schemas de spec evaluator (CriterionSpec/JudgeSpec/EvaluatorSpec)"`

## Invariants

- `extra="forbid"` sur les 3 modèles.
- `JudgeSpec.mode` restreint à `Literal["rubric", "reference_based"]`.
- Tout est sérialisable JSON (roundtrip strict — `s2 == s`).
- Valeurs par défaut alignées sur la spec : `weight=0.3`, `temperature=0.0`, `success_threshold=0.7`.
