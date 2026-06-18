# Preflight dispo model par agent/rôle (ticket alf) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Avant tout run `aaosa solve`, vérifier que le model résolu de chaque agent ET de chaque rôle système est disponible dans son provider ; échouer avec une erreur claire (Exit 1) au lieu d'un échec LLM opaque en cours de route.

**Architecture:** Une capability `available_models()` sur `LLMProvider` (un seul code path : `client.models.list()`, exposé par OpenAI **et** par l'endpoint OpenAI-compatible d'Ollama `/v1/models`), une fonction pure `preflight_models(...)` qui agrège tous les manquants en une passe, câblée dans `solve_once` juste après `build_provider_registry` et avant `build_root_task` (échouer avant d'écrire une session demi-faite). La CLI traduit l'exception en Exit 1.

**Tech Stack:** Python 3.14, Pydantic 2.13, OpenAI SDK 2.38, Typer 0.26.7, pytest 9.0.3. venv obligatoire (`.venv\Scripts\python -m pytest`).

## Global Constraints

- Imports absolus uniquement (`from aaosa.runtime.providers import ...`).
- Tests via le venv : `.venv\Scripts\python -m pytest <fichier> -v` — jamais Python système.
- Rétrocompat stricte : `aaosa run --scenario` inchangé, le preflight ne touche QUE le chemin `solve`.
- Zéro consommation de tokens : `models.list()` / `/v1/models` ne fait pas d'inférence → nuit-compatible.
- TDD subagent-driven : test avant impl, commit fréquent.

### Décision de design notée (à valider à la review)

Le ticket dit « Ollama `/api/tags` ». On utilise à la place l'endpoint OpenAI-compatible `GET /v1/models` (déjà ciblé par le `_client` d'`OllamaProvider`, base_url `.../v1`), qui liste les mêmes models pullés avec les mêmes ids (`qwen3:4b`). Bénéfice : **un seul** code path `available_models()` dans la classe de base, partagé OpenAI/Ollama, testable avec un seul mock. Provider injoignable → l'appel lève → erreur preflight claire (comportement voulu).

### Couverture (tranché avec Quentin)

