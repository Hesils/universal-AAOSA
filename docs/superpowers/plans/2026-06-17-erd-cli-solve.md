# `aaosa solve` (task libre + N rosters injectés) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter une commande `aaosa solve` qui résout une tâche libre avec N rosters injectés depuis des chemins arbitraires, persiste trace/session/ELO et produit un manifest dérivé de la trace.

**Architecture:** Commande dédiée à côté de `run --scenario` (démo intacte). Le scaffolding session/meta/tracer/snapshot de `run_once` est factorisé en helper partagé `_persisted_run`. `solve_once` charge les rosters (agents.yaml + tools.py), construit le `provider_registry`, tague la tâche via `build_root_task` (extrait de `run_recovery`), exécute `run_with_recovery`, et dérive un `Manifest` pur de la trace.

**Tech Stack:** Python 3.14, Pydantic v2, Typer, pytest, importlib (chargement tools.py).

**Spec de référence :** `docs/superpowers/specs/2026-06-17-erd-cli-solve.md`.

## Global Constraints

- **Imports absolus uniquement** : `from aaosa.x.y import Z`, jamais relatifs.
- **Timestamps UTC** : `datetime.now(timezone.utc)`, jamais `datetime.utcnow()`.
- **Pydantic v2** : `model_config = ConfigDict(extra="forbid")` sur tout nouveau modèle.
- **Tests via le venv** : `.venv\Scripts\python -m pytest <fichier> -v`.
- **Rétrocompat dure** : `aaosa run --scenario {main|roster_gap}` et `demo/incident/*` restent bit-identiques en comportement ; suite globale verte (1073 tests au merge d6i).
- **Seuls `ollama`/`openai`** acceptés comme providers (enforcé par `create_provider`).
- **Tracer = observer découplé** : `build_manifest` est une fonction pure post-hoc.
- Commits fréquents, un par tâche.

## File Structure

- `src/aaosa/config/roster.py` (créé) — `load_roster` / `load_rosters` : agents.yaml + tools.py via `TOOL_REGISTRY`, cloisonnement, collision de noms.
- `src/aaosa/runtime/default_prompts.py` (créé) — prompts génériques divider/aggregator/tagger.
- `src/aaosa/runtime/provider_registry.py` (créé) — `build_provider_registry`.
- `src/aaosa/runtime/runner.py` (modifié) — extrait `build_root_task`, `run_recovery` devient emballage + gagne `context`.
- `src/aaosa/runtime/manifest.py` (créé) — `Manifest` + `build_manifest` (pur).
- `src/aaosa/cli/incident_runs.py` (modifié) — extrait `_persisted_run` / `_PersistedResult` ; `run_once` le consomme.
- `src/aaosa/cli/solve_runs.py` (créé) — `solve_once` + `SolveOutcome`.
- `src/aaosa/cli/app.py` (modifié) — commande `solve`.
- Tests miroir sous `tests/`.

---

### Task 1: Chargement des rosters (`config/roster.py`)

**Files:**
- Create: `src/aaosa/config/roster.py`
- Test: `tests/config/test_roster.py`

