# v1m — Sécurité Monde B (sandbox FS + plancher non-destruction + fetch_file) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poser le substrat de sécurité de Monde B (isolation FS par run + plancher de non-destruction structurel) et livrer le premier vrai tool exécuteur `fetch_file`, sans toucher au runtime synchrone.

**Architecture:** Une `Sandbox` (objet pur, frozen) est l'**unique porte FS** : path jail sur lecture/écriture + refus d'écriture si `writable=False` (enforce par construction, doctrine night-guard). Les tools FS la capturent en closure (précédent `ipv`). `fetch_file` (built-in injecté seulement si `--context-dir` fourni) lit sous la racine jalée. `tool.py`/`agent.py`/`runner.py`/`dispatch.py` = 0 diff ; tout vit dans 2 modules neufs + le wiring `solve_once`/`app.py`.

**Tech Stack:** Python 3.14, `uv`, Pydantic 2, Typer 0.26, pytest 9 + typer.testing.CliRunner. Imports absolus. Venv obligatoire (`.venv\Scripts\python -m pytest`).

**Spec source:** `docs/superpowers/specs/2026-06-19-v1m-securite-monde-b-sandbox.md`.

## Global Constraints

- **Imports absolus uniquement** (`from aaosa.core.sandbox import Sandbox`).
- **Rétrocompat stricte** : `sandbox=None` ⇒ runtime identique ; aucun champ obligatoire ajouté ; suite globale (≥ 1215 tests) reste verte, 0 régression.
- **Runtime intouché** : ne pas modifier `core/tool.py`, `core/agent.py`, `runtime/runner.py`, `runtime/dispatch.py`.
- **Tools retournent toujours `str`** : `fetch_file` ne lève jamais dans la boucle tool-use.
- **Enforce > instruct** : la non-destruction est structurelle (la Sandbox refuse), jamais une consigne au prompt.
- **Backend pur ⇒ nuit-compatible** : DoD = tests verts, aucun appel LLM. Smoke LLM-réel = matin Quentin.
- Tests via le venv : `.venv\Scripts\python -m pytest <fichier> -v`.
- `fetch_file` (nom neuf, distinct du stub `read_file` de la démo) ; `--fetch-max` défaut 50000 chars, refus dur sans troncature.

---

### Task 1: Sandbox — unique porte FS (path jail + plancher non-destruction)

**Files:**
- Create: `src/aaosa/core/sandbox.py`
- Test: `tests/core/test_sandbox.py`

