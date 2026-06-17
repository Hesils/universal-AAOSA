# Backlog — `load_roster` : collision de nom de module importlib si deux rosters partagent un basename

**Découvert** : 2026-06-17, revue finale whole-branch du ticket erd (`aaosa solve`).
**Constat** : latent, non exercé par les tests. `load_rosters([...])` charge chaque `tools.py` via importlib en nommant le module `_roster_tools_{directory.name}`. Si deux dossiers roster injectés partagent le même basename (ex. `a/tools` et `b/tools`, ou deux dossiers `jouet` sous des racines différentes), les deux imports réutilisent la **même clé `sys.modules`** → le second `exec_module` tourne sur l'objet module déjà en cache et le second roster récupère **silencieusement le `TOOL_REGISTRY` du premier**. Mêmes outils mal résolus, sans erreur.

## Diagnostic (complet, pas de recherche à refaire)

Chemin :
1. `_load_tool_registry` (`src/aaosa/config/roster.py:21`) : `spec = importlib.util.spec_from_file_location(f"_roster_tools_{directory.name}", tools_path)`. Le nom de module ne dépend que du **basename** du dossier, pas du chemin complet.
2. `importlib` enregistre le module sous ce nom. Sur deux rosters de même basename, le cache (`sys.modules`) renvoie le premier ; le code du second n'a pas d'effet observable sur le registre exposé.
3. Pas de crash : l'agent du second roster déclarant `tools: [x]` résout `x` contre le registre du premier → soit `x` existe par coïncidence (mauvais outil), soit `ValueError` tardive « tool inconnu » trompeuse.

Non exercé par erd (démo = un seul roster ; les tests `test_load_rosters_*` utilisent des basenames distincts `ra`/`rb`). Devient vivant **dès que l'AIOS (fqd) injecte plusieurs rosters réels** dont les dossiers peuvent partager un basename.

## Fix proposé (1 ligne, low-risk)

Clé de module dérivée du **chemin résolu**, pas du basename :

```python
mod_name = f"_roster_tools_{tools_path.resolve().as_posix().replace('/', '_').replace(':', '')}"
spec = importlib.util.spec_from_file_location(mod_name, tools_path)
```

(ou `f"_roster_tools_{abs(hash(tools_path.resolve()))}"`). Garantit l'unicité par chemin.

## Critères d'acceptation

- [ ] Test rouge : deux rosters de même basename, `tools.py` exposant des registres différents → chaque agent résout l'outil de SON roster.
- [ ] Fix appliqué ; les 7 tests `test_roster.py` existants restent verts.
- [ ] (si pertinent) note de cloisonnement dans le docstring de `roster.py`.

## Pointeurs

- Source : `src/aaosa/config/roster.py:21` (`_load_tool_registry`, `spec_from_file_location`).
- Tests : `tests/config/test_roster.py` (`test_load_rosters_merges_and_detects_name_collision` — étendre).
- Contexte : ticket erd, plan `docs/superpowers/plans/2026-06-17-erd-cli-solve.md` (Task 1).
- Consommateur futur : injection multi-rosters côté AIOS (fqd).
