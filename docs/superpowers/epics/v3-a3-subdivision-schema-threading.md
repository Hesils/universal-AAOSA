# V3 — Épique A3 — Subdivision de tâches (schema + threading)

- **Couche** : `src/aaosa/schemas/task.py` · `src/aaosa/runtime/runner.py`
- **Statut** : deep-dive terminé → prêt pour plan + exécution
- **Dépendances** : aucune dure. Prérequis de A4.
- **Roadmap** : section V3, épique A3

---

## Contexte

`Task` est aujourd'hui strictement atomique. A3 ajoute le modèle d'exécution d'une liste
pré-découpée de sous-tâches ordonnées par **graphe de dépendances d'outputs**.

L'idée centrale : chaque sous-tâche déclare explicitement de quelles autres sous-tâches elle
a besoin pour être résolue. Certaines ont zéro dépendances (exécutables immédiatement), d'autres
en ont une ou plusieurs. L'ordre d'exécution est dérivé de ce graphe — pas imposé linéairement.
La tâche racine (le plus haut parent) est l'input utilisateur original.

A3 ne génère pas la liste de sous-tâches (c'est A4 — TaskDivider). A3 implémente uniquement
**l'exécution ordonnée-par-dépendances d'une liste déjà construite**.

---

## Ce qui ne change pas

- `run_task` : signature et comportement inchangés (rétrocompat stricte)
- Tous les champs existants de `Task` : inchangés
- Les 588+ tests existants : inchangés (nouveaux champs optionnels)

---

## Décisions

| Question | Décision | Justification |
|---|---|---|
| Nouveaux champs `Task` | `parent_task_id: str \| None = None`, `order_index: int \| None = None`, `depends_on: list[str] = []`, `required_outputs: list[Output] = []` | `depends_on` = IDs des tâches sœurs dont cette tâche a besoin. `required_outputs` = rempli par le runner juste avant l'exécution avec les outputs résolus. |
| Sémantique `depends_on` | Liste d'`id` de sous-tâches sœurs (même `parent_task_id`). 0 = exécutable immédiatement. | Le graphe est déclaratif dans le schema — le runner le résout. |
| Résolution par le runner | Tri topologique de la liste de sous-tâches selon `depends_on`. Injection de `required_outputs` = outputs des tâches dont `id` est dans `depends_on` (uniquement les outputs réussis). | Seuls les outputs **nécessaires** à la tâche lui sont transmis — pas tous les précédents. |
| Point d'entrée chaînage | `run_chain(tasks, agents, client, tracer, evaluator) -> list[Output \| DispatchResult \| QAFailure]` dans `runner.py` | Séparé de `run_task` — le code path V1/V2 est inchangé. |
| Tâche dont une dépendance échoue | Marquée `DispatchResult(status="dependency_failed")` sans être exécutée | Pas de fallback silencieux — l'échec est tracé. |
| `required_outputs` dans `execute` | `Agent.execute` intègre `task.required_outputs` dans le user message si non-vide | Le LLM reçoit uniquement ce dont il a besoin, nommé par la description de la tâche source. |
| Cycle dans `depends_on` | `run_chain` lève `ValueError("cycle detected in task dependencies")` | Invariant structurel — un graphe cyclique est une erreur de construction. |

---

## Seams confirmés

| Fichier | État actuel | Ce qui change |
|---|---|---|
| `src/aaosa/schemas/task.py` | 6 champs, `required_tags` non-empty validé | +`parent_task_id`, `order_index`, `depends_on`, `required_outputs` — tous optionnels |
| `src/aaosa/runtime/runner.py` | `run_task` strictement atomique | +`run_chain(tasks, ...) -> list[...]` avec tri topologique |
| `src/aaosa/core/agent.py` | `execute` : context depuis `task.metadata["context"]` | +lecture de `task.required_outputs` pour enrichir le user message |

---

## Nouveaux champs `Task`

```python
from aaosa.schemas.output import Output   # pas de circularité : output.py n'importe pas task.py

class Task(BaseModel):
    # ... champs existants inchangés ...
    parent_task_id: str | None = None
    order_index: int | None = None
    depends_on: list[str] = Field(default_factory=list)       # IDs de tâches sœurs
    required_outputs: list[Output] = Field(default_factory=list)  # rempli par le runner
```

---

## Logique de `run_chain`

```
run_chain(tasks, agents, client, ...):
    1. Valider absence de cycles dans le graphe depends_on → ValueError si cycle
    2. Tri topologique des tasks selon depends_on
    3. Pour chaque task dans l'ordre topologique :
        a. Vérifier que toutes les dépendances ont un output réussi
           → si manquant : task.result = DispatchResult(status="dependency_failed"), continuer
        b. Injecter dans task.required_outputs = [outputs[dep_id] for dep_id in task.depends_on]
        c. result = run_task(task, agents, client, tracer, evaluator)
        d. Si result est un Output réussi → stocker dans outputs[task.id]
    4. Retourner la liste des résultats dans l'ordre topologique
```

---

## Propagation dans `Agent.execute`

```python
def execute(self, task: Task, client: OpenAI) -> Output:
    context = task.metadata.get("context", "")
    deps = ""
    if task.required_outputs:
        deps = "\n\n# Required context from previous steps\n" + "\n---\n".join(
            f"[{o.task_id}]: {o.content}" for o in task.required_outputs
        )
    user_content = f"{task.description}{deps}\n\n{context}".strip()
    # ... reste inchangé
```

---

## Stratégie de test (TDD)

**`tests/schemas/test_task_v3.py`** :
- `test_task_new_optional_fields_default` : création sans nouveaux champs → tous à None/[]
- `test_task_depends_on_roundtrip` : JSON roundtrip avec `depends_on` non-vide
- `test_task_required_outputs_roundtrip` : JSON roundtrip avec `required_outputs` non-vide
- `test_existing_task_unaffected` : `Task(description=..., required_tags=...)` → valide, pas de régression

**`tests/runtime/test_run_chain.py`** :
- `test_run_chain_no_deps` : 3 tâches sans dépendances → exécutées dans l'ordre de la liste
- `test_run_chain_linear_deps` : A → B → C (chaque dépend du précédent) → C reçoit l'output de B dans `required_outputs`
- `test_run_chain_diamond_deps` : A → B, A → C, B+C → D : D reçoit outputs de B et C
- `test_run_chain_zero_deps_receives_no_outputs` : tâche sans `depends_on` → `required_outputs` vide à l'exécution
- `test_run_chain_dependency_failed_skips` : si B échoue → C qui dépend de B reçoit `DispatchResult(status="dependency_failed")`
- `test_run_chain_cycle_raises` : graphe cyclique → `ValueError`
- `test_run_chain_run_task_unchanged` : `run_task` seul sur une `Task` avec `depends_on` → comportement identique à V2

---

## Critères de done

- [ ] `Task` : 4 nouveaux champs optionnels, `extra="forbid"` respecté, roundtrip JSON OK
- [ ] `run_chain` avec tri topologique + injection `required_outputs` + détection de cycle
- [ ] `Agent.execute` intègre `required_outputs` si non-vide (uniquement les dépendances déclarées)
- [ ] `run_task` : comportement identique à V2 (non modifié)
- [ ] `tests/schemas/test_task_v3.py` : 4 tests verts
- [ ] `tests/runtime/test_run_chain.py` : 7 tests verts
- [ ] Suite complète ≥ 604 + 11 = **615 tests verts** (après A1+B1)

---

## Questions tranchées ici

1. **`depends_on` référence des IDs d'une autre liste — que se passe-t-il si l'ID est inconnu ?**
   `run_chain` lève `ValueError("unknown dependency id: ...")` — invariant structural.
2. **Exécution parallèle des tâches sans dépendances ?** Non en A3 — exécution séquentielle dans
   l'ordre topologique. La parallélisation est une optimisation future hors scope.
3. **`required_outputs` modifié directement sur la `Task` passée en input ?**
   Non — `run_chain` crée une copie (`task.model_copy(update={"required_outputs": [...]})`)
   pour ne pas muter l'input.
4. **`parent_task_id` utilisé par `run_chain` ?** Non directement — porté par le schema pour A4
   (qui construit les sous-tâches) et le dashboard (graphe). `run_chain` ne l'utilise pas.
5. **Résultats retournés dans quel ordre ?** Ordre topologique d'exécution — cohérent avec la
   résolution des dépendances.
