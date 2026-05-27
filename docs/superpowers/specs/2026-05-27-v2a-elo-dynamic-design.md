# V2a Design Spec — ELO Dynamique + QA Protocol

_Date: 2026-05-27_
_Statut: Validated_

## Scope

V2a = ELO mechanics + Dual QA protocol. Sous-parties V2b (QA complet) et V2c (Trace viewer) scaffoldees, detaillees dans une session ulterieure.

## Decisions prises

| Question | Decision |
|---|---|
| QA model | Dual QA: runtime (inline run_task) + health check (batch periodique) |
| QA interface | `QAEvaluator` Protocol (structural typing), caller injecte son impl |
| Runtime QA role | Gate de qualite + signal ELO immediat. Echecs alimentent le health check |
| Health check QA role | Verification systeme periodique sur test set cure (base + echecs accumules) |
| Persistence | In-memory + snapshot JSON (match par agent `name`, pas UUID) |
| Succes ELO | `delta = K * (required_elo / agent_elo)` per-tag |
| Echec ELO | `delta = -K * (agent_elo / required_elo)` per-tag (inverse asymetrique) |
| Bounds | K=5, clamp +/-10, floor=1, ceiling=95 |
| Tag acquisition | Succes + tag absent -> ajout au level requis, puis update normal |
| Architecture | Nouveaux packages `elo/` et `qa/` (Approche A) |
| V1 compat | `evaluator=None` dans `run_task` -> comportement V1 identique |

---

## 1. ELO Formula & Constants

### 1.1 Constants (dans `schemas/elo.py`)

```python
# V1 (inchange)
ELO_EXPERT_MIN = 85
ELO_EXPERT_MAX = 95
ELO_COMPETENT_MIN = 30
ELO_COMPETENT_MAX = 50
ELO_BASIC_MIN = 10
ELO_BASIC_MAX = 25
ELO_ACQUIRABLE_THRESHOLD = ELO_BASIC_MAX

# V2 additions
ELO_FLOOR = 1
ELO_CEILING = ELO_EXPERT_MAX  # 95
ELO_K = 5
ELO_MAX_DELTA = 10
```

### 1.2 Formula (dans `elo/formula.py`)

```python
def compute_delta(agent_elo: int, required_elo: int, success: bool) -> int:
    """Compute clamped ELO delta for a single tag.
    
    Success: delta = K * (required_elo / agent_elo)  -- ratio > 1 amplifies
    Failure: delta = -K * (agent_elo / required_elo) -- ratio > 1 amplifies
    """
```

Semantique:
- Succes sur tache facile (ratio < 1) -> gain faible
- Succes sur tache dure (ratio > 1) -> gain amplifie (clampe a MAX_DELTA)
- Echec sur tache facile (expert rate) -> penalite severe
- Echec sur tache dure (junior rate) -> penalite clemente
- Delta arrondi a int (ELO reste `dict[str, int]`)
- Clamp floor/ceiling applique apres le delta, pas dans la formule

### 1.3 Edge cases

- `agent_elo = 0` : impossible (floor=1 + validation existante)
- `required_elo = 0` : impossible (task validator rejette required_tags/acquirable_tags a 0)
- Division par zero : impossible par les deux gardes ci-dessus

---

## 2. ELO Updater & Tag Acquisition

### 2.1 Schema resultat (dans `elo/updater.py`)

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

### 2.2 Logique `update_agent_elo(agent, task, success) -> EloUpdateResult`

1. Snapshot `elo_before = dict(agent.tags_with_elo)`
2. Pour chaque tag dans `task.required_tags`:
   - `delta = compute_delta(agent.tags_with_elo[tag], required_elo, success)`
   - `new_elo = clamp(old + delta, FLOOR, CEILING)`
   - Mute `agent.tags_with_elo[tag] = new_elo`
3. Pour chaque tag dans `task.acquirable_tags` (si success uniquement):
   - Si tag absent chez l'agent -> `agent.tags_with_elo[tag] = required_elo` (acquisition)
   - Si tag deja present -> meme formule que required_tags (compute_delta avec success=True)
4. Acquirable tags sur echec: pas d'acquisition, pas de penalite (l'agent n'avait pas le tag)
5. Snapshot `elo_after = dict(agent.tags_with_elo)`
6. Return `EloUpdateResult`

### 2.3 Mutation directe

