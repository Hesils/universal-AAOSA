# `cnq` — `aaosa solve --context-dir` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un flag `--context-dir <dir>` à `aaosa solve` qui injecte l'arborescence filtrée (liste de chemins relatifs) d'un dossier dans `Task.context`, sans son contenu.

**Architecture:** Un helper **pur** `cli/context_dir.py` walk le dossier (filtre dotfiles + `.gitignore` racine via `pathspec`) et rend une liste plate triée de chemins POSIX. `cli/app.py` câble ce helper comme 3ᵉ source dans le mécanisme `parts` existant de la commande `solve` (en-tête de provenance + budget `--context-max` partagé). Aucun changement de schéma ni de `solve_once`.

**Tech Stack:** Python 3.14, Typer 0.26.7, `pathspec>=1.1.1` (gitignore matching), pytest 9.0.3 + `typer.testing.CliRunner`.

**Spec:** `docs/superpowers/specs/2026-06-19-cnq-solve-context-dir.md`.

## Global Constraints

- Python 3.14, **toujours le venv** : `.venv\Scripts\python -m pytest` — jamais Python système.
- **Imports absolus uniquement** : `from aaosa.cli.context_dir import build_context_tree`, jamais relatifs.
- `app.py` = **seul endroit qui printe** (Typer). Le helper est **pur** : zéro print, zéro Typer.
- **Rétrocompat stricte** : sans `--context-dir`, comportement `solve` identique à erd.
- **Fail loud, jamais de troncature silencieuse** : overflow et filtrage-vide → `Exit(1)` avec message clair.
- Chemins rendus en séparateurs **POSIX** (`/`) via `.as_posix()`, déterministe cross-platform.
- Dernière version stable des deps (`pathspec>=1.1.1`, vérifiée sur PyPI le 2026-06-19).

---

### Task 1: Helper pur `build_context_tree` + dépendance pathspec

**Files:**
- Modify: `pyproject.toml` (ajout dep `pathspec>=1.1.1`)
- Create: `src/aaosa/cli/context_dir.py`
- Test: `tests/cli/test_context_dir.py`

**Interfaces:**
- Consumes: rien (pur, stdlib `os`/`pathlib` + `pathspec.GitIgnoreSpec`).
- Produces: `build_context_tree(root: Path) -> str` — liste triée newline-join de chemins relatifs POSIX ; lève `ValueError` si `root` n'est pas un dossier ou si zéro fichier après filtrage.

- [ ] **Step 1: Ajouter la dépendance pathspec**

Dans `pyproject.toml`, sous `dependencies = [`, ajouter la ligne (après `"typer>=0.26.7",`) :

```toml
    "pathspec>=1.1.1",
```

Puis installer :

```bash
.venv/Scripts/python -m pip install "pathspec>=1.1.1"
```

Expected: `Successfully installed pathspec-1.1.1` (ou déjà présent).

- [ ] **Step 2: Écrire les tests du helper (échouent)**

Créer `tests/cli/test_context_dir.py` :

```python
# tests/cli/test_context_dir.py
import pytest

from aaosa.cli.context_dir import build_context_tree


def _mk(tmp_path, rel, content="x"):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_flat_sorted_relative_posix_paths(tmp_path):
    _mk(tmp_path, "src/main.py")
    _mk(tmp_path, "notes/roadmap.md")
    _mk(tmp_path, "notes/decisions.md")
    tree = build_context_tree(tmp_path)
    assert tree == "notes/decisions.md\nnotes/roadmap.md\nsrc/main.py"


def test_dotfiles_and_dotdirs_excluded(tmp_path):
    _mk(tmp_path, "keep.md")
    _mk(tmp_path, ".env", "secret")
    _mk(tmp_path, ".git/config", "[core]")
    _mk(tmp_path, ".obsidian/app.json", "{}")
    tree = build_context_tree(tmp_path)
    assert tree == "keep.md"


def test_gitignore_root_honored(tmp_path):
    _mk(tmp_path, ".gitignore", "*.log\nbuild/\n!keep.log\n")
    _mk(tmp_path, "app.py")
    _mk(tmp_path, "debug.log", "noise")
    _mk(tmp_path, "keep.log", "kept")
    _mk(tmp_path, "build/artifact.bin", "blob")
    tree = build_context_tree(tmp_path)
    assert tree == "app.py\nkeep.log"


def test_paths_are_posix_even_in_subdirs(tmp_path):
    _mk(tmp_path, "a/b/c.md")
    tree = build_context_tree(tmp_path)
    assert tree == "a/b/c.md"
    assert "\\" not in tree


def test_not_a_directory_raises(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(ValueError, match="not found or not a directory"):
        build_context_tree(missing)


def test_empty_after_filtering_raises(tmp_path):
    _mk(tmp_path, ".env", "only dotfiles")
    with pytest.raises(ValueError, match="no files"):
        build_context_tree(tmp_path)
```

