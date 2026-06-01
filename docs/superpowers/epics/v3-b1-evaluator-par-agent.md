# V3 — Épique B1 — Evaluator émis par agent

- **Couche** : `src/aaosa/qa/` (adaptive.py)
- **Statut** : deep-dive terminé → prêt pour plan + exécution
- **Dépendances** : aucune. Seam `Task -> EvaluatorSpec` en place depuis V2b.
- **Roadmap** : section V3, épique B1

---

## Contexte

`build_adaptive_spec(task: Task) -> EvaluatorSpec` produit une spec d'évaluation par règles
déterministes (nb de tags, seuil ELO). C'est humain-codé. B1 change uniquement le **producteur** :
un LLM génère la spec à partir de la description de la tâche.

Le format (`EvaluatorSpec` Pydantic sérialisable JSON) ne change pas — c'est le seam V2b→V3 prévu
et c'est pourquoi cette épique n'a aucune dépendance.

---

## Ce qui ne change pas

- `EvaluatorSpec` / `CriterionSpec` / `JudgeSpec` : inchangés
- `SpecEvaluator.evaluate(task, output) -> QAResult` : inchangé
- `build_adaptive_spec` : **conservé** — utilisé comme fallback + dans les tests existants
- `run_demo.py` : inchangé (utilise toujours `build_adaptive_spec` par défaut)
- Les 588 tests existants ne sont pas touchés

---

## Décisions

| Question | Décision | Justification |
|---|---|---|
| Nom de la nouvelle fonction | `build_llm_spec(task, client) -> EvaluatorSpec` dans `adaptive.py` | Colocalisé avec `build_adaptive_spec`, même module, pattern symétrique |
| Structured output vs JSON raw | Structured output (`beta.chat.completions.parse`, `response_format=EvaluatorSpec`) | Même pattern que `Agent.claim` — robuste, Pydantic validation intégrée |
| Critères adaptatifs libres | Nouveau critère `"llm_check"` dans `criteria.py` — param `description: str`, évalué via micro-appel LLM | Le LLM peut inventer des critères sémantiques spécifiques à la tâche sans sortir du schéma `CriterionSpec` |
| Critères prédéfinis dans le prompt | `list(CRITERIA_REGISTRY.keys())` exposé **comme suggestions**, pas comme liste fermée | Le LLM combine déterministe + `"llm_check"` librement |
| Fallback sur échec LLM | `build_adaptive_spec(task)` | Garde-fou : si le LLM échoue ou retourne du JSON invalide, on ne casse pas le pipeline |
| Garde-fou post-parse | Filtrer les `CriterionSpec` dont `name` n'est pas dans `CRITERIA_REGISTRY` (après enregistrement de `"llm_check"`) | Défense secondaire — protège `SpecEvaluator` contre les noms purement inventés |
| Modèle LLM | `gpt-4o-mini` | Cohérent avec le reste du codebase |
| `run_demo.py` | Non modifié en B1 | Démo reste déterministe — B1 livre la capacité, pas l'intégration démo |
| Démo de la capacité | Tests unitaires (LLM mocké) | La spec est testée unitairement ; intégration démo reportée |

---

## Seams confirmés

| Fichier | État actuel | Ce qui change |
|---|---|---|
| `src/aaosa/qa/adaptive.py` | `build_adaptive_spec(task) -> EvaluatorSpec` (21 lignes, déterministe) | Ajout de `build_llm_spec(task, client) -> EvaluatorSpec` dans le même fichier |
| `src/aaosa/qa/criteria.py` | `CRITERIA_REGISTRY` + 5 critères enregistrés | Ajout du critère `"llm_check"` (param `description: str`, évaluation LLM) |
| `src/aaosa/qa/spec.py` | `EvaluatorSpec` / `CriterionSpec` / `JudgeSpec` Pydantic | Non touché — `"llm_check"` s'exprime avec `CriterionSpec(name="llm_check", params={"description": "..."})` |
| `tests/qa/test_adaptive.py` | 6 tests sur `build_adaptive_spec` | Non touché |
| `tests/qa/test_criteria.py` | Tests par critère | Ajout des tests `"llm_check"` |

---

## API de `build_llm_spec`

```python
# src/aaosa/qa/adaptive.py  (ajout)
from openai import OpenAI

def build_llm_spec(task: Task, client: OpenAI) -> EvaluatorSpec:
    """Génère un EvaluatorSpec via LLM (structured output).

    Fallback automatique sur build_adaptive_spec si le LLM échoue.
    Post-filtre les critères inconnus de CRITERIA_REGISTRY.
    """
```

---

## Prompt (structure)