L'updater mute `agent.tags_with_elo` directement. L'Agent Pydantic V1 a un dict mutable. Coherent avec le principe "in-memory pendant le run, snapshot pour persister".

---

## 3. Dual QA Architecture

### 3.1 QA Protocol & Schema (dans `qa/protocol.py`)

```python
class QAResult(BaseModel):
    task_id: str
    agent_id: str
    success: bool
    score: float                       # 0.0-1.0 (V2b pourra exploiter la granularite)
    reason: str
    criteria_results: dict[str, bool]  # critere -> pass/fail (audit trail)

class QAEvaluator(Protocol):
    def evaluate(self, task: Task, output: Output) -> QAResult: ...
```

Le Protocol permet du structural typing: n'importe quel objet avec `evaluate(task, output) -> QAResult` est un QAEvaluator valide. Pas d'heritage requis.

### 3.2 Runtime QA (inline dans `run_task`)

**Signature V2 de `run_task`:**

```python
def run_task(
    task: Task,
    agents: list[Agent],
    client: OpenAI,
    evaluator: QAEvaluator | None = None,  # V2
    tracer: Tracer | None = None,
) -> Output | DispatchResult | QAFailure:   # V2: QAFailure possible
```

**Schema `QAFailure` (dans `qa/protocol.py`):**

```python
class QAFailure(BaseModel):
    task_id: str
    agent_id: str
    output: Output          # output rejete (conserve pour debug + health check)
    qa_result: QAResult     # verdict QA
```

**Pipeline V2:**

```
filter -> phase2 -> dispatch -> execute -> [QA evaluate] -> [ELO update]
                                                |
                                           success -> return Output (+ ELO up)
                                           failure -> return QAFailure (+ ELO down)
                                           no evaluator -> return Output (V1 compat)
```

**Backward compatibility:** `evaluator=None` -> pipeline V1 identique. 252 tests inchanges.

### 3.3 Health Check QA (batch separe, dans `qa/health_check.py`)

```python
def run_health_check(
    agents: list[Agent],
    test_suite: list[Task],       # cas de base + echecs accumules
    client: OpenAI,
    evaluator: QAEvaluator,
    tracer: Tracer | None = None,
) -> HealthCheckReport
```

**Schema `HealthCheckReport`:**

```python
class HealthCheckReport(BaseModel):
    timestamp: datetime
    total_tasks: int
    passed: int
    failed: int
    results: list[EloUpdateResult]
    qa_failures: list[QAFailure]
```

Le health check reutilise `run_task` V1 en interne. Les `QAFailure` du runtime sont conserves par le caller et passes en `test_suite` au prochain health check. V2a ne gere pas le stockage du test set (scope V2b).

### 3.4 BasicRuleEvaluator (impl demo, dans `qa/rule_based.py`)

Criteres deterministes simples: non-empty, min length (50 chars), references task tags. Suffisant pour valider la mecanique ELO en demo.

---

## 4. Persistence (Snapshot JSON)

### 4.1 Schemas (dans `elo/persistence.py`)

```python
class AgentEloSnapshot(BaseModel):
    agent_name: str              # cle de matching (stable entre redemarrages)
    agent_id: str                # audit only (UUID du dernier run)
    tags_with_elo: dict[str, int]

class EloSnapshot(BaseModel):
    timestamp: datetime
    agents: list[AgentEloSnapshot]
```

### 4.2 Operations

```python
def save_snapshot(agents: list[Agent], path: Path) -> Path:
    """Ecrit un snapshot horodate + ecrase latest.json."""

def load_snapshot(path: Path) -> EloSnapshot:
    """Charge un snapshot. FileNotFoundError si absent."""

def apply_snapshot(agents: list[Agent], snapshot: EloSnapshot) -> None:
    """Mute les agents depuis le snapshot. Match par agent name.
    Agents non trouves dans le snapshot: untouched.
    Snapshot agents absents de la liste: ignores.
    Raise ValueError si noms dupliques dans agents."""
```

### 4.3 Layout fichier

```
elo_snapshots/
├── latest.json
└── 2026-05-27T10-30-00.json
```

### 4.4 Matching par name

`apply_snapshot` matche par `agent_name` (stable). L'UUID est stocke pour audit mais n'est pas utilise pour le matching. Validation: noms uniques dans la liste d'agents (ValueError sinon).

### 4.5 Quand sauvegarder

