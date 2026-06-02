# Design — Tuning du seed `run_health_check_v3`

Date : 2026-06-03
Statut : validé (brainstorming), prêt pour plan d'implémentation
Scope : `src/aaosa/demo/run_health_check_v3.py` uniquement (+ son test unitaire)

## 1. Problème

Le seed de `run_health_check_v3` déclare 3 cas censés produire 3 attributions de triage
différentes (`agent` / `task_spec` / `evaluator`), mais **les 3 tâches sont bien formées**.

Exemple : `TASK_REFACTOR_REST_API` est explicite ("comply with OpenAPI 3.1, proper status
codes, schema validation, no raw SQL"). Le triage LLM (B2, `gpt-4o-mini`, temp=0) classe donc
correctement les 3 cas en `agent` — l'output seedé est mauvais, mais la tâche n'est pas en
cause. Conséquence : **B3 (`fix_task_spec_cases`) tourne à vide**, aucun cas n'étant attribué
`task_spec`. Le commentaire `# tâche ambiguë -> triage attendu "task_spec"` (ligne 49) est un
vœu, pas une réalité.

Caveat documenté dans CLAUDE.md (vague 1, 2026-06-02) : « le seed a besoin d'une tâche
réellement ambiguë pour exercer B3 end-to-end ».

## 2. Objectif

**Taxonomie complète, cas simulés, seed-only.** Concevoir 3 cas seed dont les inputs sont
*conçus* pour orienter le triage vers 3 attributions distinctes, et démontrer la boucle
d'auto-amélioration de bout en bout sur un run LLM réel :

- le triage **discrimine** (3 attributions différentes) ;
- **B3 fire** réellement sur le cas `task_spec` et réécrit sa description ;
- le **re-triage** reclasse le cas corrigé.

Hors scope : aucun rework de `triage.py` (B2) ni d'aucun module runtime. On pilote les
attributions par le **design des inputs**. C'est un proof-of-concept par run orienté, pas une
validation durcie. Si le LLM hésite sur le cas le plus fragile (`evaluator`), c'est accepté —
le rework du prompt de triage reste sur l'étagère si le besoin se confirme sur des runs réels.

## 3. Contrainte clé découverte

Le prompt de triage (`triage.py:31-34`) n'expose que les **noms** des critères, pas leurs
params : le LLM voit `- min_length (gate)`, jamais `min_chars=2000`. Le cas `evaluator` doit
donc se déclencher sans s'appuyer sur la valeur d'un param → il s'appuie sur le **contraste
sémantique** entre la nature de la tâche (réponse concise attendue) et la présence d'un gate de
longueur, plus le fait que l'output seedé est *correct*.

## 4. Les trois cas

Matériel de tâche **volontairement dégénéré** → défini **inline dans le seed**, jamais ajouté à
`DEMO_TASKS` (qui reste du matériel demo bien formé).

| Cas | Tâche | Output seedé | Spec | Triage visé | Mécanique |
|-----|-------|--------------|------|-------------|-----------|
| **agent** | `TASK_SECURITY_AUDIT` (existante, bien formée) | `"Looks fine to me."` | `_spec_for(task, client)` (normale) | `agent` | output nul sur tâche claire — déjà en place |
| **task_spec** | `TASK_VAGUE` *(nouveau, inline)* | `"I made some improvements."` | `_spec_for(task, client)` (normale) | `task_spec` | description sans livrable concret → le triage impute la tâche |
| **evaluator** | `TASK_STATUS_CODE` *(nouveau, inline)* | `"204 No Content."` *(bon output)* | spec **hand-craftée** (voir §5) | `evaluator` | bon output + bonne tâche, pourtant flaggé → seul reste le critère ; gate `min_length` sur une réponse d'un mot lu comme « critères trop stricts » |

Tâches piégées :

```python
TASK_VAGUE = Task(
    description="Improve the codebase and make it better",
    required_tags={"python": 50},
)

TASK_STATUS_CODE = Task(
    description="State the correct HTTP status code for a successful DELETE with no body",
    required_tags={"backend": 30},
)
```

## 5. Spec hand-craftée du cas evaluator

Le cas `evaluator` n'utilise **pas** `_spec_for` (qui dérive une spec appropriée de la tâche).
Il passe une `EvaluatorSpec` explicitement inadaptée :

```python
EvaluatorSpec(criteria=[
    CriterionSpec(name="non_empty", gate=True),
    CriterionSpec(name="min_length", params={"min_chars": 2000}, gate=True),
])
```

Le gate `min_length` à 2000 chars échoue sur `"204 No Content."` → le cas est flaggé échec
malgré un output correct. La spec étant construite sans LLM, le **chemin offline
(`client=None`)** du seed reste constructible (test unitaire vert).

## 6. Flow attendu (run LLM réel)

```
Seed (3 cas, fix_target, unattributed)
        │  B2 triage_unattributed
  agent ── task_spec ── evaluator
            │  B3 fix_task_spec_cases
            │  description réécrite, attribution → unattributed
        │   │            │
        │  re-triage B2  │
  agent ── agent* ────── evaluator      (*tâche désormais claire,
        │   │            │               output toujours nul → faute agent)
        └─┬─┘       (quarantaine)
   active_cases → 2 cas agent → run_health_check (n_runs=3)
```

`active_cases` (`test_set.py:62-67`) garde `regression_guard` + `fix_target` attribués `agent`.
Les cas `task_spec` et `evaluator` sont exclus (quarantaine). Après re-triage, 2 cas `agent`
sont actifs ; le cas `evaluator` reste quarantiné — il démontre la discrimination du triage
sans être exécuté.

Sortie console (4 blocs `_print_attributions` existants) :
- *Seed* : 3× `unattributed`
- *Après triage (B2)* : `agent` / `task_spec` / `evaluator` ← la taxonomie discrimine
- *Après correction (B3)* : le cas `task_spec` repasse `unattributed`, description réécrite
- *Après re-triage* : `agent` / `agent` / `evaluator` ← B3 a fait son travail
- *Rapport* : 2 cas actifs testés, evaluator quarantiné

## 7. Changements

Fichier unique : `src/aaosa/demo/run_health_check_v3.py`

1. Définir `TASK_VAGUE` et `TASK_STATUS_CODE` inline (constantes module).
2. Réécrire `build_seed_test_set` : 3 cas selon §4. Le cas evaluator passe la spec hand-craftée
   de §5 au lieu de `_spec_for`.
3. Mettre à jour les commentaires pour refléter l'intention réelle (supprimer le
   `# tâche ambiguë` mensonger ligne 49).
4. Imports nécessaires : `EvaluatorSpec`, `CriterionSpec` (`aaosa.qa.spec`).

## 8. Invariants préservés

- Test unitaire `test_build_seed_test_set_all_unattributed_with_wrong_output` reste vert :
  3 cas, tous `attribution="unattributed"`, `origin="runtime_failure"`, `wrong_output is not None`.
- Chemin offline `build_seed_test_set(client=None)` reste constructible (specs déterministes /
  hand-craftées, aucun appel LLM).
- `DEMO_TASKS` inchangé — aucune tâche dégénérée n'y est ajoutée.
- Aucun module hors `demo/` touché.

## 9. Critère de succès

- `.venv\Scripts\python -m pytest tests/demo/test_run_health_check_v3.py -v` vert.
- Suite complète verte (699 tests, pas de régression).
- Run LLM réel (`.venv\Scripts\python src\aaosa\demo\run_health_check_v3.py`) : le bloc
  *Après triage (B2)* affiche 3 attributions distinctes, et le bloc *Après correction (B3)*
  montre la description du cas `task_spec` réécrite. (Validation manuelle, best-effort.)