**Interfaces:**
- Consumes: `load_agents(path, tool_registry)` (existant), `ToolDef`, `Agent`.
- Produces: `load_roster(directory: Path) -> list[Agent]` ; `load_rosters(directories: list[Path]) -> list[Agent]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/config/test_roster.py
import textwrap
from pathlib import Path

import pytest

from aaosa.config.roster import load_roster, load_rosters

AGENTS_YAML = textwrap.dedent("""\
    - name: alice
      tags_with_elo: {python: 1500}
      system_prompt: You are alice.
    - name: bob
      tags_with_elo: {ops: 1500}
      system_prompt: You are bob.
""")

TOOLS_PY = textwrap.dedent("""\
    from aaosa.core.tool import ToolDef
    TOOL_REGISTRY = {
        "echo": ToolDef(name="echo", description="echo", parameters={"type": "object", "properties": {}}, fn=lambda: "ok"),
    }
""")


def _write_roster(dir: Path, agents_yaml: str, tools_py: str | None = None) -> Path:
    dir.mkdir(parents=True, exist_ok=True)
    (dir / "agents.yaml").write_text(agents_yaml, encoding="utf-8")
    if tools_py is not None:
        (dir / "tools.py").write_text(tools_py, encoding="utf-8")
    return dir


def test_load_roster_without_tools(tmp_path):
    d = _write_roster(tmp_path / "r1", AGENTS_YAML)
    agents = load_roster(d)
    assert {a.name for a in agents} == {"alice", "bob"}


def test_load_roster_resolves_tools_from_tool_registry(tmp_path):
    yaml = AGENTS_YAML + textwrap.dedent("""\
        - name: carol
          tags_with_elo: {python: 1500}
          system_prompt: You are carol.
          tools: [echo]
    """)
    d = _write_roster(tmp_path / "r2", yaml, TOOLS_PY)
    agents = load_roster(d)
    carol = next(a for a in agents if a.name == "carol")
    assert [t.name for t in carol.tools] == ["echo"]


def test_load_roster_missing_agents_yaml_raises(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(ValueError, match="agents.yaml"):
        load_roster(d)


def test_load_roster_tools_declared_without_tools_py_raises(tmp_path):
    yaml = textwrap.dedent("""\
        - name: dan
          tags_with_elo: {python: 1500}
          system_prompt: You are dan.
          tools: [missing]
    """)
    d = _write_roster(tmp_path / "r3", yaml)  # no tools.py
    with pytest.raises(ValueError):
        load_roster(d)


def test_load_roster_bad_tool_registry_type_raises(tmp_path):
    bad = "TOOL_REGISTRY = ['not', 'a', 'dict']\n"
    d = _write_roster(tmp_path / "r4", AGENTS_YAML, bad)
    with pytest.raises(ValueError, match="TOOL_REGISTRY"):
        load_roster(d)


def test_load_rosters_merges_and_detects_name_collision(tmp_path):
    a = _write_roster(tmp_path / "ra", AGENTS_YAML)
    b = _write_roster(tmp_path / "rb", "- name: alice\n  tags_with_elo: {x: 1500}\n  system_prompt: dup\n")
    with pytest.raises(ValueError, match="collision"):
        load_rosters([a, b])


def test_load_rosters_empty_list_raises(tmp_path):
    with pytest.raises(ValueError, match="at least one"):
        load_rosters([])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/config/test_roster.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aaosa.config.roster'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/aaosa/config/roster.py
"""Chargement de rosters (dossiers agents.yaml + tools.py optionnel).

Convention tools.py : un symbole TOOL_REGISTRY: dict[str, ToolDef] (pas d'auto-scan).
Importé via importlib (exécution de code au load — hypothèse rosters de confiance, erd).
Registres cloisonnés par roster ; collision de noms d'agents = erreur dure (clé ELO = name).
"""

import importlib.util
from pathlib import Path

from aaosa.config.loader import load_agents
from aaosa.core.agent import Agent
from aaosa.core.tool import ToolDef


def _load_tool_registry(directory: Path) -> dict[str, ToolDef] | None:
    """Importe directory/tools.py et retourne son TOOL_REGISTRY, ou None si absent."""
    tools_path = directory / "tools.py"
    if not tools_path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"_roster_tools_{directory.name}", tools_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load tools.py at {tools_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    registry = getattr(module, "TOOL_REGISTRY", None)
    if registry is None:
        raise ValueError(f"tools.py at {tools_path} must expose a TOOL_REGISTRY dict[str, ToolDef]")
    if not isinstance(registry, dict) or not all(
        isinstance(k, str) and isinstance(v, ToolDef) for k, v in registry.items()
    ):
        raise ValueError(f"TOOL_REGISTRY in {tools_path} must be a dict[str, ToolDef]")
    return registry


def load_roster(directory: Path) -> list[Agent]:
    """Charge UN roster : agents.yaml résolu contre le TOOL_REGISTRY de son tools.py."""
    directory = Path(directory)
    agents_path = directory / "agents.yaml"
    if not agents_path.exists():
        raise ValueError(f"Roster {directory} is missing agents.yaml")
    registry = _load_tool_registry(directory)
    return load_agents(agents_path, registry)


def load_rosters(directories: list[Path]) -> list[Agent]:
    """Charge N rosters et fusionne. Collision de noms d'agents -> ValueError."""
    if not directories:
        raise ValueError("load_rosters requires at least one roster directory")
    merged: list[Agent] = []
    seen: dict[str, Path] = {}
    for d in directories:
        d = Path(d)
        for agent in load_roster(d):
            if agent.name in seen:
                raise ValueError(
                    f"Agent name collision: {agent.name!r} in {d} "
                    f"already loaded from {seen[agent.name]}"
                )
            seen[agent.name] = d
            merged.append(agent)
    return merged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/config/test_roster.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/config/roster.py tests/config/test_roster.py
git commit -m "feat(config): load_roster/load_rosters (agents.yaml + tools.py via TOOL_REGISTRY) [erd]"
```

---

### Task 2: Prompts génériques (`runtime/default_prompts.py`)

**Files:**
- Create: `src/aaosa/runtime/default_prompts.py`
- Test: `tests/runtime/test_default_prompts.py`

**Interfaces:**
- Produces: `DIVIDER_PROMPT`, `AGGREGATOR_PROMPT`, `TAGGER_PROMPT` (str), domain-agnostic.

- [ ] **Step 1: Write the failing test**

```python
# tests/runtime/test_default_prompts.py
from aaosa.runtime import default_prompts


def test_prompts_are_nonempty_strings():
    for p in (default_prompts.DIVIDER_PROMPT, default_prompts.AGGREGATOR_PROMPT, default_prompts.TAGGER_PROMPT):
        assert isinstance(p, str) and p.strip()


def test_aggregator_prompt_is_domain_agnostic():
    # « incident » est le seul terme domaine de la version démo : il ne doit pas fuiter ici.
    assert "incident" not in default_prompts.AGGREGATOR_PROMPT.lower()
    assert "task" in default_prompts.AGGREGATOR_PROMPT.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_default_prompts.py -v`
Expected: FAIL with `ImportError: cannot import name 'default_prompts'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/aaosa/runtime/default_prompts.py
"""Prompts système génériques (domain-agnostic) pour `aaosa solve`.

Repris de demo/incident/prompts.py avec « incident » -> « task ». Run-level (1 par
run). Override par fichier custom = YAGNI (sous-ticket si besoin). La démo garde ses
propres prompts « incident » dans demo/incident/prompts.py (inchangé).
"""

DIVIDER_PROMPT = (
    "You are a task decomposer. Break the task into the minimal set of "
    "sub-tasks needed to fully resolve it. Express a dependency between two "
    "sub-tasks only when one genuinely needs the other's output. Prefer few, "
    "well-scoped sub-tasks."
)

AGGREGATOR_PROMPT = (
    "You are a synthesizer. Merge the sub-task results into one coherent, complete "
    "answer to the original task."
)

TAGGER_PROMPT = (
    "You assign capability tags to a task description. Use the roster vocabulary "
    "when it fits; name a real capability even if absent. Return at least one tag."
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_default_prompts.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/default_prompts.py tests/runtime/test_default_prompts.py
git commit -m "feat(runtime): default_prompts génériques (divider/aggregator/tagger) [erd]"
```

---

### Task 3: Construction du provider_registry (`runtime/provider_registry.py`)

**Files:**
- Create: `src/aaosa/runtime/provider_registry.py`
- Test: `tests/runtime/test_provider_registry.py`