- [ ] **Step 3: Lancer les tests pour vérifier qu'ils échouent**

Run: `.venv\Scripts\python -m pytest tests/cli/test_context_dir.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aaosa.cli.context_dir'`.

- [ ] **Step 4: Écrire le helper minimal**

Créer `src/aaosa/cli/context_dir.py` :

```python
"""Helper pur de `aaosa solve --context-dir` : walk filtré -> arbo de chemins.

Zéro print, zéro Typer (convention de pureté CLI du repo). app.py câble + printe.
Injecte l'ARBORESCENCE seule (chemins relatifs), jamais le contenu : les agents
fetchent les fichiers via leurs tools (Monde B).
"""

import os
from pathlib import Path

from pathspec import GitIgnoreSpec


def build_context_tree(root: Path) -> str:
    """Walk `root`, retourne la liste triée (newline-join) des chemins relatifs
    POSIX des fichiers, en filtrant dotfiles/dot-dirs + matches `.gitignore`
    racine. Pur. Lève ValueError si `root` n'est pas un dossier ou si aucun
    fichier ne subsiste après filtrage."""
    if not root.is_dir():
        raise ValueError(f"context-dir not found or not a directory: {root}")

    gitignore = root / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.is_file() else []
    spec = GitIgnoreSpec.from_lines(lines)

    rels: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # pruner les dot-dirs (.git, .obsidian, .venv) ET les dirs gitignorés
        kept_dirs = []
        for d in dirnames:
            if d.startswith("."):
                continue
            drel = (Path(dirpath) / d).relative_to(root).as_posix() + "/"
            if spec.match_file(drel):
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs

        for fn in filenames:
            if fn.startswith("."):
                continue
            rel = (Path(dirpath) / fn).relative_to(root).as_posix()
            if spec.match_file(rel):
                continue
            rels.append(rel)

    if not rels:
        raise ValueError(f"no files under {root} after filtering")

    return "\n".join(sorted(rels))
```

- [ ] **Step 5: Lancer les tests pour vérifier qu'ils passent**

Run: `.venv\Scripts\python -m pytest tests/cli/test_context_dir.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/aaosa/cli/context_dir.py tests/cli/test_context_dir.py
git commit -m "feat(cnq): pure build_context_tree helper (filtered walk + gitignore) [cnq]"
```

---

### Task 2: Câblage CLI `--context-dir` dans `solve`

**Files:**
- Modify: `src/aaosa/cli/app.py` (commande `solve` : nouveau paramètre + bloc `parts`)
- Test: `tests/cli/test_solve_context_dir.py`

**Interfaces:**
- Consumes: `build_context_tree(root: Path) -> str` (Task 1) ; `solve_once(...)` et `SolveOutcome` inchangés.
- Produces: rien de nouveau pour l'aval — `context` reste un `str | None` passé à `solve_once`.

- [ ] **Step 1: Écrire les tests d'intégration CLI (échouent)**

Créer `tests/cli/test_solve_context_dir.py` :