**Interfaces:**
- Produces: `SandboxViolation(Exception)` ; `Sandbox` (frozen dataclass) avec `root: Path`, `writable: bool = False`, classmethod `for_reading(root) -> Sandbox`, `resolve(rel_path: str) -> Path`, `read_text(rel_path: str) -> str`, `write_text(rel_path: str, data: str) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/core/test_sandbox.py
import os

import pytest

from aaosa.core.sandbox import Sandbox, SandboxViolation


def _tree(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "sub" / "b.txt").write_text("world", encoding="utf-8")
    return tmp_path


def test_for_reading_is_readonly_and_resolved(tmp_path):
    sb = Sandbox.for_reading(_tree(tmp_path))
    assert sb.writable is False
    assert sb.root == tmp_path.resolve()


def test_read_text_under_root(tmp_path):
    sb = Sandbox.for_reading(_tree(tmp_path))
    assert sb.read_text("a.txt") == "hello"
    assert sb.read_text("sub/b.txt") == "world"


def test_resolve_rejects_parent_traversal(tmp_path):
    sb = Sandbox.for_reading(_tree(tmp_path))
    with pytest.raises(SandboxViolation):
        sb.resolve("../outside.txt")


def test_resolve_rejects_absolute_path(tmp_path):
    sb = Sandbox.for_reading(_tree(tmp_path))
    with pytest.raises(SandboxViolation):
        sb.resolve(str(tmp_path.parent / "x.txt"))


def test_resolve_rejects_symlink_escaping_root(tmp_path):
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("top secret", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    link = root / "leak.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted in this environment")
    sb = Sandbox.for_reading(root)
    with pytest.raises(SandboxViolation):
        sb.read_text("leak.txt")


def test_write_text_refused_on_readonly(tmp_path):
    sb = Sandbox.for_reading(_tree(tmp_path))
    with pytest.raises(SandboxViolation):
        sb.write_text("new.txt", "data")
    assert not (tmp_path / "new.txt").exists()


def test_write_text_allowed_when_writable(tmp_path):
    sb = Sandbox(root=tmp_path.resolve(), writable=True)
    sb.write_text("nested/new.txt", "data")
    assert (tmp_path / "nested" / "new.txt").read_text(encoding="utf-8") == "data"


def test_write_text_still_jailed_when_writable(tmp_path):
    sb = Sandbox(root=tmp_path.resolve(), writable=True)
    with pytest.raises(SandboxViolation):
        sb.write_text("../escape.txt", "data")


def test_for_reading_missing_root_raises(tmp_path):
    with pytest.raises(SandboxViolation):
        Sandbox.for_reading(tmp_path / "does-not-exist")


def test_for_reading_file_not_dir_raises(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(SandboxViolation):
        Sandbox.for_reading(f)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/core/test_sandbox.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aaosa.core.sandbox'`

- [ ] **Step 3: Write the implementation**

```python
# src/aaosa/core/sandbox.py
"""Sandbox (v1m) — isolation FS par run + plancher de non-destruction.

Unique porte d'accès FS pour les tools d'agent (Monde B). Path jail : aucun
chemin ne sort de `root`. Plancher de non-destruction : `writable=False` par
défaut -> toute écriture lève SandboxViolation (enforce par construction, pas
une consigne au prompt). Doctrine reprise de night-guard-destructive-floor.
"""

from dataclasses import dataclass
from pathlib import Path


class SandboxViolation(Exception):
    """Accès hors racine, ou écriture sur une sandbox read-only."""


@dataclass(frozen=True)
class Sandbox:
    root: Path
    writable: bool = False

    @classmethod
    def for_reading(cls, root: Path) -> "Sandbox":
        resolved = Path(root).resolve()
        if not resolved.is_dir():
            raise SandboxViolation(f"sandbox root is not a directory: {root}")
        return cls(root=resolved, writable=False)

    def resolve(self, rel_path: str) -> Path:
        candidate = (self.root / rel_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            raise SandboxViolation(f"path escapes sandbox root: {rel_path!r}")
        return candidate

    def read_text(self, rel_path: str) -> str:
        return self.resolve(rel_path).read_text(encoding="utf-8")

    def write_text(self, rel_path: str, data: str) -> None:
        if not self.writable:
            raise SandboxViolation("sandbox is read-only: writes are disabled")
        target = self.resolve(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/core/test_sandbox.py -v`
Expected: PASS (le test symlink peut être `SKIPPED` selon les droits Windows)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/core/sandbox.py tests/core/test_sandbox.py
git commit -m "feat(v1m): Sandbox — path jail + non-destruction floor [v1m]"
```

---

### Task 2: fetch_file réel + sample write_file (preuve du contrat)

**Files:**
- Create: `src/aaosa/core/fs_tools.py`
- Test: `tests/core/test_fs_tools.py`

**Interfaces:**
- Consumes: `Sandbox`, `SandboxViolation` (Task 1) ; `ToolDef` (`aaosa.core.tool`).
- Produces: `FETCH_FILE_TOOL_NAME = "fetch_file"` ; `DEFAULT_FETCH_MAX_CHARS = 50_000` ; `make_fetch_file_tool(sandbox: Sandbox, max_chars: int = DEFAULT_FETCH_MAX_CHARS) -> ToolDef` ; `make_write_file_tool(sandbox: Sandbox) -> ToolDef` (preuve du plancher pour les futurs tools write).

- [ ] **Step 1: Write the failing tests**

```python
# tests/core/test_fs_tools.py
from aaosa.core.fs_tools import (
    DEFAULT_FETCH_MAX_CHARS,
    FETCH_FILE_TOOL_NAME,
    make_fetch_file_tool,
    make_write_file_tool,
)
from aaosa.core.sandbox import Sandbox


