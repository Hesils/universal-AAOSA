# Spec — Épique « hygiène d'ingénierie production-grade »

> Statut : **validée** — 4 forks tranchés + décision roster actée (Quentin, 2026-06-24). Prête pour découpe en tickets + plan.
> Contexte : MVP production-ready de universal-AAOSA, fer de lance présentation SFEIR. Décision de cadrage : `AIOS/decisions/log.md` 2026-06-24 (reframe runtime émergent + socle prod-grade réel).
> Sous-projet 1 / 2 de l'épique MVP. Sous-projet 2 = pont `fqd` (AIOS→AAOSA), spec séparée à venir.

## 1. Objectif

Rendre le repo universal-AAOSA **crédible comme artefact d'ingénierie** au premier regard d'un évaluateur GenAI, sans toucher au moteur. Cinq leviers, du plus haut ROI au plus bas :

1. **Master poussé** sur GitHub (aujourd'hui 11 commits d'avance non poussés — la pièce maîtresse n'est littéralement pas regardable).
2. **CI** qui lance la suite (1239 tests que rien n'exécute automatiquement).
3. **Convention feature-branch → PR → master** + branch protection (signal « je travaille comme en équipe »).
4. **README front-door** (point d'entrée absent ; la doc technique est enterrée dans `docs/`).
5. **Versioning / tags** appliquant la convention 95c + **gitignore propre**.

C'est de la crédibilité, pas de la fonctionnalité : aucun comportement runtime ne change.

## 2. Périmètre

**Dans cet épique :**
- `.github/workflows/ci.yml` : install via `uv`, suite pytest complète sur push + PR.
- Branch protection sur `master` (PR obligatoire + CI verte requise, self-merge autorisé).
- Convention de nommage de branches documentée (README + CLAUDE.md repo).
- `README.md` racine : thèse, archi en bref, quickstart démo 1-commande, statut tests/CI, lien vers `docs/documentation-technique.md`.
- Bump de version (pyproject) selon la règle 95c + tag `v{version}` sur master.
- `.gitignore` : ignorer `runs_live_check/`, `runs_solve_smoke*/`, `smoke_v1m/` ; **tracker** `rosters/` (configs `agents.yaml`, pas des sorties runtime).
- Push de master sur origin.

**Hors périmètre (siblings / follow-ups) :**
- Pont `fqd` (AIOS→AAOSA) → spec 2.
- Mode service / API / Dockerfile / télémétrie live (Langfuse+OTel) → roadmap, pas MVP.
- Mise à jour du skill `/night-run` global pour ouvrir des PR au lieu de merger en direct → **follow-up AIOS obligatoire** (voir §4.1), hors de ce repo.
- Écriture de la convention de versioning dans le CLAUDE.md global → c'est le ticket **95c** lui-même (scope AIOS). Ici on ne fait que la **consommer**.

## 3. Composantes

### 3.1 Convention de branche + PR + branch protection

- Nommage : `feat/<ticket>-<slug>`, `fix/<slug>`, `docs/<slug>`, `chore/<slug>`. (Aligne l'existant : `feat/ipv-hitl-tool`, `feature/d6i-...` → normaliser sur `feat/`.)
- Flux : branche → push → `gh pr create` → CI verte → **self-merge en squash** (§4.3) → tag auto si bump → suppression de branche.
- Branch protection master : `require a pull request before merging` + `require status checks to pass` (le job CI) + **pas** de `require approvals` (solo dev, sinon auto-blocage).

### 3.2 CI GitHub Actions

- Trigger : `push` (toutes branches) + `pull_request` vers master.
- Steps : `astral-sh/setup-uv` → `uv python install 3.14` → `uv sync --extra dev` → `uv run pytest -q`.
- Plateforme : **`ubuntu-latest`** par défaut (rapide, standard, attendu par un reviewer). Risque connu : la sandbox a des tests « path jail symlink-aware » et plancher de non-destruction potentiellement sensibles à l'OS (repo dev = Windows). Stratégie : lancer sur ubuntu d'abord ; si rouge sur ces tests, **préférer les rendre platform-agnostic** plutôt qu'ajouter un job `windows-latest` (un seul OS vert = signal plus propre). Décision finale §4.2.
- Badge CI dans le README.
- **Job de tag auto** (séparé, sur `push` master uniquement) : `permissions: contents: write`, lit `pyproject.toml`, crée + pousse `v{version}` si absent (cf. §3.3, §4.4).

### 3.3 Versioning / tags (consomme 95c)

- Règle 95c (semver, alignée sur le ticket board) : **patch** `x.x.X+1`, **mineur** `x.X+1.0`, **majeur (breaking)** `X+1.0.0`.
- Mécanique : le bump de `version` dans `pyproject.toml` fait partie du diff de la PR quand le changement le justifie ; **tag `v{version}` créé automatiquement** par un job CI sur `push` vers master (lit la version dans `pyproject.toml`, crée + pousse `v{version}` si le tag n'existe pas encore ; no-op sinon). Pas de tag si pas de bump. Requiert `permissions: contents: write` sur ce job (§4.4 tranché).
- État de départ : `0.1.0`. Le push initial du backlog accumulé peut justifier un premier bump cadré (à trancher au moment du push).
- `CHANGELOG.md` : **non** au MVP (YAGNI — l'historique git + les tags suffisent ; à réévaluer si la roadmap publique le demande).

### 3.4 README front-door

Structure cible (≤ 1 écran avant le quickstart) :
1. Une phrase de thèse (coordination bottom-up émergente par claiming, vs orchestrateur central).
2. Badge CI + compteur de tests.
3. Schéma archi compact (le bloc `src/aaosa/` du CLAUDE.md, élagué).
4. **Quickstart 1-commande** : cloner → `uv sync` → `uv run aaosa run` (la démo interne, artefact principal). Mentionner `.env` `OPENAI_API_KEY`.
5. Lien vers `docs/documentation-technique.md` (le narratif complet) et la roadmap.

Ton : technique, sobre, zéro chrome marketing (cohérent avec `PRODUCT.md`).

### 3.5 gitignore + push

- Ajouter au `.gitignore` : `runs_live_check/`, `runs_solve_smoke/`, `runs_solve_smoke_hitl/`, `smoke_v1m/`. (Cohérent avec `runs/` et `runs_campaign*/` déjà ignorés ; `runs_demo/` reste **versionné** car exhibits curés.)
- `rosters/` : **tracké** (contient `jouet/agents.yaml`, `jouet_hitl/agents.yaml` = définitions de roster d'exemple, pas des sorties). Vérifié : non load-bearing pour la suite de tests (fixtures `tmp_path`), mais référencés par la doc/plans comme commandes d'exemple `aaosa solve --roster rosters/jouet` → les tracker rend ces commandes rejouables à froid. **TODO du ticket** : réécrire l'en-tête de ces deux fichiers (`Artefact de smoke — NE PAS committer`) en « roster d'exemple », sinon le commentaire contredit le tracking. Les stores ELO par-roster générés au runtime devront, eux, viser un chemin ignoré (à confirmer contre l'implémentation actuelle d'`elo_snapshots/`).
- Commit de nettoyage `.gitignore` + ajout `rosters/` + (séparément) push master.

## 4. Décisions tranchées (Quentin, 2026-06-24)

### 4.1 Branch protection vs night-run — **PR pour tout, y compris les night-runs**
Pas d'exemption `night/*`. La protection master exige une PR pour 100 % des changements. Conséquence : **follow-up AIOS obligatoire** — modifier le skill global `/night-run review` pour qu'il fasse `gh pr create` au lieu de merger en direct (sinon le night-run sur ce repo se bloque tout seul). Intérim avant ce follow-up : self-merge manuel des PR night-run au matin. Ticket AIOS séparé (hors de ce repo).

### 4.2 Plateforme CI — **ubuntu-latest seul**
Pas de job `windows-latest`. Si des tests OS-sensibles (path jail symlink-aware, plancher non-destruction) sont rouges sur ubuntu, les rendre platform-agnostic plutôt qu'ajouter un OS (un seul OS vert = signal plus propre).

### 4.3 Stratégie de merge — **squash-merge**
Historique master linéaire, une ligne propre par feature, lisible comme un changelog par un évaluateur. Le détail TDD survit dans la PR GitHub.

### 4.4 Tag — **automatisé via CI**
Job CI sur `push` master : lit `version` dans `pyproject.toml`, crée + pousse `v{version}` si absent, no-op sinon (cf. §3.3). Pas de tag manuel.

## 5. Critère de done (vérifiable)

- [ ] `origin/master` == `master` (0 commit d'avance local).
- [ ] PR ouverte déclenche un run CI ; merge bloqué tant que rouge (vérifié sur une PR témoin).
- [ ] `README.md` racine présent, quickstart testé à froid (clone propre → démo tourne).
- [ ] Un tag `v{version}` existe sur master, cohérent avec `pyproject.toml`.
- [ ] `git status` propre (plus de `runs_*` / `smoke_v1m` non trackés ; `rosters/` tracké).
- [ ] Convention de branches écrite dans le CLAUDE.md du repo.

## 6. Notes d'implémentation

- Pas de TDD classique ici (infra/config, pas de logique métier) : la « suite verte » reste le garde-fou, mais le livrable est de la config CI + des fichiers repo. La vérification se fait par les critères §5, pas par des tests unitaires nouveaux.
- Ordre conseillé : (1) gitignore + push master (débloque la visibilité immédiatement), (2) CI, (3) README, (4) branch protection + convention, (5) tag. La protection vient **après** la CI (elle en dépend comme status check requis).
