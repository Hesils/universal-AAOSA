# V2a Subtask 01 — ELO Constants + Formula

_Statut: TODO_
_Depends on: nothing (fondation V2a)_
_Blocking: subtask 03 (updater), subtask 04 (persistence)_

## Objectif

Ajouter les constantes ELO V2 et implementer `compute_delta`, la fonction pure qui calcule le delta ELO pour un tag apres un succes ou echec.

## Methode

TDD strict : ecrire tous les tests d'abord, verifier qu'ils echouent, puis implementer.

## Fichiers a creer/modifier

| Fichier | Action |
|---|---|
| `src/aaosa/schemas/elo.py` | MODIFIER — ajouter 4 constantes V2 |
| `src/aaosa/elo/__init__.py` | CREER — package init vide |
| `src/aaosa/elo/formula.py` | CREER — fonction `compute_delta` |
| `tests/elo/__init__.py` | CREER — package init vide |
| `tests/elo/test_formula.py` | CREER — tests exhaustifs |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/elo/test_formula.py -v
.venv\Scripts\python -m pytest tests/ -v   # les 252 tests V1 doivent toujours passer
```

---

## Etape 1 — Constantes V2 dans `schemas/elo.py`

Le fichier existant contient :

```python
"""ELO bootstrap ranges for skill levels."""

ELO_EXPERT_MIN = 85
ELO_EXPERT_MAX = 95

ELO_COMPETENT_MIN = 30
ELO_COMPETENT_MAX = 50

ELO_BASIC_MIN = 10
ELO_BASIC_MAX = 25

# Tags with required_elo <= this threshold are "acquirable" in Phase 1:
# agents can pass the filter without having them, and may gain them on task success (V2).
ELO_ACQUIRABLE_THRESHOLD = ELO_BASIC_MAX
```

Ajouter a la fin du fichier :

```python
# V2 — Dynamic ELO update constants
ELO_FLOOR = 1
ELO_CEILING = ELO_EXPERT_MAX  # 95
ELO_K = 5
ELO_MAX_DELTA = 10
```

Pas de tests dedies pour les constantes — elles sont validees via les tests de `compute_delta`.

---

## Etape 2 — Tests `compute_delta` (RED)

Creer `tests/elo/test_formula.py`. Tous les tests doivent echouer (module inexistant).

### Signature attendue

```python
from aaosa.elo.formula import compute_delta

def compute_delta(agent_elo: int, required_elo: int, success: bool) -> int:
    ...
```

Retourne un `int` (delta signe, positif ou negatif). Le delta est **deja clampe** a `[-ELO_MAX_DELTA, +ELO_MAX_DELTA]`. Le floor/ceiling n'est PAS applique ici (c'est le job de l'updater, subtask 03).

### Formule

- Succes : `delta = round(K * (required_elo / agent_elo))`
- Echec : `delta = round(-K * (agent_elo / required_elo))`
- Clamp : `max(-MAX_DELTA, min(MAX_DELTA, delta))`

Avec `K = 5`, `MAX_DELTA = 10`.

### Cas de test a ecrire

**Succes — ratio < 1 (tache facile pour l'agent) :**

```python
def test_success_easy_task():
    # agent_elo=80, required=20 -> K * (20/80) = 5 * 0.25 = 1.25 -> round = 1
    assert compute_delta(agent_elo=80, required_elo=20, success=True) == 1

def test_success_same_level():
    # agent_elo=50, required=50 -> K * (50/50) = 5 * 1.0 = 5
    assert compute_delta(agent_elo=50, required_elo=50, success=True) == 5
```

**Succes — ratio > 1 (tache dure pour l'agent) :**

```python
def test_success_hard_task():
    # agent_elo=20, required=80 -> K * (80/20) = 5 * 4.0 = 20 -> clamp = 10
    assert compute_delta(agent_elo=20, required_elo=80, success=True) == 10

def test_success_moderate_hard():
    # agent_elo=30, required=50 -> K * (50/30) = 5 * 1.667 = 8.33 -> round = 8
    assert compute_delta(agent_elo=30, required_elo=50, success=True) == 8
```

**Echec — ratio < 1 (tache dure, echec clement) :**

```python
def test_failure_hard_task():
    # agent_elo=20, required=80 -> -K * (20/80) = -5 * 0.25 = -1.25 -> round = -1
    assert compute_delta(agent_elo=20, required_elo=80, success=False) == -1

