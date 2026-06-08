# V3 — Live mode observabilité (ex-B7) — Design

Date : 2026-06-08
Statut : validé (brainstorming), prêt pour plan d'implémentation
Branche cible : `feat/v3-live-mode` (à créer)

## Intention

Regarder un run **se construire en direct** dans le dashboard : on lance `aaosa run`
et l'arbre émergent (`/impeccable`, aujourd'hui le graphe du Sessions tab) se révèle
jalon par jalon au fil de l'exécution. C'est le « wow » démo d'entretien — voir le
claiming / la division / le QA s'assembler en temps réel, pas en post-mortem.

Contexte : prérequis entretien (négociation backend → GenAI engineer). L'observabilité
statique est complète ; il manque le live. L'archi V2c excluait explicitement le live
mode (« review statique sur runs persistés ») — ce ticket lève cette limite.

## Décisions de cadrage (tranchées au brainstorming)

- **Expérience** : run qui se déroule en direct. Le **pilotage depuis l'UI** (lancer /
  pause un run depuis le dashboard) est **hors scope** → autre ticket.
- **Surface frontend** : l'arbre émergent `/impeccable` (= graphe du Sessions tab).
  Pas le graphe V2c legacy, pas les deux.
- **Transport** : approche **poll du graphe partiel via le store fichier**. Pas de SSE
  (gain de latence invisible au rythme gpt-4o-mini, vrai risque démo sur Flask dev).
- **Persistance incrémentale = défaut** pour tous les runs. Pas de flag `--live` : un
  seul chemin de persistance, tout run est observable en live sans y penser.

## 1. Modèle : découplage par le filesystem

Le run (`aaosa run`, process A) et le dashboard (`aaosa dashboard`, process B) partagent
`runs_root`. Le run **écrit la trace au fil de l'eau** dans `sessions/<id>/`, le dashboard
**poll** ce dossier. Zéro IPC, zéro socket — le store fichier *est* le canal, ce qui
préserve le découplage existant (run et dashboard restent 2 process indépendants).

Démo : `aaosa dashboard --runs-root runs` dans un terminal, `aaosa run --runs-root runs`
dans un autre (mêmes defaults ⇒ marche sans argument). La session apparaît et s'anime.

## 2. Persistance incrémentale (runtime, `src/aaosa/`)

- **`StreamingTracer`** : variante de `Tracer` qui, sur `emit`, append la ligne JSON à
  `trace.jsonl` (handle ouvert + flush), en plus de l'accumulation en mémoire. Le
  `Tracer` de base reste **pur en-mémoire, inchangé** — la variante streaming reste un
  pur observer (la séparation « le runtime émet, le tracer écoute » tient). Additif :
  zéro impact sur les callers existants (`run_health_check_v3`, tests, fixtures).
  - Détail d'implémentation laissé au plan : sous-classe `StreamingTracer(session_dir)`
    OU `Tracer(stream_path=None)` write-through optionnel. Préférence : sous-classe, pour
    ne pas toucher la signature de `Tracer`.

- **`SessionMeta.status: Literal["running", "complete"] = "complete"`** — champ **additif
  defaulté**. Default `"complete"` ⇒ les 16 `meta.json` de `runs_demo/` et toutes les
  fixtures existantes parsent inchangées (`extra="forbid"` respecté : un champ absent
  prend son default). Le frontend lit ce champ pour savoir qui poller.

- **`run_once` restructuré** (`src/aaosa/cli/incident_runs.py`) :
  1. Génère `session_id`, crée `session_dir`, écrit `meta.json` **provisoire**
     (`status="running"`, vraie `description`/`required_tags`/`context` de la tâche,
     `ended_at` = placeholder = `started_at`), ouvre le `StreamingTracer` → la session
     est **visible dès le démarrage** (liste + graphe INPUT-seul).
  2. `run_with_recovery(task, ctx)` émet → trace streamée incrémentalement.
  3. À la fin : **finalise** `meta.json` (`status="complete"`, vrai `ended_at`, outcome
     réel), **ferme le handle de stream** (lock Windows), écrit agents + snapshot.
     `save_session` réécrit `trace.jsonl` à l'identique depuis la liste en mémoire
     (idempotent — même contenu) APRÈS fermeture du handle.
  - `aaosa campaign` hérite gratuitement du streaming (partage `run_once`). Sans effet
    de bord : chaque run reste observable s'il est ouvert.

