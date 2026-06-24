# V3 — Épique A1 — Agents par config

- **Couche** : `src/aaosa/` (nouveau `config/`) + `src/aaosa/demo/`
- **Statut** : deep-dive terminé → prêt pour plan + exécution
- **Dépendances** : aucune. **Premier point d'entrée V3.**
- **Roadmap** : `AIOS\context\projects\universal-AAOSA\roadmap.md` — section V3, épique A1

---

## Contexte

`src/aaosa/demo/agents.py` définit 4 agents hardcodés (`AGENT_FRONTEND`, `AGENT_BACKEND`,
`AGENT_DEVOPS`, `AGENT_FULLSTACK`) et une liste `DEMO_AGENTS`. Changer les agents = modifier le
code Python. Un domaine alternatif (A2) est impossible sans ce loader.

Cette épique extrait la définition des agents dans un fichier de config (YAML) et fournit un
loader réutilisable dans tout le runtime.

---

## Décisions

| Question | Décision | Justification |
|---|---|---|
| Format de config | YAML | Lisible humain, commentaires natifs, standard pour la config déclarative |
| Emplacement loader | `src/aaosa/config/loader.py` | Nouveau package `config/` — concern distinct de `demo/` et `runtime/` |
| Schema de désérialisation | `Agent` directement (`id` a `default_factory`) | Pas de modèle intermédiaire — `Agent(**{name,tags_with_elo,system_prompt})` suffit |
| Rétrocompat `DEMO_AGENTS` | Conservé — `demo/agents.py` l'expose toujours | Importé partout (tests, run_demo) — ne pas casser les imports existants |
| Constantes nommées (`AGENT_FRONTEND` etc.) | Supprimées du module | Elles sont couplées au domaine logiciel — un domaine alternatif n'a pas ces noms. Les tests qui en dépendent sont mis à jour (accès par index ou nom). |
| Config demo | `src/aaosa/demo/agents.yaml` | Colocalisée avec la démo, chemin résolu via `Path(__file__).parent` |
| Erreur malformé | `ValueError` avec message lisible | La validation Pydantic est suffisante — pas besoin d'une exception custom |
| Tasks | Hors scope A1 | `DEMO_TASKS` reste hardcodé — A1 = agents uniquement |

---

## Seams confirmés

| Fichier | État actuel | Ce qui change |
|---|---|---|
| `src/aaosa/demo/agents.py` | 4 constantes + `DEMO_AGENTS` hardcodés | Remplacé par `load_agents(...)` → `DEMO_AGENTS`. Constantes nommées supprimées. |
| `src/aaosa/demo/agents.yaml` | n'existe pas | Créé avec les 4 agents actuels (valeurs identiques) |
| `src/aaosa/config/__init__.py` | n'existe pas | Créé vide |
| `src/aaosa/config/loader.py` | n'existe pas | `load_agents(path: Path) -> list[Agent]` |
| `tests/demo/test_agents.py` | Importe `AGENT_FRONTEND` etc. | Mis à jour — accès par `DEMO_AGENTS[i]` ou `{a.name: a for a in DEMO_AGENTS}` |
| `tests/demo/test_demo.py` | Importe `AGENT_FRONTEND`, `AGENT_BACKEND`, `AGENT_FULLSTACK` | Mis à jour idem |
| `src/aaosa/runtime/runner.py` | Non touché | `run_task(task, agents, ...)` accepte déjà `list[Agent]` — inchangé |
| `src/aaosa/demo/run_demo.py` | Importe `DEMO_AGENTS` | Inchangé — `DEMO_AGENTS` est toujours exporté |

---

## API du loader

```python
# src/aaosa/config/loader.py
from pathlib import Path
from aaosa.core.agent import Agent

def load_agents(path: Path) -> list[Agent]:
    """Charge une liste d'agents depuis un fichier YAML.
    
    Chaque entrée YAML doit avoir : name, tags_with_elo, system_prompt.
    Le champ id est généré automatiquement (default_factory uuid4).
    Lève ValueError si le fichier est absent, malformé, ou invalide Pydantic.
    """
```

