# V3 — Nature C (docs/présentation) — Design

_Date : 2026-06-03_
_Statut : design validé (brainstorm), spec à relire avant plan d'implémentation_

## 1. Contexte & objectif

Nature C = rendre AAOSA **présentable**. Ce n'est pas un portfolio générique : c'est un **dossier de compétence** servant un objectif de carrière précis.

- **But** : Quentin démarre en ESN le 21 sept 2026 avec un contrat « backend engineer ». Il veut négocier le passage direct à **GenAI engineer** auprès de la **directrice des ingénieurs**, avant la prise de poste.
- **Plan en 3 temps** : (1) finir + documenter AAOSA [ce cycle], (2) un 2e projet preuve-de-compétence (même schéma), (3) une présentation globale 2-projets pour la directrice. Le temps 3 est **hors scope** de ce cycle.
- **Audience cible** : la directrice des ingénieurs — technique mais senior, évalue la compétence/séniorité d'architecte GenAI, pas du debug de code.

**Thèse à porter** : « j'architecture des systèmes GenAI, je ne fais pas que les utiliser. » Hiérarchie verrouillée :

| Rôle | Contenu | Fonction |
|---|---|---|
| **Héros** | Le graphe émerge (coordination bottom-up par claiming, pas d'orchestrateur central) | Différenciation, mémorabilité |
| **2e acte** | Système auto-améliorant (QA générée par les agents) | Profondeur + pertinence 2026 |
| **Spine** | La démarche end-to-end (spec→plan→TDD, versions, séparations) | Signal senior, montré implicitement |

## 2. Approche retenue — Source unique, 3 rendus (Approche A)

La vérité du projet est écrite **une seule fois** (faits, chiffres, décisions, diagrammes, beats narratifs). Chaque livrable est une **projection** de ce canon, à une profondeur et avec une forme propres. On écrit l'histoire une fois, on la *rend* trois fois.

- Taille **par projection** (sélection + reframing), pas par réécriture indépendante.
- Garantit la cohérence (mêmes chiffres/noms partout — critique pour un dossier qui prouve la rigueur) et minimise le travail/maintenance.
- **A ≠ C** : les slides ne sont pas « la doc compressée ». A sépare *ce qui est vrai* (canon) de *comment on le raconte* (arc propre à chaque livrable). Les slides gardent leur arc persuasif visuel-first.

Langue : **README en EN** (vitrine GitHub, signal standard international) ; **doc technique + slides en FR** (audience directrice).

## 3. Le canon (source unique)

### 3a. La spine narrative (6 beats, héros = graphe émergent)

1. **Le problème** — multi-agent classique = orchestrateur central qui route. Graphe figé d'avance, fragile, plafond d'autonomie.
2. **La thèse (HÉROS)** — et si le graphe d'exécution *émergeait* des décisions des agents ? Coordination bottom-up par claiming.
3. **Le mécanisme** — claiming two-phase (Phase 1 déterministe filter+fit_score / Phase 2 reasoning LLM), dispatch, ELO par tag dynamique ; divider/aggregator : une tâche se subdivise, le graphe se déploie.
4. **La durabilité (2e ACTE)** — un système qui dure = un système qui s'auto-corrige. Boucle QA générée par les agents (evaluator émis par LLM → triage → task-spec generator).
5. **La preuve** — tout est tracé et rejouable ; le dashboard *rend visible* le graphe émergent.
6. **La rigueur (SPINE, montrée pas dite)** — TDD, séparations strictes, généricité par config, démarche spec→plan→TDD versionnée.

### 3b. La fiche de faits (chiffres/noms canoniques, écrits une fois)

Stack (Python 3.14 / Pydantic 2 / OpenAI SDK / Flask), progression V1→V3, claiming two-phase, ELO per-tag asymétrique (K=5), divider/aggregator, tools par agent, dual QA, boucle B1/B2/B3, nombre de tests. Les valeurs issues d'un run réel (nombre de sous-tâches, tool calls, scores QA, deltas ELO, résultats du run d'amélioration) sont **demo-dependent** (cf. §8). Liste exhaustive énumérée à l'écriture des docs.

### 3c. L'inventaire des diagrammes

