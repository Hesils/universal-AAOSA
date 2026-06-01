# V3 — Épique B4 — Sidecar advisory (stats agrégées)

- **Couche** : `src/aaosa/sidecar/` (nouveau package)
- **Statut** : deep-dive terminé → prêt pour plan + exécution
- **Dépendances** : aucune (réutilise l'existant)
- **Roadmap** : section V3, épique B4

---

## Contexte

Les stats système existent mais sont **dispersées et inaccessibles au runtime** :

| Stat | Où elle vit aujourd'hui |
|---|---|
| Claim rate / win rate | `detect_overclaims/underclaims` (analysis.py) — per-session, pas agrégé |
| QA pass rate | `InfraStats.qa_pass_rate` (dashboard/infra.py) — dashboard only |
| Latence | `InfraStats.latency` (dashboard/infra.py) — mean/min/max seulement, pas p50/p99 |
| ELO courant | `AgentDetailView.tags_with_elo` (dashboard/agents.py) — dashboard only |
| AgentActivity | `dashboard/collectors/agents.py` — claims/wins/successes/failures en brut |

B4 crée un module runtime `src/aaosa/sidecar/` qui agrège tout ça en un `SystemAdvisory`
Pydantic calculable à la demande depuis `runs/`. **Prérequis de B5** (agents qui consultent
le sidecar avant de claim).

---

## Ce qui ne change pas

- `analysis.py` : `detect_overclaims`/`detect_underclaims` réutilisés tels quels (par session)
- `dashboard/collectors/` : inchangés (concern dashboard)
- `src/aaosa/qa/health_check.py` : inchangé
- Tous les tests existants : inchangés

---

## Décisions

| Question | Décision | Justification |
|---|---|---|
| Emplacement | `src/aaosa/sidecar/advisory.py` | Nouveau package `sidecar/` — concern distinct de tracing/qa/dashboard ; B5 importera depuis `sidecar/` |
| Input | `build_advisory(runs_root: Path) -> SystemAdvisory` | Même source que les collectors dashboard — `runs/` persisté |
| Persistance | Aucune — calculé à la demande | B5 décide du caching. B4 = calcul pur depuis fichiers |
| Agents inclus | Tous les agents du registry, même inactifs (stats à 0) | Le registry est la source authoritative ; un agent sans runs apparaît avec rates à 0 |
| Latence p50/p99 | `sorted(latencies)[int(n * p/100)]` sur toutes les sessions | Améliore `InfraStats` (mean/min/max) avec des percentiles robustes |
| Overclaim/underclaim | Réutilise `detect_overclaims`/`detect_underclaims` par session, accumule | Ne duplique pas la logique — juste l'agrégation |
| Health check | `health_check_count` + `avg_fix_target_pass_rate` + `avg_regression_guard_pass_rate` dans `SystemAdvisory` | Réutilise `report.json` des health_checks persistés — valeur ajoutée sans complexité |
| `unassigned_rate` | `UnassignedEvent count / (DispatchedEvent count + UnassignedEvent count)` | Fraction de tâches sans agent — signal d'alerte roster |

---

## Seams confirmés

| Fichier | Rôle dans B4 |
|---|---|
| `src/aaosa/sidecar/__init__.py` | Nouveau — vide |
| `src/aaosa/sidecar/advisory.py` | Nouveau — `AgentAdvisory`, `SystemAdvisory`, `build_advisory` |
| `src/aaosa/tracing/analysis.py` | Importé (detect_overclaims/underclaims) — **inchangé** |
| `src/aaosa/tracing/store.py` | Importé (`load_trace`, `AgentRegistry`) — **inchangé** |
| `src/aaosa/qa/health_check.py` | `HealthCheckReport` lu depuis disque — **inchangé** |

---

## Schémas

```python
# src/aaosa/sidecar/advisory.py

class AgentAdvisory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    agent_name: str
    current_elo: dict[str, int]        # depuis registry
    claim_rate: float                  # Phase2 "claim" / total Phase2 pour cet agent
    win_rate: float                    # DispatchedEvent / total claims
    qa_success_rate: float             # QAEvaluated success / total QAEvaluated
    overclaim_rate: float              # overclaims / total claims (analysis.py)
    underclaim_rate: float             # underclaims / Phase1 passes-with-no_claim
    avg_latency_ms: float | None       # moyenne latence sur ExecutedEvent (cet agent)


class SystemAdvisory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generated_at: datetime
    total_tasks: int                   # DispatchedEvent + UnassignedEvent
    unassigned_rate: float             # UnassignedEvent / total_tasks
    qa_pass_rate: float | None         # global cross-session
    latency_p50_ms: float | None       # p50 sur toutes les ExecutedEvent
    latency_p99_ms: float | None       # p99 sur toutes les ExecutedEvent
    health_check_count: int            # runs health check persistés
    avg_fix_target_pass_rate: float | None
    avg_regression_guard_pass_rate: float | None
    agents: list[AgentAdvisory]
```

---

## Logique de `build_advisory`

```
build_advisory(runs_root):

  1. Charger le registry (agents/ registry.json)
     → dict agent_id → {name, current_elo}
     → Si absent : SystemAdvisory vide (tous les compteurs à 0 / None)

  2. Initialiser accumulateurs par agent_id :
     {phase2_total, phase2_claims, dispatched, qa_total, qa_pass,
      overclaim_count, underclaim_count, phase1_pass_total, latencies}

  3. Initialiser accumulateurs système :
     {total_dispatched, total_unassigned, qa_total, qa_pass, latencies}

  4. Pour chaque session dans runs/sessions/ (trace.jsonl) :
     a. Charger les events via load_trace(trace_path)
     b. Passer les events à detect_overclaims / detect_underclaims
        → accumuler par agent_id : overclaim_count, underclaim_count
     c. Itérer les events :
        - Phase2ClaimedEvent → phase2_total[agent]++
                               phase2_claims[agent]++ si "claim"
        - DispatchedEvent    → dispatched[agent]++, total_dispatched++
        - UnassignedEvent    → total_unassigned++
        - ExecutedEvent      → si llm_metadata : latencies (système + agent)
        - QAEvaluatedEvent   → qa_total/pass (système + agent)
        - Phase1FilteredEvent(passed=True) + Phase2ClaimedEvent(no_claim) :
          → underclaim source (déjà dans detect_underclaims)

  5. Pour chaque health check dans runs/health_checks/ (report.json) :
     → lire HealthCheckReport.fix_target_pass_rate + regression_guard_pass_rate
     → accumuler pour moyenne

  6. Calculer les rates :
     - claim_rate    = phase2_claims[a] / phase2_total[a]  (ou 0 si 0)
     - win_rate      = dispatched[a] / phase2_claims[a]    (ou 0 si 0)
     - qa_success_rate = qa_pass[a] / qa_total[a]          (ou 0 si 0)
     - overclaim_rate  = overclaim_count[a] / phase2_claims[a]
     - underclaim_rate = underclaim_count[a] / phase2_total[a]
       (normaliser sur phase2_total : proportion de cas où l'agent aurait pu claim et ne l'a pas fait)
     - unassigned_rate = total_unassigned / (total_dispatched + total_unassigned)

  7. p50/p99 : sorted(all_latencies)[int(n * p/100)]

  8. Construire SystemAdvisory
```

---

## Helper percentile

```python
def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    sv = sorted(values)
    idx = max(0, min(int(len(sv) * p / 100), len(sv) - 1))
    return sv[idx]
```

Utilisé pour p50 (`p=50`) et p99 (`p=99`).

---

## Stratégie de test (TDD)

**`tests/sidecar/test_advisory.py`** (8 tests) :

- `test_agent_advisory_valid` : construction + roundtrip JSON (`AgentAdvisory`)
- `test_system_advisory_valid` : construction + roundtrip JSON (`SystemAdvisory`)
- `test_build_advisory_empty_runs` : `runs_root` sans sessions → `SystemAdvisory` cohérent (0/None)
- `test_build_advisory_claim_rate` : trace fictive avec 2 Phase2 (1 claim, 1 no_claim) → `claim_rate=0.5`
- `test_build_advisory_win_rate` : claim + DispatchedEvent → `win_rate=1.0`
- `test_build_advisory_qa_success_rate` : 2 QAEvaluated (1 success) → `qa_success_rate=0.5`
- `test_build_advisory_latency_percentiles` : latences connues [10, 20, 30, 40, 50, 60, 70, 80, 90, 100] → p50≈50, p99≈100
- `test_build_advisory_unassigned_rate` : 1 dispatched + 1 unassigned → `unassigned_rate=0.5`

Les tests utilisent des fichiers temporaires (`tmp_path`) pour simuler la structure `runs/`.

---

## Critères de done

- [ ] `src/aaosa/sidecar/__init__.py` + `advisory.py` créés
- [ ] `AgentAdvisory` + `SystemAdvisory` Pydantic (`extra="forbid"`)
- [ ] `build_advisory(runs_root) -> SystemAdvisory` : toutes les stats correctes
- [ ] p50/p99 : calculé sur les latences de `ExecutedEvent.llm_metadata`
- [ ] `detect_overclaims`/`detect_underclaims` réutilisés tels quels
- [ ] Health check stats : lus depuis `runs/health_checks/*/report.json`
- [ ] `analysis.py`, `health_check.py`, `dashboard/collectors/` : zéro modification
- [ ] `tests/sidecar/test_advisory.py` : 8 tests verts avec `tmp_path`
- [ ] Suite complète ≥ 656 + 8 = **664 tests verts** (après A1+B1+A3+A4+A5+B2+B3)

---

## Questions tranchées ici

1. **Pourquoi un nouveau package `sidecar/` plutôt qu'étendre `tracing/analysis.py` ?**
   `analysis.py` est per-session (input = liste d'events). Le sidecar agrège cross-session
   depuis le disque — concern distinct. B5 importera `from aaosa.sidecar.advisory import
   build_advisory` : l'import doit être clair sur la frontière runtime/dashboard.

2. **Pourquoi ne pas cacher le `SystemAdvisory` en mémoire ou sur disque ?**
   Hors scope B4. Le caching (TTL, invalidation) est une décision B5 : soit il calcule à
   chaque claim (acceptable si `runs/` est petit), soit il maintient un cache avec TTL
   configurable. B4 fournit le calcul, B5 décide de la politique.

3. **`underclaim_rate` normalisé sur `phase2_total` (pas sur `phase1_pass`) ?**
   Les données Phase1 par agent ne sont pas facilement séparables de `detect_underclaims`
   sans dupliquer la logique. Normaliser sur `phase2_total` donne une fraction interprétable :
   "quelle fraction de mes sessions de Phase2 finissent en under-claim ?" Cohérent avec les
   autres rates. Si la normalisation doit changer, le test pinne la valeur exacte.

4. **Les agents sans aucun event dans les traces — quelle ELO exposer ?**
   `current_elo` vient du registry (état courant), pas des traces. Un agent sans event a
   bien une ELO dans le registry (bootstrap). Les rates sont tous à 0.0. C'est le comportement
   correct — l'agent est connu mais n'a jamais participé.

5. **p99 sur un petit corpus (<100 latences) — est-ce significatif ?**
   Non — mais c'est intentionnel. Le sidecar est honnête : il calcule ce qu'il peut sur ce
   qu'il a. Un p99 sur 5 points n'est pas robuste, mais il vaut mieux l'exposer que le cacher.
   L'interprétation est à la charge du caller (B5 peut ignorer p99 si `len(latencies) < 20`).
