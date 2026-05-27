# V2a Subtask 06 — Tracer Formatter V2

_Statut: TODO_
_Depends on: subtask 05 (nouveaux event types)_
_Blocking: subtask 10 (demo V2)_

## Objectif

Ajouter le rendu des 3 nouveaux event types (`QAEvaluatedEvent`, `EloUpdatedEvent`, `TagAcquiredEvent`) dans le formatter de timeline.

## Methode

TDD strict : ecrire les tests d'abord, puis modifier le fichier existant.

## Fichiers a modifier

| Fichier | Action |
|---|---|
| `src/aaosa/tracing/formatter.py` | MODIFIER — ajouter 3 branches isinstance + import |
| `tests/tracing/test_formatter.py` | MODIFIER — ajouter tests pour les 3 nouveaux types |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/tracing/test_formatter.py -v
.venv\Scripts\python -m pytest tests/ -v
```

---

## Context — Fichier existant `tracing/formatter.py`

```python
from aaosa.tracing.events import (
    ClaimEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    DispatchedEvent,
    ExecutedEvent,
    UnassignedEvent,
)


def format_timeline(events: list[ClaimEvent]) -> str:
    """Timeline verticale, une ligne par event, triee par timestamp."""
    if not events:
        return ""

    sorted_events = sorted(events, key=lambda e: e.timestamp)

    lines = []
    for event in sorted_events:
        time_str = event.timestamp.strftime("%H:%M:%S")

        if isinstance(event, Phase1FilteredEvent):
            if event.passed:
                line = f"[{time_str}] PHASE1 {event.agent_id} -> passed (fit={event.fit_score:.2f})"
            else:
                line = f"[{time_str}] PHASE1 {event.agent_id} -> filtered"
            lines.append(line)

        elif isinstance(event, Phase2ClaimedEvent):
            justification = event.justification
            if len(justification) > 50:
                justification_display = justification[:50] + "..."
            else:
                justification_display = justification
            line = f"[{time_str}] PHASE2 {event.agent_id} -> {event.decision} ({justification_display})"
            lines.append(line)

        elif isinstance(event, DispatchedEvent):
            line = f"[{time_str}] DISPATCH -> {event.agent_id} ({event.reason})"
            lines.append(line)

        elif isinstance(event, ExecutedEvent):
            output_summary = event.output_summary
            if len(output_summary) > 60:
                output_display = output_summary[:60] + "..."
            else:
                output_display = output_summary
            line = f"[{time_str}] EXECUTED -> {event.agent_id} ({output_display})"
            lines.append(line)

        elif isinstance(event, UnassignedEvent):
            line = f"[{time_str}] UNASSIGNED -> {event.reason}"
            lines.append(line)

    return "\n".join(lines)


def print_timeline(events: list[ClaimEvent]) -> None:
    """Convenience wrapper that prints format_timeline to stdout."""
    print(format_timeline(events))
