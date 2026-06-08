# V2d — Couche de persistance : SQLite vs double-DB vs statu quo JSON — Étude

Date : 2026-06-08
Statut : étude (ne tranche pas — **recommande**). Décision finale = Quentin (P1, architectural).
Branche : `night/v2d-etude-stockage-db`
Périmètre : **doc uniquement**, zéro code, zéro POC (tranché avec Quentin le 2026-06-08).

## Intention

Décider si la couche de persistance d'AAOSA — aujourd'hui un store **fichiers JSON/JSONL**
sous `runs/` — doit migrer vers une base (SQLite mono, ou un découpage « double-DB »), ou
rester en l'état. La couche data n'existe que pour servir ses **consommateurs aval** (le
dashboard + la CLI `report`). Ce sont eux qui dictent les patterns de requête ; l'étude
part donc de ce qu'ils scannent réellement, pas d'une vue idéalisée du « bon » stockage.

Cette étude n'engage pas l'archi. Elle pose les options honnêtes, mesure le terrain réel,
applique des critères, et **recommande**. Le choix reste à Quentin.

## 1. Contexte — le store JSON actuel

### 1.1 Layout (gitignoré sous `runs/`, versionné sous `runs_demo/`)

```
runs/
├── agents/registry.json          AgentRegistry courant (id, name, system_prompt, tags_with_elo)
├── elo_snapshots/
│   ├── <ts>.json                 EloSnapshot horodaté (match par agent_name, pas UUID)
│   └── latest.json               doublon du dernier snapshot
├── sessions/<session_id>/
│   ├── trace.jsonl               1 ClaimEvent par ligne (append-only à l'écriture)
│   ├── meta.json                 SessionMeta (tasks[], agent_ids[], status running/complete)
│   └── agents.json               AgentRegistry figée pour ce run (B1)
└── health_checks/<ts>/
    ├── report.json               HealthCheckReport (case_results, quarantaines, pass rates)
    ├── test_set.json             TestSet (cases : task + evaluator_spec + attribution)
    ├── trace.jsonl               trace agrégée des N runs du health check
    └── agents.json               registry figée
```

### 1.2 Chemins d'écriture (vérifié dans le code)

- `Tracer.flush(path)` — réécrit `trace.jsonl` en bloc depuis la liste en mémoire (`store.py`).
- `StreamingTracer.emit()` — **append + flush ligne par ligne** dans un handle ouvert (live mode).
  Handle fermé avant que `save_session` ne réécrive le fichier (lock Windows).
- `save_session(tracer, meta, runs_root, agents)` — crée `sessions/<id>/`, flush trace,
  écrit `meta.json` (+ `agents.json`). `meta.json` est réécrit en entier à la finalisation
  (provisoire `running` → final `complete`).
- `save_snapshot(agents, dir)` — écrit `<ts>.json` **et** réécrit `latest.json`.
- `save_agent_registry(agents, path)` — réécrit `agents/registry.json` en entier.

Constat : **tout est write-whole-file**, sauf `trace.jsonl` en live mode (append-only).
Aucune mutation in-place, aucun update partiel. C'est un store « immutable par fichier ».

### 1.3 Ce que le JSON fait bien

- **Zéro dépendance, zéro schéma à migrer** : Pydantic `model_dump_json` / `model_validate_json`
  sont la seule couche. Le format **est** le modèle Pydantic — pas de drift schéma/code possible.
- **Inspectable à l'œil** : un run = un dossier lisible, diffable, copiable. `runs_demo/`
  est versionné dans git → exhibits démo reproductibles, review humaine triviale.
- **Découplage process gratuit** : run (process A) et dashboard (process B) partagent
  `runs_root` via le filesystem. Le live mode (ex-B7) **repose** là-dessus : le store
  fichier *est* le canal de streaming, zéro IPC/socket. C'est un acquis architectural fort.