- **D1** — pipeline claiming (Task → Phase1 → Phase2 → dispatch → execute → QA → ELO). *Demo-independent.*
- **D2** — graphe émergent (run divisé : divider → sous-tâches → agents+tools → aggregator). *Schématique = demo-independent ; capture d'un vrai run = demo-dependent (money shot slides).*
- **D3** — boucle d'auto-amélioration (échec → triage → task-spec gen → re-triage → health check). *Schéma demo-independent ; narration d'un run réel = demo-dependent.*
- **D4** — architecture des modules (`src/aaosa/` + `dashboard/`). *Demo-independent.*
- **D5** — captures dashboard (le graphe rendu, courbes ELO, health tab). *Demo-dependent.*

Format : **Mermaid** pour D1-D4 (source `.mmd`, rendu inline par GitHub, pré-rendu SVG pour les slides). D5 = captures PNG du dashboard live.

### 3d. Les décisions (annotations contextuelles, pas un chapitre)

Les décisions de design vivent en **encadrés/footnotes inline** dans les sections concernées de la doc technique — pas un chapitre-changelog séparé. Format : problème → choix → pourquoi. Exemples : pas de `confidence` sur `Claim`, `fit_score` hors prompt Phase 2, tie-break lexicographique, evaluator-as-data (pont V2b→V3), judge jamais primaire, **B4/B5 déferrés** (savoir dire non = signal de séniorité). Source : `decisions/log.md` + roadmap AIOS.

**Exception slides** : 2-3 décisions phares restent mises en avant explicitement (le signal senior y est concentré, pas dispersé).

## 4. Projection README (EN)

Orienté usage, porte le pitch 60s. Structure :

1. Titre + one-liner (thèse, beat 2) + badges (tests, Python).
2. Pitch (3-4 phrases, hook graphe émergent, beats 1-2).
3. Visuel hero — D2 ou D5. *[DÉMO-DÉPENDANT pour la capture réelle]*
4. Key features (bullets) — claiming émergent · QA auto-générée · observabilité · générique par config.
5. Quickstart — install (uv/venv), `OPENAI_API_KEY`, lancer la démo, lancer le dashboard. Commandes copy-paste (stables) ; sorties/captures *[DÉMO-DÉPENDANT]*.
6. How it works (bref) — D1 + 3 phrases, lien vers la doc technique.
7. Architecture at a glance — D4, une ligne par module.
8. Project status — V1→V3, tests, fait/déféré.
9. Links — doc technique, slides.

Repo privé → pas de section licence/contribution (à revoir si rendu public un jour).

## 5. Projection doc technique (FR) — ordre des sections

Projection la plus complète (canon + décisions inline + diagrammes + pointeurs code). Ordre :

1. **Le problème** — orchestration centralisée et ses limites ; pose la thèse.
2. **Vue d'ensemble** — pipeline (D1) + carte des modules (D4). La carte avant les détails.
3. **Le claiming émergent — le cœur (HÉROS)** — two-phase, dispatch + conflict resolution, ELO par tag, puis le graphe qui émerge : divider/aggregator, run divisé (D2). Décisions inline (pas de `confidence`, `fit_score` hors prompt, tie-break).
4. **De la décision à l'exécution** — l'agent gagnant exécute : boucle tool-use, tools par agent, output (A5).
5. **L'auto-amélioration (2e ACTE)** — dual QA, evaluator-as-data, B1 → B2 → B3, boucle fermée (D3), health check N-runs, lifecycle. Décisions inline (judge jamais primaire, evaluator-as-data, B4/B5 déferrés).
6. **L'observabilité** — tracer (observer pattern), couche data persistée, dashboard (`build_graph` pur, 4 tabs, D5).
7. **La démarche (SPINE)** — court et explicite : V1→V3 incrémental, TDD subagent-driven, spec→plan→TDD, séparations strictes, tests. Le signal séniorité atterrit ici, une fois, noir sur blanc.
8. **Limites & suites** — déféré et *pourquoi* (B4/B5/B6/B7, A2), limite 1 run/graphe.

Logique : substance d'abord (problème → idée → cœur → couches), puis « comment c'est construit » en payoff (§7), puis lucidité (§8). Décision : démarche en §7 (pas remontée tôt).

## 6. Projection slides (FR, Marp) — arc persuasif

Visual-first, une idée par slide, détail dans les *speaker notes*. ~11 slides :

