# V3 — Épique B2 — Agent de triage (auto-attribution)

- **Couche** : `src/aaosa/qa/triage.py` (nouveau)
- **Statut** : deep-dive terminé → prêt pour plan + exécution
- **Dépendances** : aucune dure
- **Roadmap** : section V3, épique B2

---

## Contexte

En V2b, après un échec runtime (`QAFailure → TestCase(attribution="unattributed")`), un ingénieur
classifie manuellement la cause : `"agent"` (output mauvais) / `"task_spec"` (tâche malformée) /
`"evaluator"` (critères injustes). Cette attribution pilote la boucle de routage :

- `active_cases()` n'inclut les `fix_target` que si `attribution == "agent"` — les autres sont
  hors health check jusqu'à re-classification.
- `HealthCheckReport.unattributed` expose les cas non triés comme signal de backlog.
- B3 (TaskSpecGenerator) consomme `attribution == "task_spec"` pour corriger la tâche.

B2 remplace le triage manuel par un appel LLM. **Le reste de la boucle est inchangé** — le
routing via `attribution` existe déjà dans `test_set.py`, `lifecycle.py`, `health_check.py`.

---

## Ce qui ne change pas

- `TestCase` : aucun champ modifié (`attribution` existe déjà, `active_cases()` l'utilise déjà)
- `lifecycle.py` : `graduate` et `active_cases` inchangés
- `health_check.py` : `run_health_check` inchangé — après triage, le `TestSet` mis à jour
  est passé tel quel
- `failure_to_test_case` : inchangé (produit toujours `attribution="unattributed"`)
- Tous les tests existants : inchangés

---

## Décisions

| Question | Décision | Justification |
|---|---|---|
| Où vit le triage ? | `src/aaosa/qa/triage.py` (nouveau) | Concern QA distinct — ni test_set ni lifecycle |
| Quand appeler triage ? | Batch : `triage_unattributed(test_set, client) -> TestSet` | Ne bloque pas le chemin runtime. Appelé par le caller avant health check ou avant sauvegarde |
| Inputs LLM | `task.description` + `wrong_output.content` + critères de `evaluator_spec` + `reference` | Suffisant pour raisonner sur les 3 sources d'échec. `QAResult` non injecté (triage re-raisonne depuis les faits bruts) |
| `TriageResult` | Pydantic : `attribution: Literal["agent", "task_spec", "evaluator"]` + `justification: str` | Structured output OpenAI (même pattern que `JudgeResult`) |
| Échec LLM | `triage_case` retourne `None` ; le cas reste `"unattributed"` | Pas d'exception propagée — le backlog `unattributed` est visible dans le rapport |
| Température | 0 | Même décision que le judge V2b — triage doit être déterministe/reproductible |
| Modèle | `gpt-4o-mini` | Cohérent avec le reste du système |
| `wrong_output is None` | Prompt le signale ("no output — dispatch failed") | Cas curated ; pour les `runtime_failure`, `wrong_output` est toujours présent |
| Mutabilité | `triage_unattributed` retourne un **nouveau** `TestSet` | Ne mute jamais l'input — même pattern que `graduate()` |

---

## Seams confirmés

| Fichier | État actuel | Ce qui change |
|---|---|---|
| `src/aaosa/qa/triage.py` | n'existe pas | Créé : `TriageResult` + `triage_case` + `triage_unattributed` |
| `src/aaosa/qa/test_set.py` | `TestCase.attribution` présent | **Aucun changement** |
| `src/aaosa/qa/lifecycle.py` | routing via `attribution` présent | **Aucun changement** |
| `src/aaosa/qa/health_check.py` | `unattributed` dans le rapport | **Aucun changement** |

---

## API de `triage.py`

```python
# src/aaosa/qa/triage.py

class TriageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attribution: Literal["agent", "task_spec", "evaluator"]
    justification: str


def triage_case(case: TestCase, client: OpenAI) -> TriageResult | None:
    """Classifie un seul TestCase. Retourne None si le LLM échoue (cas reste unattributed)."""
    ...


def triage_unattributed(test_set: TestSet, client: OpenAI) -> TestSet:
    """Retourne un nouveau TestSet avec les cas unattributed maintenant classifiés.
    
    Les cas déjà classifiés sont copiés tels quels.
    Un cas dont le triage échoue reste unattributed.
    Ne mute pas l'input.
    """
    ...
```

---

## Prompt de triage

```
You are a quality triage specialist. An automated QA system flagged this agent output as a failure.
Your task is to identify the root cause.

Task description:
{case.task.description}

Required tags: {formatted required_tags}

Agent output:
{case.wrong_output.content if case.wrong_output else "[No output — the task was not claimed by any agent]"}

QA evaluator criteria:
{formatted list of criteria names and whether each is a gate}

Reference answer (if available):
{case.reference or "None"}

Attribute the failure to exactly one of:
- "agent": the output is genuinely poor for a well-formed task with fair evaluation criteria
- "task_spec": the task description is ambiguous, malformed, or sets unrealistic expectations
- "evaluator": the evaluation criteria are too strict, inconsistent, or inappropriate for this task
```

Le LLM retourne `TriageResult` via structured output (`beta.chat.completions.parse`).
Fallback JSON brut si structured output indisponible (même pattern que `Agent.claim`).

---

## Implémentation de `triage_case`

```python
def triage_case(case: TestCase, client: OpenAI) -> TriageResult | None:
    prompt = _build_triage_prompt(case)
    try:
        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
            response_format=TriageResult,
        )
        return response.choices[0].message.parsed
    except Exception:
        pass  # structured output failed — fallback JSON

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content or ""
        data = json.loads(raw)
        return TriageResult(attribution=data["attribution"], justification=data["justification"])
    except Exception:
        return None  # triage échoue → cas reste unattributed
```

---

## Implémentation de `triage_unattributed`

```python
def triage_unattributed(test_set: TestSet, client: OpenAI) -> TestSet:
    new_cases: list[TestCase] = []
    for case in test_set.cases:
        if case.attribution != "unattributed":
            new_cases.append(case)
            continue
        result = triage_case(case, client)
        if result is None:
            new_cases.append(case)  # reste unattributed
        else:
            new_cases.append(case.model_copy(update={"attribution": result.attribution}))
    return TestSet(cases=new_cases)
```

---

## Intégration dans la boucle existante

Avant B2 :
```
failure → failure_to_test_case → TestSet(unattributed) → [manuel] → TestSet(attributed) → active_cases → run_health_check
```

Après B2 :
```
failure → failure_to_test_case → TestSet(unattributed) → triage_unattributed → TestSet(attributed) → active_cases → run_health_check
```

Le reste de la boucle (routing, quarantaine, `graduate`, B3) reste inchangé.

---

## Stratégie de test (TDD)

**`tests/qa/test_triage.py`** (8 tests) :

- `test_triage_result_valid` : construction `TriageResult` + roundtrip JSON (attribution + justification)
- `test_triage_case_returns_agent` : mock LLM retourne `{"attribution": "agent", "justification": "..."}` → `TriageResult(attribution="agent")`
- `test_triage_case_returns_task_spec` : mock LLM retourne `"task_spec"` → attribution correcte
- `test_triage_case_returns_evaluator` : mock LLM retourne `"evaluator"` → attribution correcte
- `test_triage_case_llm_failure_returns_none` : mock LLM lève `Exception` → retourne `None`
- `test_triage_unattributed_attributes_cases` : TestSet avec 2 `"unattributed"` + 1 `"agent"` → les 2 triés, le 3e inchangé
- `test_triage_unattributed_skips_already_attributed` : cas `"agent"`, `"task_spec"`, `"evaluator"` → tous copiés sans appel LLM
- `test_triage_unattributed_does_not_mutate_input` : TestSet original inchangé après appel

---

## Critères de done

- [ ] `src/aaosa/qa/triage.py` créé : `TriageResult` + `triage_case` + `triage_unattributed`
- [ ] `triage_case` retourne `None` sur échec LLM (jamais d'exception propagée)
- [ ] `triage_unattributed` ne mute pas l'input, retourne un nouveau `TestSet`
- [ ] Cas déjà attributés : copiés sans appel LLM
- [ ] `tests/qa/test_triage.py` : 8 tests verts
- [ ] `test_set.py`, `lifecycle.py`, `health_check.py` : **zéro modification**, tous leurs tests restent verts
- [ ] Suite complète ≥ 641 + 8 = **649 tests verts** (après A1+B1+A3+A4+A5)

---

## Questions tranchées ici

1. **Pourquoi pas inline dans `failure_to_test_case` ?**
   Appelé dans le chemin runtime critique (pendant `run_task`). Ajouter un LLM call sur chaque
   échec ralentirait le pipeline de production. La séparation batch/runtime est délibérée.

2. **Pourquoi ne pas injecter le `QAResult` (score, criteria_results) dans le prompt ?**
   `TestCase` ne le stocke pas. L'ajouter changerait le schema (hors scope B2). Le LLM peut
   raisonner depuis task + output + critères — les scores lui permettraient d'aller plus vite
   mais ne sont pas indispensables. Décision : pas de schema change en B2.

3. **Un seul appel triage par cas — pas de N runs ?**
   Oui. La variance du triage est faible (temperature=0, question structurée). Contrairement au
   judge de qualité (qui évalue un output à risque de bruit), le triage classe une cause d'échec —
   la réponse est stable sur plusieurs appels.

4. **`triage_unattributed` est synchrone — pas de parallélisation ?**
   Non en B2 — même décision qu'A3 (parallélisation = optimisation future). Les cas unattributed
   sont rares (échecs runtime triés par batch, pas en continu).

5. **Attribution `"unattributed"` peut-elle sortir de `TriageResult` ?**
   Non — `TriageResult.attribution` est `Literal["agent", "task_spec", "evaluator"]`. L'état
   `"unattributed"` n'est possible que si `triage_case` retourne `None`. Pydantic validation
   garantit cela.
