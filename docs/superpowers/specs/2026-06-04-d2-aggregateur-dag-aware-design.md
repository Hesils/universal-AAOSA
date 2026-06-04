# D2 — Agrégateur DAG-aware (agrégation finale par sinks)

Date : 2026-06-04
Statut : design validé, prêt pour `writing-plans`
Dépend de : D1 (division émergente récursive, mergé master `feat/v3-d1`)

## 1. Problème

Après D1, quand un noeud ne peut pas être réclamé à plat, il se divise : `run_with_recovery`
divise la tâche, `run_chain` exécute les sous-tâches (qui forment un DAG via `depends_on`),
puis l'agrégateur synthétise les outputs réussis.

La forme actuelle de l'agrégateur (`run_with_recovery`) aplatit **tous** les outputs réussis
dans un seul prompt et **ignore le DAG** :

```python
successful = [r for r in sub_results if isinstance(r, Output)]
...
return ctx.aggregator.aggregate(task, successful, ctx.client, ctx.tracer)
```

Deux défauts structurels :

1. **Double comptage en chaîne.** Pour une division `investigate → analyze → fix`, l'agent de
   `fix` a déjà reçu l'output de `analyze` comme contexte requis (`required_outputs`, injecté
   dans son prompt par `agent._build_user_content`), qui avait reçu `investigate`. Passer
   `[investigate, analyze, fix]` à plat à l'agrégateur recompte toute la chaîne.
2. **Appel LLM inutile.** Une chaîne qui se résout en un seul résultat terminal n'a rien à
   « synthétiser » ; l'agrégateur tourne quand même, avec un coût et un risque de distorsion.

### Cadrage retenu (ce que D2 N'EST PAS)

La récursion D1 produit **déjà** l'arbre bottom-up : chaque appel `run_with_recovery` renvoie
exactement un `Output` (éventuellement lui-même une agrégation), qui remonte comme un élément de
la liste `successful` du parent. La structure « frères → parent » à travers les niveaux est donc
acquise. D2 ne construit **pas** de nouvelle machinerie d'arbre. D2 corrige uniquement le
**contrat de fan-in à un seul niveau** : quels outputs frères agréger, et comment.

