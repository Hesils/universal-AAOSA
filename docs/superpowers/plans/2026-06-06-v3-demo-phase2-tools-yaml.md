# Démo phase 2 — Tools YAML via tool_registry + nettoyage pré-V3 : Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Les tools d'un agent se déclarent dans le YAML (`tools: [...]`) et sont résolus au chargement par `load_agents(path, tool_registry=...)` ; les scripts démo pré-V3 (`run_demo.py`, `run_health_check.py`) sont supprimés.

**Architecture:** Le loader pop le champ YAML `tools` (une `list[str]`), résout chaque nom en `ToolDef` via le registry, et construit `Agent(..., tools=[ToolDef...])`. `attach_tools` (attache code-side) disparaît ; `DEMO_AGENTS` arrive outillé depuis le YAML. Spec : `docs/superpowers/specs/2026-06-06-v3-demo-phase2-tools-yaml-design.md`.

**Tech Stack:** Python 3.14, Pydantic 2.13, PyYAML, pytest 9. Tests : `.venv\Scripts\python -m pytest <fichier> -v` (toujours le venv, jamais Python système).

**Branche:** `feat/v3-demo-phase2-tools-yaml` (worktree via superpowers:using-git-worktrees à l'exécution).

**Baseline:** 883 tests verts sur master (`4db81bc`). Le total final baisse (tests pré-V3 supprimés) — assumé par la spec.

---

## Décisions verrouillées (spec)

| # | Décision |
|---|----------|
| 1 | `tools` déclaré (non vide) sans `tool_registry` → `ValueError` (pas d'ignore silencieux). `tools: []` explicite sans registry → OK (rien à résoudre) |
| 2 | Nom inconnu → `ValueError` nommant le tool ET l'agent, listant les noms disponibles |
| 3 | `tools` non-liste, items non-str, doublon → `ValueError` |
| 4 | Rétrocompat : `tools` absent → `tools=[]`, avec et sans registry |
| 5 | `tasks.py` conservé (consommé par `run_health_check_v3.py` + fixtures dashboard) ; `run_demo.py`/`run_health_check.py` supprimés |
| 6 | `run_health_check` (fonction librairie V2b, `aaosa/qa/health_check.py`) n'est PAS touchée |

---

### Task 1: Loader — paramètre `tool_registry` (TDD)

**Files:**
- Modify: `src/aaosa/config/loader.py`
- Test: `tests/config/test_loader.py`

- [ ] **Step 1: Write the failing tests**

Ajouter en haut de `tests/config/test_loader.py` (après les imports existants `pytest`, `load_agents`, `Agent`) :

```python
from aaosa.core.tool import ToolDef


def _tooldef(name: str) -> ToolDef:
    return ToolDef(
        name=name,
        description=f"{name} tool",
        parameters={"type": "object", "properties": {}},
        fn=lambda: "ok",
    )


REGISTRY = {
    "read_file": _tooldef("read_file"),
    "grep_codebase": _tooldef("grep_codebase"),
}

TOOLS_YAML = """\
- name: Backend
  tags_with_elo:
    backend: 90
  system_prompt: "You are a backend specialist."
  tools: [read_file, grep_codebase]

- name: Frontend
  tags_with_elo:
    frontend: 85
  system_prompt: "You are a frontend specialist."
"""

MINIMAL_ENTRY = """\
- name: A
  tags_with_elo: {python: 50}
  system_prompt: "x"
"""
```

Puis ajouter la classe en fin de fichier :

```python
class TestLoadAgentsTools:
    def test_tools_resolved_from_registry(self, tmp_path):
        """Les noms YAML sont résolus en ToolDef du registry, ordre préservé."""
        agents = load_agents(_write(tmp_path, TOOLS_YAML), tool_registry=REGISTRY)
        by_name = {a.name: a for a in agents}
        assert [t.name for t in by_name["Backend"].tools] == ["read_file", "grep_codebase"]
        assert by_name["Backend"].tools[0] is REGISTRY["read_file"]

    def test_entry_without_tools_gets_empty_list(self, tmp_path):
        """Une entrée sans champ tools → tools=[] même avec registry fourni."""
        agents = load_agents(_write(tmp_path, TOOLS_YAML), tool_registry=REGISTRY)
        by_name = {a.name: a for a in agents}
        assert by_name["Frontend"].tools == []

    def test_retrocompat_no_registry_no_tools(self, tmp_path):
        """YAML sans tools + pas de registry → comportement V3-A1 intact."""
        agents = load_agents(_write(tmp_path, VALID_YAML))
        assert all(a.tools == [] for a in agents)

    def test_unknown_tool_name_raises(self, tmp_path):
        """Nom absent du registry → ValueError nommant tool + agent + disponibles."""
        yaml_txt = TOOLS_YAML.replace("grep_codebase", "does_not_exist")
        with pytest.raises(ValueError, match="does_not_exist") as exc_info:
            load_agents(_write(tmp_path, yaml_txt), tool_registry=REGISTRY)
        assert "Backend" in str(exc_info.value)
        assert "read_file" in str(exc_info.value)  # noms disponibles listés

    def test_tools_declared_without_registry_raises(self, tmp_path):
        """tools non vide dans le YAML mais tool_registry=None → ValueError."""
        with pytest.raises(ValueError, match="tool_registry"):
            load_agents(_write(tmp_path, TOOLS_YAML))

    def test_empty_tools_list_ok_without_registry(self, tmp_path):
        """tools: [] explicite → tools=[], pas d'erreur même sans registry."""
        yaml_txt = MINIMAL_ENTRY.replace('system_prompt: "x"', 'system_prompt: "x"\n  tools: []')
        agents = load_agents(_write(tmp_path, yaml_txt))
        assert agents[0].tools == []

    def test_tools_not_a_list_raises(self, tmp_path):
        """tools: read_file (scalaire) → ValueError."""
        yaml_txt = MINIMAL_ENTRY.replace('system_prompt: "x"', 'system_prompt: "x"\n  tools: read_file')
        with pytest.raises(ValueError, match="list of strings"):
            load_agents(_write(tmp_path, yaml_txt), tool_registry=REGISTRY)

    def test_tools_non_str_items_raises(self, tmp_path):
        """tools: [1, 2] → ValueError."""
        yaml_txt = MINIMAL_ENTRY.replace('system_prompt: "x"', 'system_prompt: "x"\n  tools: [1, 2]')
        with pytest.raises(ValueError, match="list of strings"):
            load_agents(_write(tmp_path, yaml_txt), tool_registry=REGISTRY)

    def test_duplicate_tool_names_raises(self, tmp_path):
        """Doublon dans tools → ValueError."""
        yaml_txt = MINIMAL_ENTRY.replace(
            'system_prompt: "x"', 'system_prompt: "x"\n  tools: [read_file, read_file]'
        )
        with pytest.raises(ValueError, match="duplicate"):
            load_agents(_write(tmp_path, yaml_txt), tool_registry=REGISTRY)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/config/test_loader.py -v`
Expected: les 9 tests de `TestLoadAgentsTools` FAIL (`TypeError: load_agents() got an unexpected keyword argument 'tool_registry'` ou échec de résolution) ; les 6 tests existants de `TestLoadAgents` restent PASS.

- [ ] **Step 3: Implement the loader**

Remplacer intégralement `src/aaosa/config/loader.py` par :

```python
from pathlib import Path

import yaml
from pydantic import ValidationError

from aaosa.core.agent import Agent
from aaosa.core.tool import ToolDef


def load_agents(path: Path, tool_registry: dict[str, ToolDef] | None = None) -> list[Agent]:
    """Charge une liste d'agents depuis un fichier YAML.

    Chaque entrée YAML doit avoir : name, tags_with_elo, system_prompt.
    Champ optionnel tools (liste de noms, list[str]) : résolu en list[ToolDef]
    via tool_registry. Le champ id est généré automatiquement (default_factory
    uuid4). Lève ValueError si le fichier est absent, malformé, invalide
    Pydantic, ou si un tool déclaré ne peut pas être résolu.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"Cannot read agents config at {path}: {e}") from e

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ValueError(f"Malformed YAML in {path}: {e}") from e

    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"Expected a YAML list of agents in {path}, got {type(data).__name__}")

    agents: list[Agent] = []
    for entry in data:
        if isinstance(entry, dict) and "tools" in entry:
            entry = {**entry}  # ne pas muter la structure YAML parsée
            entry["tools"] = _resolve_tools(entry.pop("tools"), tool_registry, entry.get("name"), path)
        try:
            agents.append(Agent(**entry))
        except (ValidationError, TypeError) as e:
            raise ValueError(f"Invalid agent definition in {path}: {e}") from e
    return agents


def _resolve_tools(
    names: object,
    registry: dict[str, ToolDef] | None,
    agent_name: object,
    path: Path,
) -> list[ToolDef]:
    """Résout les noms de tools d'une entrée YAML en ToolDef via le registry."""
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ValueError(f"Agent {agent_name!r} in {path}: 'tools' must be a list of strings")
    if len(names) != len(set(names)):
        raise ValueError(f"Agent {agent_name!r} in {path}: duplicate tool names in 'tools'")
    if not names:
        return []
    if registry is None:
        raise ValueError(
            f"Agent {agent_name!r} in {path} declares tools but no tool_registry was provided"
        )
    missing = [n for n in names if n not in registry]
    if missing:
        raise ValueError(
            f"Agent {agent_name!r} in {path}: unknown tool(s) {missing}; "
            f"available: {sorted(registry)}"
        )
    return [registry[n] for n in names]
```

Notes :
- La `ValueError` de `_resolve_tools` n'est volontairement PAS attrapée par le `except (ValidationError, TypeError)` — elle remonte telle quelle.
- Le try/except Pydantic passe d'un bloc global à un bloc par entrée : sémantique identique (la première entrée invalide lève).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/config/test_loader.py -v`
Expected: 15 PASS (6 existants + 9 nouveaux).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/config/loader.py tests/config/test_loader.py
git commit -m "feat(demo-p2): load_agents resout tools YAML via tool_registry"
```

---

### Task 2: Migration démo — tools déclarés dans `agents.yaml`, suppression `attach_tools`

**Files:**
- Modify: `src/aaosa/demo/agents.yaml`
- Modify: `src/aaosa/demo/agents.py`
- Modify: `src/aaosa/demo/tools.py` (suppression `_ASSIGNMENT` + `attach_tools`)
- Modify: `src/aaosa/demo/run_demo_v3.py:12,66-67`
- Modify: `tests/runtime/test_run_with_recovery_llm.py:14,26-27`
- Test: `tests/demo/test_tools.py` (réécrit)

- [ ] **Step 1: Rewrite the test file (failing first)**

Remplacer intégralement `tests/demo/test_tools.py` par :

```python
from aaosa.core.tool import ToolDef
from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tools import (
    TOOLBOX,
    explain_query_plan,
    grep_codebase,
    read_file,
    run_tests,
)


class TestToolFns:
    def test_all_fns_return_str(self):
        assert isinstance(read_file(path="api/middleware.py"), str)
        assert isinstance(grep_codebase(pattern="SELECT"), str)
        assert isinstance(run_tests(path="tests/"), str)
        assert isinstance(explain_query_plan(sql="SELECT 1"), str)

    def test_toolbox_is_tooldefs(self):
        assert all(isinstance(t, ToolDef) for t in TOOLBOX.values())
        assert {"read_file", "grep_codebase", "run_tests", "explain_query_plan"} == set(TOOLBOX)


class TestDemoAgentsTools:
    def test_demo_agents_carry_yaml_tools(self):
        """DEMO_AGENTS porte les tools déclarés dans agents.yaml (résolution loader)."""
        by_name = {a.name: a for a in DEMO_AGENTS}
        assert {t.name for t in by_name["Backend"].tools} == {
            "read_file", "grep_codebase", "run_tests", "explain_query_plan"}
        assert {t.name for t in by_name["Frontend"].tools} == {"read_file", "grep_codebase"}
        assert {t.name for t in by_name["Fullstack"].tools} == {"read_file", "run_tests"}
        assert {t.name for t in by_name["DevOps"].tools} == {"read_file"}

    def test_demo_agents_tools_are_toolbox_instances(self):
        """Les ToolDef attachés sont ceux du TOOLBOX (pas des copies)."""
        by_name = {a.name: a for a in DEMO_AGENTS}
        for tool in by_name["Backend"].tools:
            assert tool is TOOLBOX[tool.name]
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `.venv\Scripts\python -m pytest tests/demo/test_tools.py -v`
Expected: `TestToolFns` PASS ; `TestDemoAgentsTools` FAIL (`tools == []` — le YAML ne déclare encore rien).

- [ ] **Step 3: Declare tools in agents.yaml**

Remplacer intégralement `src/aaosa/demo/agents.yaml` par (seules les lignes `tools:` sont nouvelles) :

```yaml
# Agents de la démo logicielle AAOSA.
# Chargés par aaosa.config.loader.load_agents — le champ id est généré à la volée.
# Le nom est l'identifiant stable (matché par les snapshots ELO).
# tools : noms résolus en ToolDef via le tool_registry passé à load_agents.

- name: Frontend
  tags_with_elo:
    frontend: 85
    css: 90
    javascript: 80
    testing: 40
  tools: [read_file, grep_codebase]
  system_prompt: >-
    You are a frontend specialist focused on UI, CSS, and JavaScript.
    Investigate with your available tools before answering: read the relevant
    files. Then give a complete response that quotes the relevant code, explains
    the root cause, and provides a concrete fix as a code snippet with a short
    explanation.

- name: Backend
  tags_with_elo:
    backend: 90
    database: 85
    python: 80
    testing: 50
  tools: [read_file, grep_codebase, run_tests, explain_query_plan]
  system_prompt: >-
    You are a backend specialist focused on APIs, databases, Python, and backend
    performance optimization (middleware, connection pooling, caching, async
    patterns, query indexing). Always investigate with your available tools
    before answering: read the relevant files and inspect query plans with
    explain_query_plan. Then give a complete, detailed response that quotes the
    relevant code, explains the root cause, and provides a concrete fix as a code
    or SQL snippet with a short explanation.

- name: DevOps
  tags_with_elo:
    infrastructure: 90
    docker: 85
    ci_cd: 80
    backend: 30
  tools: [read_file]
  system_prompt: >-
    You are a DevOps specialist focused on infrastructure and CI/CD.
    Investigate with your available tools before answering: read the relevant
    files. Then give a complete response that quotes the relevant configuration,
    explains the root cause, and provides a concrete fix with a short explanation.

- name: Fullstack
  tags_with_elo:
    frontend: 50
    backend: 55
    javascript: 60
    python: 50
    database: 40
  tools: [read_file, run_tests]
  system_prompt: >-
    You are a fullstack generalist covering frontend and backend.
    Investigate with your available tools before answering: read the relevant
    files and run tests when useful. Then give a complete response that quotes the
    relevant code, explains the root cause, and provides a concrete fix as a code
    snippet with a short explanation.
```

- [ ] **Step 4: Pass the registry in agents.py**

Remplacer intégralement `src/aaosa/demo/agents.py` par :

```python
from pathlib import Path

from aaosa.config.loader import load_agents
from aaosa.demo.tools import TOOLBOX

DEMO_AGENTS = load_agents(Path(__file__).parent / "agents.yaml", tool_registry=TOOLBOX)
```

- [ ] **Step 5: Reduce tools.py (drop `_ASSIGNMENT` + `attach_tools`)**

Dans `src/aaosa/demo/tools.py` :
1. Remplacer le docstring de module par :

```python
"""Toolbox stubbée déterministe pour la démo V3 (A5).

Les fn retournent des données figées mais réalistes (str). TOOLBOX sert de
tool_registry à load_agents — les tools se déclarent dans agents.yaml.
"""
```

2. Supprimer la ligne `from aaosa.core.agent import Agent` (plus utilisée).
3. Supprimer tout le bloc final (de `_ASSIGNMENT: dict[str, list[str]] = {` jusqu'à la fin de `attach_tools`). Le fichier se termine après la définition de `TOOLBOX`.

- [ ] **Step 6: Drop attach_tools from its two consumers**

Dans `src/aaosa/demo/run_demo_v3.py` :
- Supprimer la ligne 12 : `from aaosa.demo.tools import attach_tools`
- Supprimer la ligne `attach_tools(agents)` (dans `run_demo_v3`, juste après `agents = list(DEMO_AGENTS)` — cette dernière reste).

Dans `tests/runtime/test_run_with_recovery_llm.py` :
- Supprimer la ligne `from aaosa.demo.tools import attach_tools`
- Supprimer la ligne `attach_tools(agents)` (la ligne `agents = list(DEMO_AGENTS)` reste).

- [ ] **Step 7: Run the impacted suites**

Run: `.venv\Scripts\python -m pytest tests/demo/ tests/config/ -v`
Expected: tout PASS (dont `TestDemoAgentsTools`, et `tests/demo/test_demo.py` encore présent — `run_demo.py` existe toujours à ce stade). `tests/runtime/test_run_with_recovery_llm.py` est skippé sans `RUN_LLM_TESTS` — vérifier seulement qu'il collecte : `.venv\Scripts\python -m pytest tests/runtime/test_run_with_recovery_llm.py -v` → 1 skipped, 0 error.

- [ ] **Step 8: Commit**

```bash
git add src/aaosa/demo/agents.yaml src/aaosa/demo/agents.py src/aaosa/demo/tools.py src/aaosa/demo/run_demo_v3.py tests/demo/test_tools.py tests/runtime/test_run_with_recovery_llm.py
git commit -m "feat(demo-p2): tools declares dans agents.yaml, attach_tools supprime"
```

---

### Task 3: Nettoyage pré-V3 — suppression `run_demo.py` / `run_health_check.py`

**Files:**
- Create: `tests/demo/test_tasks.py` (tests DEMO_TASKS + e2e pipeline migrés depuis `test_demo.py`)
- Delete: `src/aaosa/demo/run_demo.py`
- Delete: `src/aaosa/demo/run_health_check.py`
- Delete: `tests/demo/test_demo.py`
- Delete: `tests/demo/test_demo_health_check.py`

- [ ] **Step 1: Create tests/demo/test_tasks.py**

Contenu intégral — ce sont les classes de `test_demo.py` qui ne touchent PAS aux scripts supprimés (validation des fixtures `DEMO_TASKS` + e2e `run_task`, fonction librairie) :

```python
from unittest.mock import MagicMock, patch

from aaosa.claiming.dispatch import DispatchResult
from aaosa.core.agent import Agent
from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tasks import (
    DEMO_TASKS,
    TASK_FIX_CSS_HOVER,
    TASK_OPTIMIZE_SQL,
    TASK_SECURITY_AUDIT,
    TASK_WRITE_PYTHON_TESTS,
)
from aaosa.runtime.runner import run_task
from aaosa.schemas.claim import Claim
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import (
    DispatchedEvent,
    ExecutedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    UnassignedEvent,
)
from aaosa.tracing.tracer import Tracer

_by_name = {a.name: a for a in DEMO_AGENTS}
AGENT_FRONTEND = _by_name["Frontend"]
AGENT_BACKEND = _by_name["Backend"]
AGENT_FULLSTACK = _by_name["Fullstack"]


def _make_claim(agent: Agent, task: Task, decision: str = "claim") -> Claim:
    return Claim(
        agent_id=agent.id,
        task_id=task.id,
        decision=decision,
        justification="Mock justification.",
    )


def _make_output(agent: Agent, task: Task) -> Output:
    return Output(
        task_id=task.id,
        agent_id=agent.id,
        content="Mock output content.",
        llm_metadata=LLMMetadata(
            model_name="gpt-4o-mini",
            tokens_in=10,
            tokens_out=5,
            latency_ms=50.0,
        ),
    )


class TestDemoTasksList:
    """Tests for DEMO_TASKS list structure and size."""

    def test_demo_tasks_list_length(self):
        """DEMO_TASKS should contain at least 6 tasks."""
        assert len(DEMO_TASKS) >= 6


class TestAllDemoTasksBasics:
    """Tests for basic properties of all tasks in DEMO_TASKS."""

    def test_all_demo_tasks_are_task_instances(self):
        """Every task in DEMO_TASKS should be a Task instance."""
        for task in DEMO_TASKS:
            assert isinstance(task, Task)

    def test_all_demo_tasks_have_non_empty_required_tags(self):
        """Every task should have at least one required tag."""
        for task in DEMO_TASKS:
            assert len(task.required_tags) >= 1

    def test_all_demo_tasks_have_description(self):
        """Every task should have a non-empty description string."""
        for task in DEMO_TASKS:
            assert isinstance(task.description, str)
            assert len(task.description) > 0

    def test_all_demo_tasks_have_unique_ids(self):
        """All task IDs in DEMO_TASKS should be unique."""
        ids = [task.id for task in DEMO_TASKS]
        assert len(ids) == len(set(ids))

    def test_tag_elo_values_are_valid_integers(self):
        """All tag ELO values should be integers in range [1, 100]."""
        for task in DEMO_TASKS:
            for value in task.required_tags.values():
                assert isinstance(value, int)
                assert 1 <= value <= 100


class TestSingleClaimTask:
    """Tests for single-claim task (TASK_FIX_CSS_HOVER)."""

    def test_single_claim_task_has_css_tag(self):
        """TASK_FIX_CSS_HOVER should have css tag with ELO >= 60."""
        assert "css" in TASK_FIX_CSS_HOVER.required_tags
        assert TASK_FIX_CSS_HOVER.required_tags["css"] >= 60


class TestMultiClaimTask:
    """Tests for multi-claim task (TASK_WRITE_PYTHON_TESTS)."""

    def test_multi_claim_task_has_multiple_tags(self):
        """TASK_WRITE_PYTHON_TESTS should have at least 2 required tags."""
        assert len(TASK_WRITE_PYTHON_TESTS.required_tags) >= 2


class TestNoClaimTask:
    """Tests for no-claim task with high ELO (TASK_SECURITY_AUDIT)."""

    def test_no_claim_task_has_high_elo(self):
        """TASK_SECURITY_AUDIT should have at least one tag with ELO >= 75."""
        assert max(TASK_SECURITY_AUDIT.required_tags.values()) >= 75


class TestUnderClaimTask:
    """Tests for under-claim task with low ELO (TASK_OPTIMIZE_SQL)."""

    def test_under_claim_task_has_low_elo(self):
        """TASK_OPTIMIZE_SQL should have all tags with ELO <= 50."""
        assert all(v <= 50 for v in TASK_OPTIMIZE_SQL.required_tags.values())


class TestDemoEndToEnd:
    """Tests end-to-end du pipeline run_task avec les fixtures demo et LLM mocké."""

    def test_css_hover_assigned_to_frontend(self):
        """TASK_FIX_CSS_HOVER : seul FRONTEND passe Phase 1 (css:90 >= 70).
        Mock claim + execute → Output avec agent_id == FRONTEND."""
        task = TASK_FIX_CSS_HOVER
        claim = _make_claim(AGENT_FRONTEND, task)
        output = _make_output(AGENT_FRONTEND, task)

        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                result = run_task(task, DEMO_AGENTS, MagicMock())

        assert isinstance(result, Output)
        assert result.agent_id == AGENT_FRONTEND.id

    def test_security_audit_unassigned(self):
        """TASK_SECURITY_AUDIT : aucun agent n'a le tag 'security' → 0 candidats.
        Pas de mock LLM nécessaire → DispatchResult status='unassigned'."""
        result = run_task(TASK_SECURITY_AUDIT, DEMO_AGENTS, MagicMock())

        assert isinstance(result, DispatchResult)
        assert result.status == "unassigned"

    def test_optimize_sql_backend_wins_over_fullstack(self):
        """TASK_OPTIMIZE_SQL : BACKEND (database:85, score=2.125) et FULLSTACK (database:40, score=1.0).
        Les deux clament. BACKEND gagne par fit_score → Output avec BACKEND.id."""
        task = TASK_OPTIMIZE_SQL
        claim_backend = _make_claim(AGENT_BACKEND, task)
        claim_fullstack = _make_claim(AGENT_FULLSTACK, task)
        output = _make_output(AGENT_BACKEND, task)

        # filter_candidates itère DEMO_AGENTS dans l'ordre → BACKEND avant FULLSTACK
        with patch.object(Agent, "claim", side_effect=[claim_backend, claim_fullstack]):
            with patch.object(Agent, "execute", return_value=output):
                result = run_task(task, DEMO_AGENTS, MagicMock())

        assert isinstance(result, Output)
        assert result.agent_id == AGENT_BACKEND.id

    def test_assigned_task_emits_tracer_events(self):
        """TASK_FIX_CSS_HOVER avec tracer : vérifier Phase1Filtered (1 passed=True pour FRONTEND),
        Phase2Claimed, Dispatched et Executed sont émis."""
        task = TASK_FIX_CSS_HOVER
        tracer = Tracer(session_id="test-e2e")
        claim = _make_claim(AGENT_FRONTEND, task)
        output = _make_output(AGENT_FRONTEND, task)

        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                run_task(task, DEMO_AGENTS, MagicMock(), tracer=tracer)

        event_types = {type(e) for e in tracer.events}
        assert Phase1FilteredEvent in event_types
        assert Phase2ClaimedEvent in event_types
        assert DispatchedEvent in event_types
        assert ExecutedEvent in event_types

        phase1_passed = [e for e in tracer.events if isinstance(e, Phase1FilteredEvent) and e.passed]
        assert len(phase1_passed) == 1
        assert phase1_passed[0].agent_id == AGENT_FRONTEND.id

    def test_unassigned_task_emits_unassigned_event(self):
        """TASK_SECURITY_AUDIT avec tracer : vérifier UnassignedEvent est émis."""
        tracer = Tracer(session_id="test-e2e")

        run_task(TASK_SECURITY_AUDIT, DEMO_AGENTS, MagicMock(), tracer=tracer)

        event_types = {type(e) for e in tracer.events}
        assert UnassignedEvent in event_types
```

Ce qui est volontairement abandonné (testait les scripts supprimés) : `TestDemoV2`, `TestDemoV2b`, `_fake_run_judge`, `_fake_run_recovery`, `_output_for_v2b`, `_qa_failure_for`, l'import `aaosa.demo.run_demo`.

- [ ] **Step 2: Delete the pre-V3 files**

```bash
git rm src/aaosa/demo/run_demo.py src/aaosa/demo/run_health_check.py tests/demo/test_demo.py tests/demo/test_demo_health_check.py
```

- [ ] **Step 3: Run the full suite**

Run: `.venv\Scripts\python -m pytest`
Expected: tout vert, 1 skipped (`test_run_with_recovery_llm`). Le total baisse vs 883 (suppression des tests V2/V2b/health-check-démo, ajout des tests loader + demo tools). Aucune erreur de collecte (rien d'autre n'importe `run_demo`/`run_health_check` démo — vérifié : seuls les fichiers supprimés le faisaient).

- [ ] **Step 4: Commit**

```bash
git add tests/demo/test_tasks.py
git commit -m "chore(demo-p2): suppression demos pre-V3, tests DEMO_TASKS migres vers test_tasks.py"
```

---

### Task 4: CLAUDE.md + validation LLM réelle (DoD)

**Files:**
- Modify: `CLAUDE.md` (3 endroits)

- [ ] **Step 1: Update CLAUDE.md**

1. Section **Stack et commandes**, remplacer :

```
- Lancer la démo : `.venv\Scripts\python src\aaosa\demo\run_demo.py` (requiert `.env` avec `OPENAI_API_KEY`)
```

par :

```
- Lancer la démo : `.venv\Scripts\python src\aaosa\demo\run_demo_v3.py` (requiert `.env` avec `OPENAI_API_KEY`)
```

2. Section **Architecture**, ligne `demo/`, remplacer :

```
├── demo/           agents.py (loader A1) · agents.yaml · tasks.py · run_demo.py (+run divisé A4) · run_health_check.py · tools.py (toolbox stubbée vague1) · run_demo_v3.py · run_health_check_v3.py  # *_v3 = vague1
```

par :

```
├── demo/           agents.py (loader A1) · agents.yaml (+tools déclarés P2) · tasks.py · tools.py (toolbox = tool_registry) · run_demo_v3.py · run_health_check_v3.py  # démos pré-V3 supprimées P2
```

3. Section **État courant**, ajouter après le bloc « V3 — démo phase 1 » (le total de tests exact est celui observé à la Task 3 Step 3) :

```
**V3 — démo phase 2 : tools YAML — <total> tests** (2026-06-06, branche `feat/v3-demo-phase2-tools-yaml`). `load_agents(path, tool_registry=...)` résout le champ YAML `tools: [list[str]]` en `ToolDef` (erreur au chargement : nom inconnu, registry absent, doublon, non-liste ; `tools` absent → `[]` rétrocompat). `demo/agents.yaml` déclare les tools, `DEMO_AGENTS` arrive outillé, `attach_tools`/`_ASSIGNMENT` supprimés. Nettoyage pré-V3 : `run_demo.py` + `run_health_check.py` + leurs tests supprimés (tests `DEMO_TASKS` migrés vers `test_tasks.py`) ; `tasks.py` conservé (consommé par `run_health_check_v3` + fixtures dashboard). Spec : `docs/superpowers/specs/2026-06-06-v3-demo-phase2-tools-yaml-design.md`. Prochaine étape : phase 3 (monde simulé + roster `demo/incident/`).
```

- [ ] **Step 2: Run the real-LLM demo (DoD #2)**

Run: `.venv\Scripts\python src\aaosa\demo\run_demo_v3.py` (requiert `.env` avec `OPENAI_API_KEY`)
Expected:
- le run se termine (`-> divided` ou outcome équivalent, pas de crash) ;
- la timeline affiche des évènements **ToolCalled** (les tools viennent désormais du YAML) ;
- la session est persistée sous `runs/sessions/<id>/`.

Si aucun `ToolCalledEvent` n'apparaît : vérifier `DEMO_AGENTS[i].tools` en REPL avant de conclure (les agents doivent porter leurs ToolDef). Ne pas re-lancer en boucle sans diagnostic (coût API).

- [ ] **Step 3: Full suite one last time**

Run: `.venv\Scripts\python -m pytest`
Expected: tout vert, 1 skipped.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(demo-p2): CLAUDE.md — phase 2 tools YAML, demos pre-V3 supprimees"
```

Puis : superpowers:finishing-a-development-branch (merge `master`, suppression branche/worktree).