- **Append-only naturel** pour la trace : JSONL = une ligne par event, robuste à la lecture
  partielle (`load_trace_partial` rend le préfixe valide d'un fichier mi-écrit).
- **Agnostique domaine** : aucun schéma SQL à faire évoluer quand le domaine change ;
  un nouveau type d'event = un nouveau modèle Pydantic dans l'union `ClaimEvent`.

### 1.4 Limites réelles

- **Requêtabilité = scan complet en Python.** Le dashboard n'a pas de requêtes : il
  **itère tous les dossiers** et recharge tout en mémoire à chaque collecte (cf. §2).
  Aucune capacité de filtre/agrégat/index côté stockage.
- **Concurrence d'écriture sous live mode** = bordure fine mais réelle : un lecteur peut
  surprendre une ligne JSONL mi-append. Géré côté lecture (`load_trace_partial`), pas côté
  stockage. Le lock Windows force le protocole « fermer le handle avant `save_session` ».
  Aucune transaction : un crash entre l'écriture de la trace et la finalisation de
  `meta.json` laisse une session `running` orpheline (récupérable, mais non transactionnel).
- **Croissance de `runs/`** : linéaire en nombre de runs, sans rotation ni compaction.
  Les démos « flushent `runs/` » (repartent de zéro) précisément parce qu'il n'y a pas de
  cycle de vie. Pas un problème de volume aujourd'hui (cf. §2), un problème d'**hygiène**.
- **Redondance** : `latest.json` duplique le dernier snapshot ; `agents.json` est recopié
  dans chaque session/health-check. Coût disque négligeable, mais signal d'un modèle sans
  normalisation.

## 2. Volumétrie + patterns de requête — **mesurés** (pas estimés)

### 2.1 Volumétrie réelle (`C:\…\universal-AAOSA\runs\`, lecture seule, 2026-06-08)

| Métrique | Valeur mesurée |
|---|---|
| Poids total `runs/` | **0,96 Mo** (1 007 041 octets), 92 fichiers |
| Sessions | **18** |
| Health checks | 5 |
| Snapshots ELO | 17 fichiers (+ `latest.json`) |
| Events trace (sessions) | min **1**, max **196**, **moyenne ~51**, total **914** |
| Poids `trace.jsonl` session | moyenne ~38 Ko, max **184 Ko** (196 events) |
| Plus gros dossier session | ~190 Ko (`2026-06-07T13-20-39`, 196 events) |
| Health check le plus lourd | 75 events, trace 55 Ko, dossier 82 Ko |
| `runs_demo/` (versionné) | 457 Ko, 4 sessions, 32 fichiers |

Lecture : **le corpus entier tient sous 1 Mo.** Une trace = ~0,2 à 1 Ko par event
(événements riches : `output_content`, `llm_metadata`, `criteria_results`, `judge`). Même
à 100× le volume actuel (~1 800 sessions, ~100 Mo), on reste dans un domaine où SQLite est
trivial **et** où un scan fichiers reste de l'ordre de la seconde. Le volume n'est pas le
moteur de la décision — la **requêtabilité** et l'**hygiène** le sont.

### 2.2 Patterns de requête réels (depuis les collectors + l'API)

Recensé dans `dashboard/collectors/*.py` + `dashboard/api.py`. C'est la charge à servir :

| Consommateur | Ce qu'il scanne | Pattern |
|---|---|---|
| `infra.collect` (tab Infra) | **toutes** les sessions : parse chaque `meta.json` + **toute** la `trace.jsonl`, agrège tokens/latence/QA pass rate, séries temporelles par session, + `registry.json` | **full scan + agrégat global** |
| `sessions.list_sessions` | toutes les sessions : `meta.json` seul (pas la trace) | scan léger (métadonnées) |
| `sessions.session_detail` | une session : `meta.json` + `trace.jsonl` → `build_graph` | point-read + transform |
| `sessions.session_status` | une session : `meta.json` seul | point-read minimal (gating live) |
| `agents.agent_detail._elo_history` | **tous** les `elo_snapshots/*.json`, filtre par `agent_name` | **full scan + filtre** |
| `agents.agent_detail._activity` | **toutes** les sessions, **toute** la trace, filtre par `agent_id` | **full scan + filtre** |
| `agents.list_agents` | `registry.json` seul | point-read |
| `health_checks.list_runs` | tous les `report.json` | scan léger |
| `health_checks.run_detail / case_graph` | un run : `report.json` + `test_set.json` (+ `trace.jsonl` filtrée par `task_id`) | point-read + transform |

Atténuation existante : un **cache in-memory on-demand** (`dashboard/cache.py`) mémorise
les vues calculées (clé `session_view:<id>`, `agent:<id>`, `hc_view:<id>`…). **Mais** :
- `get_infra` et `list_*` **ne sont pas cachés** → full scan à **chaque** requête API.
- Le cache n'a **ni TTL ni invalidation** : il faut redémarrer le dashboard pour voir un
  nouveau run (sauf sessions `running`, bypass explicite). Hygiène, pas perf.

**Diagnostic des patterns** : les deux opérations qui font mal sont (a) l'agrégat global
Infra (full scan de toutes les traces à chaque appel non caché) et (b) l'historique
ELO + activité par agent (full scan filtré). Ce sont exactement les opérations qu'un
`SELECT … WHERE … GROUP BY` indexé rend O(log n) au lieu de O(n total events). Le reste
(point-reads par id) est déjà optimal en fichiers — un dossier = une clé primaire.

## 3. Options

### (a) Statu quo — JSON/JSONL fichiers

Garder le store actuel. Améliorations possibles **sans base** : cacher `get_infra`,
ajouter une invalidation de cache (mtime du dossier), un `index.json` agrégé écrit à la
fin de chaque run (matérialiser les totaux Infra pour éviter le full scan de traces).

### (b) SQLite mono — une base `runs.db`

Une seule base SQLite sous `runs_root`. Tables : `sessions`, `events`, `agents`,
`elo_snapshots`, `health_checks`, `health_check_cases`. Les collectors deviennent des
`SELECT`. Le JSON disparaît comme format de stockage primaire (peut rester comme
export/exhibit). SQLite est dans la stdlib Python (`sqlite3`) → zéro dépendance ajoutée.
WAL mode → un writer + lecteurs concurrents sans bloquer (résout proprement le live mode).

**Tension avec le live mode** : aujourd'hui le canal de streaming *est* le fichier JSONL
appendé. En SQLite, le dashboard devrait poller la table `events` (`SELECT … WHERE
session_id=? AND seq > ?`) au lieu de relire le fichier. Faisable et plus propre (WAL gère
la concurrence nativement, plus de ligne tronquée), mais c'est **réécrire le chemin live**,
pas le porter tel quel.

### (c) Double-DB

« Double-DB » n'a pas de sens unique — l'étude **définit** le découpage depuis le contexte
réel et le justifie. Deux découpages plausibles ici :

- **Découpage C1 — chaud opérationnel vs froid analytique.** DB « chaude » = la session en
  cours (events live, écriture haute fréquence) ; DB « froide » = l'historique consolidé
  (sessions complètes, snapshots ELO, health checks) servant le dashboard. Motivé par le
  live mode : isoler l'écriture concurrente du run en cours des lectures analytiques.
  **Verdict : surdimensionné.** Le volume (1 Mo) et le débit (1 event / appel LLM
  gpt-4o-mini, soit ~secondes) ne justifient aucune séparation chaud/froid. WAL d'une
  SQLite unique couvre déjà le cas. C'est de l'archi de système 1000× plus gros.

- **Découpage C2 — traces de run vs référentiel agents/ELO.** DB « runs » = sessions +
  events + health checks (immutable, append par run, jetable/flushable) ; DB « référentiel »
  = agents + historique ELO (entité longue durée, identité par `agent_name` stable,
  **survit** au flush des runs). Motivé par un invariant **déjà présent dans le code** :
  l'ELO matche par `agent_name` (stable), pas par UUID régénéré à chaque run ; le registry
  et les snapshots ont un cycle de vie distinct des traces. C'est le seul découpage qui
  reflète une vraie frontière de domaine du système, pas une optimisation prématurée.

  **Verdict : défendable mais prématuré.** Le bénéfice (pouvoir flush `runs/` sans perdre
  l'historique ELO) est réel — mais atteignable dans une **SQLite mono** par un simple
  `DELETE FROM events/sessions` qui préserve `agents`/`elo_snapshots`. La séparation
  physique en 2 fichiers `.db` ajoute de la complexité de jointure (cross-DB `ATTACH`) pour
  un gain que le découpage logique en tables suffit à offrir.

## 4. Critères de comparaison

| Critère | (a) JSON statu quo | (b) SQLite mono | (c) double-DB |
|---|---|---|---|
| **Requêtabilité dashboard** | faible : full scan Python, agrégats à la main, pas d'index. Infra non caché = O(tous events) par requête | forte : `SELECT/GROUP BY/index`, agrégats Infra et historique ELO en O(log n) | forte aussi, mais jointures agents↔runs nécessitent `ATTACH` cross-DB |
| **Coût migration depuis JSON** | nul (point de départ) | moyen : réécrire les 4 collectors en SQL + un writer + une migration des `runs_demo/` versionnés ; **réécrire le chemin live** (poll table vs fichier) | élevé : tout (b) + frontière 2-DB + cross-DB joins + 2 cycles de vie à gérer |
| **Concurrence écriture (live)** | gérée à la lecture (`load_trace_partial`), lock Windows, non transactionnel | native (WAL : 1 writer + N lecteurs, transactions) — supprime la ligne tronquée | native, mais 2 connexions/2 WAL à coordonner |
| **Simplicité / dette** | très simple, inspectable à l'œil, `runs_demo/` diffable dans git ; dette = pas de cycle de vie ni d'index | 1 fichier binaire (moins inspectable, pas diffable en git) ; +1 schéma à versionner/migrer | la plus complexe : 2 schémas, 2 connexions, raisonnement cross-DB |
| **Généricité domaine** | parfaite : format = modèle Pydantic, aucun schéma SQL à faire évoluer | bonne si schéma « events JSON dans une colonne TEXT » (event polymorphe préservé) ; risque de figer le schéma | idem (b), surface de schéma doublée |

Note transverse : SQLite **perd l'inspectabilité git** de `runs_demo/` (un `.db` binaire
n'est ni diffable ni reviewable à l'œil). C'est un coût réel pour un projet dont les
exhibits versionnés sont un livrable portfolio (nature C).

## 5. Recommandation

**Recommandation : (a) statu quo JSON, durci — pas de base de données maintenant.**

Justification, dans l'ordre de poids :

1. **Le volume ne justifie rien.** Corpus entier < 1 Mo, 18 sessions, ~914 events. Aucun
   pattern de requête n'est lent *en absolu* aujourd'hui. La douleur (full scan Infra) est
   un **défaut de cache**, pas un défaut de stockage.
2. **Le coût de migration est réel et asymétrique.** Passer en SQLite oblige à réécrire les
   4 collectors **et** le chemin live mode (le canal de streaming est aujourd'hui le fichier
   JSONL — un acquis archi qui vient juste d'être livré et signé). On paierait une réécriture
   d'un sous-système stable et récent pour un gain de perf non ressenti.
3. **On perdrait deux propriétés gratuites et précieuses** : l'inspectabilité à l'œil et le
   versionnement git de `runs_demo/` (matériel portfolio nature C), et le découplage process
   par filesystem (zéro IPC).
4. **La double-DB est prématurée des deux façons** : C1 (chaud/froid) répond à un problème
   d'échelle qu'on n'a pas ; C2 (runs vs référentiel) capture une vraie frontière mais
   s'obtient en SQLite mono — donc rien ne justifie 2 fichiers `.db`.

**Durcissements à faible coût (sans base), par ordre de valeur** — ce sont les vraies
douleurs mesurées :

- **D1 — cacher `get_infra` + invalidation par mtime.** Aujourd'hui full scan à chaque
  requête. Cache la vue Infra ; invalide quand le mtime de `runs/sessions/` change. Tue la
  douleur n°1 sans toucher au format.
- **D2 — `index.json` agrégé par run.** À la finalisation d'un run, écrire les totaux
  (tokens, latence, QA, run_count) dans `meta.json` (déjà réécrit en entier à ce moment).
  `infra.collect` lit alors les métadonnées au lieu de re-scanner toutes les traces.
  Transforme l'agrégat global O(tous events) en O(nb sessions).
- **D3 — politique de rétention `runs/`.** Documenter/outiller un flush ou une rotation
  (garder les N derniers + `runs_demo/`), pour traiter l'hygiène de croissance.

**Déclencheurs de réévaluation (quand rouvrir SQLite mono)** — formulés pour être
vérifiables :

- `runs/` dépasse ~500 Mo **ou** ~5 000 sessions (full scan devient pluri-seconde) ; **ou**
- besoin de requêtes ad hoc cross-run récurrentes (« tous les runs où l'agent X a sous-claimé
  sur le tag Y ») que les collectors ne couvrent pas ; **ou**
- live mode multi-runs concurrents (plusieurs `aaosa run` en parallèle écrivant le même
  `runs_root`) où l'absence de transactions devient une vraie corruption, pas une ligne
  tronquée récupérable.

Si l'un se déclenche : **SQLite mono (option b), jamais double-DB d'emblée.** Schéma
recommandé : table `events` avec colonne `payload TEXT` (JSON du modèle Pydantic) +
colonnes indexées extraites (`session_id`, `seq`, `event_type`, `agent_id`, `task_id`),
pour préserver l'event polymorphe et la généricité domaine tout en gagnant les index.

## 6. Esquisse de plan de migration (si/quand SQLite mono est retenu)

Non engagé — fourni pour que la décision soit informée du coût.

1. **Schéma + writer parallèle.** Définir le schéma SQLite (events à payload JSON +
   colonnes indexées ; `sessions`, `agents`, `elo_snapshots`, `health_checks`,
   `health_check_cases`). Écrire un writer qui double l'écriture (JSON **et** SQLite) le
   temps de la transition — le JSON reste source de vérité tant que SQLite n'est pas validé.
2. **Backfill.** Script one-shot : rejouer `runs/` + `runs_demo/` existants dans la base.
   Vérifier que les collectors SQL rendent **exactement** les mêmes vues que les collectors
   fichiers (golden test sur `runs_demo/`, versionné = oracle reproductible).
3. **Bascule des collectors.** Réécrire les 4 collectors en `SELECT`. Garder les contrats
   Pydantic de sortie (`InfraStats`, `SessionView`, `AgentDetailView`, `HealthCheckView`)
   **identiques** → l'API et le frontend ne bougent pas. TDD : tests collectors inchangés,
   seule l'implémentation change.
4. **Bascule du live mode.** Remplacer le poll fichier par `SELECT … WHERE session_id=?
   AND seq > ?` (curseur incrémental). Supprimer `load_trace_partial` (WAL gère la
   concurrence). Re-valider le flux démo navigateur (run + dashboard concurrents).
5. **Décommissionner le double write.** SQLite devient source de vérité. Décider du sort
   du JSON : soit supprimé, soit conservé comme **export** (`aaosa export <session>`) pour
   garder l'inspectabilité et les exhibits versionnés (recommandé — préserve l'acquis
   portfolio nature C).

Risque principal du plan : l'étape 4 (live mode) touche un sous-système stable et récent.
À ne lancer que si un déclencheur §5 est réellement franchi.

## Hors scope

- Tout choix de base distribuée / serveur (Postgres, DuckDB, …) : hors sujet à cette échelle.
- Implémentation, POC, benchmark exécuté (tranché : doc only).
- Refonte des contrats Pydantic de sortie des collectors (la migration les préserve).

## Annexe — proposition de ticket backlog (non créé)

Aucun doublon trouvé dans `tasks/board.md` (vault). Proposition à arbitrer par Quentin :

> **AAOSA — Durcir le store JSON (cache Infra + index agrégé + rétention `runs/`)** — P2.
> D1/D2/D3 de cette étude. Backend pur, nuit-compatible (TDD). Indépendant de toute
> décision SQLite ; gain immédiat sur la douleur de requête mesurée, sans migration.
