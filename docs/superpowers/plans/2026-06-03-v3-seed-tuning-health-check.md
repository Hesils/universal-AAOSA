# Tuning seed `run_health_check_v3` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Réécrire le seed de `run_health_check_v3` avec 3 cas conçus pour orienter le triage (B2) vers 3 attributions distinctes (`agent` / `task_spec` / `evaluator`), de sorte que B3 fire réellement sur le cas `task_spec`.

**Architecture:** Changement mono-fichier (`src/aaosa/demo/run_health_check_v3.py`). Deux tâches volontairement dégénérées sont définies inline (jamais dans `DEMO_TASKS`). Le cas `evaluator` reçoit une `EvaluatorSpec` hand-craftée inadaptée (gate `min_length` à 2000 chars sur une réponse concise). Les attributions sont pilotées par le design des inputs ; aucun module runtime n'est touché.

**Tech Stack:** Python 3.14, Pydantic 2.13, pytest 9.0.3, OpenAI SDK (gpt-4o-mini pour le run réel). Venv : `.venv\Scripts\python`.

Spec : `docs/superpowers/specs/2026-06-03-v3-seed-tuning-health-check-design.md`

---

## File Structure

- **Modify** `src/aaosa/demo/run_health_check_v3.py` — ajoute 2 constantes de tâches piégées + 1 spec hand-craftée, réécrit `build_seed_test_set`, ajuste les imports.
- **Modify** `tests/demo/test_run_health_check_v3.py` — ajoute un test asservissant la nouvelle composition du seed (vérifiable offline). Les invariants existants restent.

---

### Task 1: Réécrire le seed pour la taxonomie de triage complète

**Files:**
- Modify: `src/aaosa/demo/run_health_check_v3.py`
- Test: `tests/demo/test_run_health_check_v3.py`

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter ce test à la fin de `tests/demo/test_run_health_check_v3.py` :

```python
def test_seed_designed_for_full_triage_taxonomy():
    ts = build_seed_test_set()  # chemin offline (client=None)
    assert len(ts.cases) == 3

    descriptions = [c.task.description for c in ts.cases]
    # tâche réellement vague -> visera "task_spec" au triage
    assert "Improve the codebase and make it better" in descriptions
    # tâche factuelle concise -> visera "evaluator" au triage
    status_case = next(
        c for c in ts.cases if "status code" in c.task.description.lower()
    )

    # le cas evaluator porte un gate min_length inadapté + un bon output
    gate_names = {cr.name for cr in status_case.evaluator_spec.criteria if cr.gate}
    assert "min_length" in gate_names
    assert status_case.wrong_output.content == "204 No Content."
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `.venv\Scripts\python -m pytest tests/demo/test_run_health_check_v3.py::test_seed_designed_for_full_triage_taxonomy -v`
Expected: FAIL — `AssertionError` ("Improve the codebase..." absent) ou le seed actuel a 3 cas mais pas les bonnes tâches.

- [ ] **Step 3: Mettre à jour les imports**

Dans `src/aaosa/demo/run_health_check_v3.py`, remplacer la ligne d'import des tâches :

```python
from aaosa.demo.tasks import TASK_OPTIMIZE_SQL, TASK_REFACTOR_REST_API, TASK_SECURITY_AUDIT
```

par :

```python
from aaosa.demo.tasks import TASK_SECURITY_AUDIT
```

Et ajouter, à côté des autres imports `aaosa.qa.*` :

```python
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
```

(`Task` est déjà importé via `from aaosa.schemas.task import Task`.)

- [ ] **Step 4: Définir les tâches piégées et la spec inadaptée**

Juste après les imports (avant `_wrong_output`), ajouter :

```python
# Tâches volontairement dégénérées — matériel de seed uniquement, jamais dans DEMO_TASKS.
TASK_VAGUE = Task(
    description="Improve the codebase and make it better",
    required_tags={"python": 50},
)

TASK_STATUS_CODE = Task(
    description="State the correct HTTP status code for a successful DELETE with no body",
    required_tags={"backend": 30},
)

