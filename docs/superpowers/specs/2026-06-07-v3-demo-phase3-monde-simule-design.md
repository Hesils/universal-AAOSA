# V3 — Démo phase 3 : monde simulé + roster incident — Design

**Date** : 2026-06-07
**Statut** : validé (sections 1-4 approuvées une à une par Quentin)
**Amont** : capture brainstorm `seconde_brain/raw/brainstorms/2026-06-05-demo-run-propre-complete.md` (source de vérité du cadrage démo), phase 2 livrée (`2201e98`, tools YAML via `tool_registry`).
**Aval** : phase 4 (CLI `run`/`campaign`), phase 5 (campagne + curation).

## 1. Objectif

Construire le package `src/aaosa/demo/incident/` : un monde simulé cohérent (fuite de données clients), un roster 7 agents / 3 domaines, les tools qui interrogent le monde, les scénarios (principal + roster_gap) et un script de validation jetable. C'est le socle de la démo portfolio — la tâche cross-domain dont le graphe émerge du claiming.

**Lignes rouges héritées du cadrage** (non négociables) :
- Zéro seed — tous les runs sont 100 % naturels. `run_with_recovery` directement, jamais de division forcée (thèse D1).
- La démo principale doit RÉUSSIR la tâche. Seul roster_gap montre un échec assumé.
- Cross-domain obligatoire (ingénierie + juridique/RGPD + communication).

## 2. Décisions de design (cette session)

| Question | Décision |
|---|---|
| Frontière phase 3/4 | Phase 3 livre un **script minimal jetable** (`run_incident.py`, pattern `run_demo_v3.py`) pour le DoD en run réel. Le CLI propre (phase 4) le remplacera. |
| Forme du monde | **Fichiers data versionnés** dans `world/` (JSONL, SQL, JSON, markdown). Les tools sont des fonctions pures qui lisent/filtrent ces fichiers. Le monde est un artefact de démo montrable. |
| Démo logicielle existante | **Intacte à côté** : `demo/agents.yaml`, `tools.py`, `run_demo_v3.py`, `run_health_check_v3.py` ne bougent pas (`run_health_check_v3` dépend du roster actuel). Sort décidé en phase 4. |
| Couplage tools ↔ monde | **Loaders purs `lru_cache` dans `world.py` + `TOOLBOX` au niveau module** dans `tools.py` — symétrie exacte avec le pattern phase 2 (`load_agents(…, tool_registry=TOOLBOX)`). Pas de factory : un seul monde, déterministe, versionné. |

Acquis du brainstorm réutilisés sans re-trancher : roster 7 agents (Q8), monde simulé + doc-search juriste (Q9), AdaptiveSpecEvaluator + ELO persistant (Q10), tâche fuite de données task-first (Q7), gpt-4o-mini (Q12), asymétrie de réalisme assumée (tech = monde riche, juridique = doc-search corpus, comm = raisonnement pur).

## 3. Layout

```
src/aaosa/demo/incident/
├── __init__.py
├── world/                      # fichiers data versionnés
│   ├── access_logs.jsonl       # ~350 entrées / 48h, exfiltration noyée dans le bruit
│   ├── db_schema.sql           # DDL : customers (PII), users, api_tokens, audit…
│   ├── customers.json          # métadonnées (total: 4217, champs) + échantillon factice
│   ├── cve_bulletins.json      # 3 bulletins dont 1 pertinent (2 = bruit)
│   └── docs/                   # corpus juriste : 5 docs markdown
├── world.py                    # loaders purs lru_cache
├── tools.py                    # TOOLBOX incident (6 tools)
├── agents.yaml                 # 7 agents, tools déclarés (pattern phase 2)
├── agents.py                   # INCIDENT_AGENTS = load_agents(..., tool_registry=TOOLBOX)
├── scenarios.py                # Task principale + rosters (full / roster_gap)
└── run_incident.py             # script de validation jetable (remplacé par le CLI phase 4)

tests/demo/incident/            # miroir : test_world.py · test_tools.py · test_agents.py · test_scenarios.py
```

## 4. Narrative de l'incident (cohérence du monde)

La fuite doit être *trouvable* en croisant les sources — c'est le monde qui répond, jamais un stub flatteur.