```
Tu génères une EvaluatorSpec pour évaluer la réponse d'un agent à cette tâche.

# Tâche
{task.description}

# Tags requis
{task.required_tags}

# Critères prédéfinis disponibles (suggestions)
{list(CRITERIA_REGISTRY.keys())}

# Critère adaptatif libre
"llm_check" accepte un param "description" (str) — utilise-le pour tout critère
sémantique spécifique à cette tâche qui ne correspond à aucun critère prédéfini.
Exemple : {"name": "llm_check", "params": {"description": "La réponse doit inclure
des exemples de code avec explications"}, "weight": 1.5}

# Règles
- Toujours inclure "non_empty" comme gate=True
- Ajouter "min_length" si la tâche attend une réponse détaillée
- Utiliser "llm_check" pour des critères qualitatifs propres à cette tâche
- Ajouter un judge (mode "rubric") si la tâche est complexe ou ambiguë
- Tout nom hors de la liste prédéfinie ET hors "llm_check" sera ignoré
- success_threshold entre 0.5 et 0.9 selon la criticité
```

Retourner directement un `EvaluatorSpec` JSON structuré.

---

## Logique de fallback

```
try:
    spec = <structured output parse>
    spec = _filter_unknown_criteria(spec)   # défense secondaire
    return spec
except Exception:
    return build_adaptive_spec(task)        # fallback déterministe
```

`_filter_unknown_criteria(spec) -> EvaluatorSpec` : retire les `CriterionSpec` dont `name` n'est
pas dans `CRITERIA_REGISTRY`. Si la liste résultante est vide, retourne `build_adaptive_spec(task)`.

---

## Stratégie de test (TDD)

**`tests/qa/test_adaptive_llm.py`** — tests `build_llm_spec` avec LLM mocké :

- `test_build_llm_spec_returns_evaluator_spec` : LLM retourne JSON valide → `EvaluatorSpec` correct
- `test_build_llm_spec_always_has_non_empty_gate` : invariant — `non_empty` gate=True toujours présent
- `test_build_llm_spec_injects_into_spec_evaluator` : spec passée à `SpecEvaluator(spec, client=None)` sans erreur
- `test_build_llm_spec_fallback_on_exception` : `parse` lève → fallback `build_adaptive_spec` retourné
- `test_build_llm_spec_filters_unknown_criteria` : critère `"hallucinated_criterion"` → filtré, spec valide
- `test_build_llm_spec_filters_all_unknown_falls_back` : tous critères inconnus après filtrage → fallback
- `test_build_llm_spec_llm_check_preserved` : critère `"llm_check"` dans la réponse LLM → conservé (pas filtré)

**`tests/qa/test_criteria.py`** — ajout pour `"llm_check"` :

- `test_llm_check_passes_when_llm_says_yes` : micro-appel LLM mocké retourne score=1.0 → `passed=True`
- `test_llm_check_fails_when_llm_says_no` : micro-appel LLM mocké retourne score=0.0 → `passed=False`
- `test_llm_check_missing_description_raises` : pas de param `description` → `ValueError`

**Tests existants** (non modifiés) : `tests/qa/test_adaptive.py` — 6 tests sur `build_adaptive_spec`, tous verts.

---

## Critères de done

- [ ] `"llm_check"` enregistré dans `criteria.py` — param `description: str`, micro-appel LLM, `ValueError` si description absente
- [ ] `build_llm_spec(task, client) -> EvaluatorSpec` ajouté dans `adaptive.py`
- [ ] `_filter_unknown_criteria` implémenté (privé) — préserve `"llm_check"`, filtre les noms purement inventés
- [ ] Prompt expose les critères prédéfinis comme suggestions + documente `"llm_check"` comme critère libre
- [ ] Fallback sur `build_adaptive_spec` testé et fonctionnel
- [ ] `tests/qa/test_adaptive_llm.py` : 7 tests, tous verts
- [ ] `tests/qa/test_criteria.py` : 3 tests `"llm_check"` ajoutés, tous verts
- [ ] `tests/qa/test_adaptive.py` : 6 tests existants inchangés, tous verts
- [ ] Suite complète ≥ 594 + 10 = **604 tests verts** (après A1)

---

## Questions tranchées ici

1. **Nouvelle classe `SpecGeneratorAgent` ?** Non — une fonction suffit. B1 = changer le producteur, pas introduire un nouveau composant de claiming.
2. **`build_llm_spec` dans `run_demo.py` ?** Non en B1 — la démo reste déterministe. L'intégration démo vient après (ou en B3 quand la boucle est complète).
3. **Température LLM pour `build_llm_spec` ?** 0.0 — spec déclarative, on veut du déterminisme, pas de créativité.
4. **Température LLM pour `"llm_check"` ?** 0.0 — évaluation binaire, pas de créativité.
5. **`success_threshold` libre pour le LLM ?** Oui, dans [0.5, 0.9] — le LLM juge la criticité, c'est précisément la valeur de B1.
6. **Post-validation `weight` et `gate` ?** Non — Pydantic valide déjà les types ; les valeurs extrêmes ne cassent pas `SpecEvaluator`.
7. **`JudgeSpec.rubric` vide ?** Ne pas ajouter cette contrainte en B1 (hors scope).
8. **`required_tags` générés par `build_llm_spec` ?** Non — `build_llm_spec` reçoit une tâche déjà taguée. La génération de tags appartient à B3 (TaskSpecGenerator).
