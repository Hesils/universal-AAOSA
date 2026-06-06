# Design — Démo phase 2 : tools déclarés dans le YAML + nettoyage pré-V3

**Date** : 2026-06-06
**Statut** : validé (Quentin, 2026-06-06)
**Contexte** : phase 2 du phasage démo (cadrage brainstorm `raw/brainstorms/2026-06-05-demo-run-propre-complete.md`, Q13). Phase 1 (observabilité série D) mergée sur master (`2854f86`, 883 tests). La phase 3 (`demo/incident/`, monde simulé, roster 7 agents) consommera ce mécanisme.

## Objectif

Les tools d'un agent se déclarent dans le YAML (`tools: [...]`) et sont résolus au chargement par un registry — plus d'attache code-side (`attach_tools`). Au passage, suppression des scripts démo pré-V3 (code mort, plus jamais utilisé).

## Décisions

| # | Décision | Justification |
|---|----------|---------------|
| 1 | Mécanisme + migration de l'existant (pas mécanisme seul) | Le mécanisme est validé par un consommateur réel (`run_demo_v3` LLM) avant la phase 3 |
| 2 | Suppression des démos pré-V3 (`run_demo.py`, `run_health_check.py`) | Code qui ne sera plus jamais utilisé — décision explicite de Quentin. Résout aussi l'effet de bord « DEMO_AGENTS outillé partout » |
| 3 | `tasks.py` conservé | Consommé par du code V3 (`run_health_check_v3.py` importe `TASK_SECURITY_AUDIT`) et les fixtures dashboard (`tests/dashboard/conftest.py` importe `DEMO_TASKS`). Tombera en phase 3 |
| 4 | `tools` déclaré sans registry → erreur | Pas d'ignore silencieux — cohérent avec « nom inconnu = erreur au chargement » (cadrage Q13) |
| 5 | Doublon dans `tools` → erreur | Config malformée ; des noms de fonction dupliqués côté API OpenAI sont indésirables |

## 1. Mécanisme loader

```python
def load_agents(path: Path, tool_registry: dict[str, ToolDef] | None = None) -> list[Agent]:
```

- YAML : champ **optionnel** `tools: [read_file, grep_codebase]` par agent (`list[str]`).
- Résolution : le loader **pop** `tools` de l'entrée (le type YAML est `list[str]`, pas `list[ToolDef]`), résout chaque nom via `tool_registry`, construit `Agent(..., tools=[ToolDef...])`.
- Erreurs — toutes `ValueError`, cohérentes avec le loader existant :
  - `tools` présent dans le YAML mais `tool_registry=None` → erreur
  - nom absent du registry → erreur nommant le tool ET l'agent, listant les noms disponibles
  - `tools` non-liste, items non-str, ou doublon → erreur
- Rétrocompat : `tools` absent → `tools=[]` (comportement actuel intact) ; registry fourni mais YAML sans `tools` → OK.

## 2. Migration de la démo existante

| Fichier | Changement |
|---------|-----------|
| `src/aaosa/demo/agents.yaml` | Ajout `tools:` par agent, reprenant `_ASSIGNMENT` à l'identique : Backend `[read_file, grep_codebase, run_tests, explain_query_plan]` · Frontend `[read_file, grep_codebase]` · Fullstack `[read_file, run_tests]` · DevOps `[read_file]` |
| `src/aaosa/demo/agents.py` | `DEMO_AGENTS = load_agents(..., tool_registry=TOOLBOX)` (import `aaosa.demo.tools`, même package) |
| `src/aaosa/demo/tools.py` | Suppression `_ASSIGNMENT` + `attach_tools` ; `TOOLBOX` et les fns restent ; docstring mise à jour (l'attache n'est plus programmatique) |
| `src/aaosa/demo/run_demo_v3.py` | Suppression import + appel `attach_tools` (DEMO_AGENTS arrive outillé) |
| `tests/runtime/test_run_with_recovery_llm.py` | Idem — suppression `attach_tools` |

## 3. Nettoyage pré-V3

**Supprimés** :
- `src/aaosa/demo/run_demo.py` (démo V1/V2)
- `src/aaosa/demo/run_health_check.py` (démo health check V2)
- `tests/demo/test_demo_health_check.py`
- Dans `tests/demo/test_demo.py` : les tests de `run_demo`. Les tests de validation `DEMO_TASKS` du même fichier survivent → déplacés vers `tests/demo/test_tasks.py`, `test_demo.py` supprimé.

**Conservés** : `tasks.py` · `run_demo_v3.py` · `run_health_check_v3.py` · `agents.py`/`agents.yaml` · `tools.py` (réduit). Le tout sera remplacé en phase 3 par `demo/incident/`.

**Doc** : CLAUDE.md — « Lancer la démo » pointe vers `run_demo_v3.py` ; mention du nettoyage dans l'état courant.

**Note** : `run_health_check` (la fonction *librairie* V2b dans `aaosa/qa/health_check.py`) n'est PAS touchée — seuls les scripts démo partent.

## 4. Tests / DoD

**TDD loader** (`tests/config/test_loader.py`) :
- résolution OK (agents construits avec les bons `ToolDef`)
- nom inconnu → `ValueError` (message : tool + agent + noms disponibles)
- `tools` déclaré + registry absent → `ValueError`
- rétrocompat : YAML sans `tools` → `tools=[]`, avec et sans registry
- `tools` non-liste / items non-str / doublon → `ValueError`
- `tools: []` explicite → `tools=[]`, pas d'erreur

**Tests démo** (`tests/demo/test_tools.py`) :
- TOOLBOX intact (4 tools)
- tests `attach_tools` supprimés
- nouveau : `DEMO_AGENTS` porte les tools déclarés dans le YAML (mapping par nom d'agent)

**DoD** :
1. Suite complète verte (le total baisse — tests pré-V3 supprimés, assumé)
2. `run_demo_v3` réel LLM tourne avec les tools issus du YAML (tool calls visibles dans la trace)
3. Commit(s) sur une branche dédiée, merge master
