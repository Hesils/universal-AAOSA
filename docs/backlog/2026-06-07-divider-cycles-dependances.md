# Backlog — Divider : dépendances cycliques → 4/20 runs en erreur (campagne N=20)

**Découvert** : 2026-06-07, campagne N=20 phase 5 (`runs_campaign_n20`, gpt-4o-mini temp 0).
**Constat** : 4 runs sur 20 (9, 12, 16, 20) échouent en ~7 s avec `cycle detected in task dependencies`. Échec rapide et propre : 0 appel agent gaspillé, containment campagne OK (`error` dans l'index, la boucle continue). Trou de design découvert par la campagne — même famille que le bug tagger AND-contract (phase 3) : un produit LLM structurellement valide (Pydantic passe) mais sémantiquement invalide pour le consommateur aval.

## Diagnostic (complet, pas de recherche à refaire)

Chemin de l'erreur :
1. `TaskDivider.divide` (`src/aaosa/runtime/divider.py`) retourne un `DivisionResult` dont les `SubTaskSpec.depends_on_indices` sont des indices 0-based émis par le LLM. **Aucune validation des indices** : ni bornes, ni auto-référence, ni acyclicité (le `model_validator` ne vérifie que atomic XOR sub_tasks).
2. Le runner construit les `Task` avec ces deps, puis le tri de Kahn (`_topological_order`, `src/aaosa/runtime/runner.py:164`) détecte le cycle et raise `ValueError("cycle detected in task dependencies")`.
3. La `ValueError` remonte jusqu'au containment de `run_campaign` (`src/aaosa/cli/incident_runs.py`) → outcome `error`, typologies `[]`.

Taux observé : **20 % à temp 0** sur la tâche incident (4/20). Non observé sur les 7 runs de phase 4 ni les runs de phase 3 (échantillons trop petits). Le mode exact du cycle (auto-référence `i → i`, paire `i ↔ j`, indice hors bornes interprété ?) n'a pas été extrait des traces — les runs en erreur n'ont pas de session persistée (l'échec précède la persistance), donc le payload divider exact n'est pas conservé. Première étape de tout chantier : reproduire avec un log du `DivisionResult` brut.

**Piste connexe relevée au diagnostic** : le user-prompt du divider (`divider.py:58`, `_build_divide_prompt`) dit encore « decompose it into **ordered** sub-tasks » — la décision phase 4 (« adoucir ordered ») n'a réécrit que le system prompt (`demo/incident/prompts.py`, verrouillé par tests). Tension entre les deux niveaux de prompt ; sans lien causal établi avec les cycles, mais à regarder dans le même chantier.

## Options (à trancher hors phase 5)

- **Valider dans `DivisionResult`** (`model_validator` : bornes + acyclicité) → l'erreur devient un échec de parse → mais alors quoi ? Raise plus tôt, même outcome.
- **Retry du divider sur cycle détecté** (1 retry avec le cycle nommé dans le prompt, pattern failure_context D3 existant) → transforme 20 % d'erreur en runs récupérés ; coût : 1 appel LLM de plus dans le cas d'erreur.
- **Réparer plutôt que rejeter** (casser l'arête retour du cycle, déterministe) → récupération gratuite mais découpe silencieusement altérée — en tension avec « le graphe émerge » et la traçabilité.
- **Assumer** (20 % d'échec rapide, containment propre) → zéro code ; acceptable pour la démo (documenté dans `exhibits.md`), discutable pour un runtime qui se veut robuste.

## Critères d'acceptation (une fois tranché)

- [ ] Mode du cycle identifié sur reproduction (payload `DivisionResult` loggé).
- [ ] Décision loggée (validation / retry / réparation / assumer) avec justification.
- [ ] Si retry ou réparation : taux d'erreur campagne < 5 % sur une mini-campagne de validation (n≈10).

## Pointeurs

- Tri de Kahn : `src/aaosa/runtime/runner.py:164` (`_topological_order`).
- Schémas divider : `src/aaosa/runtime/divider.py` (`SubTaskSpec.depends_on_indices`, `DivisionResult`).
- Containment campagne : `src/aaosa/cli/incident_runs.py` (`run_campaign`, record `error`).
- Données : `runs_demo/campaign_report.md` (runs 9, 12, 16, 20) ; `runs_demo/campaign_index.json`.
- Précédent méthodo : fix tagger AND-contract phase 3 (fix à la source runtime, validé composant seul avant re-run complet).