- **CVE-2026-21804** : bypass d'auth dans la lib `fastjwt 2.3.x`. Le bulletin pertinent est dans `cve_bulletins.json` ; le schéma DB note la stack (dont `fastjwt 2.3.1`) en commentaire d'en-tête. Les 2 autres bulletins concernent des libs non utilisées (bruit).
- **Exfiltration** : l'IP `185.220.101.34` appelle `GET /api/v2/customers/export?page=N&size=100` pages 1→42, entre 02:10 et 03:40 UTC, avec le token d'un compte service compromis — 42 requêtes 200 noyées dans ~300 entrées de trafic normal (checkout, login, quelques 404/500 anodins).
- **Chiffrage** : `customers.json` porte `total: 4217` ; 42 pages × 100 = **4200 clients exposés**. Champs exposés : email, nom, téléphone, adresse — PII au sens RGPD, pas de données bancaires (nuance que le juriste doit qualifier).
- **Corpus juriste** (`world/docs/`, 5 docs markdown) : procédure interne de réponse incident · fiche art. 33 RGPD (notification CNIL 72h) · fiche art. 34 (information des personnes concernées) · registre des traitements · modèle de notification. Le doc-search permet de répondre : faut-il notifier la CNIL, sous quel délai, faut-il informer les clients.

Chaque domaine a son point d'entrée : l'ingénierie croise logs+CVE+schéma, le data-analyst chiffre, le juriste qualifie via doc-search, la comm rédige à partir des faits agrégés.

## 5. Loaders (`world.py`)

Fonctions pures, `@lru_cache`, chemins relatifs à `Path(__file__).parent / "world"` :

- `load_access_logs() -> list[dict]` (parse JSONL)
- `load_db_schema() -> str`
- `load_customers() -> dict` (métadonnées + échantillon)
- `load_cve_bulletins() -> list[dict]`
- `load_docs() -> dict[str, str]` (nom de fichier → contenu markdown)

Monde immuable : aucun tool n'écrit.

## 6. Tools (`tools.py`)

6 tools, retours `str` (contrat `ToolDef.fn` existant), `TOOLBOX: dict[str, ToolDef]` au niveau module (même helper `_tool` que la démo actuelle).

| Tool | Signature | Comportement |
|---|---|---|
| `query_logs` | `(filter: str)` | Filtre les entrées dont une valeur contient la sous-chaîne (IP, path, status, user-agent…). Retour plafonné (~50 lignes + compte total) pour ne pas exploser le contexte gpt-4o-mini. |
| `inspect_schema` | `(table: str)` | DDL de la table demandée ; `"*"` ou table inconnue → liste des tables + en-tête stack. |
| `count_affected_users` | `(criteria: str)` | Croise les requêtes d'export des logs (pages × size) avec `customers.total` → chiffrage + champs exposés. Déterministe. |
| `lookup_cve` | `(query: str)` | Recherche substring dans les 3 bulletins (id, package, mots-clés) → bulletin(s) complet(s) ou « no match ». |
| `doc_search` | `(query: str)` | Scoring mots-clés sur le corpus `docs/` (occurrences pondérées titre/corps), retourne les 2 meilleurs extraits (doc + passage). Simulation RAG déterministe. |
| `get_incident_report` | `()` | Le rapport initial du ticket (alerte trafic anormal, date, endpoint suspecté). Point de départ commun — évite de tout fourrer dans `task.context`. |

**Erreurs** : entrée non matchée → message explicite (`"no entries match …"`), jamais d'exception — un tool qui lève casserait la boucle tool-use pour rien.

## 7. Roster (`agents.yaml`)

7 agents, 3 domaines. Tags conçus pour deux propriétés : **compétition intra-domaine** (tags partagés à ELO proches) et **monopole du juriste** sur les tags réglementaires (le retirer → roster_gap naturel).

