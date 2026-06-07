# Démo AAOSA — Exhibits curés (campagne N=20 du 2026-06-07)

Sélection de runs 100 % naturels (zéro seed — ligne rouge du cadrage démo) issus
de la campagne `runs_campaign_n20` (gpt-4o-mini, temp 0, départ ELO YAML).
Données brutes : `runs_demo/campaign_index.json` · rapport : `runs_demo/campaign_report.md`.

## Rejeu (clone frais)

    .venv\Scripts\aaosa dashboard --runs-root runs_demo

Tab Sessions = les exhibits ci-dessous · tab Agents = courbes ELO « le roster après 20 incidents ».

## Exhibits

### 2026-06-07T20-40-15-0e5cf438 — divided + success (run 1)

Le cas nominal lisible : la tâche incident (fuite de données cross-domaine) n'est
claimée par personne à la racine → le TaskDivider la découpe en 5 sous-tâches
(thèse D1 : la division est une récupération, jamais forcée). 10 claims en
compétition phase 2, 5 dispatches best-fit, 11 tool calls d'investigation,
5/5 QA PASS, 5 mises à jour ELO. 132,6 s.

### 2026-06-07T20-45-08-ce926a54 — divided + recursion (run 3)

La récursion D1 émergente, sans bruit : une sous-tâche issue de la première
division reste elle-même non claimable → elle est redivisée à son tour
(2 `TaskDividedEvent`). 9 sous-tâches exécutées au total, 20 tool calls,
9/9 QA PASS. L'arbre du dashboard montre la paire DIVIDER/AGGREGATOR enfant
révélée sous la branche concernée. 238,0 s.

### 2026-06-07T21-07-51-92b82f5f — divided + recursion + diagnosed:agent (run 14)

Le run le plus riche de la campagne : 3 divisions (récursion), et un échec QA
déclenche le diagnostic inline D3 — `DiagnosedEvent` avec attribution `agent`,
visible comme nœud DIAG dans l'arbre. 8 sous-tâches exécutées, 14 tool calls.
La boucle d'auto-observation du système (échec → triage → attribution) fire
naturellement, sans aucun cas seedé. 624,3 s.

### 2026-06-07T21-39-27-448f6ca4 — roster_gap

`RosterGapEvent missing_tags=[gdpr]` dès la racine, 0 appel agent : sur un
roster amputé du dpo-jurist (6 agents), le système nomme le trou de compétence
au lieu d'halluciner une réponse. Run unitaire (le scénario est systématique,
pas besoin de campagne) ; la session porte son propre `agents.json`, le
dashboard la rend cross-roster sans toucher au registry 7 agents.

## Lecture du delta ELO

La colonne « départ » du rapport est le premier snapshot persisté, c'est-à-dire
l'état **après le run 1** — l'état YAML d'avant tout run n'est jamais capturé.
Les runs en erreur ne produisent pas de snapshot (échec avant persistance) :
16 snapshots pour 20 runs. La courbe raconte quand même la spécialisation :
security-analyst logs 76→95 (+19), client-comm customer_relations 82→95 (+13),
dpo-jurist legal 87→95 (+8) ; les non-claimers restent à plat.

## Typologies non observées sur N=20

- `simple` : 0/20 — la tâche incident divise toujours (racine jamais claimée
  d'un bloc, cohérent avec sa nature cross-domaine).
- `aggregated` : 0/20 — le divider produit des chaînes pures (1 sink → le
  court-circuit D2 s'applique, aucun `TaskAggregatedEvent`). Constat tranché au
  dépouillement : l'aggregator est assumé comme filet pour les vrais fan-ins,
  rares par nature — cf. `docs/backlog/2026-06-07-divider-topologie-aggregator.md`.
- `diagnosed:evaluator`, `diagnosed:task_spec`, `diagnosed:unattributed` : 0/20 —
  les 5 diagnostics de la campagne ont tous attribué à `agent`.
- `roster_gap` : 0/20 sur le scénario `main` (roster complet — attendu) ;
  exhibité via le scénario dédié ci-dessus.

Non observées naturellement, jamais provoquées (curation ≠ seeding).
Relancer des campagnes plus tard est non bloquant.

## Constat campagne : 4 runs en erreur (cycles du divider)

4/20 runs échouent en ~7 s sur `cycle detected in task dependencies` : le
divider émet parfois des dépendances cycliques, le tri topologique de
`run_chain` les détecte et le containment enregistre l'erreur sans tuer la
campagne (0 appel agent gaspillé). Trou de design découvert par la campagne —
ticket : `docs/backlog/2026-06-07-divider-cycles-dependances.md`.

## Curation — provenance

Copie manuelle depuis `runs_campaign_n20/` (sessions sélectionnées + registry +
16 snapshots ELO + index + rapport), exhibit roster_gap depuis un run unitaire
en root jetable. Commandes consignées dans le plan phase 5
(`docs/superpowers/plans/2026-06-07-v3-demo-phase5-campagne-curation.md`).
