# V3 — Démo phase 4 : CLI `aaosa` (Typer, projet-wide) — Design

**Date** : 2026-06-07
**Statut** : validé (décisions tranchées une à une par Quentin, design global approuvé)
**Amont** : capture brainstorm `seconde_brain/raw/brainstorms/2026-06-05-demo-run-propre-complete.md` (cadrage démo), phase 3 livrée (`6dfa9dd`, `demo/incident/` + `run_incident.py` jetable), tickets backlog `docs/backlog/2026-06-07-*.md` (intrants directs).
**Aval** : phase 5 (campagne N=20 + curation, consomme l'index de campagne), puis live mode dashboard (ex-B7) et nature C.

## 1. Objectif

Remplacer le script jetable `run_incident.py` par un CLI Typer projet-wide : `aaosa`, entrée unique de tous les points d'exécution (démo incident, campagne, dashboard, health check). La phase 4 tranche aussi le ticket divider/topologie (les prompts migrent vers le CLI — c'est le moment décidé en phase 3) et outille la phase 5 (index de campagne + classification de typologie).

**Lignes rouges héritées du cadrage** (non négociables) :
- Zéro seed — tous les runs sont 100 % naturels. `run_with_recovery` directement, jamais de division forcée (thèse D1).
- La démo principale doit RÉUSSIR la tâche. Seul roster_gap montre un échec assumé.
- Garde-fou campagne : refus explicite si le store est déjà peuplé, jamais de cleanup auto (brainstorm Q13).

## 2. Décisions de design (cette session)

