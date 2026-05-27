# V2a Subtask 03 — ELO Updater

_Statut: TODO_
_Depends on: subtask 01 (formula + constants)_
_Blocking: subtask 08 (runner V2), subtask 09 (health check)_

## Objectif

Implementer `update_agent_elo(agent, task, success) -> EloUpdateResult` qui mute `agent.tags_with_elo` et retourne un rapport complet des changements (deltas, acquisitions, snapshots before/after).

## Methode

TDD strict : ecrire tous les tests d'abord, verifier qu'ils echouent, puis implementer.

## Fichiers a creer

| Fichier | Action |
|---|---|
| `src/aaosa/elo/updater.py` | CREER — EloUpdateResult + update_agent_elo |
| `tests/elo/test_updater.py` | CREER — tests exhaustifs |

## Pre-requis

Les fichiers suivants doivent exister (subtask 01 completee) :

- `src/aaosa/schemas/elo.py` — contient `ELO_FLOOR`, `ELO_CEILING`, `ELO_K`, `ELO_MAX_DELTA`
- `src/aaosa/elo/__init__.py` — package init
- `src/aaosa/elo/formula.py` — `compute_delta(agent_elo, required_elo, success) -> int`

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/elo/test_updater.py -v
.venv\Scripts\python -m pytest tests/ -v   # V1 + subtask 01 tests doivent passer
```

---

## Context — Schemas existants

### `Agent` (dans `src/aaosa/core/agent.py`)

```python
class Agent(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    tags_with_elo: dict[str, int]
    system_prompt: str
```

`tags_with_elo` est un dict mutable. L'updater mute directement ce dict.

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

### `compute_delta` (dans `src/aaosa/elo/formula.py` — subtask 01)

```python
def compute_delta(agent_elo: int, required_elo: int, success: bool) -> int:
    # Retourne un int signe, clampe a [-ELO_MAX_DELTA, +ELO_MAX_DELTA]
```

### Constantes (dans `src/aaosa/schemas/elo.py`)

```python
ELO_FLOOR = 1
ELO_CEILING = 95  # = ELO_EXPERT_MAX
ELO_K = 5
ELO_MAX_DELTA = 10
```

---

## Etape 1 — Tests (RED)

Creer `tests/elo/test_updater.py`. Tous les tests doivent echouer (module inexistant).

### Imports attendus

```python
from aaosa.elo.updater import EloUpdateResult, update_agent_elo
from aaosa.core.agent import Agent
from aaosa.schemas.task import Task
from aaosa.schemas.elo import ELO_FLOOR, ELO_CEILING
```

### Schema EloUpdateResult attendu

```python
class EloUpdateResult(BaseModel):
    agent_id: str
    task_id: str
    success: bool
    deltas: dict[str, int]          # tag -> delta applique (apres clamp)
    acquired_tags: dict[str, int]   # tag -> ELO initial (nouveaux tags uniquement)
    elo_before: dict[str, int]      # snapshot avant
    elo_after: dict[str, int]       # snapshot apres
```

### Helpers

```python
def make_agent(tags: dict[str, int], name: str = "TestAgent") -> Agent:
    return Agent(name=name, tags_with_elo=tags, system_prompt="test")

def make_task(required: dict[str, int], acquirable: dict[str, int] | None = None) -> Task:
    return Task(
        description="test task",
        required_tags=required,
        acquirable_tags=acquirable or {},
    )
```

### Tests — Succes sur required_tags

```python
class TestUpdateAgentEloSuccess:
    def test_success_single_tag(self):
        """Succes, 1 required tag. Delta positif, agent mute."""
        agent = make_agent({"python": 50})
        task = make_task({"python": 50})
        result = update_agent_elo(agent, task, success=True)
        # compute_delta(50, 50, True) = round(5 * 50/50) = 5
        assert result.deltas == {"python": 5}
        assert result.elo_before == {"python": 50}
        assert result.elo_after == {"python": 55}
        assert agent.tags_with_elo["python"] == 55  # mutation

    def test_success_multiple_tags(self):
        """Succes, 2 required tags. Both updated."""
        agent = make_agent({"python": 50, "backend": 80})
        task = make_task({"python": 50, "backend": 30})
        result = update_agent_elo(agent, task, success=True)
        # python: round(5 * 50/50) = 5 -> 55
        # backend: round(5 * 30/80) = round(1.875) = 2 -> 82
        assert result.deltas["python"] == 5
        assert result.deltas["backend"] == 2
        assert agent.tags_with_elo["python"] == 55
        assert agent.tags_with_elo["backend"] == 82

    def test_success_ceiling_clamp(self):
        """Succes qui pousserait au-dessus de 95 -> clampe a 95."""
        agent = make_agent({"python": 92})
        task = make_task({"python": 92})
        result = update_agent_elo(agent, task, success=True)
        # delta = 5, 92+5 = 97 -> clamp to 95
        assert agent.tags_with_elo["python"] == ELO_CEILING
        assert result.elo_after["python"] == ELO_CEILING
```

### Tests — Echec sur required_tags

```python
class TestUpdateAgentEloFailure:
    def test_failure_single_tag(self):
        """Echec, 1 required tag. Delta negatif, agent mute."""
        agent = make_agent({"python": 50})
        task = make_task({"python": 50})
        result = update_agent_elo(agent, task, success=False)
        # compute_delta(50, 50, False) = round(-5 * 50/50) = -5
        assert result.deltas == {"python": -5}
        assert result.elo_before == {"python": 50}
        assert result.elo_after == {"python": 45}
        assert agent.tags_with_elo["python"] == 45

    def test_failure_floor_clamp(self):
        """Echec qui pousserait en dessous de 1 -> clampe a 1."""
        agent = make_agent({"python": 3})
        task = make_task({"python": 1})
        result = update_agent_elo(agent, task, success=False)
        # delta = round(-5 * 3/1) = -15, clampe a -10. 3 + (-10) = -7 -> floor = 1
        assert agent.tags_with_elo["python"] == ELO_FLOOR
        assert result.elo_after["python"] == ELO_FLOOR
```

### Tests — Tag acquisition (acquirable_tags)

```python
class TestUpdateAgentEloAcquisition:
    def test_success_acquires_new_tag(self):
        """Succes + acquirable tag absent -> acquisition au level requis."""
        agent = make_agent({"python": 50})
        task = make_task({"python": 50}, acquirable={"docker": 20})
        result = update_agent_elo(agent, task, success=True)
        assert "docker" in agent.tags_with_elo
        assert agent.tags_with_elo["docker"] == 20
        assert result.acquired_tags == {"docker": 20}

    def test_success_existing_acquirable_tag_updated(self):
        """Succes + acquirable tag deja present -> update normal (pas acquisition)."""
        agent = make_agent({"python": 50, "docker": 30})
        task = make_task({"python": 50}, acquirable={"docker": 20})
        result = update_agent_elo(agent, task, success=True)
        # docker: compute_delta(30, 20, True) = round(5 * 20/30) = round(3.33) = 3
        assert result.acquired_tags == {}  # pas une acquisition (tag existait)
        assert result.deltas["docker"] == 3
        assert agent.tags_with_elo["docker"] == 33

    def test_failure_no_acquisition(self):
        """Echec + acquirable tag absent -> PAS d'acquisition, PAS de penalite."""
        agent = make_agent({"python": 50})
        task = make_task({"python": 50}, acquirable={"docker": 20})
        result = update_agent_elo(agent, task, success=False)
        assert "docker" not in agent.tags_with_elo
        assert result.acquired_tags == {}
        assert "docker" not in result.deltas

    def test_failure_existing_acquirable_penalized(self):
        """Echec + acquirable tag present -> penalite normale (meme formule que required)."""
        agent = make_agent({"python": 50, "docker": 30})
        task = make_task({"python": 50}, acquirable={"docker": 20})
        result = update_agent_elo(agent, task, success=False)
        # python (required): compute_delta(50, 50, False) = -5 -> 45
        # docker (acquirable, present): compute_delta(30, 20, False) = round(-5 * 30/20) = round(-7.5) = -8 -> 22
        assert result.deltas["python"] == -5
        assert result.deltas["docker"] == -8
        assert agent.tags_with_elo["python"] == 45
        assert agent.tags_with_elo["docker"] == 22

    def test_failure_existing_acquirable_floor_clamp(self):
        """Echec + acquirable tag present avec ELO tres bas -> clampe au floor global (1)."""
        agent = make_agent({"python": 50, "docker": 3})
        task = make_task({"python": 50}, acquirable={"docker": 1})
        result = update_agent_elo(agent, task, success=False)
        # docker: compute_delta(3, 1, False) = round(-5 * 3/1) = -15 -> clamp -10. 3 + (-10) = -7 -> floor = 1
        assert agent.tags_with_elo["docker"] == ELO_FLOOR
```

### Tests — Snapshots et metadata

```python
class TestUpdateAgentEloMetadata:
    def test_elo_before_is_snapshot_before_mutation(self):
        """elo_before doit etre une copie AVANT mutation."""
        agent = make_agent({"python": 50})
        task = make_task({"python": 50})
        result = update_agent_elo(agent, task, success=True)
        assert result.elo_before == {"python": 50}
        assert result.elo_after == {"python": 55}

    def test_result_ids_match(self):
        agent = make_agent({"python": 50})
        task = make_task({"python": 50})
        result = update_agent_elo(agent, task, success=True)
        assert result.agent_id == agent.id
        assert result.task_id == task.id
        assert result.success is True

    def test_elo_before_is_independent_copy(self):
        """elo_before ne doit pas etre affecte par la mutation."""
        agent = make_agent({"python": 50})
        task = make_task({"python": 50})
        result = update_agent_elo(agent, task, success=True)
        agent.tags_with_elo["python"] = 999
        assert result.elo_before == {"python": 50}  # copie independante

    def test_no_acquirable_tags_field_empty(self):
        """Quand pas d'acquirable tags, acquired_tags est vide."""
        agent = make_agent({"python": 50})
        task = make_task({"python": 50})
        result = update_agent_elo(agent, task, success=True)
        assert result.acquired_tags == {}

    def test_untouched_tags_not_in_deltas(self):
        """Tags de l'agent non references par la task ne sont pas dans deltas."""
        agent = make_agent({"python": 50, "css": 80})
        task = make_task({"python": 50})
        result = update_agent_elo(agent, task, success=True)
        assert "css" not in result.deltas
        assert agent.tags_with_elo["css"] == 80  # inchange
```

---

## Etape 2 — Implementation (GREEN)

Creer `src/aaosa/elo/updater.py`.

### Signature

```python
from pydantic import BaseModel, ConfigDict
from aaosa.core.agent import Agent
from aaosa.schemas.task import Task
from aaosa.schemas.elo import ELO_FLOOR, ELO_CEILING
from aaosa.elo.formula import compute_delta


class EloUpdateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    task_id: str
    success: bool
    deltas: dict[str, int]
    acquired_tags: dict[str, int]
    elo_before: dict[str, int]
    elo_after: dict[str, int]


def update_agent_elo(agent: Agent, task: Task, success: bool) -> EloUpdateResult:
    ...
```

### Logique

1. `elo_before = dict(agent.tags_with_elo)` — copie avant mutation
2. Pour chaque tag dans `task.required_tags` :
   - `delta = compute_delta(agent.tags_with_elo[tag], required_elo, success)`
   - `agent.tags_with_elo[tag] = max(ELO_FLOOR, min(ELO_CEILING, old + delta))`
   - Stocker `deltas[tag] = delta`
3. Pour chaque tag dans `task.acquirable_tags` :
   - **Si `success`** :
     - Si tag absent : `agent.tags_with_elo[tag] = required_elo` (acquisition), stocker dans `acquired_tags`
     - Si tag present : meme formule que required (compute_delta avec success=True), stocker dans `deltas`
   - **Si echec** :
     - Si tag absent : ignorer (pas d'acquisition, pas de penalite)
     - Si tag present : meme formule que required (compute_delta avec success=False), stocker dans `deltas`, floor global = 1
4. `elo_after = dict(agent.tags_with_elo)` — copie apres mutation
5. Retourner `EloUpdateResult`

---

## Etape 3 — Tous les tests verts

```powershell
.venv\Scripts\python -m pytest tests/elo/test_updater.py -v
.venv\Scripts\python -m pytest tests/ -v
```

## Invariants a respecter

- Import absolu uniquement
- `update_agent_elo` mute `agent.tags_with_elo` directement (design decision V2a)
- `elo_before` et `elo_after` sont des copies independantes (pas des references au meme dict)
- `acquired_tags` ne contient QUE les tags nouvellement acquis, pas les tags existants mis a jour
- `deltas` ne contient PAS les tags acquis (leur "delta" est l'ELO initial, stocke dans `acquired_tags`)
- Floor/ceiling applique APRES le delta (pas dans `compute_delta`)
- Echec + acquirable tag absent = pas d'acquisition, pas de penalite (on ne peut pas penaliser un tag que l'agent n'a pas)
- Echec + acquirable tag present = penalite normale (meme formule que required, floor global = 1)
