# V2b Subtask 05 — TestCase / TestSet / persistance

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development ou superpowers:executing-plans.

_Statut: TODO_
_Depends on: 02 (EvaluatorSpec)_
_Blocking: 06 (health check), 07 (lifecycle)_

## Objectif

Promouvoir le `TestCase` (V2a : `tuple[Task, QAEvaluator]`) en modèle Pydantic riche, ajouter `TestSet`, la persistance JSON (même pattern que `elo/persistence.py`), la conversion `QAFailure -> TestCase`, et le helper de routage `active_cases` (regression_guard + fix_target attribués `agent`). Tout est sérialisable car l'evaluator est une spec.

> Note : `active_cases` vit ici (et non dans `lifecycle.py`) car il ne dépend que du `TestSet` — `lifecycle.py` (subtask 07) dépend du `HealthCheckReport` (subtask 06), placer `active_cases` ici évite un cycle de dépendances.

## Méthode

TDD strict.

## Fichiers

| Fichier | Action |
|---|---|
| `src/aaosa/qa/test_set.py` | CRÉER |
| `tests/qa/test_test_set.py` | CRÉER |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/qa/test_test_set.py -v
.venv\Scripts\python -m pytest tests/ -v
```

---

## Context

```python
# src/aaosa/qa/protocol.py
class QAFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    agent_id: str
    output: Output
    qa_result: QAResult

# Output : voir schemas/output.py (task_id, agent_id, content, llm_metadata, timestamp)
# EvaluatorSpec : voir qa/spec.py (subtask 02)
```

Pattern persistance à calquer sur `elo/persistence.py` : `latest.json` + fichier horodaté `%Y-%m-%dT%H-%M-%S.json`, encoding UTF-8, le caller crée le directory.

---

## Étape 1 — Tests (RED)

Créer `tests/qa/test_test_set.py`.

```python
from pathlib import Path

import pytest

from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.qa.protocol import QAFailure, QAResult
from aaosa.qa.test_set import (
    TestCase,
    TestSet,
    save_test_set,
    load_test_set,
    failure_to_test_case,
    active_cases,
)
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.schemas.task import Task


def make_task() -> Task:
    return Task(description="do x", required_tags={"python": 80})


def make_spec() -> EvaluatorSpec:
    return EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])


