# V2a Subtask 05 — Tracer Events V2

_Statut: TODO_
_Depends on: subtask 02 (QA schemas existent pour les types)_
_Blocking: subtask 06 (formatter V2), subtask 08 (runner V2)_

## Objectif

Ajouter 3 nouveaux event types au tracer : `QAEvaluatedEvent`, `EloUpdatedEvent`, `TagAcquiredEvent`. Mettre a jour la union `ClaimEvent` (5 -> 8 types).

## Methode

TDD strict : ecrire les tests d'abord, puis modifier le fichier existant.

## Fichiers a modifier/creer

| Fichier | Action |
|---|---|
| `src/aaosa/tracing/events.py` | MODIFIER — ajouter 3 events + mettre a jour ClaimEvent union |
| `tests/tracing/test_events_v2.py` | CREER — tests des nouveaux events |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/tracing/test_events_v2.py -v
.venv\Scripts\python -m pytest tests/ -v   # les 252 tests V1 + subtasks precedentes doivent passer
```

---

## Context — Fichier existant `tracing/events.py`

```python
from datetime import datetime, timezone
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class _BaseEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    task_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Phase1FilteredEvent(_BaseEvent):
    type: Literal["phase1_filtered"] = "phase1_filtered"
    agent_id: str
    passed: bool
    fit_score: float


class Phase2ClaimedEvent(_BaseEvent):
    type: Literal["phase2_claimed"] = "phase2_claimed"
    agent_id: str
    decision: Literal["claim", "no_claim"]
    justification: str


class DispatchedEvent(_BaseEvent):
    type: Literal["dispatched"] = "dispatched"
    agent_id: str
    reason: str


class ExecutedEvent(_BaseEvent):
    type: Literal["executed"] = "executed"
    agent_id: str
    output_summary: str


class UnassignedEvent(_BaseEvent):
    type: Literal["unassigned"] = "unassigned"
    reason: str


ClaimEvent = Annotated[
    Union[
        Phase1FilteredEvent,
        Phase2ClaimedEvent,
        DispatchedEvent,
        ExecutedEvent,
        UnassignedEvent,
    ],
    Field(discriminator="type"),
]
```

### Pattern a suivre

- Chaque event herite de `_BaseEvent` (qui a `extra="forbid"` herite — ne PAS re-declarer)
- Chaque event a un `type: Literal["xxx"] = "xxx"` (discriminator)
- La union `ClaimEvent` utilise `Field(discriminator="type")`

### `_BaseEvent` fournit :
- `session_id: str`
- `task_id: str`
- `timestamp: datetime` (auto UTC)

---

## Etape 1 — Tests (RED)

Creer `tests/tracing/test_events_v2.py`.

### Imports attendus

```python
from aaosa.tracing.events import (
    QAEvaluatedEvent,
    EloUpdatedEvent,
    TagAcquiredEvent,
    ClaimEvent,
)
```

### Tests QAEvaluatedEvent

```python
class TestQAEvaluatedEvent:
    def test_valid_event(self):
        e = QAEvaluatedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", success=True, score=0.95,
            reason="All criteria passed",
        )
        assert e.type == "qa_evaluated"
        assert e.success is True
        assert e.score == 0.95

    def test_failure_event(self):
        e = QAEvaluatedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", success=False, score=0.2,
            reason="Too short",
        )
        assert e.success is False

    def test_json_roundtrip(self):
        e = QAEvaluatedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", success=True, score=0.8,
            reason="ok",
        )
        data = e.model_dump_json()
        e2 = QAEvaluatedEvent.model_validate_json(data)
        assert e2.type == "qa_evaluated"
        assert e2.score == 0.8

    def test_extra_fields_rejected(self):
        import pytest
        with pytest.raises(Exception):
            QAEvaluatedEvent(
                session_id="s1", task_id="t1",
                agent_id="a1", success=True, score=0.8,
                reason="ok", extra_field="bad",
            )
```

### Tests EloUpdatedEvent

```python
class TestEloUpdatedEvent:
    def test_valid_event(self):
        e = EloUpdatedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", deltas={"python": 5, "backend": -3},
        )
        assert e.type == "elo_updated"
        assert e.deltas == {"python": 5, "backend": -3}

    def test_empty_deltas(self):
        e = EloUpdatedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", deltas={},
        )
        assert e.deltas == {}

    def test_json_roundtrip(self):
        e = EloUpdatedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", deltas={"css": 10},
        )
        data = e.model_dump_json()
        e2 = EloUpdatedEvent.model_validate_json(data)
        assert e2.deltas == {"css": 10}
