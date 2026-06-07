"""Scénarios de la démo incident — données pures, zéro runtime.

main : tâche fuite de données, roster complet (7 agents).
roster_gap : même tâche, roster privé du dpo-jurist — le gap émerge du
claiming (sous-tâche réglementaire unclaimable), jamais du scénario.
"""

from aaosa.core.agent import Agent
from aaosa.demo.incident.agents import INCIDENT_AGENTS
from aaosa.schemas.task import Task

_ALERT_CONTEXT = (
    "Monitoring alert 2026-06-06 06:30 UTC: anomalous nighttime traffic on "
    "/api/v2/customers/export. Full ticket available via the "
    "get_incident_report tool."
)


def build_data_leak_task() -> Task:
    return Task(
        description=(
            "Anomalous traffic was detected on the customers API last night. "
            "Determine whether customer data was leaked, assess the scope of "
            "the breach, qualify our regulatory obligations, and prepare the "
            "customer communication."
        ),
        required_tags={"security": 70, "gdpr": 70, "communication": 65},
        context=_ALERT_CONTEXT,
    )


def full_roster() -> list[Agent]:
    return list(INCIDENT_AGENTS)


def roster_gap_roster() -> list[Agent]:
    return [a for a in INCIDENT_AGENTS if a.name != "dpo-jurist"]