Le caller decide. Patterns attendus:
- Apres health check: `run_health_check` -> `save_snapshot`
- Apres N runs: le caller compte et snapshot periodiquement
- V2a ne force pas le pattern.

---

## 5. Tracer Events V2

### 5.1 Nouveaux types (dans `tracing/events.py`)

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

La union `ClaimEvent` passe de 5 a 8 types. Discriminator `type` inchange.

### 5.2 Formatter V2 (dans `tracing/formatter.py`)

Ajout du rendu pour les 3 nouveaux types:

```
[10:30:02] QA       Frontend -> PASS (score=1.00)
[10:30:02] ELO      Frontend -> frontend: +4, css: +3
[10:30:05] ACQUIRED Fullstack -> docker: 20 (new tag)
```

---

## 6. Demo V2 update

`demo/run_demo.py` ajoute un `BasicRuleEvaluator` au pipeline:

```python
def run_demo():
    load_dotenv()
    client = create_client()
    evaluator = BasicRuleEvaluator()
    tracer = Tracer(session_id=str(uuid.uuid4()))

    for task in DEMO_TASKS:
        result = run_task(task, DEMO_AGENTS, client, evaluator=evaluator, tracer=tracer)
        # handle Output / QAFailure / DispatchResult

    print_timeline(tracer)
    save_snapshot(DEMO_AGENTS, Path("elo_snapshots"))
```

La demo V2 montre: pipeline complet, QA verdict par tache, deltas ELO dans la timeline, snapshot sauvegarde.

---

## 7. Architecture fichiers V2a

```
src/aaosa/
├── elo/                         # NOUVEAU V2
│   ├── __init__.py
│   ├── formula.py               # compute_delta (fonction pure)
│   ├── updater.py               # update_agent_elo -> EloUpdateResult
│   └── persistence.py           # save/load/apply snapshot JSON
├── qa/                          # NOUVEAU V2
│   ├── __init__.py
│   ├── protocol.py              # QAEvaluator Protocol, QAResult, QAFailure
│   ├── rule_based.py            # BasicRuleEvaluator (impl demo)
│   └── health_check.py          # run_health_check -> HealthCheckReport
├── schemas/elo.py               # V1 constants + V2 constants (K, MAX_DELTA, FLOOR, CEILING)
├── tracing/events.py            # + QAEvaluatedEvent, EloUpdatedEvent, TagAcquiredEvent
├── tracing/formatter.py         # + rendu 3 nouveaux event types
├── runtime/runner.py            # run_task V2 (+ evaluator param, + QAFailure return)
├── demo/run_demo.py             # V2 update (+ evaluator + snapshot)
└── (reste V1 inchange)

tests/                           # miroir
├── elo/
│   ├── test_formula.py
│   ├── test_updater.py
│   └── test_persistence.py
├── qa/
│   ├── test_protocol.py
│   ├── test_rule_based.py
│   └── test_health_check.py
├── tracing/test_formatter.py    # + tests nouveaux types
├── runtime/test_runner.py       # + tests evaluator/QAFailure
└── demo/test_demo.py            # + tests V2 demo
```

---

## 8. V2b / V2c Scaffolds (non detailles)

### V2b — QA complet

- Test set management (stockage, accumulation des echecs runtime)
- Injection de cas d'echec prioritaire (logique inversee Rodin)
- Train/test split protection (anti-overfitting)
- Evaluators specialises par domaine
- Score granulaire exploitation (au-dela du bool success)

### V2c — Trace viewer complet

- Timeline viewer web (HTML/JS) branche sur les JSONL tracer
- Grafana-like stats (claim rate, ELO distribution, QA pass rate, latence p50/p99)
- Vue ELO evolution par agent dans le temps
- Canal bidirectionnel advisory (agents consultent avant de claim)

---

## 9. Contraintes et invariants

- `tags_with_elo` reste `dict[str, int]` (pas de float)
- ELO floor=1, ceiling=95 enforces a l'application (pas dans la formule)
- Agent names uniques par deploiement (validation dans apply_snapshot et run_health_check)
- `evaluator=None` -> V1 behavior exact (backward compat)
- Les 252 tests V1 passent sans modification
- Le tracer reste optionnel (advisory) -- les ELO updates fonctionnent sans tracer
- Acquirable tags: pas d'acquisition sur echec, pas de penalite si tag absent
