# V2c — Épique 5 — Tabs 1/2/3 + intégration finale

- **Couche** : `dashboard/templates/` + `dashboard/static/`
- **Statut** : à creuser (deep-dive → plan → impl)
- **Dépendances** : Épique 3b (API), Épique 4 (composant graphe réutilisé par Tab 3).
- **Spec source** : Section 3 — Tabs 1/2/3.

## Contexte

Dernière épique : les trois vues restantes (infra, agents, health check) + le câblage final des 4 tabs en une app cohérente. Tab 3 réutilise le composant graphe de l'Épique 4 (mode un-run-par-cas, pas de stepping).

## Tab 1 — Infra (Grafana-like)

Cartes chiffres (sessions, runs, agents, tasks, QA pass %, tokens, latence moyenne) + charts (distribution latence, pass rate dans le temps, runs/session, tokens in/out). Consomme `GET /api/infra`.

## Tab 2 — Agents (supervision unitaire)

Liste agents → détail : prompt, tags+ELO courant (barres), **historique ELO par tag (courbes)**, historique claim/win/success/fail. Consomme `GET /api/agents` + `GET /api/agents/<id>`.

## Tab 3 — Health check runs

Sélecteur de run → overview (pass rates fix_target/regression_guard, unstable, quarantaines) + vue TestSet (split train/test, evaluator + attribution par cas) + **graphe avec sélecteur de task** (par cas, affiche `pass_rate`). Réutilise le composant graphe (Épique 4) en mode health check : un `GraphModel` par cas, **pas de stepping** (décision #5). Consomme `GET /api/health-checks`, `/<id>`, `/<id>/graph?task_id=`.

## Décisions portées

- **#5** — Tab 3 = sélecteur de task qui bascule le graphe d'un cas à l'autre (cas décorrélés), pas de stepping. Confirmé ici à l'usage.

## Stratégie de test

- Hors TDD automatisé : vérification manuelle navigateur. Logique testable déjà côté Python (collectors + API).
- Vérifier au navigateur : Tab 1 charts non vides sur runs réels, Tab 2 courbes ELO multi-tags, Tab 3 bascule entre cas + pass_rate affiché, navigation entre les 4 tabs.

## Critères de done

- [ ] Tab 1 : cartes + charts alimentés par `/api/infra`.
- [ ] Tab 2 : liste + détail agent avec courbes ELO par tag.
- [ ] Tab 3 : overview + TestSet + graphe avec sélecteur de cas (pass_rate annoté).
- [ ] Les 4 tabs navigables dans une app cohérente.
- [ ] Vérifié au navigateur de bout en bout sur runs réels.

## À creuser en session de deep-dive

- Choix de la lib de charts (vanilla SVG maison vs micro-lib) — cohérence avec la contrainte "pas de framework".
- Réutilisation effective du composant graphe (Épique 4) en mode health check : paramétrage stepping on/off.
- Layout de navigation entre tabs (état actif, deep-link éventuel).
- Vue TestSet : rendu du split train/test + attribution par cas.