**Interfaces:**
- Consumes: `create_provider(name)` (existant), `Agent`, `LLMProvider`.
- Produces: `build_provider_registry(agents, default_provider="ollama") -> tuple[LLMProvider, dict[str, LLMProvider]]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/runtime/test_provider_registry.py
import pytest

import aaosa.runtime.provider_registry as pr_mod
from aaosa.runtime.provider_registry import build_provider_registry


def _agent(name, provider=None):
    from aaosa.core.agent import Agent
    return Agent(name=name, tags_with_elo={"x": 1500}, system_prompt="p", provider=provider)


def test_registry_has_default_even_without_agent_providers(monkeypatch):
    monkeypatch.setattr(pr_mod, "create_provider", lambda name: f"prov:{name}")
    default, registry = build_provider_registry([_agent("a"), _agent("b")], default_provider="ollama")
    assert set(registry) == {"ollama"}
    assert default == "prov:ollama"


def test_registry_collects_distinct_agent_providers(monkeypatch):
    monkeypatch.setattr(pr_mod, "create_provider", lambda name: f"prov:{name}")
    agents = [_agent("a", "openai"), _agent("b", "ollama"), _agent("c", "openai")]
    default, registry = build_provider_registry(agents, default_provider="ollama")
    assert set(registry) == {"ollama", "openai"}
    assert default == "prov:ollama"


def test_unknown_provider_name_propagates(monkeypatch):
    def boom(name):
        raise ValueError(f"Unknown provider: {name!r}")
    monkeypatch.setattr(pr_mod, "create_provider", boom)
    with pytest.raises(ValueError, match="Unknown provider"):
        build_provider_registry([_agent("a", "weird")])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_provider_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aaosa.runtime.provider_registry'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/aaosa/runtime/provider_registry.py
"""Construction du registre de providers d'un run `solve`.

Noms distincts = {default_provider} ∪ {a.provider for a in agents if a.provider}.
create_provider lève déjà sur un nom != ollama|openai. Le registre câblé dans
RunContext.provider_registry active la résolution provider-par-agent (déjà codée
dans run_task). Défaut projet = ollama (gratuit).
"""

from aaosa.core.agent import Agent
from aaosa.runtime.llm_client import create_provider
from aaosa.runtime.providers import LLMProvider


def build_provider_registry(
    agents: list[Agent], default_provider: str = "ollama"
) -> tuple[LLMProvider, dict[str, LLMProvider]]:
    """Retourne (provider_par_défaut_du_run, registry_par_nom)."""
    names = {default_provider}
    names.update(a.provider for a in agents if a.provider)
    registry = {name: create_provider(name) for name in sorted(names)}
    return registry[default_provider], registry
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_provider_registry.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/provider_registry.py tests/runtime/test_provider_registry.py
git commit -m "feat(runtime): build_provider_registry (défaut ollama, noms distincts) [erd]"
```

---

### Task 4: Extraire `build_root_task`, `run_recovery` devient emballage + `context`

**Files:**
- Modify: `src/aaosa/runtime/runner.py:517-535`
- Test: `tests/runtime/test_build_root_task.py`
- (régression) `tests/runtime/test_run_recovery*.py` existants restent verts.

**Interfaces:**
- Consumes: `Task`, `RunContext`, `EmptyTaggingError`, `DEFAULT_REQUIRED_ELO`, `run_with_recovery` (tous déjà importés dans runner.py).
- Produces: `build_root_task(description, ctx, *, pinned_tags=None, context=None) -> Task` (lève `EmptyTaggingError` sur tagging vide). `run_recovery` gagne un param `context: str | None = None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/runtime/test_build_root_task.py
import pytest

from aaosa.runtime.runner import build_root_task, run_recovery
from aaosa.runtime.tagger import EmptyTaggingError
from aaosa.schemas.elo import DEFAULT_REQUIRED_ELO


class _FakeTagger:
    def __init__(self, tags):
        self._tags = set(tags)
    def tag(self, description, agents, provider):
        return self._tags


def _ctx(tagger):
    from aaosa.runtime.context import RunContext
    return RunContext(
        agents=[], provider=object(), divider=object(),
        aggregator=object(), tagger=tagger,
    )


def test_pinned_tags_skip_tagger_and_carry_context():
    ctx = _ctx(_FakeTagger([]))  # tagger must NOT be called
    task = build_root_task("do it", ctx, pinned_tags={"python": 1500}, context="ctx-here")
    assert task.required_tags == {"python": 1500}
    assert task.context == "ctx-here"


def test_tags_from_tagger_use_default_elo_and_carry_context():
    ctx = _ctx(_FakeTagger({"python"}))
    task = build_root_task("do it", ctx, context="provenance")
    assert task.required_tags == {"python": DEFAULT_REQUIRED_ELO}
    assert task.context == "provenance"


def test_empty_tagging_raises():
    ctx = _ctx(_FakeTagger(set()))
    with pytest.raises(EmptyTaggingError):
        build_root_task("do it", ctx)


def test_run_recovery_empty_tagging_returns_execution_failed():
    ctx = _ctx(_FakeTagger(set()))
    result = run_recovery("do it", ctx)
    from aaosa.claiming.dispatch import DispatchResult
    assert isinstance(result, DispatchResult)
    assert result.status == "execution_failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_build_root_task.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_root_task'`

- [ ] **Step 3: Write minimal implementation**

Replace `run_recovery` (runner.py:517-535) with `build_root_task` + thin wrapper:

