# V2a Subtask 04 — ELO Persistence

_Statut: TODO_
_Depends on: subtask 01 (elo package existe)_
_Blocking: subtask 10 (demo V2)_

## Objectif

Implementer la persistence ELO par snapshot JSON : `save_snapshot`, `load_snapshot`, `apply_snapshot`. Match par `agent.name` (stable entre redemarrages), pas par UUID.

## Methode

TDD strict : ecrire tous les tests d'abord, verifier qu'ils echouent, puis implementer.

## Fichiers a creer

| Fichier | Action |
|---|---|
| `src/aaosa/elo/persistence.py` | CREER — schemas + 3 fonctions |
| `tests/elo/test_persistence.py` | CREER — tests exhaustifs |

## Pre-requis

- `src/aaosa/elo/__init__.py` existe (subtask 01)

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/elo/test_persistence.py -v
.venv\Scripts\python -m pytest tests/ -v
```

---

## Context — Agent schema

### `Agent` (dans `src/aaosa/core/agent.py`)

```python
class Agent(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    tags_with_elo: dict[str, int]
    system_prompt: str
```

`id` est un UUID regenere a chaque instanciation. `name` est stable.

### Layout fichier attendu

```
elo_snapshots/
├── latest.json               # ecrase a chaque save
└── 2026-05-27T10-30-00.json  # horodate
```

---

## Etape 1 — Tests (RED)

Creer `tests/elo/test_persistence.py`. Utiliser `tmp_path` (fixture pytest) pour l'isolation filesystem.

### Imports attendus

```python
from aaosa.elo.persistence import (
    AgentEloSnapshot,
    EloSnapshot,
    save_snapshot,
    load_snapshot,
    apply_snapshot,
)
from aaosa.core.agent import Agent
```

### Helpers

```python
def make_agent(name: str, tags: dict[str, int]) -> Agent:
    return Agent(name=name, tags_with_elo=tags, system_prompt="test")
```

### Tests — Schemas

```python
class TestAgentEloSnapshot:
    def test_valid_snapshot(self):
        s = AgentEloSnapshot(
            agent_name="Frontend",
            agent_id="uuid-1",
            tags_with_elo={"css": 85, "javascript": 80},
        )
        assert s.agent_name == "Frontend"

    def test_json_roundtrip(self):
        s = AgentEloSnapshot(
            agent_name="Backend",
            agent_id="uuid-2",
            tags_with_elo={"python": 90},
        )
        data = s.model_dump_json()
        s2 = AgentEloSnapshot.model_validate_json(data)
        assert s2.agent_name == s.agent_name
        assert s2.tags_with_elo == s.tags_with_elo


class TestEloSnapshot:
    def test_valid_snapshot(self):
        snap = EloSnapshot(
            timestamp=datetime.now(timezone.utc),
            agents=[
                AgentEloSnapshot(agent_name="A", agent_id="1", tags_with_elo={"x": 50}),
            ],
        )
        assert len(snap.agents) == 1

    def test_empty_agents_list(self):
        snap = EloSnapshot(
            timestamp=datetime.now(timezone.utc),
            agents=[],
        )
        assert snap.agents == []
```

### Tests — save_snapshot

```python
class TestSaveSnapshot:
    def test_save_creates_latest_json(self, tmp_path):
        agents = [make_agent("A", {"python": 50})]
        save_snapshot(agents, tmp_path)
        assert (tmp_path / "latest.json").exists()

    def test_save_creates_timestamped_file(self, tmp_path):
        agents = [make_agent("A", {"python": 50})]
        path = save_snapshot(agents, tmp_path)
        # Le fichier retourne doit exister et etre different de latest.json
        assert path.exists()
        assert path.name != "latest.json"

    def test_save_latest_matches_timestamped(self, tmp_path):
        agents = [make_agent("A", {"python": 50})]
        path = save_snapshot(agents, tmp_path)
        latest_content = (tmp_path / "latest.json").read_text(encoding="utf-8")
        timestamped_content = path.read_text(encoding="utf-8")
        assert latest_content == timestamped_content

    def test_save_multiple_agents(self, tmp_path):
        agents = [
            make_agent("A", {"python": 50}),
            make_agent("B", {"css": 80, "js": 60}),
        ]
        save_snapshot(agents, tmp_path)
        snap = load_snapshot(tmp_path / "latest.json")
        assert len(snap.agents) == 2

    def test_save_returns_path(self, tmp_path):
        agents = [make_agent("A", {"python": 50})]
        result = save_snapshot(agents, tmp_path)
        assert isinstance(result, Path)
```

### Tests — load_snapshot

```python
class TestLoadSnapshot:
    def test_load_roundtrip(self, tmp_path):
        agents = [make_agent("A", {"python": 50, "backend": 80})]
        save_snapshot(agents, tmp_path)
        snap = load_snapshot(tmp_path / "latest.json")
        assert len(snap.agents) == 1
        assert snap.agents[0].agent_name == "A"
        assert snap.agents[0].tags_with_elo == {"python": 50, "backend": 80}

    def test_load_nonexistent_raises(self, tmp_path):
        import pytest
        with pytest.raises(FileNotFoundError):
            load_snapshot(tmp_path / "nope.json")
```

### Tests — apply_snapshot

```python
class TestApplySnapshot:
    def test_apply_restores_elo(self, tmp_path):
        """Save -> modify agent -> apply -> ELO restored."""
        agent = make_agent("A", {"python": 50})
        save_snapshot([agent], tmp_path)
        agent.tags_with_elo["python"] = 99  # simulate drift
        snap = load_snapshot(tmp_path / "latest.json")
        apply_snapshot([agent], snap)
        assert agent.tags_with_elo["python"] == 50

    def test_apply_matches_by_name_not_id(self):
        """Agents with same name but different IDs should match."""
        agent1 = make_agent("A", {"python": 50})
        snap = EloSnapshot(
            timestamp=datetime.now(timezone.utc),
            agents=[AgentEloSnapshot(
                agent_name="A",
                agent_id="different-uuid",
                tags_with_elo={"python": 80},
            )],
        )
        apply_snapshot([agent1], snap)
        assert agent1.tags_with_elo["python"] == 80

    def test_apply_agent_not_in_snapshot_untouched(self):
        """Agent absent from snapshot should not be modified."""
        agent = make_agent("B", {"css": 60})
        snap = EloSnapshot(
            timestamp=datetime.now(timezone.utc),
            agents=[AgentEloSnapshot(
                agent_name="A", agent_id="1", tags_with_elo={"python": 80},
            )],
        )
        apply_snapshot([agent], snap)
        assert agent.tags_with_elo == {"css": 60}  # untouched

    def test_apply_snapshot_agent_absent_from_list_ignored(self):
        """Snapshot agent absent from agents list should be silently ignored."""
        agent = make_agent("A", {"python": 50})
        snap = EloSnapshot(
            timestamp=datetime.now(timezone.utc),
            agents=[
                AgentEloSnapshot(agent_name="A", agent_id="1", tags_with_elo={"python": 80}),
                AgentEloSnapshot(agent_name="Ghost", agent_id="2", tags_with_elo={"x": 10}),
            ],
        )
        apply_snapshot([agent], snap)  # should not raise
        assert agent.tags_with_elo["python"] == 80

    def test_apply_duplicate_agent_names_raises(self):
        """Duplicate names in agents list should raise ValueError."""
        import pytest
        a1 = make_agent("A", {"python": 50})
        a2 = make_agent("A", {"css": 60})
        snap = EloSnapshot(
            timestamp=datetime.now(timezone.utc),
            agents=[],
        )
        with pytest.raises(ValueError, match="duplicate"):
            apply_snapshot([a1, a2], snap)

    def test_apply_overwrites_all_tags(self):
        """apply_snapshot replaces the entire tags_with_elo dict, not just shared keys."""
        agent = make_agent("A", {"python": 50, "css": 30})
        snap = EloSnapshot(
            timestamp=datetime.now(timezone.utc),
            agents=[AgentEloSnapshot(
                agent_name="A", agent_id="1",
                tags_with_elo={"python": 80, "docker": 40},
            )],
        )
        apply_snapshot([agent], snap)
        assert agent.tags_with_elo == {"python": 80, "docker": 40}
```

---

## Etape 2 — Implementation (GREEN)

Creer `src/aaosa/elo/persistence.py`.

```python
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from aaosa.core.agent import Agent


class AgentEloSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_name: str
    agent_id: str
    tags_with_elo: dict[str, int]


class EloSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    agents: list[AgentEloSnapshot]


def save_snapshot(agents: list[Agent], directory: Path) -> Path:
    now = datetime.now(timezone.utc)
    snap = EloSnapshot(
        timestamp=now,
        agents=[
            AgentEloSnapshot(
                agent_name=a.name,
                agent_id=a.id,
                tags_with_elo=dict(a.tags_with_elo),
            )
            for a in agents
        ],
    )
    json_data = snap.model_dump_json(indent=2)

    # Timestamped file
    ts_name = now.strftime("%Y-%m-%dT%H-%M-%S") + ".json"
    ts_path = directory / ts_name
    ts_path.write_text(json_data, encoding="utf-8")

    # latest.json (overwrite)
    latest_path = directory / "latest.json"
    latest_path.write_text(json_data, encoding="utf-8")

    return ts_path


def load_snapshot(path: Path) -> EloSnapshot:
    if not path.exists():
        raise FileNotFoundError(f"Snapshot not found: {path}")
    return EloSnapshot.model_validate_json(path.read_text(encoding="utf-8"))


def apply_snapshot(agents: list[Agent], snapshot: EloSnapshot) -> None:
    names = [a.name for a in agents]
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate agent names: {[n for n in names if names.count(n) > 1]}")

    agent_by_name = {a.name: a for a in agents}
    for snap_agent in snapshot.agents:
        if snap_agent.agent_name in agent_by_name:
            agent_by_name[snap_agent.agent_name].tags_with_elo = dict(snap_agent.tags_with_elo)
```

---

## Etape 3 — Tous les tests verts

```powershell
.venv\Scripts\python -m pytest tests/elo/test_persistence.py -v
.venv\Scripts\python -m pytest tests/ -v
```

## Invariants a respecter

- Import absolu uniquement
- Match par `agent.name`, JAMAIS par `agent.id`
- `apply_snapshot` mute `agent.tags_with_elo` directement (remplace le dict entier)
- `apply_snapshot` ne raise pas si un snapshot agent n'est pas dans la liste
- `apply_snapshot` raise `ValueError` si noms dupliques dans la liste d'agents
- `save_snapshot` cree le directory si manquant ? NON — le caller gere ca. Le directory doit exister.
- Encoding UTF-8 explicite sur les read/write (Windows compat)
- `latest.json` est ecrase a chaque save (pas append)
