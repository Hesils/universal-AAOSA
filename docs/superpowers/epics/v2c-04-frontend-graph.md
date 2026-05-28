# V2c — Épique 4 — Frontend : composant graphe + overlay + scrubber

- **Couche** : `dashboard/templates/` + `dashboard/static/`
- **Statut** : à creuser (deep-dive → plan → impl)
- **Dépendances** : Épique 3b (API : endpoints graphe).
- **Spec source** : Section 3 — composant graphe, overlay, Tab 4.

## Contexte

Le composant visuel central, **commun à Tab 3 et Tab 4** : rendu SVG du `GraphModel` en 3 bandes, overlay modal au clic, scrubber de stepping. Cette épique couvre l'essentiel de Tab 4 (session run). Vanilla JS + SVG, pas de framework, servi par Flask.

## Décisions portées

- **#2** — Rendu en 3 bandes spatiales TOP/CENTER/BOTTOM (le `layer` vient du `GraphModel`).
- **#6** — **Auto-fit** : viewBox calculé selon le nombre de nœuds → tout loge sans scroll page ; contrôles zoom/dézoom optionnels.
- **#7** — **Overlay au clic = modal centré style aios** (celui des messages longs du trace viewer), appendé hors zoom, contenu **adapté par type de nœud**.
- **#8** — Esthétique : structure validée ; le skin peut s'écarter de l'aios (décidé ici, en implémentation).

## Composant graphe (commun Tab 3 & 4)

- Rendu SVG du `GraphModel` en 3 bandes (TOP/CENTER/BOTTOM).
- Auto-fit (viewBox dynamique), contrôles zoom/dézoom optionnels.
- Chemin sollicité en surbrillance ; gagnant mis en avant (pulse) ; filtrés grisés ; branche fail en pointillé.
- **Clic sur un nœud → modal centré**, contenu adapté :
  - **Dispatch** : fit_scores Phase 1, claims + justifications Phase 2, résolution → winner
  - **Agent** : system prompt (tronqué/expandable), tags + ELO, input de la task, output (+ latence/tokens)
  - **Evaluator** : critères/gates, judge (mode + score), score final, raison
  - **Input/Output/TestSet** : task détaillée, contenu output, lien vers le cas TestSet

## Tab 4 — Session run

Toolbar (sélecteur session + chips stats) + graphe + panneau todo (tasks de la session, cochées au fil du stepping) + scrubber (step task-par-task). Le scrubber consomme les `steps` du `GraphModel` (un par task, ordonnés).

## Stratégie de test

- Hors TDD automatisé : vérification manuelle navigateur (comme aios). La logique testable vit côté Python (Épiques 2/3).
- Vérifier golden path + edge cases au navigateur : session sans winner (unassigned), QA fail (branche pointillée), session multi-task (scrubber + todo cochées).

## Critères de done

- [ ] Composant graphe SVG 3 bandes, auto-fit sans scroll, réutilisable Tab 3 & 4.
- [ ] Overlay modal adapté aux 6 types de nœuds.
- [ ] Surbrillance chemin / pulse winner / grisé filtrés / pointillé fail.
- [ ] Tab 4 fonctionnel : graphe + todo + scrubber synchronisés.
- [ ] Vérifié au navigateur sur runs réels persistés (Épique 1).

## À creuser en session de deep-dive

- Lire le trace viewer / aios-dashboard pour réutiliser le pattern modal et le skin de départ.
- Calcul du viewBox auto-fit (positionnement des nœuds dans chaque bande).
- Synchronisation scrubber ↔ surbrillance `active_nodes`/`active_edges` ↔ todo.
- Stratégie d'expand du system prompt tronqué dans l'overlay Agent.