```python
# tests/cli/test_solve_context_dir.py
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


def _roster(tmp_path) -> Path:
    d = tmp_path / "r"
    d.mkdir(parents=True, exist_ok=True)
    (d / "agents.yaml").write_text(
        "- name: a\n  tags_with_elo: {x: 1500}\n  system_prompt: p\n", encoding="utf-8"
    )
    return d


def _ctxdir(tmp_path) -> Path:
    c = tmp_path / "vault"
    (c / "notes").mkdir(parents=True, exist_ok=True)
    (c / "notes" / "a.md").write_text("aaa", encoding="utf-8")
    (c / "b.py").write_text("bbb", encoding="utf-8")
    return c


def test_context_dir_injects_tree_with_provenance_header(tmp_path, monkeypatch):
    captured = {}
    def fake_solve_once(roster_dirs, task_text, context, runs_root, provider_name="ollama",
                        roles_path=None, hitl_callback=None):
        captured["context"] = context
        return _fake_outcome(tmp_path)
    monkeypatch.setattr(app_mod, "solve_once", fake_solve_once)

    c = _ctxdir(tmp_path)
    result = runner.invoke(app, [
        "solve", "--roster", str(_roster(tmp_path)), "--task", "do it",
        "--context-dir", str(c), "--runs-root", str(tmp_path / "runs"),
    ])
    assert result.exit_code == 0, result.output
    assert f"# context: tree of {c}\n" in captured["context"]
    assert "b.py" in captured["context"]
    assert "notes/a.md" in captured["context"]


def test_context_dir_combines_with_context_text(tmp_path, monkeypatch):
    captured = {}
    def fake_solve_once(roster_dirs, task_text, context, runs_root, provider_name="ollama",
                        roles_path=None, hitl_callback=None):
        captured["context"] = context
        return _fake_outcome(tmp_path)
    monkeypatch.setattr(app_mod, "solve_once", fake_solve_once)

    c = _ctxdir(tmp_path)
    result = runner.invoke(app, [
        "solve", "--roster", str(_roster(tmp_path)), "--task", "x",
        "--context-text", "inline-ctx", "--context-dir", str(c),
    ])
    assert result.exit_code == 0, result.output
    ctx = captured["context"]
    assert "# context: inline\ninline-ctx" in ctx
    assert f"# context: tree of {c}\n" in ctx
    assert ctx.index("inline-ctx") < ctx.index("tree of")  # ordre: text avant dir


def test_context_dir_overflow_refused(tmp_path, monkeypatch):
    called = {"n": 0}
    def fake_solve_once(*a, **k):
        called["n"] += 1
        return _fake_outcome(tmp_path)
    monkeypatch.setattr(app_mod, "solve_once", fake_solve_once)

    c = _ctxdir(tmp_path)
    result = runner.invoke(app, [
        "solve", "--roster", str(_roster(tmp_path)), "--task", "x",
        "--context-dir", str(c), "--context-max", "5",
    ])
    assert result.exit_code == 1
    assert "too large" in result.output.lower()
    assert called["n"] == 0  # refus AVANT solve_once


def test_context_dir_invalid_exits_1(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "solve_once", lambda *a, **k: _fake_outcome(tmp_path))
    missing = tmp_path / "nope"
    result = runner.invoke(app, [
        "solve", "--roster", str(_roster(tmp_path)), "--task", "x",
        "--context-dir", str(missing),
    ])
    assert result.exit_code == 1
    assert "not found or not a directory" in result.output
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `.venv\Scripts\python -m pytest tests/cli/test_solve_context_dir.py -v`
Expected: FAIL — `--context-dir` n'existe pas (Typer rejette l'option / `No such option`).

- [ ] **Step 3: Ajouter le paramètre `--context-dir` à `solve`**

Dans `src/aaosa/cli/app.py`, ajouter le paramètre après `context_file` (ligne ~78) dans la signature de `def solve(`:

```python
    context_dir: Path | None = typer.Option(
        None, "--context-dir",
        help="Arborescence (chemins relatifs) injectée dans le contexte ; les agents fetchent les fichiers via leurs tools. Filtré (dotfiles + .gitignore).",
    ),
```

- [ ] **Step 4: Importer le helper et câbler le bloc `parts`**

En tête de `src/aaosa/cli/app.py`, ajouter l'import (avec les autres imports `aaosa.cli`) :

```python
from aaosa.cli.context_dir import build_context_tree
```

Dans le corps de `solve`, juste après le bloc `if context_file is not None:` (après la ligne `parts.append(f"# context: {context_file}\n{file_text}")`) et avant `context = "\n\n".join(...)` :

```python
    if context_dir is not None:
        try:
            tree = build_context_tree(context_dir)
        except ValueError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1)
        parts.append(f"# context: tree of {context_dir}\n{tree}")
