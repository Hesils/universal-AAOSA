"""Tools de la démo incident — fonctions pures sur le monde simulé.

Contrat : retour str, jamais d'exception (une entrée non matchée retourne un
message explicite — un tool qui lève casserait la boucle tool-use pour rien).
TOOLBOX sert de tool_registry à load_agents (pattern phase 2).
"""

import json
import re

from aaosa.core.tool import ToolDef
from aaosa.demo.incident.world import (
    load_access_logs,
    load_customers,
    load_cve_bulletins,
    load_db_schema,
    load_docs,
)

_MAX_LOG_LINES = 50

_INCIDENT_REPORT = """\
INCIDENT TICKET #2026-0606-01 - opened 2026-06-06 06:30 UTC by monitoring
Severity: to be assessed

Anomalous traffic detected on the customer-management API during the night
of 2026-06-05 to 2026-06-06: unusual volume of requests on
/api/v2/customers/export between roughly 02:00 and 04:00 UTC, originating
from outside our usual office/VPN ranges. This endpoint normally serves a
handful of requests per week from the internal reporting job.

Open questions: was data actually exfiltrated, by whom and how, how many
customers and which fields are affected, what are our regulatory
obligations, and what do we tell affected customers?

Access logs, DB schema and the internal document base are available
through your tools.
"""


def query_logs(filter: str) -> str:
    needle = filter.lower()
    matches = [
        e for e in load_access_logs()
        if any(needle in str(v).lower() for v in e.values())
    ]
    if not matches:
        return f"no entries match {filter!r}"
    shown = matches[:_MAX_LOG_LINES]
    header = f"{len(matches)} matching entries (showing first {len(shown)}):"
    return "\n".join([header, *(json.dumps(e) for e in shown)])


_TABLE_RE = re.compile(r"CREATE TABLE (\w+) \([^;]*?\);", re.DOTALL)


def inspect_schema(table: str) -> str:
    schema = load_db_schema()
    tables = {m.group(1): m.group(0) for m in _TABLE_RE.finditer(schema)}
    if table in tables:
        return tables[table]
    header = "\n".join(line for line in schema.splitlines() if line.startswith("--"))
    return f"{header}\nTables: {', '.join(sorted(tables))}"


def get_incident_report() -> str:
    return _INCIDENT_REPORT