# Spec inadaptée pour le cas evaluator : gate min_length absurde sur une réponse concise.
# Construite sans LLM -> le chemin offline du seed reste constructible.
_MISMATCHED_SPEC = EvaluatorSpec(criteria=[
    CriterionSpec(name="non_empty", gate=True),
    CriterionSpec(name="min_length", params={"min_chars": 2000}, gate=True),
])
```

- [ ] **Step 5: Réécrire `build_seed_test_set`**

Remplacer entièrement la fonction `build_seed_test_set` par :

```python
def build_seed_test_set(client: OpenAI | None = None) -> TestSet:
    """Trois cas runtime_failure non attribués, conçus pour orienter le triage (B2)
    vers trois attributions distinctes. Voir le design 2026-06-03.

    - agent     : tâche bien formée + output nul
    - task_spec : tâche réellement vague (corrigée par B3 ensuite)
    - evaluator : bon output + tâche claire mais gate min_length inadapté
    """
    return TestSet(cases=[
        # tâche bien formée + output nul -> triage attendu "agent"
        TestCase(
            task=TASK_SECURITY_AUDIT,
            evaluator_spec=_spec_for(TASK_SECURITY_AUDIT, client),
            origin="runtime_failure", role="fix_target", attribution="unattributed",
            wrong_output=_wrong_output(TASK_SECURITY_AUDIT, "Looks fine to me."),
        ),
        # tâche réellement vague -> triage attendu "task_spec" -> corrigée par B3
        TestCase(
            task=TASK_VAGUE,
            evaluator_spec=_spec_for(TASK_VAGUE, client),
            origin="runtime_failure", role="fix_target", attribution="unattributed",
            wrong_output=_wrong_output(TASK_VAGUE, "I made some improvements."),
        ),
        # bon output + tâche claire mais gate min_length inadapté -> triage attendu "evaluator"
        TestCase(
            task=TASK_STATUS_CODE,
            evaluator_spec=_MISMATCHED_SPEC,
            origin="runtime_failure", role="fix_target", attribution="unattributed",
            wrong_output=_wrong_output(TASK_STATUS_CODE, "204 No Content."),
        ),
    ])
```

- [ ] **Step 6: Lancer le test ciblé pour vérifier qu'il passe**

Run: `.venv\Scripts\python -m pytest tests/demo/test_run_health_check_v3.py -v`
Expected: PASS — les 2 tests existants + le nouveau (3 passent).

- [ ] **Step 7: Lancer la suite complète (non-régression)**

Run: `.venv\Scripts\python -m pytest tests/ -q`
Expected: PASS — aucune régression (699 tests verts).

- [ ] **Step 8: Commit**

```bash
git add src/aaosa/demo/run_health_check_v3.py tests/demo/test_run_health_check_v3.py
git commit -m "fix(v3-observabilite): seed health check v3 oriente la taxonomie triage

Trois cas concus pour atteindre agent/task_spec/evaluator distincts au triage
B2, pour que B3 fire reellement sur le cas task_spec. Taches degenerees inline,
hors DEMO_TASKS. Cas evaluator: spec min_length inadaptee + bon output.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Validation manuelle sur run LLM réel (best-effort)

**Files:** aucun (validation observationnelle).

Cette tâche n'est pas TDD : le triage est un appel LLM, non assertable en unit test. C'est le critère de succès §9 du design.

- [ ] **Step 1: Lancer la démo end-to-end**

Run: `.venv\Scripts\python src\aaosa\demo\run_health_check_v3.py`
Pré-requis : `.env` avec `OPENAI_API_KEY`.

- [ ] **Step 2: Vérifier la discrimination du triage**

Dans la sortie console, le bloc **« Apres triage (B2) »** doit afficher **3 attributions distinctes** :
```
   [agent       ] Perform full security audit of the authentication middleware
   [task_spec   ] Improve the codebase and make it better
   [evaluator   ] State the correct HTTP status code for a successful DELETE...
```

- [ ] **Step 3: Vérifier que B3 a fire**

Le bloc **« Apres correction task_spec (B3) »** doit montrer le cas `task_spec` :
- repassé `unattributed`
- avec une **description réécrite** (≠ "Improve the codebase and make it better").

Le bloc **« Apres re-triage (B2) »** doit montrer ce cas reclassé (typiquement `agent`, la tâche étant désormais claire mais l'output toujours nul).

- [ ] **Step 4: Vérifier le rapport**

Le rapport final doit montrer **2 cas actifs** testés (les 2 cas `agent` après re-triage) ; le cas `evaluator` reste quarantiné (exclu par `active_cases`).

- [ ] **Step 5 (si écart) : consigner, ne pas durcir**

Si le triage classe un cas autrement qu'attendu (cas `evaluator` le plus fragile), **ne pas** rework `triage.py` — c'est hors scope (PoC best-effort). Noter l'écart observé pour réévaluation ultérieure (cf. caveat « rework prompt triage sur l'étagère » du design §2).

---

## Self-Review

- **Spec coverage :** §4 (3 cas) → Task 1 steps 4-5. §5 (spec hand-craftée) → step 4 `_MISMATCHED_SPEC`. §6 (flow + console) → Task 2 steps 2-4. §7 (changements) → Task 1 steps 3-5. §8 (invariants) → test existant intact + step 7 suite complète. §9 (critère succès) → Task 2.
- **Placeholder scan :** aucun TBD/TODO ; tout code est complet.
- **Type consistency :** `CriterionSpec(name, params, weight, gate)` et `EvaluatorSpec(criteria=...)` conformes à `aaosa/qa/spec.py` (usage identique dans `adaptive.py`). `TestCase`/`TestSet` champs conformes au seed actuel. `_spec_for` et `_wrong_output` réutilisés tels quels.
