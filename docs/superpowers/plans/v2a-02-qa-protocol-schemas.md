# V2a Subtask 02 — QA Protocol + Schemas

_Statut: TODO_
_Depends on: nothing (independant de subtask 01)_
_Blocking: subtask 05 (tracer events), subtask 07 (rule evaluator), subtask 08 (runner V2), subtask 09 (health check)_

## Objectif

Creer le package `qa/` avec le `QAEvaluator` Protocol (structural typing), `QAResult`, et `QAFailure`. Ces schemas sont la fondation du systeme QA V2a.

## Methode

TDD strict : ecrire tous les tests d'abord, verifier qu'ils echouent, puis implementer.

## Fichiers a creer

| Fichier | Action |
|---|---|
| `src/aaosa/qa/__init__.py` | CREER — package init vide |
| `src/aaosa/qa/protocol.py` | CREER — QAResult, QAEvaluator Protocol, QAFailure |
| `tests/qa/__init__.py` | CREER — package init vide |
| `tests/qa/test_protocol.py` | CREER — tests exhaustifs |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/qa/test_protocol.py -v
.venv\Scripts\python -m pytest tests/ -v   # les 252 tests V1 doivent toujours passer
```

---

## Context — Schemas existants utilises

### `Output` (dans `src/aaosa/schemas/output.py`)

```python
class LLMMetadata(BaseModel):
    model_config = ConfigDict(strict=True)
    model_name: str
    tokens_in: int
    tokens_out: int
    latency_ms: float

class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    agent_id: str
    content: str
    llm_metadata: LLMMetadata
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### `Task` (dans `src/aaosa/schemas/task.py`)

```python
class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    required_tags: dict[str, int]
    acquirable_tags: dict[str, int] = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

---

## Etape 1 — Tests (RED)

Creer `tests/qa/test_protocol.py`. Tous les tests doivent echouer (module inexistant).

### Imports attendus

```python
from aaosa.qa.protocol import QAResult, QAEvaluator, QAFailure
from aaosa.schemas.task import Task
from aaosa.schemas.output import Output, LLMMetadata
```

### Tests QAResult

```python
class TestQAResult:
    def test_valid_qa_result(self):
        r = QAResult(
            task_id="t1",
            agent_id="a1",
            success=True,
            score=0.95,
            reason="All criteria met",
            criteria_results={"non_empty": True, "min_length": True},
        )
        assert r.success is True
        assert r.score == 0.95
        assert r.criteria_results == {"non_empty": True, "min_length": True}

    def test_qa_result_failure(self):
        r = QAResult(
            task_id="t1",
            agent_id="a1",
            success=False,
            score=0.3,
            reason="Too short",
            criteria_results={"non_empty": True, "min_length": False},
        )
        assert r.success is False
        assert r.score == 0.3

    def test_qa_result_score_zero(self):
        r = QAResult(
            task_id="t1", agent_id="a1", success=False,
            score=0.0, reason="Empty", criteria_results={},
        )
        assert r.score == 0.0

    def test_qa_result_score_one(self):
        r = QAResult(
            task_id="t1", agent_id="a1", success=True,
            score=1.0, reason="Perfect", criteria_results={"all": True},
        )
        assert r.score == 1.0

    def test_qa_result_empty_criteria(self):
        r = QAResult(
            task_id="t1", agent_id="a1", success=True,
            score=1.0, reason="No criteria", criteria_results={},
        )
        assert r.criteria_results == {}

    def test_qa_result_serialization_roundtrip(self):
        r = QAResult(
            task_id="t1", agent_id="a1", success=True,
            score=0.8, reason="ok", criteria_results={"c1": True},
        )
        data = r.model_dump()
        r2 = QAResult(**data)
        assert r2 == r

    def test_qa_result_json_roundtrip(self):
        r = QAResult(
            task_id="t1", agent_id="a1", success=True,
            score=0.8, reason="ok", criteria_results={"c1": True},
        )
        json_str = r.model_dump_json()
        r2 = QAResult.model_validate_json(json_str)
        assert r2 == r

    def test_qa_result_extra_fields_forbidden(self):
        """QAResult should reject unknown fields."""
        import pytest
        with pytest.raises(Exception):
            QAResult(
                task_id="t1", agent_id="a1", success=True,
                score=0.8, reason="ok", criteria_results={},
                unknown_field="oops",
            )