- Agents **+** les 7 rôles système (`divider`, `aggregator`, `tagger`, `evaluator`, `diagnostic`, `triage`, `task_spec`).
- Model résolu = `entité.model or registry[provider_name].default_model` — on préflighte aussi le **défaut** du provider (ex. `qwen3:4b`), pas seulement les models explicites.
- Provider injoignable → erreur preflight (même traitement qu'un model absent).
- Agrégation : tous les problèmes en un seul message (pas de fail-fast).

---

### Task 1: Capability provider — `default_model` + `available_models()`

**Files:**
- Modify: `src/aaosa/runtime/providers.py` (classe de base `LLMProvider`, après `_parse_via_json`)
- Test: `tests/runtime/test_providers.py` (ajouter une classe `TestAvailableModels`)

**Interfaces:**
- Produces:
  - `class ProviderUnreachableError(Exception)` dans `providers.py`
  - `LLMProvider.default_model -> str` (property, retourne `self._default_model`)
  - `LLMProvider.available_models(self) -> set[str]` — set des model ids ; lève `ProviderUnreachableError` si le provider est injoignable.

- [ ] **Step 1: Write the failing tests**

Ajouter dans `tests/runtime/test_providers.py` :

```python
from aaosa.runtime.providers import ProviderUnreachableError


class TestAvailableModels:
    def test_default_model_property(self):
        p = OpenAIProvider(client=_fake_openai(), default_model="gpt-4o")
        assert p.default_model == "gpt-4o"

    def test_available_models_returns_ids(self):
        client = _fake_openai()
        m1, m2 = MagicMock(), MagicMock()
        m1.id, m2.id = "gpt-4o-mini", "gpt-4o"
        client.models.list.return_value = [m1, m2]
        p = OpenAIProvider(client=client)
        assert p.available_models() == {"gpt-4o-mini", "gpt-4o"}

    def test_available_models_raises_provider_unreachable_on_error(self):
        client = _fake_openai()
        client.models.list.side_effect = RuntimeError("connection refused")
        p = OpenAIProvider(client=client)
        with pytest.raises(ProviderUnreachableError):
            p.available_models()

    def test_ollama_available_models_uses_same_path(self):
        p = OllamaProvider()
        p._client = _fake_openai()  # injecte un client mocké
        m = MagicMock()
        m.id = "qwen3:4b"
        p._client.models.list.return_value = [m]
        assert p.available_models() == {"qwen3:4b"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_providers.py::TestAvailableModels -v`
Expected: FAIL avec `ImportError: cannot import name 'ProviderUnreachableError'` (ou `AttributeError`).

- [ ] **Step 3: Write minimal implementation**

Dans `src/aaosa/runtime/providers.py`, ajouter après la définition de `DEFAULT_MODEL` (avant la classe) :

```python
class ProviderUnreachableError(Exception):
    """Le provider n'a pas pu être interrogé (serveur éteint, auth KO, réseau)."""
```

Puis dans la classe `LLMProvider`, après `_parse_via_json` :

```python
    @property
    def default_model(self) -> str:
        """Modèle utilisé quand aucun model explicite n'est demandé."""
        return self._default_model

    def available_models(self) -> set[str]:
        """Set des model ids exposés par le provider (OpenAI: /v1/models ;
        Ollama: endpoint OpenAI-compatible /v1/models = models pullés).

        Lève ProviderUnreachableError si le provider est injoignable.
        """
        try:
            return {m.id for m in self._client.models.list()}
        except Exception as exc:  # noqa: BLE001 — toute panne provider = injoignable
            raise ProviderUnreachableError(str(exc)) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_providers.py -v`
Expected: PASS (la nouvelle classe + les tests existants restent verts).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/providers.py tests/runtime/test_providers.py
git commit -m "feat(providers): available_models() + default_model + ProviderUnreachableError [alf]"
```

---

### Task 2: Fonction pure `preflight_models`

**Files:**
- Create: `src/aaosa/runtime/preflight.py`
- Test: `tests/runtime/test_preflight.py`

**Interfaces:**
- Consumes (Task 1): `LLMProvider.default_model`, `LLMProvider.available_models()`, `ProviderUnreachableError`.
- Produces:
  - `class PreflightError(Exception)` dans `preflight.py`
  - `def preflight_models(agents: list[Agent], roles: RoleProviders, registry: dict[str, LLMProvider], default_provider_name: str) -> None` — lève `PreflightError` (message agrégé) si ≥1 model absent ou ≥1 provider injoignable ; retourne `None` sinon.

- [ ] **Step 1: Write the failing tests**

Créer `tests/runtime/test_preflight.py` :

```python
import pytest

from aaosa.config.role_providers import RoleProvider, RoleProviders
from aaosa.core.agent import Agent
from aaosa.runtime.preflight import PreflightError, preflight_models
from aaosa.runtime.providers import ProviderUnreachableError


class _FakeProvider:
    def __init__(self, default_model: str, available: set[str] | None = None, unreachable: bool = False):
        self._default_model = default_model
        self._available = available if available is not None else {default_model}
        self._unreachable = unreachable

    @property
    def default_model(self) -> str:
        return self._default_model

    def available_models(self) -> set[str]:
        if self._unreachable:
            raise ProviderUnreachableError("down")
        return self._available


def _agent(name: str, provider=None, model=None) -> Agent:
    return Agent(name=name, role="r", capabilities=["c"], provider=provider, model=model)


def test_all_models_available_passes():
    registry = {"ollama": _FakeProvider("qwen3:4b", {"qwen3:4b", "llama3:8b"})}
    agents = [_agent("a", model="qwen3:4b"), _agent("b")]  # b -> défaut qwen3:4b
    preflight_models(agents, RoleProviders(), registry, "ollama")  # ne lève pas


def test_missing_agent_model_raises_with_name_and_model():
    registry = {"ollama": _FakeProvider("qwen3:4b", {"qwen3:4b"})}
    agents = [_agent("alice", model="absent:99b")]
    with pytest.raises(PreflightError) as exc:
        preflight_models(agents, RoleProviders(), registry, "ollama")
    msg = str(exc.value)
    assert "alice" in msg and "absent:99b" in msg and "ollama" in msg


def test_missing_role_model_raises():
    registry = {"ollama": _FakeProvider("qwen3:4b", {"qwen3:4b"})}
    roles = RoleProviders(divider=RoleProvider(model="ghost:7b"))
    with pytest.raises(PreflightError) as exc:
        preflight_models([_agent("a")], roles, registry, "ollama")
    assert "divider" in str(exc.value) and "ghost:7b" in str(exc.value)


def test_unreachable_provider_raises():
    registry = {"openai": _FakeProvider("gpt-4o-mini", unreachable=True)}
    agents = [_agent("a", provider="openai", model="gpt-4o-mini")]
    with pytest.raises(PreflightError) as exc:
        preflight_models(agents, RoleProviders(), registry, "openai")
    assert "openai" in str(exc.value) and "injoignable" in str(exc.value).lower()


def test_aggregates_all_problems_in_one_message():
    registry = {"ollama": _FakeProvider("qwen3:4b", {"qwen3:4b"})}
    agents = [_agent("a", model="x:1"), _agent("b", model="y:2")]
    with pytest.raises(PreflightError) as exc:
        preflight_models(agents, RoleProviders(), registry, "ollama")
    msg = str(exc.value)
    assert "x:1" in msg and "y:2" in msg  # les deux, pas fail-fast


def test_queries_each_provider_once(monkeypatch):
    calls = {"n": 0}
    prov = _FakeProvider("qwen3:4b", {"qwen3:4b"})
    orig = prov.available_models

    def counting():
        calls["n"] += 1
        return orig()

    prov.available_models = counting
    registry = {"ollama": prov}
    agents = [_agent("a"), _agent("b"), _agent("c")]
    preflight_models(agents, RoleProviders(), registry, "ollama")
    assert calls["n"] == 1  # un seul appel réseau par provider distinct
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_preflight.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'aaosa.runtime.preflight'`.

- [ ] **Step 3: Write minimal implementation**

Créer `src/aaosa/runtime/preflight.py` :

```python
"""Preflight : vérifie que chaque model demandé (agents + rôles système) est
disponible dans son provider AVANT le run. Échec opaque mid-run -> erreur claire.

Fonction pure : ne mute rien, n'écrit rien. Interroge chaque provider distinct une
seule fois (cache local), agrège tous les problèmes en un seul PreflightError.
"""

from __future__ import annotations

from aaosa.config.role_providers import RoleProviders
from aaosa.core.agent import Agent
from aaosa.runtime.providers import LLMProvider, ProviderUnreachableError


class PreflightError(Exception):
    """≥1 model absent ou ≥1 provider injoignable, détecté avant le run."""


def _role_items(roles: RoleProviders):
    """(nom, RoleProvider) pour les 7 rôles système, ordre stable."""
    return [
        ("divider", roles.divider),
        ("aggregator", roles.aggregator),
        ("tagger", roles.tagger),
        ("evaluator", roles.evaluator),
        ("diagnostic", roles.diagnostic),
        ("triage", roles.triage),
        ("task_spec", roles.task_spec),
    ]


def preflight_models(
    agents: list[Agent],
    roles: RoleProviders,
    registry: dict[str, LLMProvider],
    default_provider_name: str,
) -> None:
    """Lève PreflightError si un model demandé est absent ou un provider injoignable."""
    # 1. (provider_name, model_résolu, source) pour chaque consommateur LLM.
    reqs: list[tuple[str, str, str]] = []
    for a in agents:
        pname = a.provider or default_provider_name
        model = a.model or registry[pname].default_model
        reqs.append((pname, model, f"agent {a.name!r}"))
    for role_name, rp in _role_items(roles):
        pname = rp.provider or default_provider_name
        model = rp.model or registry[pname].default_model
        reqs.append((pname, model, f"role {role_name!r}"))

    # 2. Disponibilité : un appel par provider distinct.
    available: dict[str, set[str]] = {}
    unreachable: dict[str, str] = {}
    for pname in {r[0] for r in reqs}:
        try:
            available[pname] = registry[pname].available_models()
        except ProviderUnreachableError as exc:
            unreachable[pname] = str(exc)

    # 3. Agrégation des problèmes.
    problems: list[str] = []
    for pname in sorted(unreachable):
        problems.append(f"  - provider {pname!r} injoignable: {unreachable[pname]}")
    for pname, model, source in reqs:
        if pname in unreachable:
            continue  # déjà signalé au niveau provider
        if model not in available[pname]:
            problems.append(f"  - {source}: model {model!r} absent du provider {pname!r}")

    if problems:
        raise PreflightError(
            "Preflight model availability failed:\n" + "\n".join(problems)
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_preflight.py -v`
Expected: PASS (les 6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/preflight.py tests/runtime/test_preflight.py
git commit -m "feat(runtime): preflight_models() pur (agents + rôles, agrégé) [alf]"
```

---

### Task 3: Câblage `solve_once` + traduction CLI

**Files:**
- Modify: `src/aaosa/cli/solve_runs.py` (après `build_provider_registry`, avant `build_root_task`)
- Modify: `src/aaosa/cli/app.py` (fonction `solve`, ajout `except PreflightError`)
- Test: `tests/cli/test_solve_runs.py` (preflight appelé + propagation) et `tests/cli/test_app_solve.py` (Exit 1)

**Interfaces:**
- Consumes (Task 2): `preflight_models(agents, roles, registry, default_provider_name)`, `PreflightError`.

- [ ] **Step 1: Write the failing tests**

Dans `tests/cli/test_solve_runs.py`, ajouter :

```python
def test_solve_once_raises_when_model_unavailable(tmp_path, monkeypatch):
    import aaosa.cli.solve_runs as sr
    from aaosa.runtime.preflight import PreflightError

    def boom(agents, roles, registry, default_provider_name):
        raise PreflightError("Preflight model availability failed:\n  - agent 'x'")

    monkeypatch.setattr(sr, "preflight_models", boom)
    roster = _make_roster(tmp_path)  # helper existant du fichier
    with pytest.raises(PreflightError):
        sr.solve_once([roster], "fais un truc", None, tmp_path / "runs", "ollama")
```

> Note implémenteur : réutiliser le helper de fabrication de roster déjà présent dans `test_solve_runs.py` (chercher comment les autres tests construisent un `roster`). Si aucun helper, créer un dossier roster minimal (`agents.yaml` + `tools.py`) comme les tests voisins.

Dans `tests/cli/test_app_solve.py`, ajouter :

```python
def test_solve_command_exits_1_on_preflight_error(monkeypatch, tmp_path):
    import aaosa.cli.app as app_mod
    from aaosa.runtime.preflight import PreflightError

    def boom(*a, **k):
        raise PreflightError("Preflight model availability failed:\n  - agent 'x': model 'absent:99b' absent")

    monkeypatch.setattr(app_mod, "solve_once", boom)
    result = runner.invoke(  # `runner` = CliRunner du fichier
        app_mod.app,
        ["solve", "--roster", str(tmp_path), "--task", "t"],
    )
    assert result.exit_code == 1
    assert "Preflight model availability failed" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/cli/test_solve_runs.py -k preflight tests/cli/test_app_solve.py -k preflight -v`
Expected: FAIL (`preflight_models` non importé dans `solve_runs` ; `solve` ne catche pas `PreflightError`).

- [ ] **Step 3: Write minimal implementation**

Dans `src/aaosa/cli/solve_runs.py`, ajouter l'import :

```python
from aaosa.runtime.preflight import preflight_models
```

et insérer l'appel dans `solve_once`, juste après la ligne `provider, registry = build_provider_registry(...)` et avant la construction de `pre_ctx` / `build_root_task` :

```python
    provider, registry = build_provider_registry(agents, provider_name, roles=roles)
    preflight_models(agents, roles, registry, provider_name)  # échoue AVANT toute session
    load_elo_into(agents, runs_root)
```

Dans `src/aaosa/cli/app.py`, ajouter l'import :

```python
from aaosa.runtime.preflight import PreflightError
```

et le `except` dans la fonction `solve`, **avant** le `except ValueError` (PreflightError ne sous-classe pas ValueError, l'ordre n'est pas critique mais on le met explicite) :

```python
    try:
        outcome = solve_once(roster, task, context, runs_root, provider, roles_path=roles)
    except EmptyTaggingError:
        typer.echo("Tagging produced no tags for this task — cannot route it. Refine --task.")
        raise typer.Exit(code=1)
    except PreflightError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)
    except ValueError as exc:  # erreurs de chargement roster/roles
        typer.echo(str(exc))
        raise typer.Exit(code=1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/cli/test_solve_runs.py tests/cli/test_app_solve.py -v`
Expected: PASS (nouveaux tests + existants).

- [ ] **Step 5: Run full suite (non-régression)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: tout vert (≈1097+ passed, 1 skipped) — `aaosa run` et les chemins sans model custom inchangés.

- [ ] **Step 6: Commit**

```bash
git add src/aaosa/cli/solve_runs.py src/aaosa/cli/app.py tests/cli/test_solve_runs.py tests/cli/test_app_solve.py
git commit -m "feat(cli): solve preflight model availability -> Exit 1 clair [alf]"
```

---

## Hors scope (noté)

- `aaosa run --scenario` (incident_runs) : scénario démo fixe, pas de models injectés arbitrairement → pas de preflight (rétrocompat test-locked). Si besoin plus tard, ticket séparé.
- Validation LLM-réel / cross-provider Ollama : la machine n'a pas de GPU (cf. mémoire erd). Le preflight lui-même ne consomme pas de tokens et se valide en mock ; le smoke réel `solve --provider openai` peut servir de sign-off matinal (Quentin), mais le DoD nuit = suite verte.

## Self-review

- **Spec coverage** : agents ✓ (Task 2/3), 7 rôles ✓ (`_role_items`), model défaut résolu ✓ (`or registry[pname].default_model`), provider injoignable ✓ (`ProviderUnreachableError` → message), agrégation ✓ (test dédié), erreur AVANT session ✓ (appel avant `build_root_task`), CLI Exit 1 ✓.
- **Placeholders** : aucun TODO ; le seul renvoi (helper roster de `test_solve_runs.py`) est explicité avec fallback concret.
- **Type consistency** : `available_models() -> set[str]`, `default_model -> str`, `preflight_models(...) -> None` cohérents entre Task 1/2/3 ; `ProviderUnreachableError` (providers.py) ≠ `PreflightError` (preflight.py), pas de cycle d'import (providers n'importe pas preflight).
