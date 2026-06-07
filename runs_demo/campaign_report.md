# Rapport de campagne — scénario `main`

- Runs demandés : 20
- Runs exécutés : 20
- Période : 2026-06-07T20:40:15.181462+00:00 → 2026-06-07T21:29:02.616802+00:00

## Outcomes

- success : 16/20 (80%)
- qa_fail : 0/20 (0%)
- unassigned : 0/20 (0%)
- error : 4/20 (20%)

## Typologies

- simple : 0
- divided : 16
- recursion : 3
- roster_gap : 0
- diagnosed:agent : 5
- diagnosed:evaluator : 0
- diagnosed:task_spec : 0
- diagnosed:unattributed : 0
- aggregated : 0

## Observation aggregator (ticket divider)

**0/20 runs avec `TaskAggregatedEvent` réel.**
Critère du ticket divider non atteint sur cette campagne (aucun fan-in agrégé — cf. docs/backlog/2026-06-07-divider-topologie-aggregator.md).

## Runs

| i | session | outcome | typologies | durée |
|---|---------|---------|------------|-------|
| 1 | 2026-06-07T20-40-15-0e5cf438 | success | divided | 132.6s |
| 2 | 2026-06-07T20-42-27-d4e1c26a | success | divided, diagnosed:agent | 161.1s |
| 3 | 2026-06-07T20-45-08-ce926a54 | success | divided, recursion | 238.0s |
| 4 | 2026-06-07T20-49-06-4c67f2a9 | success | divided | 135.3s |
| 5 | 2026-06-07T20-51-22-8d1eaafd | success | divided, diagnosed:agent | 164.9s |
| 6 | 2026-06-07T20-54-07-6cf53b78 | success | divided | 138.3s |
| 7 | 2026-06-07T20-56-25-e4786791 | success | divided, diagnosed:agent | 105.1s |
| 8 | 2026-06-07T20-58-10-a7318a88 | success | divided | 116.5s |
| 9 | — | error | — | 7.7s |
| 10 | 2026-06-07T21-00-14-81e79003 | success | divided, diagnosed:agent | 176.7s |
| 11 | 2026-06-07T21-03-11-0e5ceae1 | success | divided | 133.0s |
| 12 | — | error | — | 6.7s |
| 13 | 2026-06-07T21-05-31-496e0d00 | success | divided | 140.7s |
| 14 | 2026-06-07T21-07-51-92b82f5f | success | divided, recursion, diagnosed:agent | 624.3s |
| 15 | 2026-06-07T21-18-16-bd808936 | success | divided, recursion | 259.2s |
| 16 | — | error | — | 7.1s |
| 17 | 2026-06-07T21-22-42-cd091028 | success | divided | 120.1s |
| 18 | 2026-06-07T21-24-42-8b1aaa9b | success | divided | 130.1s |
| 19 | 2026-06-07T21-26-52-f49d22f8 | success | divided | 123.6s |
| 20 | — | error | — | 6.4s |

- run 9 error : cycle detected in task dependencies
- run 12 error : cycle detected in task dependencies
- run 16 error : cycle detected in task dependencies
- run 20 error : cycle detected in task dependencies

## Delta ELO (premier → dernier snapshot)

| agent | tag | départ | arrivée | delta |
|-------|-----|--------|---------|-------|
| backend-dev | backend | 85 | 85 | +0 |
| backend-dev | database | 80 | 80 | +0 |
| backend-dev | investigation | 65 | 65 | +0 |
| backend-dev | logs | 70 | 70 | +0 |
| client-comm | communication | 90 | 95 | +5 |
| client-comm | customer_relations | 82 | 95 | +13 |
| client-comm | writing | 85 | 95 | +10 |
| data-analyst | data_analysis | 88 | 88 | +0 |
| data-analyst | database | 70 | 70 | +0 |
| data-analyst | reporting | 75 | 75 | +0 |
| dpo-jurist | compliance | 90 | 95 | +5 |
| dpo-jurist | gdpr | 92 | 95 | +3 |
| dpo-jurist | legal | 87 | 95 | +8 |
| security-analyst | investigation | 81 | 95 | +14 |
| security-analyst | logs | 76 | 95 | +19 |
| security-analyst | security | 92 | 95 | +3 |
| security-analyst | vulnerability | 85 | 85 | +0 |
| sre | access_control | 70 | 70 | +0 |
| sre | infrastructure | 85 | 85 | +0 |
| sre | investigation | 60 | 60 | +0 |
| sre | logs | 75 | 75 | +0 |
| support-lead | communication | 70 | 70 | +0 |
| support-lead | customer_relations | 85 | 85 | +0 |
| support-lead | support | 90 | 90 | +0 |

## Rejeu

- Dashboard (sessions + courbes ELO complètes) : `aaosa dashboard --runs-root runs_campaign_n20`
