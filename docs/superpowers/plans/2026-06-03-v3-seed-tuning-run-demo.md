# Tuning seed `run_demo_v3` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire en sorte que `run_demo_v3` aboutisse à une agrégation alimentée par plusieurs sous-tâches qui passent le QA réel — en corrigeant les invariants V2b violés par `build_llm_spec` et en musclant la qualité des outputs agents.

**Architecture:** Deux leviers complémentaires. (1) `build_llm_spec` empêche par construction que le LLM produise une spec qui viole V2b : le poids du judge est verrouillé à 0.3 (jamais primaire) et seul `non_empty` peut être un gate (les champs `weight`/`gate` sont retirés des schémas LLM-facing). (2) Les system prompts des agents de démo et un stub de tool sont enrichis pour produire des outputs complets et exploitables. Le divider/aggregator restent intacts (émergence préservée).

**Tech Stack:** Python 3.14, Pydantic 2.13, OpenAI SDK 2.38, pytest 9.0.3. Venv : `.venv\Scripts\python`.

---

## Référence : diagnostic (evidence run réel 2026-06-02)

- Sous-tâche 0 (auth) : QA FAIL `0.67` < `0.7`. `det=0.94`, mais judge à **poids 1.0** émis par le LLM → `final = 0·0.94 + 1.0·0.67`. Judge devenu signal primaire (interdit V2b).
- Sous-tâche 1 (SQL) : QA FAIL `0.0`, `gate failed: min_length (166/300)`. `min_length` fait **gate** par le LLM (seul `non_empty` devrait l'être). Agent n'a pas appelé `explain_query_plan`, output maigre.
- Cascade : sous-tâches 2-5 dépendent de 0/1 → `dependency_failed` → `unassigned`.
- `min_length` est **gradué** (`min(1, n/threshold)`) → passer de gate à scoré ne suffit pas, la qualité agent reste nécessaire.
- Fix invariants seul → sous-tâche 0 passe (`0.7·0.94 + 0.3·0.67 = 0.86`) → agrégation garantie. Qualité agents → richesse de l'agrégation.

---

## File Structure

- **Modify** `src/aaosa/qa/adaptive.py` — retirer `weight` de `_LLMJudge` et `gate` de `_LLMCriterion`, ajuster `to_criterion`/`to_judge` et `_build_prompt`.
- **Modify** `tests/qa/test_adaptive_llm.py` — retirer les kwargs `gate=`/`weight=` des constructions, ajouter les tests d'invariants.
- **Modify** `src/aaosa/demo/agents.yaml` — directive de méthode (investiguer via tools, réponse complète avec code/SQL) dans chaque `system_prompt`.
- **Modify** `src/aaosa/demo/tools.py` — `explain_query_plan` renvoie des recommandations d'index concrètes.
- **Verify** `src/aaosa/demo/run_demo_v3.py` — run réel + inspection de trace (aucune modif de code).

---

## Task 1 : Verrouiller les invariants judge-weight & gate dans `build_llm_spec`

**Files:**
- Modify: `src/aaosa/qa/adaptive.py` (classes `_LLMCriterion` ~19-40, `_LLMJudge` ~43-50, fn `_build_prompt` ~109-128)
- Test: `tests/qa/test_adaptive_llm.py`

- [ ] **Step 1 : Ajouter les tests d'invariants (nouveaux)**

Ajouter ces tests à la fin de la classe `TestBuildLLMSpec` dans `tests/qa/test_adaptive_llm.py` :

```python
    def test_llm_criterion_rejects_gate_field(self):
        # Le LLM ne peut plus déclarer de gate : seul non_empty en est un (invariant V2b).
        with pytest.raises(Exception):
            _LLMCriterion(name="min_length", gate=True)

    def test_llm_judge_rejects_weight_field(self):
        # Le LLM ne contrôle plus le poids du judge (jamais signal primaire, V2b).
        with pytest.raises(Exception):
            _LLMJudge(rubric=["correctness"], weight=1.0)

    def test_judge_weight_always_03(self):
        spec = _LLMEvaluatorSpec(
            criteria=[_LLMCriterion(name="non_empty")],
            judge=_LLMJudge(mode="rubric", rubric=["correctness"]),
        )
        result = build_llm_spec(make_task(), _FakeParseClient(spec))
        assert result.judge is not None
        assert result.judge.weight == 0.3

    def test_only_non_empty_is_gate(self):
        # Même si le LLM propose non_empty + min_length, le seul gate de sortie
        # doit être non_empty (min_length reste scoré, gradué).
        spec = _LLMEvaluatorSpec(
            criteria=[
                _LLMCriterion(name="non_empty"),
                _LLMCriterion(name="min_length", min_chars=300),
            ],
        )
        result = build_llm_spec(make_task(), _FakeParseClient(spec))
        gated = [c.name for c in result.criteria if c.gate]
        assert gated == ["non_empty"]
```

- [ ] **Step 2 : Lancer les nouveaux tests pour vérifier qu'ils échouent**

Run : `.venv\Scripts\python -m pytest tests/qa/test_adaptive_llm.py::TestBuildLLMSpec::test_llm_criterion_rejects_gate_field tests/qa/test_adaptive_llm.py::TestBuildLLMSpec::test_llm_judge_rejects_weight_field -v`
Attendu : les deux `reject_field` ÉCHOUENT (`DID NOT RAISE` — les champs `gate`/`weight` existent encore). Les tests `test_judge_weight_always_03` et `test_only_non_empty_is_gate` passent déjà (ils verrouillent le comportement courant et futur).

- [ ] **Step 3 : Retirer le champ `gate` de `_LLMCriterion` et ne plus le propager**

Dans `src/aaosa/qa/adaptive.py`, remplacer la classe `_LLMCriterion` :

```python
class _LLMCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    weight: float = 1.0
    # Pas de champ `gate` : seul "non_empty" peut être un gate (invariant V2b),
    # injecté par _ensure_non_empty_gate. Le LLM ne propose que des critères scorés.
    # params possibles, aplatis (un critère n'en utilise qu'un sous-ensemble) :
    min_chars: int | None = None          # min_length
    description: str | None = None        # llm_check
    keywords: list[str] | None = None     # keyword_presence
    kind: str | None = None               # format_check

    def to_criterion(self) -> CriterionSpec:
        params: dict = {}
        if self.min_chars is not None:
            params["min_chars"] = self.min_chars
        if self.description is not None:
            params["description"] = self.description
        if self.keywords is not None:
            params["keywords"] = self.keywords
        if self.kind is not None:
            params["kind"] = self.kind
        return CriterionSpec(name=self.name, params=params, weight=self.weight)
```

- [ ] **Step 4 : Retirer le champ `weight` de `_LLMJudge` et ne plus le propager**

Dans `src/aaosa/qa/adaptive.py`, remplacer la classe `_LLMJudge` :

```python
class _LLMJudge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["rubric", "reference_based"] = "rubric"
    rubric: list[str]
    # Pas de champ `weight` : le judge n'est jamais le signal primaire (invariant
    # V2b). Poids verrouillé à 0.3 via le défaut JudgeSpec — le LLM ne le contrôle pas.

    def to_judge(self) -> JudgeSpec:
        return JudgeSpec(mode=self.mode, rubric=self.rubric)
```

- [ ] **Step 5 : Ajuster `_build_prompt` (règles)**

Dans `src/aaosa/qa/adaptive.py`, dans `_build_prompt`, remplacer la ligne de règle sur le gate :

Remplacer :
```python
        '- Toujours inclure "non_empty" comme gate=True\n'
```
par :
```python
        '- "non_empty" est ajouté automatiquement comme unique gate — ne le déclare pas\n'
```

(Les autres règles restent inchangées. Aucune mention de poids de judge n'existe dans le prompt — rien d'autre à retirer.)

- [ ] **Step 6 : Mettre à jour les constructions de tests cassées par le retrait des champs**

Dans `tests/qa/test_adaptive_llm.py`, retirer tous les kwargs `gate=True` des appels `_LLMCriterion(...)` et le kwarg `weight=0.3` de l'appel `_LLMJudge(...)`. Précisément :

- `_LLMCriterion(name="non_empty", gate=True)` → `_LLMCriterion(name="non_empty")` (occurrences dans `test_returns_evaluator_spec`, `test_response_format_is_closed_schema`, `test_judge_converted`, `test_injects_into_spec_evaluator`, `test_filters_unknown_criteria`, `test_llm_check_preserved_with_description`).
- `_LLMJudge(mode="rubric", rubric=["correctness", "completeness"], weight=0.3)` → `_LLMJudge(mode="rubric", rubric=["correctness", "completeness"])` (dans `test_judge_converted`).

Le corps de `test_judge_converted` garde `assert result.judge.weight == 0.3` (toujours vrai via le défaut JudgeSpec).

- [ ] **Step 7 : Lancer tout le fichier de tests**

Run : `.venv\Scripts\python -m pytest tests/qa/test_adaptive_llm.py -v`
Attendu : PASS (tous, y compris les 4 nouveaux tests d'invariants).

- [ ] **Step 8 : Lancer la suite QA + adaptive complète (non-régression)**

Run : `.venv\Scripts\python -m pytest tests/qa/ -v`
Attendu : PASS (aucune régression sur `test_adaptive.py`, `test_spec_evaluator.py`, etc.).

- [ ] **Step 9 : Commit**

```bash
git add src/aaosa/qa/adaptive.py tests/qa/test_adaptive_llm.py
git commit -m "fix(v3-b1): verrouille les invariants V2b dans build_llm_spec (judge 0.3, seul non_empty gate)"
```

---

## Task 2 : Muscler les system prompts des agents de démo

**Files:**
- Modify: `src/aaosa/demo/agents.yaml`

Pas de test unitaire (prompts validés par le run réel en Task 4). `test_loader.py` utilise ses propres YAML inline et `test_agents.py` ne vérifie que `len(system_prompt) > 0` — donc rien ne casse.

- [ ] **Step 1 : Réécrire `src/aaosa/demo/agents.yaml`**

Remplacer tout le contenu par (chaque `system_prompt` reçoit une directive de méthode commune : investiguer via les tools, répondre complètement avec code/SQL et explication) :

```yaml
# Agents de la démo logicielle AAOSA.
# Chargés par aaosa.config.loader.load_agents — le champ id est généré à la volée.
# Le nom est l'identifiant stable (matché par les snapshots ELO).

- name: Frontend
  tags_with_elo:
    frontend: 85
    css: 90
    javascript: 80
    testing: 40
  system_prompt: >-
    You are a frontend specialist focused on UI, CSS, and JavaScript.
    Investigate with your available tools before answering: read the relevant
    files. Then give a complete response that quotes the relevant code, explains
    the root cause, and provides a concrete fix as a code snippet with a short
    explanation.

- name: Backend
  tags_with_elo:
    backend: 90
    database: 85
    python: 80
    testing: 50
  system_prompt: >-
    You are a backend specialist focused on APIs, databases, Python, and backend
    performance optimization (middleware, connection pooling, caching, async
    patterns, query indexing). Always investigate with your available tools
    before answering: read the relevant files and inspect query plans with
    explain_query_plan. Then give a complete, detailed response that quotes the
    relevant code, explains the root cause, and provides a concrete fix as a code
    or SQL snippet with a short explanation.

- name: DevOps
  tags_with_elo:
    infrastructure: 90
    docker: 85
    ci_cd: 80
    backend: 30
  system_prompt: >-
    You are a DevOps specialist focused on infrastructure and CI/CD.
    Investigate with your available tools before answering: read the relevant
    files. Then give a complete response that quotes the relevant configuration,
    explains the root cause, and provides a concrete fix with a short explanation.

- name: Fullstack
  tags_with_elo:
    frontend: 50
    backend: 55
    javascript: 60
    python: 50
    database: 40
  system_prompt: >-
    You are a fullstack generalist covering frontend and backend.
    Investigate with your available tools before answering: read the relevant
    files and run tests when useful. Then give a complete response that quotes the
    relevant code, explains the root cause, and provides a concrete fix as a code
    snippet with a short explanation.
```

- [ ] **Step 2 : Vérifier que le chargement YAML + les tests demo passent**

Run : `.venv\Scripts\python -m pytest tests/demo/test_agents.py tests/config/test_loader.py -v`
Attendu : PASS (les agents se chargent, system_prompts non vides).

- [ ] **Step 3 : Commit**

```bash
git add src/aaosa/demo/agents.yaml
git commit -m "feat(v3-demo): prompts agents orientes investigation tools + reponse complete"
```

---

## Task 3 : Enrichir le stub `explain_query_plan` avec des recommandations d'index

**Files:**
- Modify: `src/aaosa/demo/tools.py` (fn `explain_query_plan` ~43-48)
- Test: `tests/demo/test_tools.py` (déjà vert, vérifie seulement `isinstance str`)

- [ ] **Step 1 : Enrichir `explain_query_plan`**

Dans `src/aaosa/demo/tools.py`, remplacer la fonction :

```python
def explain_query_plan(sql: str) -> str:
    return (
        "Seq Scan on users  (cost=0.00..38221.00 rows=2000000)\n"
        "Seq Scan on orders (cost=0.00..51234.00 rows=15000000)\n"
        "-> no index used; full table scans on FK columns\n"
        "Recommendation: CREATE INDEX idx_orders_user_id ON orders(user_id);\n"
        "Recommendation: CREATE INDEX idx_users_token ON users(token);\n"
        "Estimated p99 after indexing: < 200ms (currently > 8s)\n"
    )
```

- [ ] **Step 2 : Lancer les tests tools**

Run : `.venv\Scripts\python -m pytest tests/demo/test_tools.py -v`
Attendu : PASS (les assertions ne vérifient que le type `str` et la composition du TOOLBOX).

- [ ] **Step 3 : Commit**

```bash
git add src/aaosa/demo/tools.py
git commit -m "feat(v3-demo): explain_query_plan suggere des index concrets (matiere pour le fix)"
```

---

## Task 4 : Validation end-to-end (run LLM réel + capture trace canonique)

**Files:**
- Verify: `src/aaosa/demo/run_demo_v3.py` (aucune modif de code)

Requiert `OPENAI_API_KEY` dans `.env`. Coût : un run divisé LLM réel (gpt-4o-mini).

- [ ] **Step 1 : Lancer la suite complète (non-régression globale)**

Run : `.venv\Scripts\python -m pytest -q`
Attendu : PASS (706 tests existants + les 4 nouveaux invariants = 710).

- [ ] **Step 2 : Lancer le run de démo divisé**

Run : `.venv\Scripts\python src\aaosa\demo\run_demo_v3.py`
Attendu : la dernière ligne du run affiche `-> divided` (et non `-> unassigned`). Noter le chemin `runs\sessions\<id>` affiché à la fin.

- [ ] **Step 3 : Inspecter la trace persistée**

Adapter `<id>` au dossier affiché en Step 2, puis lancer :

```bash
.venv\Scripts\python -c "import json,glob,os; d=sorted(glob.glob('runs/sessions/*'),key=os.path.getmtime)[-1]; print('session:',d); [print(e['type'], '|', (e.get('reason') or e.get('tool_name') or e.get('output_summary') or '')[:90]) for e in (json.loads(l) for l in open(d+'/trace.jsonl',encoding='utf-8'))]"
```

Attendu (critères de réussite) :
- un `task_divided` (≥ 2 sous-tâches),
- des `tool_called` (les agents utilisent leurs tools, dont `explain_query_plan`),
- **≥ 2 `qa_evaluated` avec `success=True`** (plusieurs sous-tâches passent réellement le QA),
- un `task_aggregated` (l'agrégateur a synthétisé les outputs réussis).

Si `unassigned` ou agrégation maigre (1 seule sous-tâche réussie) : relire les `reason` des `qa_evaluated` en échec et ajuster les prompts (Task 2) ou la matière des tools (Task 3) en conséquence, puis re-commit et relancer.

- [ ] **Step 4 : Vérifier la robustesse (2e et 3e run)**

Relancer `.venv\Scripts\python src\aaosa\demo\run_demo_v3.py` deux fois de plus.
Attendu : `-> divided` à chaque fois (cible « passe de façon fiable »). Le divider/spec sont en `temperature=0.0`, mais les outputs agents varient — confirmer que la marge tient.

- [ ] **Step 5 : Vérifier le rendu dashboard (visuel)**

Lancer le dashboard : `.venv\Scripts\python -m dashboard` → http://localhost:5000
Onglet Sessions : sélectionner la session capturée. Vérifier que le graphe rend les jalons divider → agents → tools → evaluator → aggregator → output, et que le modal Evaluator affiche l'« Output évalué » du winner.

(Aucun commit : `runs/` est gitignored. La trace est régénérable ; c'est le seed robuste committé en Tasks 1-3 qui est l'artefact.)

---

## Self-Review (effectué)

- **Couverture spec** : Composant 1 → Task 1 ; Composant 2 (agents.yaml) → Task 2 ; Composant 2 (tools.py) → Task 3 ; Composant 3 (divider intact) → aucune tâche (volontaire) ; Composant 4 (tests + trace canonique) → Task 1 (TDD) + Task 4 (run réel + dashboard). Couvert.
- **Placeholders** : aucun — code complet à chaque step, commandes exactes, attendus explicites.
- **Cohérence des types** : `_LLMCriterion`/`_LLMJudge`/`to_criterion`/`to_judge`/`JudgeSpec.weight`/`CriterionSpec.gate` cohérents entre Task 1 et le diagnostic. Les noms de tests référencés en Step 6 existent dans le fichier actuel.