> **Décision — Rôle de l'agrégateur.** L'idée initiale d'un agrégateur « magasin » (collecter
> les outputs et les passer au prochain agent) est déjà réalisée : le dict `outputs` de
> `run_chain` est ce blackboard, `required_outputs` en est le mécanisme de lecture. L'idée d'un
> agrégateur « curateur de contexte aval » (synthétiser les `required_outputs` avant de nourrir
> le prochain agent, pour éviter le sur-contexte) est **déférée** : aujourd'hui seuls les deps
> **directs** circulent (pas d'accumulation transitive), le consommateur est le meilleur juge de
> pertinence, et un curateur par arête est un intermédiaire lossy résolvant un problème
> spéculatif. À réévaluer si un run réel montre un goulot de fan-in large. L'agrégateur reste
> donc le **synthétiseur final** uniquement.

## 2. Mécanisme central — les sinks

À un fan-in (l'ensemble des sous-tâches frères d'une même division), on remplace
« tous les frères réussis, à plat » par « les **sinks** du sous-DAG des frères réussis ».

**Définition.** Une sous-tâche frère réussie `S` est un **sink** quand aucune sous-tâche frère
**réussie** ne dépend de `S`.

Justification : si `T` dépend de `S` et `T` a réussi, alors l'agent de `T` a déjà reçu `S`
comme contexte requis, donc `S` est replié dans `T`. Seuls les résultats terminaux non consommés
sont « lâches » et doivent être fusionnés.

**Propriétés** (toutes exploitées par le design) :

- **Les sinks forment une antichaîne.** Si un sink `B` dépendait d'un sink `C`, alors `C` serait
  consommé par un noeud réussi et ne serait pas un sink. Les sinks ne dépendent donc jamais les
  uns des autres : ce sont des pairs. L'agrégateur fusionne des pairs, aucune structure de DAG
  n'a besoin d'apparaître dans son prompt.
- **Au moins un sink dès qu'il y a un succès.** Un DAG non vide possède toujours un élément
  maximal (sans dépendant). Donc `≥1` frère réussi ⟹ `≥1` sink. Le test existant
  `if not successful: unassigned` couvre le cas vide ; sinon le nombre de sinks est `≥ 1`.
- **L'échec partiel est géré.** Si l'étape de fusion finale a échoué, ses entrées ne sont plus
  « consommées par un noeud réussi » et réapparaissent comme sinks : elles sont fusionnées au
  lieu d'être silencieusement perdues.

### Exemples (✓ = succès, ✗ = échec)

```
investigate✓ → analyze✓ → fix✓            sinks = {fix}                 (chaîne : dernière étape)
parse_logs✓   check_db✓  (indépendants)    sinks = {parse_logs, check_db} (vraie fusion)
A✓→B✓→D✓, A✓→C✓→D✓ (diamant)            sinks = {D}                   (D replie B,C ; B,C replient A)
A✓→B✓→D✗, A✓→C✓→D✗ (fusion échouée)     sinks = {B, C}                (D a échoué → fusionner ses entrées)
```

## 3. Comportement du fan-in

Dans `run_with_recovery`, après `run_chain` :

| Cas | Comportement |
| --- | --- |
| 0 frère réussi | `DispatchResult(status="unassigned", reason="no sub-tasks recovered")` (inchangé) |
| 1 sink | **court-circuit** : renvoyer l'`Output` du sink tel quel. Aucun appel LLM, aucun `TaskAggregatedEvent` |
| ≥2 sinks | `ctx.aggregator.aggregate(task, sinks, ...)` : synthèse LLM des sinks (pairs) |

> **Décision — Court-circuit à un seul sink.** Renvoyer le sink tel quel (pas d'agrégation).
> Raisons : pas de coût LLM, pas de distorsion d'une chaîne triviale, résultat fidèle (aucune
> agrégation n'a eu lieu). Si un re-cadrage au niveau parent est souhaité, la décomposition doit
> contenir une étape finale « report/synthesize » qui devient alors le sink. La décomposition
> exprime donc le besoin de cadrage, on ne le force pas par défaut.

> **Décision — Identité du court-circuit.** Le sink est renvoyé **inchangé** : son `agent_id`
> réel et son propre `task_id`. `run_chain` le stocke sous l'id de la tâche de boucle
> (`outputs[task.id] = result`), donc le chaînage reste correct ; le `task_id` interne de
> l'objet (un id d'enfant) n'est qu'une étiquette sans conséquence. Pas de `model_copy`. Le
> sentinel `agent_id="aggregator"` reste réservé à l'agrégateur réel (≥2 sinks), conforme à la
> séparation V3 (l'output de l'agrégateur porte le sentinel, jamais un UUID).

## 4. Plumbing (changements de code)

### 4.1 `runtime/runner.py`

- **`run_chain` change de type de retour.** Il renvoie aujourd'hui une liste plate
  (`list[Output | DispatchResult | QAFailure]`) qui perd l'association tâche↔output. Il
  renverra les outputs réussis indexés par id de tâche : `dict[str, Output]` (ordre
  d'insertion = ordre topologique). Les échecs ne sont pas nécessaires dans le retour : ils sont
  déjà tracés pendant l'exécution (events émis dans `run_task`). `run_chain` reste interne à la
  récursion (seul `run_with_recovery` l'appelle), donc ce changement est contenu. Met à jour les
  tests D1 de `run_chain`.
- **Nouveau helper pur `_sinks(sub_tasks, outputs_by_id) -> list[Output]`.** Calcule les sinks
  comme défini en §2, dans l'ordre de `sub_tasks` (ordre du divider). Pas d'effet de bord, pas
  d'appel LLM. Esquisse :

  ```python
  def _sinks(sub_tasks: list[Task], outputs_by_id: dict[str, Output]) -> list[Output]:
      succeeded = set(outputs_by_id)
      consumed = {
          dep
          for t in sub_tasks if t.id in succeeded
          for dep in t.depends_on if dep in succeeded
      }
      return [outputs_by_id[t.id] for t in sub_tasks if t.id in succeeded and t.id not in consumed]
  ```

- **`run_with_recovery` branche sur le nombre de sinks** (remplace le bloc `successful`/`aggregate`) :

  ```python
  outputs_by_id = run_chain(sub_tasks, ctx, depth + 1)
  if not outputs_by_id:
      return DispatchResult(status="unassigned", agent_id=None, reason="no sub-tasks recovered")
  sinks = _sinks(sub_tasks, outputs_by_id)
  if len(sinks) == 1:
      return sinks[0]
  try:
      return ctx.aggregator.aggregate(task, sinks, ctx.client, ctx.tracer)
  except Exception:
      return sinks[-1]
  ```

  Le fallback sur exception de l'agrégateur (`sinks[-1]`) est conservé (miroir du comportement D1
  `successful[-1]`), borné aux sinks.

### 4.2 `runtime/aggregator.py`

- Signature de `aggregate` **inchangée** : elle prend déjà une `list[Output]`. On lui passe les
  sinks au lieu de tous les réussis.
- Prompt resserré : indiquer que les résultats fournis sont **complémentaires** (chacun couvre
  une partie de la tâche d'origine) et demander une réponse unique qui les couvre tous. Pas de
  structure de DAG dans le prompt (les sinks sont des pairs).
- `TaskAggregatedEvent.sub_task_ids` devient l'ensemble des ids de sinks (sous-ensemble des
  réussis) — automatique, puisqu'il est construit depuis `sub_outputs`.

## 5. Observabilité (`dashboard/graph_model.py`)

Deux conséquences dans `_milestones_divided`. Le contrat de données frontend (formes
`GraphStep` / `*Detail`) ne change pas ; seules les valeurs et le câblage des jalons changent.
Travail dans `build_graph`, donc testable (cœur pur).

- **Multi-sink (≥2).** `TaskAggregatedEvent.sub_task_ids` ne liste que les sinks ; le noeud
  `aggregator` ne se connecte donc qu'aux sinks. Le récit progressif « collected/total » (qui
  compte aujourd'hui chaque `qa_pass`) doit compter les **sinks** : `total = nombre de sinks`,
  l'agrégateur ne « collecte » que les sous-tâches sinks. Les sous-tâches intermédiaires
  s'allument comme aujourd'hui mais ne nourrissent pas l'agrégateur (elles sont consommées par
  leurs dépendants).
- **Single-sink (court-circuit).** Aucun `TaskAggregatedEvent` n'est émis. Le code actuel saute
  alors les jalons `aggregator` **et** `output`, laissant un run divisé sans sortie terminale.
  Correctif : rendre le jalon **OUTPUT terminal depuis le sink** (l'output produit par l'agent
  du sink), **sans** noeud `aggregator`. C'est l'image honnête : aucune agrégation n'a eu lieu.

> **Décision — Détecter les sinks côté dashboard.** `build_graph` reconstruit les sinks depuis
> les sous-tâches divisées (`TaskDividedEvent.sub_tasks`, qui portent `depends_on`) et les
> issues des sous-runs (`qa_pass`), avec la même règle qu'en §2. Single-sink se détecte par
> l'absence de `TaskAggregatedEvent` combinée à un unique sink réussi ; multi-sink par la
> présence de l'event. La règle de sink vit donc en deux endroits (runtime + build_graph) mais
> reste une fonction pure simple ; on accepte la légère duplication plutôt qu'un couplage data.

## 6. Heads-up démo (hors scope, à noter)

`run_demo_v3` divise aujourd'hui en une chaîne de dépendances se terminant par une étape de
synthèse. Sous l'agrégation par sinks, c'est un **seul sink** : le run court-circuitera et le
« showpiece » d'agrégation de 6 outputs disparaîtra. C'est **correct** (la chaîne était
double-comptée) : la vraie agrégation ne s'illumine que quand une division a des **branches
parallèles** indépendantes (plusieurs sinks). C'est une meilleure démonstration de « le graphe
émerge », et elle relève de la future **C-démo** (un cas cross-domaine avec fan-out/fan-in
réel), pas d'un trucage ici. Le divider étant un appel LLM, la forme exacte reste émergente :
l'agrégation pourra encore se déclencher si le LLM produit des branches parallèles.

## 7. Hors scope / déféré

- **Curation de contexte aval (Job 2)** : synthétiser les `required_outputs` avant le prochain
  agent. Déféré (cf. décision §1).
- **Exécution parallèle des branches indépendantes** : prérequis durs Gap 5 (ELO mute intra-run)
  + Gap 13 (events entrelacés). Hors D2.
- **C-démo à branches parallèles** : matériel nature C, spec séparée.

## 8. Tests (critères vérifiables)

- `_sinks` (pur) sur les 4 formes de §2 : chaîne (1 sink = dernière), parallèle (n sinks), diamant
  convergent (1 sink), diamant à fusion échouée (sinks = entrées de la fusion).
- `_sinks` : un frère réussi consommé par un frère **échoué** est un sink ; consommé par un frère
  **réussi**, non.
- Fan-in 1 sink → aucun appel à `aggregator.aggregate` (mock/spy), renvoie l'`Output` du sink
  inchangé (même `agent_id`).
- Fan-in ≥2 sinks → `aggregate` appelé avec exactement les sinks (pas les intermédiaires).
- Fan-in 0 réussi → `unassigned` (régression).
- `run_chain` renvoie `dict[str, Output]` des réussis indexés par id (mise à jour des tests D1).
- `build_graph` : run divisé single-sink → jalon OUTPUT terminal depuis le sink, pas de noeud
  `aggregator`. Run divisé multi-sink → `aggregator` connecté aux sinks, `total`/`collected`
  comptent les sinks.

## 9. Séparations strictes préservées

- L'agrégateur n'est pas un Agent (pas de `claim`, pas d'ELO) ; son output réel porte le sentinel
  `agent_id="aggregator"`. Le court-circuit n'est **pas** l'agrégateur : il renvoie l'output réel
  d'un agent, donc garde son `agent_id` réel — pas de violation du sentinel.
- `run_task` reste la frontière unique de containment, **inchangée**.
- Le divider reste purement structurel (zéro tags, zéro agrégation). Le tagger reste pur.
- `build_graph` reste une fonction pure ; le graphe ne montre que le pipeline réel (un noeud
  `aggregator` n'apparaît que s'il y a eu un `TaskAggregatedEvent` réel).