| Question | Décision |
|---|---|
| Ticket divider (chaînes pures → aggregator jamais sollicité) | **Retirer la consigne synthèse** et adoucir « ordered » : le divider décide librement de la topologie → des découpes auront des sinks par domaine → l'aggregator D2 devient démontrable, graphes variés pour la campagne. Risque assumé : la synthèse sort du roster (plus de QA/ELO dessus). |
| QA de l'output aggregator (trou qualité du ticket) | **Re-déferré explicitement en D5.** Phase 4 = chantier CLI, zéro changement runtime. La campagne phase 5 fournira les données (fréquence réelle des agrégations, qualité perçue) pour trancher D5. Ticket backlog mis à jour. |
| Frontière 4/5 sur `campaign` | Phase 4 livre la **mécanique + classification minimale** : N runs séquentiels, ELO chaîné, garde-fou, index JSON par run (outcome + typologies détectées depuis la trace). La curation et le rapport présentable = phase 5, qui consomme l'index. |
| Forme du CLI | **Typer, projet-wide** (choix Quentin — pas limité à la démo : tous les points d'entrée du projet). Dépendance nouvelle `typer` (dernière stable), console script `aaosa` via `[project.scripts]`. |
| Arborescence | **Plate, orientée action** : `aaosa run` · `aaosa campaign` · `aaosa dashboard` · `aaosa health-check`. La démo incident EST la démo du projet — pas de namespace `demo incident`. |
| Scripts v3 existants | `run_demo_v3.py` **supprimé avec ses tests** (subsumé par la démo incident : même mécanique division + tools + AdaptiveSpecEvaluator, et il contredit la thèse D1 en forçant la division). `aaosa health-check` **enveloppe `run_demo_health_check_v3()` telle quelle** (roster software + seed B2/B3 intacts — ils démontrent la boucle auto-amélioration, indépendante de l'incident). `demo/tasks.py` reste (consommé par le health check + fixtures dashboard). |
| Persistance ELO | **Load au démarrage, `run` ET `campaign`** : charger `runs_root/elo_snapshots/latest.json` s'il existe, `apply_snapshot` par nom sur le roster frais, sauver après chaque run. Un `aaosa run` isolé contribue à la même histoire ELO que la campagne. Rejouer depuis zéro = `--runs-root` frais. |
| Architecture module | Package **`src/aaosa/cli/`** (`app.py` + `incident_runs.py`), prompts dans **`demo/incident/prompts.py`** (single home), classification dans **`tracing/analysis.py`** (elle opère sur des events — réutilisable par le dashboard). |

**Hors scope explicite** : ticket dataflow-edges dashboard (chantier dashboard, reste au backlog) · rapport de campagne formaté + courbes ELO (phase 5) · live mode (post-démo) · flag `--model` (gpt-4o-mini constaté suffisant, montée en gamme = changement manuel si besoin).

## 3. Layout

```
src/aaosa/cli/
├── __init__.py
├── app.py             # Typer app : run · campaign · dashboard · health-check (wiring fin)
└── incident_runs.py   # helpers partagés run/campaign (contexte, ELO, persistance, garde-fou)

src/aaosa/demo/incident/
├── prompts.py          # NOUVEAU : DIVIDER_PROMPT (réécrit) · AGGREGATOR_PROMPT · TAGGER_PROMPT
└── run_incident.py     # SUPPRIMÉ (remplacé par le CLI — destin déclaré en phase 3)

src/aaosa/demo/
├── run_demo_v3.py      # SUPPRIMÉ avec ses tests
└── run_health_check_v3.py  # conservé tel quel, appelé par `aaosa health-check`

src/aaosa/tracing/analysis.py   # + classify_run(events) -> list[str]

tests/cli/              # NOUVEAU : test_app.py · test_incident_runs.py
tests/tracing/test_analysis.py  # + tests classify_run

pyproject.toml          # + typer (dernière stable) · [project.scripts] aaosa = "aaosa.cli.app:app"
```

`uv.lock` mis à jour et commité dans le même mouvement que l'ajout de `typer` (leçon phase 2 : désync lock).

## 4. Commandes

### 4.1 `aaosa run`

```
aaosa run [--scenario main|roster_gap] [--runs-root runs]
```

Reprend la mécanique de `run_incident.py` (build roster → `RunContext` → `run_with_recovery` → timeline → persistance session + registry + snapshot ELO) avec deux changements :

1. **ELO load au démarrage** : si `runs_root/elo_snapshots/latest.json` existe → `load_snapshot` + `apply_snapshot` sur le roster frais (matching par nom — les noms absents du roster sont ignorés, comportement V2a existant, compatible roster_gap).
2. **Prompts importés de `demo/incident/prompts.py`** — divider réécrit (§6).

Console sobre (acquis brainstorm) : scénario + taille roster, description de la tâche, outcome, `print_timeline`, chemins persistés. `--scenario` = enum Typer (`main` par défaut), `--runs-root` = `Path` (défaut `runs`).

### 4.2 `aaosa campaign`

```
aaosa campaign --n 20 [--scenario main|roster_gap] [--runs-root runs]
```

- `--n` **obligatoire** (une campagne coûte des appels LLM — pas de défaut silencieux).
- **Garde-fou store non vide** : si `runs_root/sessions/` contient ≥1 session → refus explicite (`typer.Exit(code=1)`) avec message nommant le chemin peuplé et suggérant un `--runs-root` frais. Vérifié une fois au démarrage (les sessions écrites par la campagne elle-même ne re-déclenchent pas le garde-fou).
- **Boucle** : N exécutions séquentielles du scénario dans le même process. Chaque itération = un run complet identique à `aaosa run` (roster frais + ELO appliqué depuis `latest.json`, session persistée, snapshot sauvé) → l'ELO se chaîne de run en run par les snapshots.
- **Containment** : une exception d'un run n'avorte pas la campagne — l'itération est enregistrée `outcome="error"` (message court dans l'index) et la boucle continue.
- **Index de campagne** : `runs_root/campaign_index.json`, réécrit après **chaque** run (crash-safe — un Ctrl-C ne perd que le run en cours) :

```json
{
  "scenario": "main",
  "n_requested": 20,
  "runs": [
    {
      "i": 1,
      "session_id": "2026-06-07T18-02-11-ab34cd56",
      "outcome": "divided",
      "typologies": ["divided", "aggregated"],
      "started_at": "...", "ended_at": "..."
    }
  ]
}
```

`outcome` de l'index = **`success` / `unassigned` / `error`** (dérivé du type de retour : `Output` → success, `DispatchResult` → unassigned, exception → error) — le chemin réel (simple/divisé/récursif) vit dans `typologies` = `classify_run(tracer.events)` (§5). `SessionMeta.outcome` garde son comportement actuel (pas de changement de la couche store). La phase 5 consomme cet index pour la curation.

### 4.3 `aaosa dashboard`

```
aaosa dashboard [--port 5000]
```

Équivalent exact de `python -m dashboard` : `create_app(DashboardConfig())` + serveur dev Flask (`debug=True`). `--port` surcharge `cfg.port` ; le reste de la config ne bouge pas. `dashboard/__main__.py` reste en place (zéro régression d'usage).

### 4.4 `aaosa health-check`

```
aaosa health-check
```

Wrapper mince : `load_dotenv()` + appel de `run_demo_health_check_v3()` (import depuis `aaosa.demo.run_health_check_v3`, fonction existante, intacte). Démontre la boucle B2 → B3 → re-triage sur le roster software — indépendant de la démo incident, conservé tel quel.

## 5. `classify_run` (`tracing/analysis.py`, fonction pure)

```python
def classify_run(events: Sequence[ClaimEvent]) -> list[str]
```

Labels détectés depuis la trace, retournés dans un ordre canonique fixe (déterministe) :

| Label | Condition |
|---|---|
| `simple` | aucun `TaskDividedEvent` |
| `divided` | ≥1 `TaskDividedEvent` |
| `recursion` | un `TaskDividedEvent.task_id` apparaît dans les `sub_tasks` d'un autre `TaskDividedEvent` (division imbriquée, D1 récursif) |
| `roster_gap` | ≥1 `RosterGapEvent` |
| `diagnosed:<attribution>` | un label par valeur distincte de `DiagnosedEvent.attribution` rencontrée (`agent`/`evaluator`/`task_spec`/`unattributed`) |
| `aggregated` | ≥1 `TaskAggregatedEvent` (agrégation réelle — le court-circuit 1-sink n'émet pas d'event, règle D2) |

`simple` et `divided` sont mutuellement exclusifs ; les autres se cumulent. Fonction pure sans I/O, même famille que les helpers existants d'`analysis.py` — réutilisable par le dashboard plus tard (badge typologie sur les sessions).

## 6. Prompts (`demo/incident/prompts.py`)

Single home des trois prompts système (l'unique consommateur restant est le CLI — `run_demo_v3.py` supprimé). Aggregator et tagger migrent tels quels depuis `run_incident.py`. **Divider réécrit** (résolution du ticket topologie) :

```python
DIVIDER_PROMPT = (
    "You are a task decomposer. Break the task into the minimal set of "
    "sub-tasks needed to fully resolve it. Express a dependency between two "
    "sub-tasks only when one genuinely needs the other's output. Prefer few, "
    "well-scoped sub-tasks."
)
```

Disparus : « include a final synthesis sub-task » (garantissait un consommateur terminal unique — découpe hardcodée en tension avec « le graphe émerge ») et « ordered » (poussait vers le strictement séquentiel). Le divider décide librement → des découpes produiront ≥2 sinks → l'aggregator D2 tourne et la paire DIVIDER/AGGREGATOR apparaît au dashboard.

**Critère du ticket** (acceptation) : observer ≥1 run réel avec `TaskAggregatedEvent` dans la trace et nœud AGGREGATOR au dashboard. La topologie étant émergente, ce n'est pas garanti par run — le DoD l'observe sur une mini-campagne (§8) ; si zéro occurrence sur n≈5, constat documenté dans le ticket, la N=20 de phase 5 tranche, on n'inverse pas la décision.

## 7. `incident_runs.py` (helpers partagés)

- `run_once(scenario: str, runs_root: Path, client) -> RunOutcome` : crée session_id + tracer, build roster (`_ROSTERS` migré de `run_incident.py`) → ELO load/apply → `RunContext` (divider/aggregator/tagger depuis `prompts.py`, `AdaptiveSpecEvaluator(client)`) → `run_with_recovery` → persistance (registry, session, snapshot). Retourne un petit objet (outcome success/unassigned, session_dir, events) consommé par `run` et `campaign`.
- `ensure_empty_store(runs_root: Path) -> None` : garde-fou — lève/`typer.Exit` si `runs_root/sessions/` est peuplé.
- Le wiring console (echo, timeline) reste dans `app.py` — les helpers ne printent pas (testables sans capture).

## 8. Tests (TDD) et DoD

**TDD (zéro LLM, comme toujours)** :
- `classify_run` : traces synthétiques par typologie (simple, divided, recursion imbriquée, roster_gap, diagnosed par attribution, aggregated, combinaisons) + ordre canonique stable.
- `ensure_empty_store` : tmp_path vide → OK ; avec une session → refus.
- ELO : roundtrip load/apply/save sur roster frais ; `latest.json` absent → ELO YAML intacts ; roster_gap (nom absent du snapshot) → pas d'erreur.
- Boucle campaign : runner stubbé (monkeypatch `run_once`) — compte les itérations, index écrit après chaque run, une exception d'un run n'avorte pas (entrée `error` + la boucle continue).
- Parsing Typer (`typer.testing.CliRunner`) : les 4 commandes wirées sur stubs — `--scenario` invalide rejeté, `--n` obligatoire, exit codes.

**DoD réel (checkpoint humain, gpt-4o-mini)** :
1. `aaosa run --scenario main` → la tâche réussit (un `Output` est retourné, QA PASS — chemin simple ou divisé, peu importe : il émerge).
2. `aaosa run --scenario roster_gap` → `RosterGapEvent` émis.
3. **Mini-campagne réelle `aaosa campaign --n 5 --runs-root <frais>`** : garde-fou vérifié (relance sur le même root → refus), index complet, ELO chaîné (snapshots successifs distincts), et observation aggregator (§6).
4. `aaosa dashboard` rend les sessions de la campagne ; `aaosa health-check` tourne.
5. Tickets backlog mis à jour : divider (tranché + résultat d'observation), QA-aggregator (re-déferré D5 explicite). CLAUDE.md à jour.

## 9. Risques et limites assumées

- **Aggregator non garanti par run** : topologie émergente — le DoD observe, ne force pas (zéro seed). Si la campagne phase 5 n'en produit aucun, retour au ticket en connaissance de cause.
- **Synthèse hors roster** : quand l'aggregator synthétise, son output n'est ni QA-évalué ni ELO-tracké (trou D5, re-déferré explicitement — données de campagne d'abord).
- **`campaign_index.json` réécrit en entier à chaque run** : O(N) par écriture, négligeable à N=20 ; pas de format append-only prématuré (YAGNI).
- **`aaosa dashboard` = serveur dev Flask** : statu quo assumé (outil local de démo, pas de prod).
