# D3 — Diagnostic d'échec inline (triage runtime)

Date : 2026-06-05
Statut : design validé, prêt pour `writing-plans`
Dépend de : D1 (division émergente récursive), D2 (agrégateur DAG-aware)
Dépendance aval : D4 (robustesse générateur d'evaluator)

---

## 1. Problème

Aujourd'hui, un `qa_fail` termine la tâche sans diagnostic. Le caller reçoit un
`DispatchResult(status="qa_failed")` et c'est tout — la cause est inconnue, le recovery
impossible sans intervention manuelle (B2/B3 batch après le run).

Trois causes structurellement différentes peuvent produire un `qa_fail` :

- **Agent** : l'output est objectivement mauvais, ou l'agent a mal compris la tâche
- **Evaluator** : la spec d'évaluation est mal générée (trop stricte, mauvais critères)
- **Task spec** : la description de la tâche est ambiguë, l'agent a répondu à la mauvaise
  interprétation

Chaque cause appelle un path de recovery différent. Sans diagnostic inline, toutes
produisent le même résultat : un échec silencieux.

**Contrainte architecturale** : B2/B3 (triage batch) restent batch — ils opèrent sur
l'historique, ont accès à des patterns cross-run, et ne génèrent pas de consignes. D3 crée
un chemin inline **indépendant**, avec une philosophie différente : diagnostic ponctuel sur
un run live, orienté recovery immédiat.

---

## 2. Périmètre

D3 introduit quatre composants :

1. **Agent de diagnostic unifié** (`diagnose_failure`) — 1 LLM call, retourne attribution +
   consignes
2. **Routes déterministes dans `run_with_recovery`** — branchement code sur l'attribution
3. **Refonte du divider** — reçoit un `chained_context` optionnel (path root→tâche), un
   `FailureContext` optionnel, et génère un `context` focalisé par sous-tâche
4. **`Task.context`** — nouveau champ premier rang sur le schema `Task`, propagé et
   spécialisé par le divider à chaque niveau de l'arbre

Hors périmètre :
- `execution_failed` : auto-détecté mécaniquement, pas de diagnostic (inchangé)
- `unassigned` : géré par D1
- B2/B3 batch : inchangés
- Robustesse du générateur d'evaluator : D4

---

## 3. Flow complet

```
execution_failed ──→ DispatchResult(status="execution_failed")  [auto, inchangé]

qa_fail ──→ diagnose_failure(task, output, qa_result, client)
              └─→ DiagnosticResult(attribution, consignes, reason)

  attribution=agent
    → consignes injectées dans le context de l'agent → retry 1x
      → Output                           → retourner l'output
      → qa_fail | DispatchResult         → DispatchResult(status="qa_failed",
                                              attribution="agent",
                                              consignes_tried=True)

  attribution=evaluator
    → régénérer l'evaluator (AdaptiveSpecEvaluator, nouveau call)
    → re-évaluer l'output EXISTANT avec le nouvel evaluator
      → ok  → Output (l'output original passe, on continue)
      → ko  → consignes → retry agent 1x
               → Output                 → retourner l'output
               → ko                    → DispatchResult(status="qa_failed",
                                              attribution="evaluator",
                                              consignes_tried=True)

  attribution=task_spec
    → division contextualisée(chained_context + failure_context)
    → run_chain sur les sous-tâches produites
    → chaque sous-tâche qa_fail → D3 récursif (même pattern)
    → agrégation D2 sur les sinks

  attribution=unattributed
    → DispatchResult(status="qa_failed", attribution="unattributed",
                     consignes_tried=False)
```

**Note sur la route evaluator** : on fait confiance au nouvel evaluator régénéré. Si
l'output le rate encore, on considère que c'est l'output qui est en faute (pas
l'evaluator). Cette hypothèse rend D3 dépendant de la qualité de D4 : un générateur
d'evaluator défaillant produira des faux positifs "agent fail". À documenter comme
contrainte dans D4.

---

## 4. Nouveaux composants

### 4.1 `FailureContext` (schema Pydantic)

```python
class FailureContext(BaseModel):
    failed_output: Output          # output produit par l'agent
    qa_result: QAResult            # résultat QA (scores, critères ratés, reason)
    diagnostic_reason: str         # explication du diagnostic (pourquoi task_spec)
```

Utilisé par le divider pour contextualiser la division. Tous les champs optionnels au
niveau du divider (signature `failure_context: FailureContext | None = None`).

### 4.2 `DiagnosticResult` (schema Pydantic)

```python
class DiagnosticResult(BaseModel):
    attribution: Literal["agent", "evaluator", "task_spec", "unattributed"]
    consignes: str | None = None   # présent si attribution in (agent, evaluator→ko)
    reason: str                    # explication — alimente FailureContext.diagnostic_reason
```

### 4.3 `diagnose_failure` (`qa/diagnostic.py`)

```python
def diagnose_failure(
    task: Task,
    output: Output,
    qa_result: QAResult,
    client: OpenAI,
) -> DiagnosticResult
```

- Structured output (même pattern que `triage_case` en B2)
- Fallback JSON brut + validation Pydantic si structured output échoue
- `None` sur échec LLM non récupérable → caller traite comme `unattributed`
- **Indépendant de B2** : prompt différent, orienté "que faire maintenant ?" vs
  "à qui imputer ?" — les deux questions se recoupent mais n'ont pas le même output

Prompt : fournit la description de la tâche, l'output produit, les critères QA ratés, et
demande : attribution + consignes courtes si l'agent peut réessayer avec des clarifications.

### 4.4 `Task.context` (`schemas/task.py`)

```python
class Task(BaseModel):
    ...
    context: str | None = None   # contexte domaine focalisé sur cette tâche
```

Champ premier rang, `None` par défaut — rétrocompat totale avec les 761 tests existants.

**Rôle** : porter le contexte domaine pertinent pour cette tâche spécifique (ex : "système
HIPAA, PostgreSQL 14, contrainte temps réel < 200ms"). Distinct de `description` (ce qu'il
faut faire) et de `previous_outputs` (ce qui a déjà été produit).

**Consommateurs** :
- `agent.execute` : injecte `task.context` dans le user content (formalise le pattern
  `task.metadata.get("context")` existant en V2c — migration transparente)
- `AdaptiveSpecEvaluator.evaluate` : use context pour générer une spec d'évaluation
  adaptée au domaine
- `diagnose_failure` : use context pour affiner le diagnostic

### 4.5 Refonte du divider (`runtime/divider.py`)

Signature actuelle :
```python
def divide(self, task: Task, client: OpenAI, tracer: Tracer | None = None) -> list[Task]
```

Nouvelle signature :
```python
def divide(
    self,
    task: Task,
    client: OpenAI,
    tracer: Tracer | None = None,
    chained_context: list[Task] | None = None,
    failure_context: FailureContext | None = None,
) -> list[Task]
```

**`chained_context`** : liste des tâches ancêtres (root → parent immédiat) avec leurs
outputs. Permet au divider de comprendre le contexte global qui a mené à cette tâche.
Construit par `run_with_recovery` à partir de `task.parent_task_id` en remontant.

**`failure_context`** : alimenté uniquement depuis la route `task_spec` de D3 — contient
l'output raté, le résultat QA, et l'explication du diagnostic. Révèle où se trouve
l'ambiguïté dans la spec.

**Génération de `context` par sous-tâche** : le divider génère déjà les descriptions de
sous-tâches via un LLM call. Ce même call produit un `context: str | None` par sous-tâche
dans son structured output — contexte distillé depuis `task.context` + `chained_context`,
focalisé sur ce que la sous-tâche doit savoir. Coût additionnel : tokens supplémentaires
dans le call existant, pas de call LLM supplémentaire.

Principe : chaque sous-tâche reçoit un contexte taillé pour elle, pas une copie du parent.
À mesure que l'arbre s'approfondit, le contexte se distille — pas de context rot.

**Rétrocompat** : tous les paramètres nouveaux sont optionnels avec `None` par défaut.
D1 passe `chained_context` seul. Les appels existants passent tout à `None`.

### 4.6 `DispatchResult` — nouveaux champs

```python
class DispatchResult(BaseModel):
    ...
    attribution: Literal["agent", "evaluator", "task_spec", "unattributed"] | None = None
    consignes_tried: bool = False
```

Ces champs sont renseignés uniquement depuis les routes D3. Rétrocompat : `None`/`False`
par défaut.

### 4.7 `run_with_recovery` étendu (`runtime/runner.py`)

Point d'orchestration unique des routes D3. Reçoit en paramètre optionnel :
- `chained_context: list[Task] | None` — passé au divider si route `task_spec`

Logique ajoutée après `qa_fail` :

```python
diagnostic = diagnose_failure(task, output, qa_result, client)

if diagnostic.attribution == "agent":
    output = _retry_with_consignes(task, diagnostic.consignes, ...)
    ...

elif diagnostic.attribution == "evaluator":
    new_evaluator = AdaptiveSpecEvaluator(client)
    qa_result2 = new_evaluator.evaluate(task, output)
    if qa_result2.success:
        return output
    output = _retry_with_consignes(task, diagnostic.consignes, ...)
    ...

elif diagnostic.attribution == "task_spec":
    failure_ctx = FailureContext(
        failed_output=output,
        qa_result=qa_result,
        diagnostic_reason=diagnostic.reason,
    )
    return run_with_recovery(task, ctx, chained_context=chained_context,
                             failure_context=failure_ctx)  # récursif via D1

else:  # unattributed
    return DispatchResult(status="qa_failed", attribution="unattributed")
```

---

## 5. Séparations strictes

- **B2/B3 restent batch** : `triage_case`, `triage_unattributed`, `fix_task_spec` ne sont
  jamais appelés depuis `run_task` ou `run_with_recovery`. D3 est un chemin parallèle
  indépendant.
- **`diagnose_failure` est pur** : prend des données en entrée, retourne un `DiagnosticResult`.
  Pas d'accès au runtime, au store, ni à l'historique.
- **Le divider reste pur** : `chained_context`, `failure_context`, et la génération de
  `context` par sous-tâche sont des données en entrée/sortie. Le divider ne sait pas d'où
  viennent ces données ni qui les consomme.
- **`run_with_recovery` est le seul point d'orchestration** : la logique de branchement D3
  vit exclusivement là. Ni `run_task`, ni `run_chain` ne savent qu'un diagnostic a eu lieu.
- **Récursion D3 via D1** : la route `task_spec` produit des sous-tâches via D1 (division
  émergente). D3 ne court-circuite pas D1, il l'alimente avec plus de contexte.
- **`Task.context` est une donnée, pas du comportement** : le runtime ne décide jamais du
  contenu du contexte. C'est le caller (à la racine) ou le divider (aux nœuds internes)
  qui écrit `context`. L'agent et l'evaluator le lisent sans le modifier.

---

## 6. Dépendance D4

D3 fait confiance au nouvel evaluator généré sur la route `evaluator`. Si `build_llm_spec`
(D4) génère systématiquement de mauvaises specs, les échecs evaluator seront classés en
faux positifs "agent fail" et termineront en `consignes_tried=True` sans vraie recovery.

**Conséquence pour D4** : robustesse et qualité de `build_llm_spec` sont un prérequis pour
que D3 fonctionne correctement sur la route evaluator. D4 doit traiter ce cas explicitement
dans son scope.

---

## 7. Tests

### `qa/diagnostic.py`

- `diagnose_failure` retourne un `DiagnosticResult` valide pour les 4 attributions (mock
  LLM structured output)
- Fallback JSON brut : output LLM mal formé → Pydantic valide quand même
- Échec LLM non récupérable → retourne `None`
- `consignes` présent pour `agent`, absent pour `task_spec`/`unattributed`

### Routes `run_with_recovery`

- Route `agent` : retry avec consignes → Output si deuxième tentative ok
- Route `agent` : retry avec consignes → `DispatchResult(consignes_tried=True)` si ko
- Route `evaluator` → ok au re-eval : Output retourné sans retry agent
- Route `evaluator` → ko re-eval → retry agent ok : Output retourné
- Route `evaluator` → ko re-eval → retry agent ko : `DispatchResult(attribution="evaluator")`
- Route `task_spec` : produit des sous-tâches et les exécute (intégration D1)
- Route `unattributed` : `DispatchResult` immédiat, pas de retry

### `Task.context`

- `task.context=None` : comportement identique à aujourd'hui (rétrocompat)
- `task.context` défini : injecté dans `agent.execute` et `AdaptiveSpecEvaluator.evaluate`
- Migration V2c : `task.metadata.get("context")` remplacé par `task.context` dans les
  demos et le dashboard — même valeur, champ premier rang

### Divider contextualisé

- `chained_context=None` : comportement identique à aujourd'hui (rétrocompat)
- `chained_context=[task_parent]` : context ancêtre inclus dans le prompt divider
- `failure_context` présent : output raté + QA reason inclus dans le prompt divider
- `failure_context=None` : prompt divider inchangé (rétrocompat)
- Chaque sous-tâche produite porte un `context` distillé — non vide si `task.context` ou
  `chained_context` sont présents

### Récursion `task_spec`

- Sous-tâche issue de `task_spec` qui re-`qa_fail` en `task_spec` → D3 récursif
- Terminaison : `roster_gap` détecté par D1 → surface sans division infinie