```python
def build_root_task(
    description: str,
    ctx: RunContext,
    *,
    pinned_tags: dict[str, int] | None = None,
    context: str | None = None,
) -> Task:
    """Construit la Task racine : applique pinned_tags, sinon tague via ctx.tagger.
    Porte `context`. Lève EmptyTaggingError si le tagging ne produit aucun tag
    (le caller décide de la dégradation). Partagé par run_recovery et solve_once."""
    if pinned_tags:
        return Task(description=description, required_tags=pinned_tags, context=context)
    tags = ctx.tagger.tag(description, ctx.agents, ctx.provider)
    if not tags:
        raise EmptyTaggingError(description)
    return Task(
        description=description,
        required_tags={t: DEFAULT_REQUIRED_ELO for t in tags},
        context=context,
    )


def run_recovery(
    description: str,
    ctx: RunContext,
    pinned_tags: dict[str, int] | None = None,
    context: str | None = None,
) -> Output | DispatchResult | QAFailure:
    """Entrée publique D1. Tague la racine (sauf pinned_tags), porte `context`, puis
    délègue au cœur récursif. Tagging vide -> execution_failed (comportement V3)."""
    try:
        task = build_root_task(description, ctx, pinned_tags=pinned_tags, context=context)
    except EmptyTaggingError:
        return DispatchResult(
            status="execution_failed",
            agent_id=None,
            reason="tagging produced no tags",
        )
    return run_with_recovery(task, ctx, depth=0)
```

- [ ] **Step 4: Run test to verify it passes (new + regression)**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_build_root_task.py -v`
Expected: PASS (4 tests)

Run: `.venv\Scripts\python -m pytest tests/runtime/ -v`
Expected: PASS (toute la suite runner reste verte — `run_recovery` rétrocompat)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/runner.py tests/runtime/test_build_root_task.py
git commit -m "refactor(runner): extract build_root_task; run_recovery porte context [erd]"
```

---

### Task 5: Manifest dérivé de la trace (`runtime/manifest.py`)

**Files:**
- Create: `src/aaosa/runtime/manifest.py`
- Test: `tests/runtime/test_manifest.py`

**Interfaces:**
- Consumes: `ClaimEvent` (union events), `classify_run`, `Output`/`DispatchResult`/`QAFailure`.
- Produces: `Manifest`, `ToolCallRecord`, `FinalOutputRecord`, `build_manifest(events, result, trace_path: str) -> Manifest`.

- [ ] **Step 1: Write the failing test**

```python
# tests/runtime/test_manifest.py
from aaosa.runtime.manifest import build_manifest, Manifest
from aaosa.schemas.output import Output
from aaosa.claiming.dispatch import DispatchResult
from aaosa.tracing.events import ExecutedEvent, RosterGapEvent, ToolCalledEvent


def _executed(task_id="t1", agent_id="a1", content="answer"):
    return ExecutedEvent(session_id="s", task_id=task_id, agent_id=agent_id,
                         output_summary=content[:100], output_content=content)


def _tool(agent_id="a1", name="search", args=None, result="hit"):
    return ToolCalledEvent(session_id="s", task_id="t1", agent_id=agent_id,
                           tool_name=name, arguments=args or {"q": "x"}, result=result, latency_ms=1.0)


def test_manifest_from_successful_output():
    events = [_tool(), _executed()]
    result = Output(task_id="t1", agent_id="a1", content="answer")
    m = build_manifest(events, result, "trace.jsonl")
    assert isinstance(m, Manifest)
    assert m.outcome == "success"
    assert m.typologies == ["simple"]
    assert [o.content for o in m.final_outputs] == ["answer"]
    assert m.tool_calls[0].tool_name == "search"
    assert m.trace_path == "trace.jsonl"
    assert m.roster_gaps == []


def test_manifest_roster_gap_is_surfaced_not_a_bug():
    events = [RosterGapEvent(session_id="s", task_id="t1", missing_tags=["forensics"])]
    result = DispatchResult(status="roster_gap", agent_id=None, reason="no agent")
    m = build_manifest(events, result, "trace.jsonl")
    assert m.outcome == "unassigned"
    assert m.roster_gaps == ["forensics"]
    assert m.final_outputs == []


def test_manifest_divided_run_takes_last_executed_as_final():
    events = [_executed(task_id="sub1", content="part1"), _executed(task_id="sub2", content="part2")]
    result = DispatchResult(status="unassigned", agent_id=None, reason="divided then merged elsewhere")
    # outcome unassigned mais un Output terminal existe dans la trace (run divisé court-circuité)
    m = build_manifest(events, result, "trace.jsonl")
    assert m.final_outputs[-1].content == "part2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aaosa.runtime.manifest'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/aaosa/runtime/manifest.py
"""Manifest d'un run `solve` — fonction PURE dérivée de la trace + résultat.

Post-hoc (suit classify_run, respecte « tracer = observer découplé »). Le runtime
n'imprime/ne juge jamais lui-même. tool-calls « déclarés » (ToolCalledEvent), pas
FS-diff des effets réels (plus tard, lié v1m). roster_gap = signal (création d'agent
côté AIOS), pas un bug.
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from aaosa.claiming.dispatch import DispatchResult
from aaosa.qa.protocol import QAFailure
from aaosa.schemas.output import Output
from aaosa.tracing.analysis import classify_run
from aaosa.tracing.events import (
    ClaimEvent,
    ExecutedEvent,
    RosterGapEvent,
    TaskAggregatedEvent,
    ToolCalledEvent,
)


class ToolCallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    tool_name: str
    arguments: dict
    result: str


class FinalOutputRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    agent_id: str
    content: str


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: str
    typologies: list[str]
    final_outputs: list[FinalOutputRecord]
    tool_calls: list[ToolCallRecord]
    roster_gaps: list[str]
    trace_path: str


def _outcome(result: Output | DispatchResult | QAFailure) -> str:
    """Même vocabulaire que cli.incident_runs._result_kind (success|qa_fail|unassigned)."""
    if isinstance(result, Output):
        return "success"
    if isinstance(result, QAFailure):
        return "qa_fail"
    if result.status == "qa_failed":
        return "qa_fail"
    return "unassigned"


def _final_outputs(
    events: Sequence[ClaimEvent], result: Output | DispatchResult | QAFailure
) -> list[FinalOutputRecord]:
    if isinstance(result, Output):
        return [FinalOutputRecord(task_id=result.task_id, agent_id=result.agent_id, content=result.content)]
    # Run divisé / agrégé : dernier event porteur de contenu terminal dans la trace.
    for e in reversed(list(events)):
        if isinstance(e, TaskAggregatedEvent):
            return [FinalOutputRecord(task_id=e.task_id, agent_id="aggregator", content=e.output_content)]
        if isinstance(e, ExecutedEvent) and e.output_content is not None:
            return [FinalOutputRecord(task_id=e.task_id, agent_id=e.agent_id, content=e.output_content)]
    return []


def build_manifest(
    events: Sequence[ClaimEvent],
    result: Output | DispatchResult | QAFailure,
    trace_path: str,
) -> Manifest:
    """Dérive le manifest de la trace + résultat. Aucune I/O (la persistance est au caller)."""
    roster_gaps: list[str] = []
    for e in events:
        if isinstance(e, RosterGapEvent):
            roster_gaps.extend(e.missing_tags)
    tool_calls = [
        ToolCallRecord(agent_id=e.agent_id, tool_name=e.tool_name, arguments=e.arguments, result=e.result)
        for e in events
        if isinstance(e, ToolCalledEvent)
    ]
    return Manifest(
        outcome=_outcome(result),
        typologies=classify_run(events),
        final_outputs=_final_outputs(events, result),
        tool_calls=tool_calls,
        roster_gaps=roster_gaps,
        trace_path=trace_path,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_manifest.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/manifest.py tests/runtime/test_manifest.py
git commit -m "feat(runtime): build_manifest pur (outcome + tool-calls + roster_gaps) [erd]"
```