def test_failure_same_level():
    # agent_elo=50, required=50 -> -K * (50/50) = -5
    assert compute_delta(agent_elo=50, required_elo=50, success=False) == -5
```

**Echec — ratio > 1 (tache facile, penalite severe) :**

```python
def test_failure_easy_task():
    # agent_elo=80, required=20 -> -K * (80/20) = -5 * 4.0 = -20 -> clamp = -10
    assert compute_delta(agent_elo=80, required_elo=20, success=False) == -10

def test_failure_moderate_easy():
    # agent_elo=50, required=30 -> -K * (50/30) = -5 * 1.667 = -8.33 -> round = -8
    assert compute_delta(agent_elo=50, required_elo=30, success=False) == -8
```

**Clamp :**

```python
def test_clamp_positive():
    # agent_elo=1, required=95 -> K * (95/1) = 475 -> clamp = 10
    assert compute_delta(agent_elo=1, required_elo=95, success=True) == 10

def test_clamp_negative():
    # agent_elo=95, required=1 -> -K * (95/1) = -475 -> clamp = -10
    assert compute_delta(agent_elo=95, required_elo=1, success=False) == -10
```

**Boundary (valeurs limites du systeme) :**

```python
def test_floor_agent_elo():
    # agent_elo=1 (floor), required=50 -> K * (50/1) = 250 -> clamp = 10
    assert compute_delta(agent_elo=1, required_elo=50, success=True) == 10

def test_ceiling_agent_elo():
    # agent_elo=95 (ceiling), required=50 -> K * (50/95) = 2.63 -> round = 3
    assert compute_delta(agent_elo=95, required_elo=50, success=True) == 3

def test_both_at_floor():
    # agent_elo=1, required=1 -> K * (1/1) = 5
    assert compute_delta(agent_elo=1, required_elo=1, success=True) == 5

def test_both_at_ceiling():
    # agent_elo=95, required=95 -> K * (95/95) = 5
    assert compute_delta(agent_elo=95, required_elo=95, success=True) == 5
```

**Rounding :**

```python
def test_rounding_half():
    # agent_elo=40, required=20 -> K * (20/40) = 2.5 -> round = 2 (banker's rounding)
    # Note: Python round(2.5) = 2 (banker's rounding), round(3.5) = 4
    # Si le choix est round standard (math.floor(x + 0.5)), adapter le test.
    # La spec dit "arrondi a int" sans preciser — utiliser round() builtin Python.
    assert compute_delta(agent_elo=40, required_elo=20, success=True) == 2
```

**Return type :**

```python
def test_returns_int():
    result = compute_delta(agent_elo=50, required_elo=50, success=True)
    assert isinstance(result, int)
```

---

## Etape 3 — Implementation `compute_delta` (GREEN)

Creer `src/aaosa/elo/__init__.py` (vide) et `src/aaosa/elo/formula.py`.

La fonction est pure : pas de state, pas de side-effect, pas d'import externe (sauf les constantes).

```python
from aaosa.schemas.elo import ELO_K, ELO_MAX_DELTA


def compute_delta(agent_elo: int, required_elo: int, success: bool) -> int:
    if success:
        raw = ELO_K * (required_elo / agent_elo)
    else:
        raw = -ELO_K * (agent_elo / required_elo)
    clamped = max(-ELO_MAX_DELTA, min(ELO_MAX_DELTA, round(raw)))
    return clamped
```

L'implementation tient en 5 lignes. L'essentiel de la valeur est dans les tests.

---

## Etape 4 — Tous les tests verts (REFACTOR si necessaire)

```powershell
.venv\Scripts\python -m pytest tests/elo/test_formula.py -v
```

Puis regression V1 :

```powershell
.venv\Scripts\python -m pytest tests/ -v
```

Les 252 tests V1 + les ~16 nouveaux tests doivent tous passer.

---

## Invariants a respecter

- Import absolu uniquement : `from aaosa.schemas.elo import ...`
- `compute_delta` ne mute rien, ne leve pas d'exception (les cas agent_elo=0 et required_elo=0 sont impossibles par les validateurs existants dans `schemas/task.py` et `schemas/claim.py`)
- Le delta retourne est un `int` signe, clampe a `[-10, +10]`
- Le floor/ceiling ELO (1-95) n'est PAS applique ici — c'est le job de l'updater (subtask 03)
- Ne pas toucher aux constantes V1 existantes dans `schemas/elo.py`
