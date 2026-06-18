# HITL `ask_human` Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner aux agents AAOSA un tool `ask_human(question)` qui demande une info à l'humain en cours de run, via un callback injecté, sans toucher au runtime synchrone.

**Architecture:** `ask_human` est un `ToolDef` framework dont le `fn` capture en closure un callback `question -> réponse`. Le callback vit aussi sur `RunContext.hitl_callback` (seam pour une extension non-agents future). Le tool est résolu par nom au chargement de roster (registre de built-ins fusionné). La CLI `aaosa solve --hitl` fournit un callback stdin ; sans le flag, un callback sentinelle non-bloquant garde les runs batch/night exécutables. L'échange est tracé par le `ToolCalledEvent` existant (aucun nouvel event).

**Tech Stack:** Python 3.14, Pydantic 2.13, Typer 0.26.7, pytest 9.0.3, `uv` venv. Tests via `.venv\Scripts\python -m pytest`.

## Global Constraints

- **Imports absolus uniquement** : `from aaosa.core.hitl import ...`, jamais relatifs.
- **Runtime synchrone intact** : aucune modification de signature ni de comportement dans `agent.execute()`, `run_task`, `run_with_recovery`. `ask_human` est un `ToolDef` comme un autre, borné par `MAX_TOOL_ROUNDS`.
- **`ToolDef.fn` reste `Callable[..., str]`** : le callback ne fuite jamais dans les args LLM (closure).
- **Rétrocompat stricte** : tout champ/param ajouté est optionnel avec default ; sans `hitl_callback` ni tool `ask_human`, comportement V1/V2/V3 identique. La suite existante (1189 tests) reste verte.
- **Démo figée** : `run --scenario` et `demo/incident/*` inchangés.
- **Night-run safe** : un roster portant `ask_human` exécuté sans humain dégrade via `unattended_callback`, jamais de blocage.
- **Tracer = observer découplé** : on réutilise `ToolCalledEvent`, le runtime ne juge/n'imprime pas l'échange HITL lui-même. Pas de nouveau type d'event.
- **Timestamps UTC** `datetime.now(timezone.utc)`, Pydantic v2 `extra="forbid"` (non concerné ici mais à respecter si un modèle est touché).
- **Tests via le venv** : `.venv\Scripts\python -m pytest <fichier> -v`, jamais Python système.

---

## File Structure

- **Create** `src/aaosa/core/hitl.py` — type `HITLCallback`, `ASK_HUMAN_TOOL_NAME`, `unattended_callback`, `make_ask_human_tool`, `build_builtin_tools`. Seul fichier net-new de logique.
- **Modify** `src/aaosa/runtime/context.py` — champ optionnel `hitl_callback` sur `RunContext`.
- **Modify** `src/aaosa/config/roster.py` — param `builtin_tools` sur `load_roster`/`load_rosters` + fusion avec collision réservée.
- **Modify** `src/aaosa/cli/solve_runs.py` — param `hitl_callback` sur `solve_once`, construit les built-ins, les passe à `load_rosters`, pose le callback sur le `RunContext`.
- **Modify** `src/aaosa/cli/app.py` — flag `--hitl/--no-hitl` sur `solve`, callback stdin.
- **Create** `tests/core/test_hitl.py`, `tests/core/test_hitl_integration.py` — tests unitaires + intégration de la boucle.
- **Modify** `tests/runtime/test_context.py`, `tests/config/test_roster.py`, `tests/cli/test_solve_runs.py`, `tests/cli/test_app_solve.py` — tests des modifications (chemins exacts à confirmer si les fichiers de test diffèrent ; sinon créer le fichier miroir).

---

### Task 1: `core/hitl.py` — builder, sentinelle, built-ins

**Files:**
- Create: `src/aaosa/core/hitl.py`
- Test: `tests/core/test_hitl.py`

