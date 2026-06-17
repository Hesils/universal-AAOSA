# Backlog — Durcissement de types sur l'API publique exposée par erd

**Découvert** : 2026-06-17, revue finale whole-branch du ticket erd (`aaosa solve`).
**Constat** : roll-up de 3 findings Minor non bloquantes, regroupées car même nature (resserrer un type laxiste sur une surface devenue publique). Aucune n'est un bug aujourd'hui — toute la construction passe par les chemins corrects. Mais erd a promu `build_root_task` et `Manifest` au rang d'API publique/persistée, ce qui expose des laxismes auparavant internes.

## Items

### 1. `build_root_task` : `if pinned_tags:` (truthy) au lieu de `is not None`

`src/aaosa/runtime/runner.py:527`. Un `pinned_tags={}` (dict vide) tombe dans la branche tagger au lieu de la branche pinned. Verbatim de l'ancien `run_recovery` (donc pas une régression), mais `build_root_task` est désormais **public** (consommé par `solve_once`). Footgun latent : un caller qui passe `{}` pour dire « aucun tag épinglé, mais ne tague pas » obtient un tagging LLM surprise.
- **Fix** : `if pinned_tags is not None:` + décider du comportement sur `{}` (probablement : `{}` = pas de tags pinned valides → `EmptyTaggingError` ou tagger, mais explicite). Ou documenter le contrat dans le docstring si le truthy est intentionnel.

### 2. `Manifest.outcome: str` → `Literal[...]`

`src/aaosa/runtime/manifest.py:44`. Le vocabulaire (`success | qa_fail | unassigned`) n'est garanti qu'à la construction via `_outcome`. Un caller construisant un `Manifest` directement peut passer n'importe quelle string (Pydantic l'accepte). Écrit `outcome: str` verbatim dans le plan → **non changé en vol** pour ne pas contredire le plan validé.
- **Fix** : `outcome: Literal["success", "qa_fail", "unassigned"]`. Fait du vocabulaire une garantie de schéma.

### 3. `ToolCallRecord.arguments: dict` (bare) → typé

`src/aaosa/runtime/manifest.py:31`. Dict non paramétré. Cohérence avec le reste de la base (ex. `ToolCalledEvent.arguments`).
- **Fix** : `arguments: dict[str, object]` (ou aligner sur le type de `ToolCalledEvent.arguments`).

## Critères d'acceptation

- [ ] Items 1-3 appliqués (ou explicitement déclinés avec justification loggée).
- [ ] Suite complète verte (1097 passed/1 skipped au moment de la découverte).
- [ ] Si item 1 change le comportement sur `{}` : test couvrant `pinned_tags={}`.

## Pointeurs

- `src/aaosa/runtime/runner.py:527` (`build_root_task`).
- `src/aaosa/runtime/manifest.py:31,44` (`ToolCallRecord.arguments`, `Manifest.outcome`).
- Contexte : ticket erd, revue finale ; plan `docs/superpowers/plans/2026-06-17-erd-cli-solve.md` (Tasks 4, 5).