## 3. Backend live-aware (dashboard) — zéro nouvel endpoint

- **Cache status-gated** : on ne met en cache **que** les sessions `complete`. Une
  session `running` est recalculée à chaque requête (`build_graph` frais sur la trace
  courante). Au passage `complete`, le cache reprend son rôle normal. Règle unique, pas
  de paramètre `?live=1`. Évite le piège du cache figé (`session_view:<id>` gelé au
  premier accès).

- **Lecture tolérante** : `load_trace_partial` — variante de `load_trace` qui **ignore
  une dernière ligne tronquée** (append concurrent surpris mi-écriture) au lieu de lever.
  Un poll raté se rattrape au tick suivant (~750 ms plus tard la ligne est complète).
  Les lignes valides du préfixe sont toujours rendues.

- **`status` exposé** dans `list_sessions` (`SessionListItem`) + `session_detail`
  (`SessionView` / `SessionDetailResponse`) → le frontend distingue running/complete.

- `build_graph` **inchangé** : il tolère déjà `meta` provisoire et trace partielle
  (fallback racine = première tâche non-enfant ; garde « trace vide » ; garde « pas de
  DIAG sans passe » pour trace partielle). On l'alimente avec une trace qui grandit, il
  rend un graphe qui grandit.

## 4. Frontend — boucle live (DÉPENDANCE FORTE : skill `impeccable`)

> **Cette section s'implémente impérativement via le skill `impeccable`.** Toute
> modification de `dashboard/static/js/` (graph.js, camera.js, modal.js, sessions.js,
> CSS) pour le live passe par `impeccable`. Ne pas coder le frontend à la main.

- **Liste des sessions auto-refresh** (~2-3 s) : une session `running` porte un badge
  **● LIVE** en tête de liste (tri `started_at` desc ⇒ déjà en tête).
- **Vue live** : à l'ouverture d'une session `running`, poll du graphe (~750 ms) →
  rebuild → **avance la frontière de révélation au dernier jalon** (réutilise le
  mécanisme scrubber/reveal existant) + **camera follow** sur le jalon neuf. C'est le
  scrubber, piloté par l'arrivée d'events au lieu de la souris.
- **Settle** : `status → complete` ⇒ fetch final, arrêt du poll, la session redevient
  une vue statique scrubbable normale. Transition invisible.
- Non-régression : une session `complete` (ouverture directe, sans live) se comporte
  exactement comme aujourd'hui.

## 5. Tests & rétrocompat

**TDD backend** (norme projet, subagent-driven) :
- `StreamingTracer` : ligne appendée et lisible **mi-stream** (avant flush final).
- `run_once` : `meta.json` provisoire (`status="running"`) écrite **avant** exécution,
  finalisée (`status="complete"`) **après**.
- `SessionMeta.status` : default `"complete"` rétrocompat (vieux meta sans le champ).
- `load_trace_partial` : tolère une dernière ligne tronquée, rend le préfixe valide.
- Cache : bypass si `running`, mis en cache si `complete`.
- `build_graph` : sur trace partielle / INPUT-seul / meta provisoire → graphe valide
  croissant (probablement déjà couvert ; ajouter les cas explicites).

**Frontend** : validé navigateur (hors TDD auto, norme projet) — flux démo réel
`aaosa run` pendant que `aaosa dashboard` tourne, sur `runs/` frais.

**Rétrocompat verrouillée** :
- `Tracer` base inchangé (streaming = sous-classe additive).
- `SessionMeta` : champ `status` additif defaulté.
- `build_graph` : signature inchangée.
- `save_session` : idempotent (réécrit la trace à l'identique).
- `runs_demo/` : rejoue identique (`aaosa dashboard --runs-root runs_demo`).

## Hors scope (autres tickets)

- Pilotage depuis l'UI (lancer / pause / inspecter à la volée un run).
- Sessions-tab V2c legacy (graphe hex tree-tiers).
- SSE / streaming push.

## Dépendances

- **FORTE — skill `impeccable`** : obligatoire pour toute la section 4 (frontend live).
  À charger au moment d'implémenter le frontend, pas avant.
- Skills process : `test-driven-development` + `subagent-driven-development` (backend),
  `writing-plans` (étape suivante immédiate).