**Interfaces:**
- Consumes: `aaosa.core.tool.ToolDef` (dataclass : `name`, `description`, `parameters: dict`, `fn: Callable[..., str]`).
- Produces:
  - `HITLCallback = Callable[[str], str]` (type alias)
  - `ASK_HUMAN_TOOL_NAME: str = "ask_human"`
  - `unattended_callback(question: str) -> str`
  - `make_ask_human_tool(callback: HITLCallback | None = None) -> ToolDef`
  - `build_builtin_tools(callback: HITLCallback | None = None) -> dict[str, ToolDef]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/core/test_hitl.py
from aaosa.core.hitl import (
    ASK_HUMAN_TOOL_NAME,
    build_builtin_tools,
    make_ask_human_tool,
    unattended_callback,
)
from aaosa.core.tool import ToolDef


def test_unattended_callback_non_blocking_sentinel():
    out = unattended_callback("Where is the config?")
    assert isinstance(out, str)
    assert "No human" in out


def test_make_tool_captures_callback_in_closure():
    captured = {}

    def cb(question: str) -> str:
        captured["q"] = question
        return "the answer"

    tool = make_ask_human_tool(cb)
    assert isinstance(tool, ToolDef)
    assert tool.name == ASK_HUMAN_TOOL_NAME
    # fn signature is (**args) -> str ; called with the LLM-provided arg
    result = tool.fn(question="What is X?")
    assert result == "the answer"
    assert captured["q"] == "What is X?"


def test_make_tool_none_callback_uses_sentinel():
    tool = make_ask_human_tool(None)
    result = tool.fn(question="anything")
    assert result == unattended_callback("anything")


def test_tool_openai_schema_requires_question():
    tool = make_ask_human_tool(lambda q: "x")
    schema = tool.to_openai()
    params = schema["function"]["parameters"]
    assert params["required"] == ["question"]
    assert params["properties"]["question"]["type"] == "string"


def test_build_builtin_tools_maps_ask_human_by_name():
    cb = lambda q: "a"
    builtins = build_builtin_tools(cb)
    assert set(builtins) == {ASK_HUMAN_TOOL_NAME}
    assert builtins[ASK_HUMAN_TOOL_NAME].fn(question="q") == "a"


def test_build_builtin_tools_none_callback_still_present():
    builtins = build_builtin_tools(None)
    assert ASK_HUMAN_TOOL_NAME in builtins
    assert "No human" in builtins[ASK_HUMAN_TOOL_NAME].fn(question="q")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/core/test_hitl.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aaosa.core.hitl'`

- [ ] **Step 3: Write the implementation**

```python
# src/aaosa/core/hitl.py
"""HITL (ipv) — tool ask_human callable par les agents.

ask_human est un ToolDef framework : son fn capture en closure un callback
question -> réponse fourni par l'invocateur (CC / opérateur). Le runtime ne
voit jamais le callback (fn(**args) -> str inchangé côté execute()). Sans
humain (night-run/batch), unattended_callback répond une chaîne non-bloquante.
"""

from typing import Callable

from aaosa.core.tool import ToolDef

HITLCallback = Callable[[str], str]   # question -> réponse

ASK_HUMAN_TOOL_NAME = "ask_human"


def unattended_callback(question: str) -> str:
    """Callback par défaut sans humain (night-run/batch). Non-bloquant."""
    return (
        "No human is available to answer in this run. "
        "Proceed with your best judgment and state any assumption you make."
    )


def make_ask_human_tool(callback: HITLCallback | None = None) -> ToolDef:
    """Construit le ToolDef ask_human. `callback` capturé en closure ;
    callback=None -> unattended_callback (dégradation sûre)."""
    cb = callback or unattended_callback

    def _fn(question: str) -> str:
        return cb(question)

    return ToolDef(
        name=ASK_HUMAN_TOOL_NAME,
        description=(
            "Ask the human operator a question when you lack a piece of "
            "information that is critical to complete the task and cannot be "
            "obtained otherwise. Returns the human's answer as text."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The single, specific question to ask the human.",
                }
            },
            "required": ["question"],
        },
        fn=_fn,
    )


def build_builtin_tools(callback: HITLCallback | None = None) -> dict[str, ToolDef]:
    """Registre des tools framework injectables dans un roster (par nom)."""
    return {ASK_HUMAN_TOOL_NAME: make_ask_human_tool(callback)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/core/test_hitl.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/core/hitl.py tests/core/test_hitl.py
git commit -m "feat(hitl): ask_human tool builder + unattended sentinel [ipv]"
```