```

### Tests QAFailure

```python
class TestQAFailure:
    def test_valid_qa_failure(self):
        output = Output(
            task_id="t1", agent_id="a1", content="Short",
            llm_metadata=LLMMetadata(
                model_name="gpt-4o-mini", tokens_in=10,
                tokens_out=5, latency_ms=100.0,
            ),
        )
        qa_result = QAResult(
            task_id="t1", agent_id="a1", success=False,
            score=0.2, reason="Too short",
            criteria_results={"min_length": False},
        )
        f = QAFailure(
            task_id="t1", agent_id="a1",
            output=output, qa_result=qa_result,
        )
        assert f.output.content == "Short"
        assert f.qa_result.success is False

    def test_qa_failure_preserves_output(self):
        """QAFailure must store the rejected output for debugging."""
        output = Output(
            task_id="t1", agent_id="a1",
            content="Rejected content that should be preserved",
            llm_metadata=LLMMetadata(
                model_name="gpt-4o-mini", tokens_in=10,
                tokens_out=5, latency_ms=100.0,
            ),
        )
        qa_result = QAResult(
            task_id="t1", agent_id="a1", success=False,
            score=0.1, reason="Bad", criteria_results={},
        )
        f = QAFailure(task_id="t1", agent_id="a1", output=output, qa_result=qa_result)
        assert f.output.content == "Rejected content that should be preserved"

    def test_qa_failure_serialization_roundtrip(self):
        output = Output(
            task_id="t1", agent_id="a1", content="x",
            llm_metadata=LLMMetadata(
                model_name="gpt-4o-mini", tokens_in=10,
                tokens_out=5, latency_ms=100.0,
            ),
        )
        qa_result = QAResult(
            task_id="t1", agent_id="a1", success=False,
            score=0.0, reason="fail", criteria_results={},
        )
        f = QAFailure(task_id="t1", agent_id="a1", output=output, qa_result=qa_result)
        data = f.model_dump()
        f2 = QAFailure(**data)
        assert f2.task_id == f.task_id

    def test_qa_failure_extra_fields_forbidden(self):
        import pytest
        with pytest.raises(Exception):
            QAFailure(
                task_id="t1", agent_id="a1",
                output=None, qa_result=None,
                unknown="oops",
            )
```

### Tests QAEvaluator Protocol

```python
class TestQAEvaluatorProtocol:
    def test_class_with_evaluate_method_satisfies_protocol(self):
        """Any class with evaluate(task, output) -> QAResult satisfies QAEvaluator."""
        from typing import runtime_checkable

        class FakeEvaluator:
            def evaluate(self, task: Task, output: Output) -> QAResult:
                return QAResult(
                    task_id=task.id, agent_id=output.agent_id,
                    success=True, score=1.0, reason="ok",
                    criteria_results={},
                )

        evaluator = FakeEvaluator()
        assert isinstance(evaluator, QAEvaluator)

    def test_class_without_evaluate_does_not_satisfy(self):
        """A class without evaluate() does not satisfy QAEvaluator."""
        class NotAnEvaluator:
            pass

        assert not isinstance(NotAnEvaluator(), QAEvaluator)

    def test_protocol_is_runtime_checkable(self):
        """QAEvaluator must be runtime_checkable for isinstance checks."""
        from typing import runtime_checkable, Protocol as TypingProtocol
        # Should not raise
        assert issubclass(QAEvaluator, TypingProtocol)
```

---

## Etape 2 — Implementation (GREEN)

Creer `src/aaosa/qa/__init__.py` (vide) et `src/aaosa/qa/protocol.py`.

### `qa/protocol.py`

```python
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class QAResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    agent_id: str
    success: bool
    score: float          # 0.0-1.0
    reason: str
    criteria_results: dict[str, bool]


@runtime_checkable
class QAEvaluator(Protocol):
    def evaluate(self, task: Task, output: Output) -> QAResult: ...


class QAFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    agent_id: str
    output: Output        # output rejete (conserve pour debug + health check)
    qa_result: QAResult   # verdict QA
```

---

## Etape 3 — Tous les tests verts (REFACTOR si necessaire)

```powershell
.venv\Scripts\python -m pytest tests/qa/test_protocol.py -v
.venv\Scripts\python -m pytest tests/ -v
```

## Invariants a respecter

- Import absolu uniquement : `from aaosa.qa.protocol import ...`
- `QAEvaluator` est un `Protocol` avec `@runtime_checkable` (pour isinstance checks)
- `QAResult` et `QAFailure` ont `extra="forbid"` (coherent avec tous les schemas AAOSA)
- `QAFailure.output` stocke l'output rejete complet (pas juste un resume)
- Pas de logique metier dans ce fichier — uniquement des schemas et le protocol
