# V3 — Démo phase 5 : campagne N=20 + curation — Design

**Date** : 2026-06-07
**Statut** : validé (3 décisions tranchées par Quentin, design global approuvé)
**Amont** : phase 4 livrée (`70f5a18`, CLI `aaosa` + `classify_run` + `campaign_index.json` crash-safe), capture brainstorm `seconde_brain/raw/brainstorms/2026-06-05-demo-run-propre-complete.md` (cadrage démo), ticket `docs/backlog/2026-06-07-divider-topologie-aggregator.md` (observation N=20 = dernier critère ouvert).
**Aval** : nature C (consomme les exhibits), live mode dashboard (ex-B7, post-démo).

## 1. Objectif

Boucler la démo : exécuter la campagne N=20 réelle, en tirer un rapport de typologie rejouable (`aaosa report`), trancher le ticket aggregator avec les données, et curer les exhibits dans un store versionné rejouable depuis un clone frais. **Zéro changement runtime** — la phase consomme ce que la phase 4 a produit (`campaign_index.json`, vocabulaire 4 valeurs `success/qa_fail/unassigned/error`, labels `classify_run`).

**Lignes rouges héritées du cadrage** (non négociables) :
- Zéro seed — curation = sélectionner des occurrences réelles, jamais provoquer.
- La démo principale doit RÉUSSIR la tâche ; seul roster_gap montre un échec assumé.
- Aucun bouton tourné avant l'observation : température, prompts, tâche-mère restent EXACTEMENT l'état phase 4 pendant la campagne.

## 2. Décisions de design (cette session)

| Question | Décision |
|---|---|
| Forme du rapport de campagne | **CLI `aaosa report`** : commande Typer qui lit `campaign_index.json` + snapshots ELO d'un `--runs-root` → rapport markdown (fichier + console). Fonction pure testable TDD, rejouable sur toute campagne future. |
| Artefact de curation | **Doc + store curé versionné** : `docs/demo/exhibits.md` (sessions retenues par typologie, quoi/comment rejouer) + `runs_demo/` versionné → la démo se rejoue depuis un clone frais via `aaosa dashboard --runs-root runs_demo`. Intrant direct nature C. |
| ELO de départ de la campagne | **ELO YAML, zéro historique** : root frais sans `latest.json` → le roster démarre aux ELO d'`agents.yaml` (versionné = « snapshot de départ versionné » du brainstorm Q10). La courbe dashboard raconte « 20 incidents, de l'état initial à l'état appris ». |
| Décision aggregator si zéro sur N=20 | **Checkpoint humain, pas de pré-commit** : la spec ne choisit pas entre les 3 options du ticket (tâche-mère moins séquentielle · température divider · assumer « filet rare ») — la décision a besoin des données (ex. : les chaînes sont-elles encore toutes pures ?). |
| Séquencement | **Outillage d'abord** (approche A) : `aaosa report` en TDD sur fixtures synthétiques (contrats d'entrée stables depuis la phase 4), puis la campagne — l'étape coûteuse — tourne une seule fois, dépouillée par l'outil. |

**Hors scope explicite** : badge typologie au dashboard · commande `aaosa curate` (la curation est un geste humain unique, 3-5 sessions à copier — YAGNI) · live mode (post-démo) · D5 QA-aggregator (re-déferré phase 4, cette campagne fournit justement ses données) · toute retouche prompts/runtime — même si la campagne donne zéro aggregator, la décision se prend au checkpoint, pas en douce dans cette phase · ticket dataflow-edges (chantier dashboard, reste au backlog).

## 3. Layout

```
src/aaosa/cli/
├── app.py             # + commande `report` (wiring : lecture fichiers, écriture, echo)
└── report.py          # NOUVEAU : build_report(index, snapshots) -> str (pur, zéro print/I/O)

tests/cli/
└── test_report.py     # NOUVEAU : build_report sur index synthétiques + wiring Typer

runs_demo/             # NOUVEAU (versionné — aucun pattern .gitignore ne le couvre)
docs/demo/exhibits.md  # NOUVEAU (doc de curation, versionné)
runs_campaign_n20/     # store de la campagne (gitignoré par runs_campaign*/)
```