Format YAML attendu :

```yaml
- name: Frontend
  tags_with_elo:
    frontend: 85
    css: 90
    javascript: 80
    testing: 40
  system_prompt: "You are a frontend specialist focused on UI, CSS, and JavaScript."

- name: Backend
  tags_with_elo:
    backend: 90
    database: 85
    python: 80
    testing: 50
  system_prompt: "You are a backend specialist..."
```

---

## Nouveau `demo/agents.py` (après A1)

```python
from pathlib import Path
from aaosa.config.loader import load_agents

DEMO_AGENTS = load_agents(Path(__file__).parent / "agents.yaml")
```

Propre, aucune constante nommée. Les tests qui dépendent des constantes accèdent les agents par nom :

```python
_by_name = {a.name: a for a in DEMO_AGENTS}
AGENT_FRONTEND = _by_name["Frontend"]  # dans les tests uniquement, si nécessaire
```

---

## Stratégie de test (TDD)

**Nouveaux tests** — `tests/config/test_loader.py` :
- `test_load_agents_valid` : fichier YAML valide → `list[Agent]` correctement populé (noms, tags, prompts)
- `test_load_agents_missing_file` : `ValueError` si le chemin n'existe pas
- `test_load_agents_malformed_yaml` : `ValueError` si le YAML est syntaxiquement invalide
- `test_load_agents_pydantic_invalid` : `ValueError` si un champ Pydantic est invalide (ex. `tags_with_elo: {}`)
- `test_load_agents_ids_unique` : chaque agent chargé a un `id` UUID unique
- `test_load_agents_empty_list` : fichier `[]` → retourne `[]` sans erreur

**Mise à jour** — `tests/demo/test_agents.py` :
- Supprimer les imports `AGENT_FRONTEND`, `AGENT_BACKEND`, etc.
- Remplacer par accès par nom depuis `DEMO_AGENTS`
- Conserver la logique (tags values, system_prompt non-empty, ids uniques)

**Mise à jour** — `tests/demo/test_demo.py` :
- Idem pour les imports de constantes nommées
- Les patchs `Agent.claim` / `Agent.execute` restent inchangés (ils patchent la méthode, pas l'instance)

**Non-régression** : la suite complète (588 tests) doit passer sans modification hors les 3 fichiers tests cités.

---

## Critères de done

- [ ] `src/aaosa/config/__init__.py` + `loader.py` créés
- [ ] `src/aaosa/demo/agents.yaml` créé (4 agents, valeurs identiques aux constantes supprimées)
- [ ] `src/aaosa/demo/agents.py` réduit au loader — `DEMO_AGENTS` exporté, constantes nommées supprimées
- [ ] `tests/config/test_loader.py` : 6 tests, tous verts
- [ ] `tests/demo/test_agents.py` et `test_demo.py` mis à jour — aucune importation de constante nommée
- [ ] Suite complète ≥ 588 + 6 = **594 tests verts**
- [ ] `run_demo.py` tourne end-to-end sans erreur (validation manuelle)

---

## Questions tranchées ici (pas à redécider au plan)

1. **`id` dans le YAML ?** Non — généré à la volée. `name` est le stable identifier (comme ELO snapshot).
2. **Loader async ?** Non — lecture fichier synchrone, context V1/V2 n'est pas async.
3. **Support JSON en plus de YAML ?** Non — YAML suffit, JSON = cas particulier de YAML si besoin.
4. **`load_tasks` en parallèle ?** Hors scope A1 — tasks restent hardcodées.
5. **Valider que `tags_with_elo` values ∈ [1,95] ?** Non — `Agent` ne le valide pas aujourd'hui, A1 n'ajoute pas cette contrainte (YAGNI).
