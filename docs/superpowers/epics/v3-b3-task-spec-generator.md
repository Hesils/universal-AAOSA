# V3 — Épique B3 — TaskSpecGenerator

- **Couche** : `src/aaosa/qa/task_spec_generator.py` (nouveau)
- **Statut** : deep-dive terminé → prêt pour plan + exécution
- **Dépendances** : B2 (consomme `attribution == "task_spec"`)
- **Roadmap** : section V3, épique B3

---

## Contexte

Après B2, les cas dont l'attribution est `"task_spec"` sont identifiés : la tâche elle-même
était malformée ou ambiguë — l'agent n'est pas responsable de l'échec. Ces cas sont
**quarantinés** : `active_cases()` les exclut, `HealthCheckReport.task_spec_quarantined`
les expose comme backlog.

B3 corrige automatiquement ces descriptions de tâches via un appel LLM. Après correction :
- Le cas retrouve `attribution="unattributed"`
- B2 (`triage_unattributed`) le re-classifie → typiquement `"agent"` si la tâche est maintenant
  bien formée
- Le cas rentre dans `active_cases()` et peut être vérifié au prochain health check

**B3 est une cible supplémentaire de la même boucle de routage** — pas un lifecycle séparé.

---

## Ce qui ne change pas

- `TestCase`, `TestSet`, `failure_to_test_case` : inchangés
- `active_cases`, `graduate` : inchangés
- `run_health_check` : inchangé
- Tous les tests existants : inchangés

---

## Décisions

| Question | Décision | Justification |
|---|---|---|
| Quoi corriger ? | `task.description` uniquement | Les `required_tags` sont une décision structurelle (config, A1) — corriger la description est le seul levier LLM-accessible |
| `Task.id` après correction | Conservé (`model_copy` ne change pas `id`) | La référence `wrong_output.task_id → task.id` reste valide ; la traçabilité de l'échec original est préservée |
| Attribution après correction | Reset à `"unattributed"` | La tâche corrigée doit repasser par B2 (`triage_unattributed`) avant d'être active — le même pipeline |
| `role` après correction | Conservé (`fix_target`) | La tâche doit être vérifiée au health check avant de `graduate()` en `regression_guard` |
| `wrong_output` après correction | Conservé | Contexte historique de l'ancien échec — utile dans le prompt de B2 pour la re-classification |
| Quand appeler B3 ? | Batch : `fix_task_spec_cases(test_set, client) -> TestSet` | Ne bloque pas le runtime. Le caller orchestre : B3 → B2 → health check |
| Échec LLM | `fix_task_spec` retourne `None` ; le cas reste `"task_spec"` | Pas d'exception propagée — le backlog reste visible dans le rapport |
| Température | 0 | Correction déterministe — le LLM doit produire une réécriture stable |
| Modèle | `gpt-4o-mini` | Cohérent avec le reste |
| `wrong_output is None` | Prompt le signale ("[No output]") | Cas rare (curated sans exemple) — ne bloque pas |

---

## Seams confirmés

| Fichier | État actuel | Ce qui change |
|---|---|---|
| `src/aaosa/qa/task_spec_generator.py` | n'existe pas | Créé : `TaskSpecFix` + `fix_task_spec` + `fix_task_spec_cases` |
| `src/aaosa/qa/test_set.py` | `attribution`, `TestCase.model_copy` présents | **Aucun changement** |
| `src/aaosa/qa/lifecycle.py` | `active_cases`, `graduate` présents | **Aucun changement** |
| `src/aaosa/qa/health_check.py` | `task_spec_quarantined` dans le rapport | **Aucun changement** |

---

## API de `task_spec_generator.py`

```python
# src/aaosa/qa/task_spec_generator.py

class TaskSpecFix(BaseModel):
    model_config = ConfigDict(extra="forbid")
    corrected_description: str
    justification: str


def fix_task_spec(case: TestCase, client: OpenAI) -> TestCase | None:
    """Retourne un nouveau TestCase avec description corrigée et attribution='unattributed'.
    
    Retourne None si le LLM échoue (le cas reste task_spec dans le TestSet).
    Ne mute pas l'input.
    """
    ...


def fix_task_spec_cases(test_set: TestSet, client: OpenAI) -> TestSet:
    """Retourne un nouveau TestSet avec les cas task_spec corrigés. Autres cas inchangés.
    
    Les cas dont le fix échoue (LLM failure) restent task_spec.
    Ne mute pas l'input.
    """
    ...
```

---

## Prompt de correction

```
You are a task specification specialist. An automated QA system determined that the following
task description caused an agent failure because the task itself was malformed or ambiguous
— not due to agent incompetence.

Original task description:
{case.task.description}

Required agent capabilities (tags and minimum ELO levels):
{formatted: "tag: elo_min" per required_tag}

Agent output that was flagged as failing:
{case.wrong_output.content if case.wrong_output else "[No output — task was not claimed]"}

QA evaluator criteria:
{formatted: criterion name + "(gate)" if gate=True, per criterion in evaluator_spec.criteria}

Reference answer (if available):
{case.reference or "None"}

Rewrite the task description so that it is:
- Clear and unambiguous — a qualified agent knows exactly what to produce
- Achievable — given the required capabilities listed above
- Specific — concrete expected output, not vague instructions
- Fair — consistent with the evaluation criteria listed above

Return only the corrected description in 'corrected_description'. Do not include explanations
inside the description itself.
```