def _ro(tmp_path):
    (tmp_path / "a.txt").write_text("hello world", encoding="utf-8")
    (tmp_path / "big.txt").write_text("x" * 100, encoding="utf-8")
    (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00\x01")
    return Sandbox.for_reading(tmp_path)


def test_fetch_file_returns_content(tmp_path):
    tool = make_fetch_file_tool(_ro(tmp_path))
    assert tool.name == FETCH_FILE_TOOL_NAME
    assert tool.fn(path="a.txt") == "hello world"


def test_fetch_file_missing(tmp_path):
    tool = make_fetch_file_tool(_ro(tmp_path))
    assert tool.fn(path="nope.txt") == "[file not found: nope.txt]"


def test_fetch_file_escape_refused(tmp_path):
    tool = make_fetch_file_tool(_ro(tmp_path))
    out = tool.fn(path="../outside.txt")
    assert out.startswith("[refused:")


def test_fetch_file_binary_clear_error(tmp_path):
    tool = make_fetch_file_tool(_ro(tmp_path))
    out = tool.fn(path="bin.dat")
    assert out.startswith("[cannot read bin.dat:")


def test_fetch_file_too_large_hard_refusal(tmp_path):
    tool = make_fetch_file_tool(_ro(tmp_path), max_chars=10)
    out = tool.fn(path="big.txt")
    assert out.startswith("[file too large:")
    assert "100" in out and "10" in out


def test_fetch_file_under_limit_returns_full(tmp_path):
    tool = make_fetch_file_tool(_ro(tmp_path), max_chars=100)
    assert tool.fn(path="big.txt") == "x" * 100


def test_default_max_is_50k():
    assert DEFAULT_FETCH_MAX_CHARS == 50_000


def test_write_file_refused_on_readonly_sandbox(tmp_path):
    tool = make_write_file_tool(Sandbox.for_reading(tmp_path))
    out = tool.fn(path="new.txt", content="data")
    assert out.startswith("[refused:")
    assert not (tmp_path / "new.txt").exists()


def test_write_file_succeeds_on_writable_sandbox(tmp_path):
    tool = make_write_file_tool(Sandbox(root=tmp_path.resolve(), writable=True))
    out = tool.fn(path="new.txt", content="data")
    assert "new.txt" in out
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "data"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/core/test_fs_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aaosa.core.fs_tools'`

- [ ] **Step 3: Write the implementation**

```python
# src/aaosa/core/fs_tools.py
"""Tools FS framework (v1m). fetch_file réel, jalé par une Sandbox closurée.

Built-in injecté UNIQUEMENT quand une sandbox existe (donc --context-dir
fourni). La racine de lecture = la racine de la sandbox = le --context-dir
dont cnq a déjà injecté l'arborescence. Plafond de taille (refus dur, pas de
troncature) pour ne pas noyer le thread tool-use. make_write_file_tool prouve
le contrat de plancher que les futurs tools write/run devront honorer.
"""

from aaosa.core.sandbox import Sandbox, SandboxViolation
from aaosa.core.tool import ToolDef

FETCH_FILE_TOOL_NAME = "fetch_file"
WRITE_FILE_TOOL_NAME = "write_file"
DEFAULT_FETCH_MAX_CHARS = 50_000


def make_fetch_file_tool(
    sandbox: Sandbox, max_chars: int = DEFAULT_FETCH_MAX_CHARS
) -> ToolDef:
    def _fn(**kwargs: str) -> str:
        path = kwargs["path"]
        try:
            content = sandbox.read_text(path)
        except SandboxViolation as exc:
            return f"[refused: {exc}]"
        except FileNotFoundError:
            return f"[file not found: {path}]"
        except (IsADirectoryError, UnicodeDecodeError, OSError) as exc:
            return f"[cannot read {path}: {exc}]"
        if len(content) > max_chars:
            return (
                f"[file too large: {len(content)} chars > limit {max_chars}. "
                f"Refusing (no truncation). Narrow your request.]"
            )
        return content

    return ToolDef(
        name=FETCH_FILE_TOOL_NAME,
        description=(
            "Fetch the full UTF-8 contents of a file by its path, relative to "
            "the provided context directory. Use the paths listed in the "
            "context tree. Returns the file contents, or a clear error string "
            "if the file is missing, too large, binary, or outside the "
            "allowed directory."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to the context directory root.",
                }
            },
            "required": ["path"],
        },
        fn=_fn,
    )


def make_write_file_tool(sandbox: Sandbox) -> ToolDef:
    """Tool write gardé par le plancher. NON câblé en v1m (pas de --allow-write) ;
    sert à prouver que write_text refuse sur sandbox read-only."""

    def _fn(**kwargs: str) -> str:
        path = kwargs["path"]
        try:
            sandbox.write_text(path, kwargs["content"])
        except SandboxViolation as exc:
            return f"[refused: {exc}]"
        except OSError as exc:
            return f"[cannot write {path}: {exc}]"
        return f"[wrote {path}]"

    return ToolDef(
        name=WRITE_FILE_TOOL_NAME,
        description="Write UTF-8 content to a file path under the context directory.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        fn=_fn,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/core/test_fs_tools.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/core/fs_tools.py tests/core/test_fs_tools.py
git commit -m "feat(v1m): fetch_file tool (jailed, size-capped) + write_file floor proof [v1m]"
```

---

### Task 3: RunContext.sandbox + wiring solve_once

**Files:**
- Modify: `src/aaosa/runtime/context.py` (ajouter champ `sandbox`)
- Modify: `src/aaosa/cli/solve_runs.py` (params `context_dir`, `fetch_max` ; build sandbox ; injecte fetch_file ; pose `sandbox` dans RunContext)
- Test: `tests/cli/test_solve_runs.py` (ajouts)

**Interfaces:**
- Consumes: `Sandbox.for_reading` (Task 1) ; `make_fetch_file_tool`, `FETCH_FILE_TOOL_NAME`, `DEFAULT_FETCH_MAX_CHARS` (Task 2) ; `build_builtin_tools` (`aaosa.core.hitl`).
- Produces: `solve_once(..., context_dir: Path | None = None, fetch_max: int = DEFAULT_FETCH_MAX_CHARS)` ; `RunContext.sandbox: Sandbox | None = None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/cli/test_solve_runs.py` (imports en tête du fichier si absents : `from pathlib import Path`, `import pytest`, `from aaosa.cli.solve_runs import solve_once`, `from aaosa.core.fs_tools import FETCH_FILE_TOOL_NAME`, `from aaosa.core.sandbox import SandboxViolation`). Ces tests interceptent `load_rosters` via monkeypatch pour capturer les `builtin_tools` sans lancer de run LLM.

```python
def _make_roster(tmp_path):
    d = tmp_path / "r"
    d.mkdir(parents=True, exist_ok=True)
    (d / "agents.yaml").write_text(
        "- name: a\n  tags_with_elo: {x: 1500}\n  system_prompt: p\n", encoding="utf-8"
    )
    return d


def _ctxdir(tmp_path):
    c = tmp_path / "ctx"
    c.mkdir(parents=True, exist_ok=True)
    (c / "f.txt").write_text("content", encoding="utf-8")
    return c


def _capture_builtins(monkeypatch):
    """Stoppe solve_once juste après load_rosters et renvoie les builtin_tools vus."""
    seen = {}
    import aaosa.cli.solve_runs as sr

    def fake_load_rosters(roster_dirs, builtin_tools=None):
        seen["builtins"] = builtin_tools
        raise _StopForTest()

    monkeypatch.setattr(sr, "load_rosters", fake_load_rosters)
    return seen


class _StopForTest(Exception):
    pass


def test_solve_once_injects_fetch_file_when_context_dir(tmp_path, monkeypatch):
    seen = _capture_builtins(monkeypatch)
    with pytest.raises(_StopForTest):
        solve_once(
            [_make_roster(tmp_path)], "task", None, tmp_path / "runs",
            context_dir=_ctxdir(tmp_path),
        )
    assert FETCH_FILE_TOOL_NAME in seen["builtins"]


def test_solve_once_no_fetch_file_without_context_dir(tmp_path, monkeypatch):
    seen = _capture_builtins(monkeypatch)
    with pytest.raises(_StopForTest):
        solve_once([_make_roster(tmp_path)], "task", None, tmp_path / "runs")
    assert FETCH_FILE_TOOL_NAME not in (seen["builtins"] or {})


def test_solve_once_fetch_max_propagated(tmp_path, monkeypatch):
    seen = _capture_builtins(monkeypatch)
    with pytest.raises(_StopForTest):
        solve_once(
            [_make_roster(tmp_path)], "task", None, tmp_path / "runs",
            context_dir=_ctxdir(tmp_path), fetch_max=3,
        )
    # "content" = 7 chars > fetch_max=3 -> refus dur
    out = seen["builtins"][FETCH_FILE_TOOL_NAME].fn(path="f.txt")
    assert out.startswith("[file too large:")


def test_solve_once_missing_context_dir_raises(tmp_path):
    with pytest.raises(SandboxViolation):
        solve_once(
            [_make_roster(tmp_path)], "task", None, tmp_path / "runs",
            context_dir=tmp_path / "nope",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/cli/test_solve_runs.py -v -k "fetch or context_dir or missing_context"`
Expected: FAIL (`TypeError: solve_once() got an unexpected keyword argument 'context_dir'`)

- [ ] **Step 3a: Add the RunContext field**

In `src/aaosa/runtime/context.py`, add the import and the field (after `hitl_callback`, before `roles`):

```python
from aaosa.core.sandbox import Sandbox
```

```python
    hitl_callback: "HITLCallback | None" = None
    sandbox: "Sandbox | None" = None        # v1m — racine FS jalée du run
    roles: RoleProviders = field(default_factory=RoleProviders)
```

- [ ] **Step 3b: Wire solve_once**

In `src/aaosa/cli/solve_runs.py` add imports:

```python
from aaosa.core.fs_tools import (
    DEFAULT_FETCH_MAX_CHARS,
    FETCH_FILE_TOOL_NAME,
    make_fetch_file_tool,
)
from aaosa.core.sandbox import Sandbox
```

Extend the signature (after `hitl_callback`):

```python
    hitl_callback: HITLCallback | None = None,
    context_dir: Path | None = None,
    fetch_max: int = DEFAULT_FETCH_MAX_CHARS,
) -> SolveOutcome:
```

Replace the builtins line and build the sandbox before `load_rosters`:

```python
    builtin_tools = build_builtin_tools(hitl_callback)
    sandbox = Sandbox.for_reading(context_dir) if context_dir is not None else None
    if sandbox is not None:
        builtin_tools[FETCH_FILE_TOOL_NAME] = make_fetch_file_tool(sandbox, fetch_max)
    agents = load_rosters(roster_dirs, builtin_tools=builtin_tools)
```

Add `sandbox=sandbox` to the `RunContext(...)` construction (alongside `hitl_callback=hitl_callback`):

```python
        hitl_callback=hitl_callback,
        sandbox=sandbox,
        roles=roles,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/cli/test_solve_runs.py tests/runtime/test_context.py -v`
Expected: PASS (nouveaux tests verts + tests RunContext existants inchangés)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/context.py src/aaosa/cli/solve_runs.py tests/cli/test_solve_runs.py
git commit -m "feat(v1m): wire sandbox + fetch_file into solve_once + RunContext.sandbox [v1m]"
```

---

### Task 4: CLI — option --fetch-max, passage context_dir, catch SandboxViolation

**Files:**
- Modify: `src/aaosa/cli/app.py` (option `--fetch-max` ; passe `context_dir`/`fetch_max` ; attrape `SandboxViolation`)
- Test: `tests/cli/test_app_solve.py` (ajouts) + mise à jour des stubs `fake_solve_once` qui ont une signature explicite

**Interfaces:**
- Consumes: `solve_once(..., context_dir=, fetch_max=)` (Task 3) ; `SandboxViolation` (Task 1).

- [ ] **Step 1: Update existing fake stubs that would break**

Les stubs `fake_solve_once` à signature explicite cassent dès qu'`app.py` passe `context_dir=`/`fetch_max=`. Dans `tests/cli/test_solve_context_dir.py`, remplacer les deux signatures explicites par une tolérante :

```python
    def fake_solve_once(roster_dirs, task_text, context, runs_root, provider_name="ollama",
                        roles_path=None, hitl_callback=None, **kwargs):
        captured["context"] = context
        return _fake_outcome(tmp_path)
```

(le 3ᵉ stub utilise déjà `*a, **k` — laisser tel quel.) Faire la même tolérance `**kwargs` sur tout autre `fake_solve_once` à signature explicite trouvé via :

Run: `git grep -n "def fake_solve_once" tests/`
Pour chaque occurrence à signature explicite, ajouter `**kwargs`.

- [ ] **Step 2: Write the failing tests**

Append to `tests/cli/test_app_solve.py` (réutiliser les helpers `_roster`/`_ctxdir`/`_fake_outcome` présents dans `tests/cli/test_solve_context_dir.py` — soit les importer, soit recopier localement ; ici on les redéfinit localement pour l'autonomie du fichier) :

```python
from pathlib import Path

from typer.testing import CliRunner

import aaosa.cli.app as app_mod
from aaosa.cli.app import app
from aaosa.cli.solve_runs import SolveOutcome
from aaosa.core.sandbox import SandboxViolation

runner = CliRunner()


def _outcome(tmp):
    sd = Path(tmp) / "s"
    return SolveOutcome(kind="success", session_id="s", session_dir=sd,
                        snapshot_path=sd / "snap.json", manifest_path=sd / "m.json",
                        events=[], task_description="t", n_agents=1)


def _roster2(tmp_path):
    d = tmp_path / "r2"
    d.mkdir(parents=True, exist_ok=True)
    (d / "agents.yaml").write_text(
        "- name: a\n  tags_with_elo: {x: 1500}\n  system_prompt: p\n", encoding="utf-8")
    return d


def _ctx2(tmp_path):
    c = tmp_path / "ctx2"
    c.mkdir(parents=True, exist_ok=True)
    (c / "f.txt").write_text("hi", encoding="utf-8")
    return c


def test_fetch_max_forwarded_to_solve_once(tmp_path, monkeypatch):
    captured = {}
    def fake(*a, **k):
        captured.update(k)
        return _outcome(tmp_path)
    monkeypatch.setattr(app_mod, "solve_once", fake)
    result = runner.invoke(app, [
        "solve", "--roster", str(_roster2(tmp_path)), "--task", "t",
        "--context-dir", str(_ctx2(tmp_path)), "--fetch-max", "1234",
    ])
    assert result.exit_code == 0, result.output
    assert captured["context_dir"] == _ctx2(tmp_path)
    assert captured["fetch_max"] == 1234


def test_sandbox_violation_exits_1(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise SandboxViolation("sandbox root is not a directory: x")
    monkeypatch.setattr(app_mod, "solve_once", boom)
    result = runner.invoke(app, [
        "solve", "--roster", str(_roster2(tmp_path)), "--task", "t",
        "--context-dir", str(_ctx2(tmp_path)),
    ])
    assert result.exit_code == 1
    assert "sandbox" in result.output.lower()
```

- [ ] **Step 3: Implement the CLI changes**

In `src/aaosa/cli/app.py`, add the import:

```python
from aaosa.core.sandbox import SandboxViolation
```

Add the `--fetch-max` option in the `solve` command signature (after `context_max`):

```python
    fetch_max: int = typer.Option(
        50000, "--fetch-max",
        help="Refus dur si un fichier fetché via fetch_file dépasse (caractères)",
    ),
```

Pass the new args to `solve_once`:

```python
        outcome = solve_once(
            roster, task, context, runs_root, provider,
            roles_path=roles,
            hitl_callback=_stdin_hitl if hitl else None,
            context_dir=context_dir,
            fetch_max=fetch_max,
        )
```

Add a `SandboxViolation` arm to the existing `except` chain of `solve` (before the generic `ValueError`):

```python
    except SandboxViolation as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/cli/test_app_solve.py tests/cli/test_solve_context_dir.py -v`
Expected: PASS (nouveaux + anciens, stubs mis à jour)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/cli/app.py tests/cli/test_app_solve.py tests/cli/test_solve_context_dir.py
git commit -m "feat(v1m): CLI --fetch-max + context_dir->sandbox wiring + SandboxViolation exit [v1m]"
```

---

### Task 5: Full-suite verification + close

**Files:** none (vérification)

- [ ] **Step 1: Run the full suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: tout vert (≥ 1215 anciens + ~25 nouveaux), 0 échec, 0 régression. Le test symlink peut être `skipped` (droits Windows).

- [ ] **Step 2: Confirm demo untouched**

Run: `.venv\Scripts\python -m pytest tests/demo -q`
Expected: PASS — la démo incident (stub `read_file`) inchangée, aucun `fetch_file` injecté sans `--context-dir`.

- [ ] **Step 3: Update the spec status**

Edit the spec header `docs/superpowers/specs/2026-06-19-v1m-securite-monde-b-sandbox.md` : `Statut : proposée` → `Statut : implémentée (suite verte) — smoke LLM-réel à valider par Quentin`.

- [ ] **Step 4: Commit the status bump**

```bash
git add docs/superpowers/specs/2026-06-19-v1m-securite-monde-b-sandbox.md
git commit -m "docs(v1m): spec status -> implémentée [v1m]"
```

---

## Self-Review notes

- **Spec coverage** : §4.1 → Task 1 ; §4.2 + §3.7 (sample destructif) → Task 2 ; §4.3 (RunContext) + §4.4 (solve_once) → Task 3 ; §4.5 (app.py) → Task 4 ; §6 tests répartis ; §8 DoD → Task 5.
- **Décisions §9** : `fetch_file` (nom), `--fetch-max`/refus dur (taille), binaire→message clair (encodage) tous couverts en Task 2/4.
- **Type consistency** : `FETCH_FILE_TOOL_NAME`, `DEFAULT_FETCH_MAX_CHARS`, `make_fetch_file_tool(sandbox, max_chars)`, `Sandbox.for_reading`, `RunContext.sandbox`, `solve_once(context_dir=, fetch_max=)` — noms stables d'une tâche à l'autre.
- **Runtime intouché** : aucune tâche ne modifie `tool.py`/`agent.py`/`runner.py`/`dispatch.py`. ✓
- **Piège stubs CLI** : adressé explicitement en Task 4 Step 1 (les `fake_solve_once` à signature figée gagnent `**kwargs`).