1. Titre — AAOSA + tagline + contexte.
2. Le hook — orchestrateur central, la limite.
3. La thèse (HÉROS) — « et si le graphe émergeait ? »
4. Le mécanisme — claiming two-phase, D1, 3 bullets.
5. **Le graphe émerge** — D2 run divisé, *le money shot*. *[DÉMO-DÉPENDANT]*
6. 2e acte — auto-amélioration — D3 la boucle. *[DÉMO-DÉPENDANT pour le run réel]*
7. La preuve — observabilité — D5 capture dashboard. *[DÉMO-DÉPENDANT]*
8. Décisions phares — 2-3 décisions (signal senior concentré).
9. La démarche — V1→V3, tests, spec→plan→TDD.
10. Limites & suites.
11. Clôture — « ce que ce projet démontre ». (L'ask explicite est porté par la présentation globale du temps 3.)

Thème Marp : réutilise l'esthétique verrouillée du dashboard (`DESIGN.md` : graphite froid + hero ember). Pas de nouveau brainstorm visuel. Export pptx + pdf. Speaker notes par slide.

## 7. Layout fichiers, diagrammes, tooling

```
README.md                          # EN, racine (point d'entrée)
docs/
  documentation-technique.md       # FR, doc complète (projection la plus riche, héberge le canon)
  slides/
    aaosa.md                       # source Marp FR
    aaosa.pdf  /  aaosa.pptx       # exports générés
  assets/
    diagrams/*.mmd                 # sources Mermaid (D1-D4)
    d1-pipeline.svg … d4-archi.svg # Mermaid pré-rendus
    d5-dashboard-*.png             # captures dashboard
```

- **Diagrammes** : Mermaid as source (cohérent « écrit une fois, projeté »). GitHub rend le Mermaid inline ; pré-rendu SVG pour Marp (qui ne rend pas Mermaid nativement).
- **Slides** : Marp CLI via `npx @marp-team/marp-cli` (projet Python, pas de Node en dur → zéro-install). Thème CSS custom réutilisant les tokens `DESIGN.md`.
- **Canon physique** : la fiche de faits, les diagrammes et les décisions inline vivent dans `documentation-technique.md` + `docs/assets/`. README et slides y puisent (liens, mêmes images, mêmes chiffres) → cohérence automatique.

## 8. Dépendances démo & placeholders (hybride validé)

C-docs **dépend** de C-démo (sous-projet séparé, sa propre spec). Stratégie : écrire tout le *demo-independent* maintenant, baliser le *demo-dependent* en placeholders, construire la démo, puis remplir.

**Demo-independent (écrit maintenant)** : toutes les structures/outlines ; README prose (titre, one-liner, pitch, features, archi, how-it-works via D1, status) ; doc §1, §2, §3 prose+décisions+D2 *schématique*, §4, §5 prose+décisions, §6 description dashboard, §7, §8 ; slides 1-4, 8-11 ; diagrammes D1/D4 ; tooling/layout.

**Demo-dependent (placeholders `[DÉMO-DÉPENDANT: …]`, remplis après la démo)** :
- Fiche de faits : valeurs issues d'un run réel (sous-tâches, tool calls, scores QA, deltas ELO, résultats run d'amélioration) ; nombre de tests final (augmentera avec la démo + tools réels).
- D2 capture d'un vrai run divisé (money shot slides 5).
- D3 narration du vrai run d'amélioration (doc §5, slide 6).
- D5 captures dashboard (doc §6, README hero, slide 7).
- README quickstart : sorties / captures attendues.
- Doc §3 exemple concret de graphe émergent, §5 walkthrough concret du run d'amélioration.

**Convention placeholder** : balise `[DÉMO-DÉPENDANT: description de ce qui ira ici]` visible dans le markdown, retirée au remplissage.

## 9. Découpage & séquencement

Nature C = deux sous-projets :
- **C-docs** (cette spec) — les 3 livrables, design validé.
- **C-démo** (spec séparée, à brainstormer) — un vrai cas complexe reproductible (domaine, tâche cross-domaine multi-agents, tools réels) + un run d'amélioration illustrant fix_target / regression_guard / les 4 attributions / B1-B2-B3.

**Ordre d'implémentation** : (1) C-docs demo-independent + placeholders → (2) C-démo → (3) C-docs : remplir placeholders + captures.

## 10. Critères de done (C-docs)

- `README.md` (EN) en place, quickstart copy-paste fonctionnel.
- `docs/documentation-technique.md` (FR) : 8 sections, décisions inline, D1-D4 intégrés, placeholders demo-dependent balisés.
- `docs/slides/aaosa.md` (Marp FR) : ~11 slides, thème dérivé de `DESIGN.md`, export pptx+pdf vérifié, placeholders balisés.
- Diagrammes D1-D4 en Mermaid versionnés + pré-rendus SVG.
- Tous les placeholders `[DÉMO-DÉPENDANT]` remplis après C-démo (gate final, hors périmètre de la 1re passe).