```

- [ ] **Step 5: Lancer les tests pour vérifier qu'ils passent**

Run: `.venv\Scripts\python -m pytest tests/cli/test_solve_context_dir.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Non-régression — suite CLI complète**

Run: `.venv\Scripts\python -m pytest tests/cli/ -v`
Expected: PASS (tous, dont `test_app_solve.py` inchangé).

- [ ] **Step 7: Commit**

```bash
git add src/aaosa/cli/app.py tests/cli/test_solve_context_dir.py
git commit -m "feat(cnq): wire --context-dir into aaosa solve [cnq]"
```

---

### Task 3: Verrou final + nettoyage

**Files:**
- Delete: `verify_context.py` (script jetable de vérif schéma, racine repo, untracked)

- [ ] **Step 1: Supprimer le script d'exploration jetable**

```bash
git rm --cached verify_context.py 2>/dev/null; rm -f verify_context.py
```

(Le fichier est untracked — `rm -f` suffit. Il vérifiait `Task.context`, déjà couvert par les tests de schéma.)

- [ ] **Step 2: Suite complète verte**

Run: `.venv\Scripts\python -m pytest`
Expected: PASS (tout vert, +10 tests cnq).

- [ ] **Step 3: Logger la décision dépendance**

Ajouter dans le vault `Projects/universal-AAOSA/decisions.md` une entrée datée 2026-06-19 : « cnq — ajout dep runtime `pathspec>=1.1.1` pour honorer `.gitignore` correctement dans `--context-dir` (vs parser maison rejeté = résolution silencieuse défaillante). »

- [ ] **Step 4: Smoke manuel — DEFER MATIN (Quentin)**

> **Pas la nuit** (convention projet : DoD LLM-réel = matin). À faire au review :
> `aaosa solve --roster rosters/jouet --task "documente ce repo" --context-dir src/aaosa/cli --provider openai`
> Vérifier dans `trace.jsonl` que le `Task.context` racine contient `# context: tree of …` + l'arbo filtrée, et qu'un `--context-max` petit refuse proprement.

## Self-Review

**Spec coverage** :
- §2.1 flag `--context-dir` → Task 2 Step 3. ✓
- §2.2 walk filtré → arbo triée POSIX → Task 1. ✓
- §2.3 filtrage dotfiles + `.gitignore` → Task 1 Steps 2/4 (tests `test_dotfiles…`, `test_gitignore…`). ✓
- §2.4 budget `--context-max` réutilisé → Task 2 (`test_context_dir_overflow_refused`, mécanisme app.py inchangé). ✓
- §2.5 erreurs dir absent / vide après filtrage → Task 1 (`ValueError`) + Task 2 (`Exit 1`). ✓
- §3 dep `pathspec>=1.1.1` → Task 1 Step 1 + Task 3 Step 3 (log). ✓
- §4 en-tête `# context: tree of <dir>`, ordre text→file→dir → Task 2 (`test_…provenance_header`, `test_…combines…`). ✓
- §5 modules (helper pur + app.py câblage) → Tasks 1 & 2. ✓
- §7 invariants (Task.context/solve_once intacts, app.py seul à printer, rétrocompat) → aucun fichier schéma/runtime touché. ✓

**Placeholder scan** : aucun TODO/TBD ; tout le code est complet et exécutable.

**Type consistency** : `build_context_tree(root: Path) -> str` cohérent entre Task 1 (def), Task 2 (import + appel). `context: str | None` inchangé. `SolveOutcome` reconstruit à l'identique des tests existants.