---

## Implémentation de `fix_task_spec`

```python
def fix_task_spec(case: TestCase, client: OpenAI) -> TestCase | None:
    prompt = _build_fix_prompt(case)
    try:
        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
            response_format=TaskSpecFix,
        )
        result = response.choices[0].message.parsed
    except Exception:
        # structured output unavailable — fallback JSON
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.choices[0].message.content or ""
            data = json.loads(raw)
            result = TaskSpecFix(
                corrected_description=data["corrected_description"],
                justification=data["justification"],
            )
        except Exception:
            return None  # LLM failure — cas reste task_spec

    new_task = case.task.model_copy(update={"description": result.corrected_description})
    return case.model_copy(update={"task": new_task, "attribution": "unattributed"})
```

---

## Implémentation de `fix_task_spec_cases`

```python
def fix_task_spec_cases(test_set: TestSet, client: OpenAI) -> TestSet:
    new_cases: list[TestCase] = []
    for case in test_set.cases:
        if case.attribution != "task_spec":
            new_cases.append(case)
            continue
        fixed = fix_task_spec(case, client)
        new_cases.append(fixed if fixed is not None else case)
    return TestSet(cases=new_cases)
```

---

## Boucle de routage complète (B2 + B3)

```
runtime failure
    → failure_to_test_case          [test_set.py]    attribution="unattributed"
    → triage_unattributed (B2)      [triage.py]      attribution="agent"|"task_spec"|"evaluator"
    → fix_task_spec_cases (B3)      [task_spec_gen]  task_spec → description corrigée, attribution="unattributed"
    → triage_unattributed (B2)      [triage.py]      attribution="agent" (après fix)
    → active_cases                  [test_set.py]    inclus dans le health check
    → run_health_check              [health_check]   pass_rate calculé
    → graduate                      [lifecycle.py]   fix_target → regression_guard si taux ≥ seuil
```

B3 s'insère dans la boucle existante sans modifier aucune de ses étapes.

---

## Stratégie de test (TDD)

**`tests/qa/test_task_spec_generator.py`** (7 tests) :

- `test_task_spec_fix_valid` : construction `TaskSpecFix` + roundtrip JSON
- `test_fix_task_spec_corrects_description` : mock LLM retourne description corrigée → `case.task.description` mis à jour
- `test_fix_task_spec_resets_attribution` : attribution reset à `"unattributed"` dans le cas retourné
- `test_fix_task_spec_preserves_task_id` : `case.task.id` identique dans le cas retourné
- `test_fix_task_spec_llm_failure_returns_none` : mock LLM lève `Exception` → retourne `None`
- `test_fix_task_spec_cases_fixes_task_spec_only` : TestSet avec `"task_spec"` + `"agent"` + `"evaluator"` → seul `"task_spec"` modifié
- `test_fix_task_spec_cases_does_not_mutate_input` : TestSet original inchangé après appel

---

## Critères de done

- [ ] `src/aaosa/qa/task_spec_generator.py` créé : `TaskSpecFix` + `fix_task_spec` + `fix_task_spec_cases`
- [ ] `fix_task_spec` : description corrigée, attribution reset à `"unattributed"`, `task.id` conservé, `None` si LLM échoue
- [ ] `fix_task_spec_cases` : itère sur `"task_spec"` uniquement, ne mute pas l'input
- [ ] `test_set.py`, `lifecycle.py`, `health_check.py` : zéro modification, tous leurs tests restent verts
- [ ] `tests/qa/test_task_spec_generator.py` : 7 tests verts
- [ ] Suite complète ≥ 649 + 7 = **656 tests verts** (après A1+B1+A3+A4+A5+B2)

---

## Questions tranchées ici

1. **Pourquoi ne pas corriger aussi `required_tags` ?**
   Les tags sont une décision de configuration (qui est capable de quoi, A1). Les modifier
   requiert de connaître le roster d'agents — connaissance système, pas tâche. En V3, c'est
   une décision humaine ou une épique dédiée. Hors scope B3.

2. **Pourquoi resetter à `"unattributed"` et non directement à `"agent"` ?**
   La tâche corrigée peut révéler un nouveau problème (evaluator maintenant trop strict pour la
   nouvelle formulation, par exemple). Repasser par B2 coûte peu et garantit que la boucle reste
   cohérente. On ne court-circuite pas le triage.

3. **Pourquoi conserver `wrong_output` sur le cas corrigé ?**
   Il devient un exemple de ce que produisait l'agent sur l'*ancienne* formulation. Utile pour
   B2 lors du re-triage (le LLM voit l'output et la nouvelle description — peut confirmer que
   l'attribution est maintenant `"agent"`). Pas de confusion car `task.id` reste identique.

4. **L'orchestration B3 → B2 est-elle explicite dans le code ?**
   Non en B3 — les deux fonctions sont indépendantes. L'orchestration vit chez le caller
   (un script, un endpoint ou un futur orchestrateur). Pas de couplage direct entre les modules.

5. **Un cas `role="regression_guard"` peut-il avoir `attribution="task_spec"` ?**
   En théorie non (un cas ne graduate pas tant qu'il n'est pas attribué à `"agent"`). Mais
   `fix_task_spec_cases` le corrèle quand même si c'est le cas — le comportement est correct
   dans tous les scénarios.