---

### Task 6: Factoriser le scaffolding (`incident_runs._persisted_run`)

**Files:**
- Modify: `src/aaosa/cli/incident_runs.py:116-203` (`run_once`)
- Test: régression — `tests/cli/` existants (`run_once`/`campaign`) restent verts.

**Interfaces:**
- Produces: `_PersistedResult` (dataclass : kind, session_id, session_dir, snapshot_path, tracer, task, result) ; `_persisted_run(agents, runs_root, build_ctx, make_task) -> _PersistedResult` où `build_ctx: Callable[[StreamingTracer], RunContext]` et `make_task: Callable[[RunContext], Task]`.
- Consumes (par `solve_runs`): `_persisted_run`, `_PersistedResult`, `load_elo_into`.

- [ ] **Step 1: Write the failing test (régression d'abord)**

Aucun nouveau test de comportement : la factorisation doit être transparente. Vérifier que la suite existante passe AVANT de refactorer (filet), puis APRÈS.

Run (filet avant) : `.venv\Scripts\python -m pytest tests/cli/ -v`
Expected: PASS (état actuel). Noter le nombre de tests.

- [ ] **Step 2: Extraire `_persisted_run` et faire consommer `run_once`**

Ajouter `from collections.abc import Callable` n'est pas nécessaire (déjà importé ligne 7). Ajouter l'import `Task` :

```python
from aaosa.schemas.task import Task
```

Ajouter le dataclass + helper (après `RunOutcome`, avant `_result_kind`) :

```python
@dataclass(frozen=True)
class _PersistedResult:
    """Sortie du scaffolding partagé : tout ce dont run_once/solve_once ont besoin."""
    kind: RunKind
    session_id: str
    session_dir: Path
    snapshot_path: Path
    tracer: "StreamingTracer"
    task: Task
    result: object  # Output | DispatchResult | QAFailure


def _persisted_run(
    agents: list[Agent],
    runs_root: Path,
    build_ctx: "Callable[[StreamingTracer], RunContext]",
    make_task: "Callable[[RunContext], Task]",
) -> _PersistedResult:
    """Scaffolding commun à run_once/solve_once : session + meta provisoire (live) +
    trace streamée + exécution contenue + finalisation + snapshot ELO mono-store.

    L'ordre place tracer/ctx avant make_task (solve tague via ctx.tagger ; le tagger
    n'émet aucun event -> le meta provisoire reste antérieur au run)."""
    session_id = new_session_id()
    started_at = datetime.now(timezone.utc)
    session_dir = runs_root / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    tracer = StreamingTracer(session_id=session_id, stream_path=session_dir / "trace.jsonl")
    ctx = build_ctx(tracer)
    task = make_task(ctx)

    def _meta(status: str, ended_at: datetime, outcome: str) -> SessionMeta:
        return SessionMeta(
            session_id=session_id,
            started_at=started_at,
            ended_at=ended_at,
            tasks=[
                SessionTaskRecord(
                    id=task.id,
                    description=task.description,
                    winner_agent_id=None,
                    outcome=outcome,
                    required_tags=task.required_tags,
                    context=task.context,
                )
            ],
            agent_ids=[a.id for a in agents],
            status=status,
        )

    provisional = _meta("running", started_at, "divided")
    (session_dir / "meta.json").write_text(provisional.model_dump_json(indent=2), encoding="utf-8")
    save_agent_registry(agents, session_dir / "agents.json")

    try:
        result = run_with_recovery(task, ctx)
    except Exception:
        (session_dir / "meta.json").write_text(
            _meta("complete", datetime.now(timezone.utc), "unassigned").model_dump_json(indent=2),
            encoding="utf-8",
        )
        raise
    finally:
        tracer.close()

    kind = _result_kind(result)
    save_agent_registry(agents, runs_root / "agents" / "registry.json")
    meta = _meta("complete", datetime.now(timezone.utc), _META_OUTCOME[kind])
    session_dir = save_session(tracer, meta, runs_root, agents=agents)

    snapshot_dir = runs_root / "elo_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = save_snapshot(agents, snapshot_dir)

    return _PersistedResult(
        kind=kind, session_id=session_id, session_dir=session_dir,
        snapshot_path=snapshot_path, tracer=tracer, task=task, result=result,
    )
```

Remplacer le corps de `run_once` (lignes 116-203) par :

```python
def run_once(scenario: str, runs_root: Path, provider: LLMProvider) -> RunOutcome:
    """Un run incident complet, observable en live. Consomme le scaffolding partagé
    `_persisted_run` (identique à l'inline d'origine ; prompts/évaluateur incident)."""
    agents = _ROSTERS[scenario]()
    load_elo_into(agents, runs_root)

    def build_ctx(tracer: StreamingTracer) -> RunContext:
        return RunContext(
            agents=agents,
            provider=provider,
            divider=TaskDivider(system_prompt=DIVIDER_PROMPT),
            aggregator=TaskAggregator(system_prompt=AGGREGATOR_PROMPT),
            tagger=Tagger(system_prompt=TAGGER_PROMPT),
            tracer=tracer,
            evaluator=AdaptiveSpecEvaluator(provider),
        )

    pr = _persisted_run(agents, runs_root, build_ctx, make_task=lambda ctx: build_data_leak_task())
    return RunOutcome(
        kind=pr.kind,
        session_id=pr.session_id,
        session_dir=pr.session_dir,
        snapshot_path=pr.snapshot_path,
        events=list(pr.tracer.events),
        task_description=pr.task.description,
        n_agents=len(agents),
    )
```

- [ ] **Step 3: Run regression to verify identical behavior**

Run: `.venv\Scripts\python -m pytest tests/cli/ -v`
Expected: PASS (même nombre qu'au Step 1)

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS (suite globale verte — la factorisation est transparente)

- [ ] **Step 4: Commit**

```bash
git add src/aaosa/cli/incident_runs.py
git commit -m "refactor(cli): extract _persisted_run scaffolding partagé run_once/solve [erd]"
```

---

### Task 7: `solve_once` (`cli/solve_runs.py`)

**Files:**
- Create: `src/aaosa/cli/solve_runs.py`
- Test: `tests/cli/test_solve_runs.py`

**Interfaces:**
- Consumes: `load_rosters`, `build_provider_registry`, `build_root_task`, `run_with_recovery`, `_persisted_run`, `_PersistedResult`, `load_elo_into`, `build_manifest`, `default_prompts`, `RunContext`, `TaskDivider`, `TaskAggregator`, `Tagger`, `AdaptiveSpecEvaluator`.
- Produces: `SolveOutcome` ; `solve_once(roster_dirs, task_text, context, runs_root, provider_name="ollama") -> SolveOutcome`. Lève `EmptyTaggingError` si la tâche ne produit aucun tag (caller CLI -> Exit 1).

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_solve_runs.py
import textwrap
from pathlib import Path

import pytest

from aaosa.cli.solve_runs import solve_once, SolveOutcome
from aaosa.runtime.tagger import EmptyTaggingError


class _FakeProvider:
    """Provider factice : parse() renvoie selon le schéma, complete() renvoie un message."""
    def __init__(self, content="done"):
        self._content = content
    def complete(self, *, messages, model=None, tools=None, **kwargs):
        class _Msg: 
            def __init__(s, c): s.content = c; s.tool_calls = None
        class _Choice:
            def __init__(s, c): s.message = _Msg(c); s.finish_reason = "stop"
        class _Usage:
            prompt_tokens = 1; completion_tokens = 1
        class _Resp:
            model = "fake"; usage = _Usage()
            def __init__(s, c): s.choices = [_Choice(c)]
        return _Resp(self._content)
    def parse(self, *, messages, schema, model=None, **kwargs):
        # TagSet -> 1 tag matchant le roster ; Claim -> claim ; sinon best-effort
        from aaosa.runtime.tagger import TagSet
        from aaosa.schemas.claim import Claim
        if schema is TagSet:
            return TagSet(tags=["python"])
        if schema is Claim:
            return Claim(agent_id="x", task_id="y", decision="claim", justification="fit")
        try:
            return schema()
        except Exception:
            return None


AGENTS_YAML = textwrap.dedent("""\
    - name: solo
      tags_with_elo: {python: 1500}
      system_prompt: You solve tasks.
""")


def _roster(dir: Path) -> Path:
    dir.mkdir(parents=True, exist_ok=True)
    (dir / "agents.yaml").write_text(AGENTS_YAML, encoding="utf-8")
    return dir


def _patch_provider(monkeypatch):
    import aaosa.cli.solve_runs as mod
    monkeypatch.setattr(mod, "build_provider_registry",
                        lambda agents, provider_name="ollama": (_FakeProvider(), {provider_name: _FakeProvider()}))
    # l'évaluateur LLM-judge ne doit pas tourner en test : forcer un evaluator None.
    monkeypatch.setattr(mod, "AdaptiveSpecEvaluator", lambda provider: None)


def test_solve_once_produces_session_trace_and_manifest(tmp_path, monkeypatch):
    _patch_provider(monkeypatch)
    roster = _roster(tmp_path / "r")
    runs_root = tmp_path / "runs"
    outcome = solve_once([roster], "write a python function", context="# context: inline\nhello", runs_root=runs_root)
    assert isinstance(outcome, SolveOutcome)
    assert (outcome.session_dir / "trace.jsonl").exists()
    assert outcome.manifest_path.exists()
    assert outcome.manifest_path.name == "manifest.json"
    # mono-store ELO
    assert (runs_root / "elo_snapshots" / "latest.json").exists()


def test_solve_once_empty_tagging_raises(tmp_path, monkeypatch):
    import aaosa.cli.solve_runs as mod
    monkeypatch.setattr(mod, "build_provider_registry",
                        lambda agents, provider_name="ollama": (_FakeProvider(), {}))
    monkeypatch.setattr(mod, "AdaptiveSpecEvaluator", lambda provider: None)
    # tagger renvoie set() -> EmptyTaggingError
    monkeypatch.setattr("aaosa.runtime.tagger.Tagger.tag", lambda self, d, a, p: set())
    roster = _roster(tmp_path / "r")
    with pytest.raises(EmptyTaggingError):
        solve_once([roster], "ambiguous", context=None, runs_root=tmp_path / "runs")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/cli/test_solve_runs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aaosa.cli.solve_runs'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/aaosa/cli/solve_runs.py
"""Helper pur de `aaosa solve` (zéro print, zéro Typer).

Parallèle à incident_runs.run_once : tâche LIBRE + N rosters injectés + provider_registry
câblé (défaut ollama) + prompts génériques + manifest dérivé de la trace. Partage le
scaffolding session/meta/tracer/snapshot via incident_runs._persisted_run.
"""

from dataclasses import dataclass, replace
from pathlib import Path

from aaosa.cli.incident_runs import RunKind, _persisted_run, load_elo_into
from aaosa.config.roster import load_rosters
from aaosa.qa.spec_evaluator import AdaptiveSpecEvaluator
from aaosa.runtime import default_prompts
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.manifest import build_manifest
from aaosa.runtime.provider_registry import build_provider_registry
from aaosa.runtime.runner import build_root_task
from aaosa.runtime.tagger import Tagger
from aaosa.tracing.events import ClaimEvent


@dataclass(frozen=True)
class SolveOutcome:
    kind: RunKind
    session_id: str
    session_dir: Path
    snapshot_path: Path
    manifest_path: Path
    events: list[ClaimEvent]
    task_description: str
    n_agents: int


def solve_once(
    roster_dirs: list[Path],
    task_text: str,
    context: str | None,
    runs_root: Path,
    provider_name: str = "ollama",
) -> SolveOutcome:
    """Résout une tâche libre avec N rosters injectés. Lève EmptyTaggingError si la
    tâche ne produit aucun tag (le caller CLI traduit en Exit 1)."""
    agents = load_rosters(roster_dirs)
    provider, registry = build_provider_registry(agents, provider_name)
    load_elo_into(agents, runs_root)

    # pre_ctx (tracer=None) pour taguer la racine AVANT toute création de session :
    # un échec de tagging ne doit pas laisser de session demi-écrite. build_root_task
    # n'utilise que tagger/agents/provider, jamais le tracer.
    pre_ctx = RunContext(
        agents=agents,
        provider=provider,
        divider=TaskDivider(system_prompt=default_prompts.DIVIDER_PROMPT),
        aggregator=TaskAggregator(system_prompt=default_prompts.AGGREGATOR_PROMPT),
        tagger=Tagger(system_prompt=default_prompts.TAGGER_PROMPT),
        tracer=None,
        evaluator=AdaptiveSpecEvaluator(provider),
        provider_registry=registry,
    )
    task = build_root_task(task_text, pre_ctx, context=context)  # peut lever EmptyTaggingError

    pr = _persisted_run(
        agents,
        runs_root,
        build_ctx=lambda tracer: replace(pre_ctx, tracer=tracer),
        make_task=lambda ctx: task,
    )

    manifest = build_manifest(list(pr.tracer.events), pr.result, "trace.jsonl")
    manifest_path = pr.session_dir / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    return SolveOutcome(
        kind=pr.kind,
        session_id=pr.session_id,
        session_dir=pr.session_dir,
        snapshot_path=pr.snapshot_path,
        manifest_path=manifest_path,
        events=list(pr.tracer.events),
        task_description=pr.task.description,
        n_agents=len(agents),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/cli/test_solve_runs.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/cli/solve_runs.py tests/cli/test_solve_runs.py
git commit -m "feat(cli): solve_once (task libre + N rosters + manifest, mono-store) [erd]"
```

---

### Task 8: Commande CLI `aaosa solve` (`cli/app.py`)

**Files:**
- Modify: `src/aaosa/cli/app.py` (imports + nouvelle commande `solve`)
- Test: `tests/cli/test_app_solve.py`

**Interfaces:**
- Consumes: `solve_once`, `SolveOutcome`, `EmptyTaggingError`.
- Produces: commande Typer `solve` (options §3 de la spec). Assemble le contexte (en-têtes `# context: <source>`), garde-fou overflow (`Exit 1`), traduit erreurs roster/tagging en `Exit 1`.

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_app_solve.py
from pathlib import Path

from typer.testing import CliRunner

import aaosa.cli.app as app_mod
from aaosa.cli.app import app
from aaosa.cli.solve_runs import SolveOutcome

runner = CliRunner()


def _fake_outcome(tmp):
    sd = Path(tmp) / "sessions" / "s1"
    return SolveOutcome(
        kind="success", session_id="s1", session_dir=sd,
        snapshot_path=sd / "snap.json", manifest_path=sd / "manifest.json",
        events=[], task_description="do it", n_agents=1,
    )


def test_solve_assembles_context_with_provenance_headers(tmp_path, monkeypatch):
    captured = {}
    def fake_solve_once(roster_dirs, task_text, context, runs_root, provider_name="ollama"):
        captured["context"] = context
        captured["task"] = task_text
        return _fake_outcome(tmp_path)
    monkeypatch.setattr(app_mod, "solve_once", fake_solve_once)

    cfile = tmp_path / "ctx.txt"
    cfile.write_text("from-file", encoding="utf-8")
    r = _roster(tmp_path)
    result = runner.invoke(app, [
        "solve", "--roster", str(r), "--task", "do it",
        "--context-text", "inline-ctx", "--context-file", str(cfile),
        "--runs-root", str(tmp_path / "runs"),
    ])
    assert result.exit_code == 0, result.output
    assert "# context: inline\ninline-ctx" in captured["context"]
    assert f"# context: {cfile}\nfrom-file" in captured["context"]


def test_solve_refuses_context_overflow(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "solve_once", lambda *a, **k: _fake_outcome(tmp_path))
    r = _roster(tmp_path)
    result = runner.invoke(app, [
        "solve", "--roster", str(r), "--task", "x",
        "--context-text", "y" * 50, "--context-max", "10",
    ])
    assert result.exit_code == 1
    assert "too large" in result.output.lower()


def test_solve_empty_tagging_exits_1(tmp_path, monkeypatch):
    from aaosa.runtime.tagger import EmptyTaggingError
    def boom(*a, **k):
        raise EmptyTaggingError("no tags")
    monkeypatch.setattr(app_mod, "solve_once", boom)
    r = _roster(tmp_path)
    result = runner.invoke(app, ["solve", "--roster", str(r), "--task", "x"])
    assert result.exit_code == 1
    assert "tag" in result.output.lower()


def _roster(tmp_path) -> Path:
    d = tmp_path / "r"
    d.mkdir(parents=True, exist_ok=True)
    (d / "agents.yaml").write_text("- name: a\n  tags_with_elo: {x: 1500}\n  system_prompt: p\n", encoding="utf-8")
    return d
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/cli/test_app_solve.py -v`
Expected: FAIL (commande `solve` inexistante → exit code 2 « No such command »)

- [ ] **Step 3: Write minimal implementation**

Ajouter aux imports d'`app.py` :

```python
from aaosa.cli.solve_runs import solve_once
from aaosa.runtime.tagger import EmptyTaggingError
```

Ajouter la commande (après `run`, avant `campaign`) :

```python
@app.command()
def solve(
    roster: list[Path] = typer.Option(..., "--roster", help="Dossier roster (agents.yaml + tools.py), répétable"),
    task: str = typer.Option(..., "--task", help="Description libre de la tâche"),
    context_text: str | None = typer.Option(None, "--context-text"),
    context_file: Path | None = typer.Option(None, "--context-file"),
    context_max: int = typer.Option(20000, "--context-max", help="Refus dur si le contexte dépasse (caractères)"),
    provider: str = typer.Option("ollama", "--provider", help="ollama (défaut) | openai"),
    runs_root: Path = typer.Option(Path("runs"), "--runs-root"),
) -> None:
    """Résout une tâche libre avec N rosters injectés -> session + manifest + lien trace."""
    load_dotenv()

    parts: list[str] = []
    if context_text is not None:
        parts.append(f"# context: inline\n{context_text}")
    if context_file is not None:
        try:
            file_text = context_file.read_text(encoding="utf-8")
        except OSError as exc:
            typer.echo(f"Cannot read --context-file {context_file}: {exc}")
            raise typer.Exit(code=1)
        parts.append(f"# context: {context_file}\n{file_text}")
    context = "\n\n".join(parts) if parts else None

    if context is not None and len(context) > context_max:
        typer.echo(
            f"Context too large: {len(context)} chars > --context-max {context_max}. "
            "Refusing (no truncation)."
        )
        raise typer.Exit(code=1)

    try:
        outcome = solve_once(roster, task, context, runs_root, provider)
    except EmptyTaggingError:
        typer.echo("Tagging produced no tags for this task — cannot route it. Refine --task.")
        raise typer.Exit(code=1)
    except ValueError as exc:  # erreurs de chargement roster (collision, agents.yaml manquant, TOOL_REGISTRY)
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    typer.echo(f"=== AAOSA solve - {outcome.kind} ({outcome.n_agents} agents) ===\n")
    typer.echo(f"Task: {outcome.task_description}\n")
    typer.echo(f"  -> {outcome.kind}\n")
    typer.echo("=== Persistence ===")
    typer.echo(f"Session:  {outcome.session_dir}")
    typer.echo(f"Trace:    {outcome.session_dir / 'trace.jsonl'}")
    typer.echo(f"Manifest: {outcome.manifest_path}")
    typer.echo(f"ELO snapshot: {outcome.snapshot_path}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/cli/test_app_solve.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run full suite (régression globale)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS (toute la suite verte, `run --scenario` inchangé)

- [ ] **Step 6: Commit**

```bash
git add src/aaosa/cli/app.py tests/cli/test_app_solve.py
git commit -m "feat(cli): commande aaosa solve (task libre + rosters + contexte + manifest) [erd]"
```

---

## Smoke réel (sign-off Quentin, hors nuit)

Hors plan TDD (consomme un LLM réel). À faire au matin :

1. Lancer ollama local (`qwen3:4b`).
2. Créer un roster jouet `rosters/jouet/agents.yaml` (1-2 agents, tags simples) + optionnel `tools.py`.
3. `.venv\Scripts\aaosa solve --roster rosters/jouet --task "<tâche>" --context-text "<contexte>" --runs-root runs_solve_smoke`
4. Vérifier : `runs_solve_smoke/sessions/<id>/{trace.jsonl,manifest.json,meta.json}`, snapshot ELO, et que le manifest porte outcome + d'éventuels `roster_gaps`.
5. `.venv\Scripts\aaosa dashboard --runs-root runs_solve_smoke` pour visualiser le graphe émergent.

## DoD

- Suite complète verte via le venv.
- `aaosa solve` produit session persistée + `trace.jsonl` + `manifest.json` cohérent + snapshot ELO mono-store.
- `aaosa run --scenario {main|roster_gap}` inchangé (régression zéro).
- Smoke réel ollama validé (matin).