```

## Context — Format attendu (spec V2a)

```
[10:30:02] QA       Frontend -> PASS (score=1.00)
[10:30:02] ELO      Frontend -> frontend: +4, css: +3
[10:30:05] ACQUIRED Fullstack -> docker: 20 (new tag)
```

Les labels sont alignes sur 8 caracteres (`QA      `, `ELO     `, `ACQUIRED`) pour la lisibilite. Mais le pattern V1 n'aligne PAS les labels (PHASE1, PHASE2, DISPATCH, EXECUTED, UNASSIGNED sont tous de longueurs differentes sans padding). Pour rester coherent avec V1, NE PAS ajouter de padding — utiliser le meme pattern que V1 :

```
[10:30:02] QA Frontend -> PASS (score=1.00)
[10:30:02] ELO Frontend -> frontend: +4, css: +3
[10:30:05] ACQUIRED Fullstack -> docker: 20 (new tag)
```

---

## Etape 1 — Tests (RED)

Ajouter dans `tests/tracing/test_formatter.py`. Les tests doivent echouer (branches inexistantes).

### Imports a ajouter

```python
from aaosa.tracing.events import (
    QAEvaluatedEvent,
    EloUpdatedEvent,
    TagAcquiredEvent,
)
```

### Tests QAEvaluatedEvent formatting

```python
class TestFormatTimelineQAEvaluated:
    def test_qa_pass(self):
        event = QAEvaluatedEvent(
            session_id="s1", task_id="t1",
            agent_id="Frontend", success=True, score=1.0,
            reason="All criteria met",
            timestamp=datetime(2026, 5, 27, 10, 30, 2, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "[10:30:02] QA Frontend -> PASS (score=1.00)" in result

    def test_qa_fail(self):
        event = QAEvaluatedEvent(
            session_id="s1", task_id="t1",
            agent_id="Backend", success=False, score=0.30,
            reason="Too short",
            timestamp=datetime(2026, 5, 27, 10, 30, 5, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "[10:30:05] QA Backend -> FAIL (score=0.30)" in result

    def test_qa_score_formatting(self):
        """Score doit etre formate avec 2 decimales."""
        event = QAEvaluatedEvent(
            session_id="s1", task_id="t1",
            agent_id="A", success=True, score=0.5,
            reason="ok",
            timestamp=datetime(2026, 5, 27, 10, 0, 0, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "score=0.50" in result
```

### Tests EloUpdatedEvent formatting

```python
class TestFormatTimelineEloUpdated:
    def test_elo_single_tag(self):
        event = EloUpdatedEvent(
            session_id="s1", task_id="t1",
            agent_id="Frontend", deltas={"frontend": 4},
            timestamp=datetime(2026, 5, 27, 10, 30, 2, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "[10:30:02] ELO Frontend -> frontend: +4" in result

    def test_elo_multiple_tags(self):
        event = EloUpdatedEvent(
            session_id="s1", task_id="t1",
            agent_id="Frontend", deltas={"frontend": 4, "css": 3},
            timestamp=datetime(2026, 5, 27, 10, 30, 2, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        # Les deux tags doivent etre presents (ordre non garanti du dict)
        assert "frontend: +4" in result
        assert "css: +3" in result

    def test_elo_negative_delta(self):
        event = EloUpdatedEvent(
            session_id="s1", task_id="t1",
            agent_id="Backend", deltas={"python": -5},
            timestamp=datetime(2026, 5, 27, 10, 30, 3, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "python: -5" in result

    def test_elo_empty_deltas(self):
        event = EloUpdatedEvent(
            session_id="s1", task_id="t1",
            agent_id="A", deltas={},
            timestamp=datetime(2026, 5, 27, 10, 0, 0, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "[10:00:00] ELO A ->" in result
```

### Tests TagAcquiredEvent formatting

```python
class TestFormatTimelineTagAcquired:
    def test_tag_acquired(self):
        event = TagAcquiredEvent(
            session_id="s1", task_id="t1",
            agent_id="Fullstack", tag="docker", initial_elo=20,
            timestamp=datetime(2026, 5, 27, 10, 30, 5, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "[10:30:05] ACQUIRED Fullstack -> docker: 20 (new tag)" in result
```

### Tests mixed V1 + V2 events

```python
class TestFormatTimelineMixedV1V2:
    def test_v1_and_v2_events_sorted(self):
        """Mix of V1 and V2 events should sort by timestamp."""
        e1 = ExecutedEvent(
            session_id="s1", task_id="t1",
            agent_id="Frontend", output_summary="Done",
            timestamp=datetime(2026, 5, 27, 10, 0, 0, tzinfo=timezone.utc),
        )
        e2 = QAEvaluatedEvent(
            session_id="s1", task_id="t1",
            agent_id="Frontend", success=True, score=1.0, reason="ok",
            timestamp=datetime(2026, 5, 27, 10, 0, 1, tzinfo=timezone.utc),
        )
        e3 = EloUpdatedEvent(
            session_id="s1", task_id="t1",
            agent_id="Frontend", deltas={"frontend": 5},
            timestamp=datetime(2026, 5, 27, 10, 0, 2, tzinfo=timezone.utc),
        )
        result = format_timeline([e3, e1, e2])  # out of order
        lines = result.split("\n")
        assert len(lines) == 3
        assert "EXECUTED" in lines[0]
        assert "QA" in lines[1]
        assert "ELO" in lines[2]
```

---

## Etape 2 — Implementation (GREEN)

### Imports a ajouter dans `formatter.py`

```python
from aaosa.tracing.events import (
    # ... existants ...
    QAEvaluatedEvent,
    EloUpdatedEvent,
    TagAcquiredEvent,
)
```

### Branches a ajouter (apres le `elif isinstance(event, UnassignedEvent)`)

```python
        elif isinstance(event, QAEvaluatedEvent):
            verdict = "PASS" if event.success else "FAIL"
            line = f"[{time_str}] QA {event.agent_id} -> {verdict} (score={event.score:.2f})"
            lines.append(line)

        elif isinstance(event, EloUpdatedEvent):
            deltas_str = ", ".join(
                f"{tag}: {'+' if d > 0 else ''}{d}"
                for tag, d in event.deltas.items()
            )
            line = f"[{time_str}] ELO {event.agent_id} -> {deltas_str}"
            lines.append(line)

        elif isinstance(event, TagAcquiredEvent):
            line = f"[{time_str}] ACQUIRED {event.agent_id} -> {event.tag}: {event.initial_elo} (new tag)"
            lines.append(line)
```

---

## Etape 3 — Tous les tests verts

```powershell
.venv\Scripts\python -m pytest tests/tracing/test_formatter.py -v
.venv\Scripts\python -m pytest tests/ -v
```

## Invariants a respecter

- NE PAS modifier les branches V1 existantes
- NE PAS modifier `print_timeline` (wrapper inchange)
- Les tests V1 du formatter (20+ tests) doivent toujours passer sans modification
- Format delta : `+N` pour positif, `-N` pour negatif (le signe `-` vient naturellement de l'int)
- Score formate a 2 decimales (`:.2f`)
- Pas de padding/alignement des labels (coherent avec V1)