```

### Tests TagAcquiredEvent

```python
class TestTagAcquiredEvent:
    def test_valid_event(self):
        e = TagAcquiredEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", tag="docker", initial_elo=20,
        )
        assert e.type == "tag_acquired"
        assert e.tag == "docker"
        assert e.initial_elo == 20

    def test_json_roundtrip(self):
        e = TagAcquiredEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", tag="k8s", initial_elo=15,
        )
        data = e.model_dump_json()
        e2 = TagAcquiredEvent.model_validate_json(data)
        assert e2.tag == "k8s"
        assert e2.initial_elo == 15
```

### Tests ClaimEvent union mise a jour

```python
class TestClaimEventUnionV2:
    def test_discriminator_qa_evaluated(self):
        """ClaimEvent union should accept QAEvaluatedEvent via discriminator."""
        from pydantic import TypeAdapter
        adapter = TypeAdapter(ClaimEvent)
        data = {
            "type": "qa_evaluated",
            "session_id": "s1", "task_id": "t1",
            "agent_id": "a1", "success": True, "score": 0.9,
            "reason": "ok",
        }
        event = adapter.validate_python(data)
        assert isinstance(event, QAEvaluatedEvent)

    def test_discriminator_elo_updated(self):
        from pydantic import TypeAdapter
        adapter = TypeAdapter(ClaimEvent)
        data = {
            "type": "elo_updated",
            "session_id": "s1", "task_id": "t1",
            "agent_id": "a1", "deltas": {"python": 5},
        }
        event = adapter.validate_python(data)
        assert isinstance(event, EloUpdatedEvent)

    def test_discriminator_tag_acquired(self):
        from pydantic import TypeAdapter
        adapter = TypeAdapter(ClaimEvent)
        data = {
            "type": "tag_acquired",
            "session_id": "s1", "task_id": "t1",
            "agent_id": "a1", "tag": "docker", "initial_elo": 20,
        }
        event = adapter.validate_python(data)
        assert isinstance(event, TagAcquiredEvent)

    def test_existing_types_still_work(self):
        """Les 5 types V1 doivent toujours fonctionner dans la union."""
        from pydantic import TypeAdapter
        from aaosa.tracing.events import Phase1FilteredEvent
        adapter = TypeAdapter(ClaimEvent)
        data = {
            "type": "phase1_filtered",
            "session_id": "s1", "task_id": "t1",
            "agent_id": "a1", "passed": True, "fit_score": 0.9,
        }
        event = adapter.validate_python(data)
        assert isinstance(event, Phase1FilteredEvent)
```

---

## Etape 2 — Implementation (GREEN)

Modifier `src/aaosa/tracing/events.py`. Ajouter les 3 classes AVANT la definition de `ClaimEvent`, puis mettre a jour la union.

### Classes a ajouter (apres `UnassignedEvent`, avant `ClaimEvent`)

```python
class QAEvaluatedEvent(_BaseEvent):
    type: Literal["qa_evaluated"] = "qa_evaluated"
    agent_id: str
    success: bool
    score: float
    reason: str


class EloUpdatedEvent(_BaseEvent):
    type: Literal["elo_updated"] = "elo_updated"
    agent_id: str
    deltas: dict[str, int]


class TagAcquiredEvent(_BaseEvent):
    type: Literal["tag_acquired"] = "tag_acquired"
    agent_id: str
    tag: str
    initial_elo: int
```

### Union mise a jour

```python
ClaimEvent = Annotated[
    Union[
        Phase1FilteredEvent,
        Phase2ClaimedEvent,
        DispatchedEvent,
        ExecutedEvent,
        UnassignedEvent,
        QAEvaluatedEvent,
        EloUpdatedEvent,
        TagAcquiredEvent,
    ],
    Field(discriminator="type"),
]
```

---

## Etape 3 — Tous les tests verts

```powershell
.venv\Scripts\python -m pytest tests/tracing/test_events_v2.py -v
.venv\Scripts\python -m pytest tests/ -v
```

## Invariants a respecter

- NE PAS modifier les 5 classes V1 existantes
- NE PAS re-declarer `model_config` dans les nouvelles classes (herite de `_BaseEvent`)
- Le discriminator `type` doit etre unique par classe (verifier qu'il n'y a pas de collision)
- Les imports existants dans d'autres fichiers (`from aaosa.tracing.events import ...`) ne doivent pas casser
- `Tracer.emit()` accepte `ClaimEvent` qui inclut maintenant les 8 types — pas de modification du tracer