def make_output() -> Output:
    return Output(
        task_id="t1", agent_id="a1", content="bad",
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


def make_failure(task: Task) -> QAFailure:
    out = make_output()
    out = out.model_copy(update={"task_id": task.id})
    return QAFailure(
        task_id=task.id, agent_id="a1", output=out,
        qa_result=QAResult(task_id=task.id, agent_id="a1", success=False,
                           score=0.2, reason="too short", criteria_results={"non_empty": True}),
    )


class TestTestCase:
    def test_defaults(self):
        tc = TestCase(task=make_task(), evaluator_spec=make_spec(), origin="curated", role="regression_guard")
        assert tc.reference is None
        assert tc.wrong_output is None
        assert tc.attribution == "unattributed"

    def test_full(self):
        tc = TestCase(
            task=make_task(), evaluator_spec=make_spec(), reference="ideal",
            origin="runtime_failure", wrong_output=make_output(),
            role="fix_target", attribution="agent",
        )
        assert tc.reference == "ideal"
        assert tc.role == "fix_target"

    def test_invalid_origin(self):
        with pytest.raises(Exception):
            TestCase(task=make_task(), evaluator_spec=make_spec(), origin="bogus", role="fix_target")

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            TestCase(task=make_task(), evaluator_spec=make_spec(), origin="curated",
                     role="fix_target", bogus=1)


class TestTestSetPersistence:
    def test_save_creates_latest(self, tmp_path):
        ts = TestSet(cases=[TestCase(task=make_task(), evaluator_spec=make_spec(),
                                     origin="curated", role="regression_guard")])
        save_test_set(ts, tmp_path)
        assert (tmp_path / "latest.json").exists()

    def test_save_returns_timestamped_path(self, tmp_path):
        ts = TestSet(cases=[])
        path = save_test_set(ts, tmp_path)
        assert isinstance(path, Path)
        assert path.name != "latest.json"
        assert path.exists()

    def test_roundtrip(self, tmp_path):
        ts = TestSet(cases=[
            TestCase(task=make_task(), evaluator_spec=make_spec(), reference="r",
                     origin="runtime_failure", wrong_output=make_output(),
                     role="fix_target", attribution="agent"),
        ])
        save_test_set(ts, tmp_path)
        loaded = load_test_set(tmp_path / "latest.json")
        assert loaded == ts

    def test_load_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_test_set(tmp_path / "nope.json")


class TestFailureToTestCase:
    def test_born_as_fix_target_unattributed(self):
        task = make_task()
        tc = failure_to_test_case(make_failure(task), task, make_spec())
        assert tc.origin == "runtime_failure"
        assert tc.role == "fix_target"
        assert tc.attribution == "unattributed"
        assert tc.reference is None

    def test_preserves_wrong_output(self):
        task = make_task()
        failure = make_failure(task)
        tc = failure_to_test_case(failure, task, make_spec())
        assert tc.wrong_output == failure.output


class TestActiveCases:
    def _case(self, role, attribution):
        return TestCase(task=make_task(), evaluator_spec=make_spec(),
                        origin="curated", role=role, attribution=attribution)

    def test_includes_regression_guards(self):
        ts = TestSet(cases=[self._case("regression_guard", "unattributed")])
        assert len(active_cases(ts)) == 1   # guards inclus quelle que soit l'attribution

    def test_includes_fix_target_attributed_agent(self):
        ts = TestSet(cases=[self._case("fix_target", "agent")])
        assert len(active_cases(ts)) == 1

    def test_excludes_fix_target_unattributed(self):
        ts = TestSet(cases=[self._case("fix_target", "unattributed")])
        assert active_cases(ts) == []

    def test_excludes_task_spec_quarantine(self):
        ts = TestSet(cases=[self._case("fix_target", "task_spec")])
        assert active_cases(ts) == []

    def test_excludes_evaluator_attributed_fix_target(self):
        ts = TestSet(cases=[self._case("fix_target", "evaluator")])
        assert active_cases(ts) == []
```

- [ ] **Step 1: Écrire les tests**
- [ ] **Step 2: RED** — `.venv\Scripts\python -m pytest tests/qa/test_test_set.py -v`

---

## Étape 2 — Implementation (GREEN)

Créer `src/aaosa/qa/test_set.py`.

```python
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from aaosa.qa.protocol import QAFailure
from aaosa.qa.spec import EvaluatorSpec
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class TestCase(BaseModel):
    __test__ = False   # empêche pytest de collecter ce modèle comme classe de test
    model_config = ConfigDict(extra="forbid")
    task: Task
    evaluator_spec: EvaluatorSpec
    reference: str | None = None
    origin: Literal["curated", "runtime_failure"]
    wrong_output: Output | None = None
    role: Literal["fix_target", "regression_guard"]
    attribution: Literal["unattributed", "agent", "task_spec", "evaluator"] = "unattributed"


class TestSet(BaseModel):
    __test__ = False   # idem
    model_config = ConfigDict(extra="forbid")
    cases: list[TestCase]


def save_test_set(test_set: TestSet, directory: Path) -> Path:
    now = datetime.now(timezone.utc)
    json_data = test_set.model_dump_json(indent=2)
    ts_path = directory / (now.strftime("%Y-%m-%dT%H-%M-%S") + ".json")
    ts_path.write_text(json_data, encoding="utf-8")
    (directory / "latest.json").write_text(json_data, encoding="utf-8")
    return ts_path


def load_test_set(path: Path) -> TestSet:
    if not path.exists():
        raise FileNotFoundError(f"Test set not found: {path}")
    return TestSet.model_validate_json(path.read_text(encoding="utf-8"))


def failure_to_test_case(
    failure: QAFailure,
    task: Task,
    evaluator_spec: EvaluatorSpec,
) -> TestCase:
    return TestCase(
        task=task,
        evaluator_spec=evaluator_spec,
        reference=None,
        origin="runtime_failure",
        wrong_output=failure.output,
        role="fix_target",
        attribution="unattributed",
    )


def active_cases(test_set: TestSet) -> list[TestCase]:
    """Cas évalués par le health check : regression_guard (toute attribution)
    + fix_target attribués 'agent'. Exclut task_spec (quarantaine),
    unattributed et evaluator (cf spec §2.6)."""
    return [
        c for c in test_set.cases
        if c.role == "regression_guard"
        or (c.role == "fix_target" and c.attribution == "agent")
    ]
```

- [ ] **Step 3: Écrire `test_set.py`**
- [ ] **Step 4: GREEN** — `.venv\Scripts\python -m pytest tests/qa/test_test_set.py -v`
- [ ] **Step 5: Suite complète** — `.venv\Scripts\python -m pytest tests/ -v`
- [ ] **Step 6: Commit** — `git add src/aaosa/qa/test_set.py tests/qa/test_test_set.py && git commit -m "feat(v2b): TestCase/TestSet + persistance + failure_to_test_case + active_cases"`

## Invariants

- Imports absolus.
- Persistance identique au pattern `elo/persistence.py` (latest + horodaté, UTF-8, directory pré-existant).
- Un échec runtime naît `role="fix_target"`, `attribution="unattributed"`, `reference=None`.
- `wrong_output` conserve l'output rejeté (cf vault 04-regression).
- Roundtrip JSON strict (`loaded == ts`) — garanti par la spec déclarative sérialisable.
- ⚠️ `TestCase` et `TestSet` portent `__test__ = False` (attribut dunder ignoré par Pydantic comme champ) — sinon pytest tente de les collecter comme classes de test et émet un `PytestCollectionWarning`. Vérifier que `pytest tests/ -v` ne produit aucun warning de collecte sur ces deux noms.