---

### Task 2: `RunContext.hitl_callback` — seam d'extensibilité

**Files:**
- Modify: `src/aaosa/runtime/context.py:21-31`
- Test: `tests/runtime/test_context.py` (créer si absent)

**Interfaces:**
- Consumes: `aaosa.core.hitl.HITLCallback` (Task 1).
- Produces: `RunContext.hitl_callback: HITLCallback | None = None` (champ optionnel, préservé par `dataclasses.replace`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/runtime/test_context.py  (ajouter ; ne pas casser les tests existants du fichier)
from dataclasses import replace

from aaosa.runtime.context import RunContext


def _minimal_ctx(**over):
    # Réutilise les fakes du fichier si présents ; sinon SimpleNamespace suffit
    # car RunContext ne valide pas ses membres (dataclass, pas Pydantic).
    from types import SimpleNamespace
    base = dict(
        agents=[],
        provider=SimpleNamespace(),
        divider=SimpleNamespace(),
        aggregator=SimpleNamespace(),
        tagger=SimpleNamespace(),
    )
    base.update(over)
    return RunContext(**base)


def test_runcontext_hitl_callback_defaults_none():
    ctx = _minimal_ctx()
    assert ctx.hitl_callback is None


def test_runcontext_hitl_callback_preserved_by_replace():
    cb = lambda q: "a"
    ctx = _minimal_ctx(hitl_callback=cb)
    ctx2 = replace(ctx, tracer=SimpleNamespace())
    assert ctx2.hitl_callback is cb
```

(Le `from types import SimpleNamespace` en tête du second test est redondant avec celui du helper ; le retirer si le linter du repo le signale.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_context.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'hitl_callback'`

- [ ] **Step 3: Write the implementation**

Dans `src/aaosa/runtime/context.py`, ajouter l'import et le champ. L'import (après les imports existants) :

```python
from aaosa.core.hitl import HITLCallback
```

Et dans la dataclass `RunContext`, ajouter le champ après `provider_registry` (avant `roles` qui porte un `field(default_factory=...)` — l'ordre des champs avec default reste valide) :

```python
    hitl_callback: "HITLCallback | None" = None
    roles: RoleProviders = field(default_factory=RoleProviders)
```

(Concrètement : insérer la ligne `hitl_callback: "HITLCallback | None" = None` entre la ligne `provider_registry: ...` et la ligne `roles: RoleProviders = ...`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_context.py -v`
Expected: PASS

Puis non-régression du contexte runtime :
Run: `.venv\Scripts\python -m pytest tests/runtime -q`
Expected: PASS (aucune régression)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/context.py tests/runtime/test_context.py
git commit -m "feat(hitl): RunContext.hitl_callback seam (default None) [ipv]"
```

---

### Task 3: `load_roster`/`load_rosters` — fusion des built-ins

**Files:**
- Modify: `src/aaosa/config/roster.py:36-62`
- Test: `tests/config/test_roster.py` (ajouter ; créer si absent)

**Interfaces:**
- Consumes: `aaosa.core.tool.ToolDef`, `aaosa.config.loader.load_agents(path, tool_registry)`.
- Produces:
  - `load_roster(directory: Path, builtin_tools: dict[str, ToolDef] | None = None) -> list[Agent]`
  - `load_rosters(directories: list[Path], builtin_tools: dict[str, ToolDef] | None = None) -> list[Agent]`
  - Comportement : les built-ins sont fusionnés au `TOOL_REGISTRY` du roster ; un roster qui redéfinit un nom built-in lève `ValueError` (nom réservé).

- [ ] **Step 1: Write the failing tests**

```python
# tests/config/test_roster.py  (ajouter)
import textwrap
from pathlib import Path

import pytest

from aaosa.config.roster import load_roster, load_rosters
from aaosa.core.tool import ToolDef


def _ask_human_builtin() -> dict[str, ToolDef]:
    return {
        "ask_human": ToolDef(
            name="ask_human",
            description="d",
            parameters={"type": "object", "properties": {}, "required": []},
            fn=lambda **k: "answer",
        )
    }


def _write_agents(dir: Path, tools_line: str = "") -> None:
    dir.mkdir(parents=True, exist_ok=True)
    (dir / "agents.yaml").write_text(
        textwrap.dedent(
            f"""
            - name: A
              tags_with_elo: {{python: 80}}
              system_prompt: You are A.
              {tools_line}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def test_agent_resolves_builtin_ask_human_without_tools_py(tmp_path):
    # Pas de tools.py ; l'agent déclare ask_human -> résolu via les built-ins.
    _write_agents(tmp_path, tools_line="tools: [ask_human]")
    agents = load_roster(tmp_path, builtin_tools=_ask_human_builtin())
    assert [t.name for t in agents[0].tools] == ["ask_human"]


def test_roster_cannot_redefine_reserved_builtin(tmp_path):
    _write_agents(tmp_path)
    (tmp_path / "tools.py").write_text(
        textwrap.dedent(
            """
            from aaosa.core.tool import ToolDef
            TOOL_REGISTRY = {
                "ask_human": ToolDef(name="ask_human", description="x",
                    parameters={"type": "object", "properties": {}, "required": []},
                    fn=lambda **k: "rogue"),
            }
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="reserved"):
        load_roster(tmp_path, builtin_tools=_ask_human_builtin())


def test_load_rosters_threads_builtins(tmp_path):
    r = tmp_path / "r1"
    _write_agents(r, tools_line="tools: [ask_human]")
    agents = load_rosters([r], builtin_tools=_ask_human_builtin())
    assert [t.name for t in agents[0].tools] == ["ask_human"]


def test_no_builtins_unchanged_behavior(tmp_path):
    # Rétrocompat : sans built-ins ni tools, comportement identique.
    _write_agents(tmp_path)
    agents = load_roster(tmp_path)
    assert agents[0].tools == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/config/test_roster.py -v`
Expected: FAIL — `load_roster()` got an unexpected keyword argument `builtin_tools`

- [ ] **Step 3: Write the implementation**

Dans `src/aaosa/config/roster.py`, ajouter un helper de fusion et threader `builtin_tools` :

```python
def _merge_builtins(
    roster_registry: dict[str, ToolDef] | None,
    builtin_tools: dict[str, ToolDef] | None,
) -> dict[str, ToolDef] | None:
    """Fusionne les tools framework au registre du roster. Un nom built-in
    redéfini par le roster est réservé -> ValueError."""
    if not builtin_tools:
        return roster_registry
    merged: dict[str, ToolDef] = dict(roster_registry or {})
    for name, tool in builtin_tools.items():
        if name in merged:
            raise ValueError(
                f"Tool name {name!r} is reserved (built-in) and cannot be "
                f"redefined by a roster"
            )
        merged[name] = tool
    return merged


def load_roster(
    directory: Path, builtin_tools: dict[str, ToolDef] | None = None
) -> list[Agent]:
    """Charge UN roster : agents.yaml résolu contre le TOOL_REGISTRY de son
    tools.py, fusionné avec les built-ins framework (ask_human)."""
    directory = Path(directory)
    agents_path = directory / "agents.yaml"
    if not agents_path.exists():
        raise ValueError(f"Roster {directory} is missing agents.yaml")
    registry = _load_tool_registry(directory)
    registry = _merge_builtins(registry, builtin_tools)
    return load_agents(agents_path, registry)


def load_rosters(
    directories: list[Path], builtin_tools: dict[str, ToolDef] | None = None
) -> list[Agent]:
    """Charge N rosters et fusionne. Collision de noms d'agents -> ValueError."""
    if not directories:
        raise ValueError("load_rosters requires at least one roster directory")
    merged: list[Agent] = []
    seen: dict[str, Path] = {}
    for d in directories:
        d = Path(d)
        for agent in load_roster(d, builtin_tools=builtin_tools):
            if agent.name in seen:
                raise ValueError(
                    f"Agent name collision: {agent.name!r} in {d} "
                    f"already loaded from {seen[agent.name]}"
                )
            seen[agent.name] = d
            merged.append(agent)
    return merged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/config/test_roster.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/config/roster.py tests/config/test_roster.py
git commit -m "feat(hitl): merge built-in tools into roster registry (reserved names) [ipv]"
```

---

### Task 4: Intégration — `ask_human` traverse la boucle tool-use

**Files:**
- Test: `tests/core/test_hitl_integration.py` (create)

> Cette task ne change AUCUN code de production : elle prouve que `ask_human`
> fonctionne via `agent.execute()` existant (le runtime n'est pas touché) et
> que l'échange est tracé par `ToolCalledEvent`. C'est le garde-fou de
> correction du cœur de la feature.

**Interfaces:**
- Consumes: `aaosa.core.agent.Agent`, `aaosa.core.hitl.make_ask_human_tool`, `aaosa.schemas.task.Task`, `aaosa.tracing.tracer.Tracer`, `aaosa.tracing.events.ToolCalledEvent`.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_hitl_integration.py
import json
from types import SimpleNamespace

from aaosa.core.agent import Agent
from aaosa.core.hitl import make_ask_human_tool
from aaosa.schemas.task import Task
from aaosa.tracing.events import ToolCalledEvent
from aaosa.tracing.tracer import Tracer


def _resp(finish_reason, content=None, tool_calls=None, tin=5, tout=3):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(finish_reason=finish_reason, message=msg)
    return SimpleNamespace(
        model="gpt-4o-mini",
        choices=[choice],
        usage=SimpleNamespace(prompt_tokens=tin, completion_tokens=tout),
    )


def _tool_call(name, args_dict, call_id="call_1"):
    return SimpleNamespace(
        id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args_dict))
    )


def _queue_provider(responses):
    it = iter(responses)

    def complete(*, messages, model=None, tools=None, **kwargs):
        return next(it)

    return SimpleNamespace(complete=complete)


def test_ask_human_round_trips_through_execute_and_traces():
    captured = {}

    def cb(question: str) -> str:
        captured["q"] = question
        return "use config.yaml"

    agent = Agent(
        name="A",
        tags_with_elo={"python": 80},
        system_prompt="You are A.",
        tools=[make_ask_human_tool(cb)],
    )
    task = Task(description="do it", required_tags={"python": 60})
    provider = _queue_provider([
        _resp("tool_calls", tool_calls=[_tool_call("ask_human", {"question": "Which config?"})]),
        _resp("stop", content="done with config.yaml"),
    ])
    tracer = Tracer(session_id="sess-hitl")

    out = agent.execute(task, provider, tracer)

    assert out.content == "done with config.yaml"
    assert out.llm_metadata.tool_calls_count == 1
    assert captured["q"] == "Which config?"
    hitl_events = [e for e in tracer.events if isinstance(e, ToolCalledEvent) and e.tool_name == "ask_human"]
    assert len(hitl_events) == 1
    assert hitl_events[0].arguments == {"question": "Which config?"}
    assert hitl_events[0].result == "use config.yaml"
```

- [ ] **Step 2: Run the test to verify it passes immediately (no production change)**

Run: `.venv\Scripts\python -m pytest tests/core/test_hitl_integration.py -v`
Expected: PASS — `ask_human` est un `ToolDef` standard, `execute()` le gère déjà.

> Si ce test ÉCHOUE, c'est un signal que `Tracer.events` ou la boucle tool-use
> diffère de l'hypothèse : déboguer avec superpowers:systematic-debugging
> AVANT de toucher au runtime (qui doit rester intact).

- [ ] **Step 3: Commit**

```bash
git add tests/core/test_hitl_integration.py
git commit -m "test(hitl): ask_human round-trips through tool-use loop + traced [ipv]"
```

---

### Task 5: `solve_once(hitl_callback=...)` — câblage runtime

**Files:**
- Modify: `src/aaosa/cli/solve_runs.py:39-100`
- Test: `tests/cli/test_solve_runs.py` (ajouter ; créer si absent)

**Interfaces:**
- Consumes: `aaosa.core.hitl.build_builtin_tools`, `aaosa.core.hitl.HITLCallback`, `load_rosters(..., builtin_tools=...)` (Task 3), `RunContext.hitl_callback` (Task 2).
- Produces: `solve_once(roster_dirs, task_text, context, runs_root, provider_name="ollama", roles_path=None, hitl_callback: HITLCallback | None = None) -> SolveOutcome`.

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_solve_runs.py  (ajouter)
import textwrap
from pathlib import Path

from aaosa.cli import solve_runs
from aaosa.core.hitl import ASK_HUMAN_TOOL_NAME


def _write_roster(dir: Path) -> None:
    dir.mkdir(parents=True, exist_ok=True)
    (dir / "agents.yaml").write_text(
        textwrap.dedent(
            """
            - name: A
              tags_with_elo: {python: 80}
              system_prompt: You are A.
              tools: [ask_human]
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def test_solve_once_injects_callback_into_agents_and_context(tmp_path, monkeypatch):
    roster = tmp_path / "r1"
    _write_roster(roster)

    seen = {}

    def fake_persisted_run(agents, runs_root, *, build_ctx, make_task):
        ctx = build_ctx(tracer=_FakeTracer())
        seen["agents"] = agents
        seen["ctx"] = ctx
        # On n'exécute pas le run réel : on inspecte le wiring.
        raise _StopForTest()

    class _StopForTest(Exception):
        pass

    class _FakeTracer:
        events = []

    # Court-circuite tout ce qui touche au provider/LLM en amont de _persisted_run.
    monkeypatch.setattr(solve_runs, "build_provider_registry",
                        lambda agents, name, roles: (object(), {}))
    monkeypatch.setattr(solve_runs, "preflight_models", lambda *a, **k: None)
    monkeypatch.setattr(solve_runs, "load_elo_into", lambda *a, **k: None)
    monkeypatch.setattr(solve_runs, "resolve_provider", lambda *a, **k: object())
    monkeypatch.setattr(solve_runs, "build_root_task", lambda text, ctx, context=None: object())
    monkeypatch.setattr(solve_runs, "_persisted_run", fake_persisted_run)

    cb = lambda q: "answer"
    try:
        solve_runs.solve_once([roster], "do it", None, tmp_path / "runs",
                              hitl_callback=cb)
    except _StopForTest:
        pass

    # 1) le tool ask_human a bien été injecté dans l'agent (built-ins fusionnés)
    assert any(t.name == ASK_HUMAN_TOOL_NAME for t in seen["agents"][0].tools)
    # 2) le callback est posé sur le RunContext (seam V2)
    assert seen["ctx"].hitl_callback is cb
```

> Note d'implémentation du test : il dépend des symboles importés dans
> `solve_runs.py` (`build_provider_registry`, `preflight_models`, etc.). Si un
> nom diffère à l'exécution, ajuster le `monkeypatch.setattr` au symbole réel
> tel qu'importé en tête de `solve_runs.py`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/cli/test_solve_runs.py -v`
Expected: FAIL — `solve_once()` got an unexpected keyword argument `hitl_callback`

- [ ] **Step 3: Write the implementation**

Dans `src/aaosa/cli/solve_runs.py` :

Ajouter l'import en tête (avec les autres imports `aaosa`) :

```python
from aaosa.core.hitl import HITLCallback, build_builtin_tools
```

Modifier la signature de `solve_once` (ajouter `hitl_callback`) :

```python
def solve_once(
    roster_dirs: list[Path],
    task_text: str,
    context: str | None,
    runs_root: Path,
    provider_name: str = "ollama",
    roles_path: Path | None = None,
    hitl_callback: HITLCallback | None = None,
) -> SolveOutcome:
```

Remplacer la ligne de chargement des rosters :

```python
    agents = load_rosters(roster_dirs)
```

par :

```python
    builtin_tools = build_builtin_tools(hitl_callback)
    agents = load_rosters(roster_dirs, builtin_tools=builtin_tools)
```

Et ajouter `hitl_callback=hitl_callback` dans la construction de `pre_ctx = RunContext(...)` (à côté de `roles=roles`) :

```python
    pre_ctx = RunContext(
        agents=agents,
        provider=provider,
        divider=TaskDivider(system_prompt=default_prompts.DIVIDER_PROMPT),
        aggregator=TaskAggregator(system_prompt=default_prompts.AGGREGATOR_PROMPT),
        tagger=Tagger(system_prompt=default_prompts.TAGGER_PROMPT),
        tracer=None,
        evaluator=AdaptiveSpecEvaluator(eprov, model=emodel),
        provider_registry=registry,
        hitl_callback=hitl_callback,
        roles=roles,
    )
```

(`replace(pre_ctx, tracer=tracer)` dans l'appel à `_persisted_run` préserve `hitl_callback` automatiquement.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/cli/test_solve_runs.py -v`
Expected: PASS

Puis non-régression CLI helpers :
Run: `.venv\Scripts\python -m pytest tests/cli -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/cli/solve_runs.py tests/cli/test_solve_runs.py
git commit -m "feat(hitl): wire hitl_callback through solve_once [ipv]"
```

---

### Task 6: `app.solve --hitl` — flag CLI + callback stdin

**Files:**
- Modify: `src/aaosa/cli/app.py:67-101`
- Test: `tests/cli/test_app_solve.py` (ajouter ; créer si absent)

**Interfaces:**
- Consumes: `solve_once(..., hitl_callback=...)` (Task 5).
- Produces: option Typer `--hitl/--no-hitl` (défaut `False`) ; helper module-level `_stdin_hitl(question: str) -> str` ; appel `solve_once(..., hitl_callback=_stdin_hitl if hitl else None)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_app_solve.py  (ajouter)
from pathlib import Path

from typer.testing import CliRunner

from aaosa.cli import app as app_module
from aaosa.cli.solve_runs import SolveOutcome

runner = CliRunner()


def _fake_outcome() -> SolveOutcome:
    return SolveOutcome(
        kind="success",
        session_id="s1",
        session_dir=Path("runs/s1"),
        snapshot_path=Path("runs/elo.json"),
        manifest_path=Path("runs/s1/manifest.json"),
        events=[],
        task_description="do it",
        n_agents=1,
    )


def test_solve_hitl_flag_passes_callback(monkeypatch, tmp_path):
    seen = {}

    def fake_solve_once(roster, task, context, runs_root, provider, *, roles_path=None, hitl_callback=None):
        seen["hitl_callback"] = hitl_callback
        return _fake_outcome()

    monkeypatch.setattr(app_module, "solve_once", fake_solve_once)
    roster = tmp_path / "r1"
    roster.mkdir()

    result = runner.invoke(app_module.app, ["solve", "--roster", str(roster), "--task", "do it", "--hitl"])
    assert result.exit_code == 0
    assert callable(seen["hitl_callback"])


def test_solve_no_hitl_defaults_none(monkeypatch, tmp_path):
    seen = {}

    def fake_solve_once(roster, task, context, runs_root, provider, *, roles_path=None, hitl_callback=None):
        seen["hitl_callback"] = hitl_callback
        return _fake_outcome()

    monkeypatch.setattr(app_module, "solve_once", fake_solve_once)
    roster = tmp_path / "r1"
    roster.mkdir()

    result = runner.invoke(app_module.app, ["solve", "--roster", str(roster), "--task", "do it"])
    assert result.exit_code == 0
    assert seen["hitl_callback"] is None
```

> Le `fake_solve_once` ci-dessus déclare `roles_path`/`hitl_callback` en
> keyword-only pour matcher l'appel ; si l'appel réel passe `roles_path`
> en positionnel, aligner la signature du fake sur l'appel produit en Step 3.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/cli/test_app_solve.py -v`
Expected: FAIL — `--hitl` n'est pas une option reconnue (exit_code != 0) / `hitl_callback` non transmis.

- [ ] **Step 3: Write the implementation**

Dans `src/aaosa/cli/app.py`, ajouter un helper module-level (près des imports / au-dessus de la commande `solve`) :

```python
def _stdin_hitl(question: str) -> str:
    """Callback HITL interactif : pose la question à l'opérateur, lit stdin."""
    typer.echo(f"\n[HITL] Agent asks: {question}")
    return typer.prompt("[HITL] Your answer")
```

Ajouter l'option dans la signature de `solve` (après `roles`) :

```python
    hitl: bool = typer.Option(
        False, "--hitl/--no-hitl",
        help="Active le HITL interactif (l'agent peut demander à l'opérateur via stdin)",
    ),
```

Et modifier l'appel à `solve_once` pour passer le callback :

```python
        outcome = solve_once(
            roster, task, context, runs_root, provider,
            roles_path=roles,
            hitl_callback=_stdin_hitl if hitl else None,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/cli/test_app_solve.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite (regression gate)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS (1189 existants + nouveaux, 0 régression). `run --scenario` intact.

- [ ] **Step 6: Commit**

```bash
git add src/aaosa/cli/app.py tests/cli/test_app_solve.py
git commit -m "feat(hitl): aaosa solve --hitl interactive stdin callback [ipv]"
```

---

## DoD (rappel spec §9)

- Suite complète verte via le venv.
- Un agent portant `ask_human` peut poser une question en cours de run → réponse réinjectée → run termine ; échange visible dans `trace.jsonl` (`ToolCalledEvent` `ask_human`). **Couvert par Task 4 (unitaire/intégration).**
- `aaosa solve --hitl` interactif (stdin) ; `--no-hitl` dégrade sans bloquer. **Couvert par Task 6 + sentinelle Task 1.**
- `run --scenario {main|roster_gap}` inchangé. **Garde-fou : suite globale verte Task 6 Step 5.**
- **Smoke LLM réel (matin, sign-off Quentin, PAS la nuit)** : roster jouet avec un agent qui appelle `ask_human` en `--hitl`, l'opérateur répond, le run aboutit. Hors périmètre TDD automatisé.

## Self-review (couverture spec)

- Spec §4.1 (builder + sentinelle) → Task 1.
- Spec §4.2 (RunContext.hitl_callback) → Task 2.
- Spec §4.3 (built-ins fusionnés, nom réservé) → Task 3.
- Spec §2/§5 (forme tool, échange tracé via ToolCalledEvent, runtime intact) → Task 4.
- Spec §4.4 (solve_once wiring) → Task 5.
- Spec §4.4 (CLI `--hitl`, stdin vs sentinelle) → Task 6.
- Spec §6 (extensibilité V2) → garanti par le seam `RunContext.hitl_callback` (Task 2), non implémenté (hors périmètre, conforme).
- Tous les types/noms (`HITLCallback`, `ASK_HUMAN_TOOL_NAME`, `make_ask_human_tool`, `build_builtin_tools`, `unattended_callback`, `hitl_callback`, `builtin_tools`) sont cohérents entre tasks.