## 4. `aaosa report`

```
aaosa report [--runs-root runs]
```

- **`build_report(index: CampaignIndex, snapshots: list[EloSnapshot]) -> str`** (`src/aaosa/cli/report.py`) : fonction pure, zéro print, zéro I/O — même contrat de testabilité que `incident_runs.py`. Réutilise les modèles Pydantic existants (`CampaignIndex`, `CampaignRunRecord`, `EloSnapshot`).
- **Wiring `app.py`** : lit `runs_root/campaign_index.json` (absent → `typer.Exit(code=1)`, message nommant le chemin attendu) + `runs_root/elo_snapshots/*.json` triés par nom, `latest.json` exclu (même règle que `_elo_history` du dashboard). Écrit `runs_root/campaign_report.md` et echo le rapport en console.

**Sections du rapport** (markdown) :

1. **En-tête** : scénario, n_requested, n exécutés, période (premier `started_at` → dernier `ended_at`).
2. **Outcomes** : counts + % des 4 valeurs `success / qa_fail / unassigned / error`.
3. **Typologies** : counts par label `classify_run` (ordre canonique : `simple`/`divided` · `recursion` · `roster_gap` · `diagnosed:<attribution>` · `aggregated`).
4. **Observation aggregator** (section explicite, nommée) : count `aggregated` sur N — c'est le critère du ticket divider, le rapport le met en évidence au lieu de le noyer dans les stats.
5. **Table par run** : i, session_id, outcome, typologies, durée. Runs `error` (session_id `None`) rendus proprement (`—` + message d'erreur tronqué).
6. **Delta ELO** : par agent/tag, premier → dernier snapshot. <2 snapshots → section dégradée annoncée (« delta indisponible »), jamais d'exception. Les courbes complètes restent au dashboard (pointeur).
7. **Rejeu** : commande `aaosa dashboard --runs-root <root>` prête à copier.

## 5. Campagne N=20 (exécution réelle)

```
aaosa campaign --n 20 --scenario main --runs-root runs_campaign_n20
```

- **Root frais** (garde-fou `ensure_empty_store` existant) **sans `latest.json`** → départ ELO YAML (décision §2).
- **`main` seul** : `roster_gap` est systématique et déjà démontré en live — une campagne n'apprendrait rien.
- **gpt-4o-mini, température inchangée, prompts inchangés** : décision phase 4 conservée — on observe, on ne tourne aucun bouton.
- Coût : ~20 runs gpt-4o-mini, négligeable (acquis brainstorm Q15).
- Crash/`Ctrl-C` : l'index est crash-safe (réécrit après chaque run) ; une reprise = nouveau root frais, pas de reprise partielle (le garde-fou refuse le root peuplé — comportement existant, assumé).

## 6. Checkpoint humain : dépouillement + ticket aggregator

Post-campagne, dépouillement ensemble, rapport en main :

- **≥1 run `aggregated`** → critère d'acceptation du ticket atteint : ticket clos, l'exhibit aggregator existe pour la curation.
- **0 sur N=20** → trancher ensemble entre les 3 options consignées au ticket (tâche-mère moins séquentielle · température divider · assumer « aggregator = filet pour les vrais fan-ins, rare par nature »). Décision loggée au ticket + `decisions/log.md` ; toute retouche éventuelle qui en découle = chantier séparé, hors phase 5.

Le checkpoint balaie aussi la récolte D3/D4 (`diagnosed:*`) et `recursion` pour la curation (§7).

## 7. Curation → store versionné

**`runs_demo/`** (racine repo, versionné) — contenu :

- `sessions/<id>/` : les sessions sélectionnées (3-5, une par typologie exhibée), copiées telles quelles depuis `runs_campaign_n20/` (et/ou `runs/` si un exhibit vient d'un run unitaire, ex. roster_gap).
- `agents/registry.json` : copié du store de campagne (les modals agents du dashboard en dépendent).
- `elo_snapshots/` : **les 20 snapshots complets** + `latest.json` — les courbes « le roster après 20 incidents » ont besoin de toute la série, pas seulement des sessions curées.
- `campaign_index.json` + `campaign_report.md` : la donnée brute et le rapport font partie de l'artefact portfolio.

Copie **manuelle documentée** (commandes consignées dans le doc d'exhibits) — pas d'outillage dédié (YAGNI, geste unique).

**`docs/demo/exhibits.md`** (versionné) : par exhibit — session_id, typologie(s), ce que le run montre (2-3 phrases orientées narration démo), commande de rejeu. Règles :

- Gérer l'absence honnêtement : si zéro `diagnosed:*` ou `aggregated` naturel sur N=20 → l'écrire (« non observé sur N=20 »), ne JAMAIS seeder pour combler (ligne rouge). L'open flag du brainstorm s'applique : relancer des campagnes plus tard est non bloquant.
- Rejeu clone frais : `aaosa dashboard --runs-root runs_demo` — vérifié au DoD.

## 8. Tests (TDD, zéro LLM) et DoD

**TDD** :
- `build_report` : index synthétiques (outcomes mixtes · runs `error` sans session_id · typologies rares · combinaisons), snapshots 0/1/N (section delta dégradée sans exception), présence des 7 sections, observation aggregator correcte (0 et ≥1), déterminisme (même input → même output).
- Wiring Typer (`CliRunner`) : `report` sans `campaign_index.json` → exit 1 + message ; cas nominal sur fixtures tmp_path → fichier écrit + echo.

**DoD réel (checkpoint humain, gpt-4o-mini)** :
1. Campagne N=20 complète : `campaign_index.json` à 20 entrées sur `runs_campaign_n20/`.
2. `aaosa report --runs-root runs_campaign_n20` → rapport complet, fidèle à l'index (spot-check).
3. Dépouillement + **décision aggregator loggée** (ticket mis à jour : clos, ou option choisie).
4. Curation : `runs_demo/` peuplé + `docs/demo/exhibits.md` écrit, **rejeu navigateur des 3 typologies sign-offé** (divided-success + roster_gap + 1 curée selon récolte : recursion / diagnosed / aggregated).
5. `aaosa dashboard --runs-root runs_demo` rend les exhibits (test du chemin clone frais).
6. Tickets backlog + CLAUDE.md à jour.

## 9. Risques et limites assumées

- **Récolte non garantie** : N=20 à temp 0 sur la même tâche peut ne produire ni `diagnosed:*` ni `aggregated` ni `recursion` en dehors de la variance ELO/LLM. La curation documente l'absence (ligne rouge zéro seed) ; exhibit D3 = bonus non bloquant (acquis brainstorm Q14).
- **`runs_demo/` versionne des outputs LLM** : traces JSONL petites, contenu 100 % fictif (monde simulé) — assumable. Pas de données sensibles par construction.
- **Copie manuelle de curation** : non rejouable automatiquement — assumé, geste unique documenté dans `exhibits.md`.
- **Rapport markdown statique** : pas de graphiques (les courbes ELO vivent au dashboard, le rapport pointe dessus).
- **Statu quo phase 4 reconduits** (notés pour cette spec, examinés, assumés) : écriture d'index non atomique (YAGNI, le rapport ne fait que lire) · `SessionMeta.outcome` grossier (`_META_OUTCOME["success"] = "divided"` ment sur un run simple — la trace est la vérité, le rapport lit l'index et `classify_run`, jamais les meta) · `print_timeline` ne rend ni roster_gap ni tool calls (matière live mode, hors scope).