| Agent | Tags (ELO) | Tools |
|---|---|---|
| `backend-dev` | backend 85 · logs 70 · database 80 · investigation 65 | query_logs, inspect_schema, get_incident_report |
| `sre` | infrastructure 85 · logs 75 · access_control 70 · investigation 60 | query_logs, get_incident_report |
| `security-analyst` | security 90 · vulnerability 85 · logs 72 · investigation 75 | query_logs, lookup_cve, get_incident_report |
| `dpo-jurist` | gdpr 90 · legal 85 · compliance 88 | doc_search, get_incident_report |
| `client-comm` | communication 88 · writing 85 · customer_relations 80 | get_incident_report |
| `support-lead` | customer_relations 85 · communication 70 · support 90 | get_incident_report |
| `data-analyst` | data_analysis 88 · database 70 · reporting 75 | count_affected_users, query_logs, inspect_schema |

Points de friction voulus :
- **logs/investigation** : backend-dev vs sre vs security-analyst (logs 70/75/72) → claiming + ELO visibles sur l'investigation.
- **communication/customer_relations** : client-comm vs support-lead.
- **database** : backend-dev vs data-analyst (chevauchement transverse).
- **gdpr/legal/compliance** : dpo-jurist seul → roster_gap quand absent.

Les ELO du YAML **sont** le snapshot de départ versionné (Q10 : rejouer depuis zéro = recharger le YAML). System prompts : pattern phase 2 — investigation-via-tools d'abord, réponse complète ensuite, chacun ancré dans son rôle (le juriste cite ses sources doc-search, l'analyst chiffre, la comm rédige un texte prêt à envoyer).

## 8. Scénarios (`scenarios.py`)

Données pures, zéro runtime :

- `build_data_leak_task() -> Task` — description orientée organisation (« Trafic anormal détecté sur l'API customers cette nuit. Déterminer s'il y a eu fuite de données, en évaluer le périmètre, qualifier nos obligations réglementaires, et préparer la communication clients. »), `required_tags` couvrant les 3 domaines : `{security: 70, gdpr: 70, communication: 65}`, `context` minimal (l'alerte brute — le détail vit dans `get_incident_report`).
- `full_roster() -> list[Agent]` — les 7 agents (depuis `INCIDENT_AGENTS`).
- `roster_gap_roster() -> list[Agent]` — les 6 sans `dpo-jurist`. Même tâche : le gap émerge du claiming, pas du scénario.

## 9. Script de validation (`run_incident.py`)

Jetable, pattern `run_demo_v3.py` : `run_with_recovery` (jamais de division forcée), `AdaptiveSpecEvaluator`, tagger/divider/aggregator, persistance `runs/` (session + registry + snapshot ELO). Argument positionnel simple `main|roster_gap` (pas d'argparse élaboré — le CLI propre est phase 4). Modèle : gpt-4o-mini.

## 10. Tests (`tests/demo/incident/`)

- **`test_world.py`** — loaders : parse OK, cache, **cohérence du monde** (l'IP attaquante a bien 42 exports dans les logs ; 42×100 ≤ `customers.total` ; la CVE pertinente matche la stack du schéma ; chaque doc du corpus est non vide).
- **`test_tools.py`** — chaque tool : cas nominal + cas « no match » sans exception + plafond de sortie de `query_logs` ; `count_affected_users` retourne 4200 ; `doc_search("notification CNIL")` remonte la fiche art. 33.
- **`test_agents.py`** — le YAML charge avec `TOOLBOX`, 7 agents, tools résolus, monopole gdpr vérifié (un seul agent porte le tag).
- **`test_scenarios.py`** — tâche bien formée, rosters corrects (7 vs 6, dpo-jurist absent du gap).

## 11. DoD phase 3 (LLM réel, hors CI)

1. `run_incident.py main` → la tâche **aboutit** (Output, QA pass) avec un graphe émergent.
2. `run_incident.py roster_gap` → `RosterGapEvent` émis sur la sous-tâche réglementaire.
3. Les deux sessions persistées et lisibles dans le dashboard.

## 12. Hors scope

- CLI `run`/`campaign` + garde-fou store non vide → phase 4.
- Campagne + curation, rapport typologie, courbes ELO → phase 5.
- Aucune modification de `src/aaosa/` hors `demo/` — le runtime ne bouge pas.
- Démo logicielle existante (`demo/agents.yaml`, `tools.py`, `run_demo_v3.py`, `run_health_check_v3.py`) intacte.
- Live mode dashboard (ex-B7) → chantier post-démo.
