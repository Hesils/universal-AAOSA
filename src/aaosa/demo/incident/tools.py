"""Tools de la démo incident — fonctions pures sur le monde simulé.

Contrat : retour str, jamais d'exception (une entrée non matchée retourne un
message explicite — un tool qui lève casserait la boucle tool-use pour rien).
TOOLBOX sert de tool_registry à load_agents (pattern phase 2).
"""

import json
import re
from urllib.parse import parse_qs, urlparse

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


def lookup_cve(query: str) -> str:
    needle = query.lower()
    matches = [
        b for b in load_cve_bulletins()
        if any(needle in str(v).lower() for v in b.values())
    ]
    if not matches:
        return f"no CVE bulletin matches {query!r}"
    return "\n\n".join(json.dumps(b, indent=2) for b in matches)


def count_affected_users(criteria: str) -> str:
    exports = [
        e for e in load_access_logs()
        if "/api/v2/customers/export" in e["path"]
    ]
    if not exports:
        return "no export requests found in access logs"
    pages: set[int] = set()
    size = 0
    for e in exports:
        params = parse_qs(urlparse(e["path"]).query)
        pages.add(int(params.get("page", ["0"])[0]))
        size = max(size, int(params.get("size", ["0"])[0]))
    customers = load_customers()
    affected = min(len(pages) * size, customers["total"])
    return (
        f"Criteria: {criteria}\n"
        f"Export requests found: {len(exports)} (pages {min(pages)}-{max(pages)}, size {size})\n"
        f"Estimated affected customers: {affected} of {customers['total']} total\n"
        f"Exposed PII fields: {', '.join(customers['pii_fields'])}"
    )


def doc_search(query: str) -> str:
    terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 2]
    if not terms:
        return f"no usable search terms in {query!r}"
    scored = []
    for name, content in load_docs().items():
        lower = content.lower()
        title = lower.splitlines()[0] if lower else ""
        score = sum(lower.count(t) + 2 * title.count(t) for t in terms)
        if score > 0:
            scored.append((score, name, content))
    if not scored:
        return f"no documents match {query!r}"
    scored.sort(key=lambda s: (-s[0], s[1]))
    parts = []
    for score, name, content in scored[:2]:
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        hits = [p for p in paragraphs if any(t in p.lower() for t in terms)][:2]
        excerpt = "\n\n".join(hits) if hits else paragraphs[0]
        parts.append(f"--- {name} (score {score}) ---\n{excerpt}")
    return "\n\n".join(parts)


def _tool(name: str, description: str, props: dict, fn) -> ToolDef:
    return ToolDef(
        name=name,
        description=description,
        parameters={"type": "object", "properties": props, "required": list(props)},
        fn=fn,
    )


TOOLBOX: dict[str, ToolDef] = {
    "query_logs": _tool(
        "query_logs",
        "Search the API access logs. Returns entries where any field (ip, path, "
        "status, user_agent, token_sub...) contains the filter substring. "
        "Output is capped at 50 entries.",
        {"filter": {"type": "string"}}, query_logs),
    "inspect_schema": _tool(
        "inspect_schema",
        "Return the DDL of a database table by name. Pass '*' or an unknown "
        "name to list all tables and the application stack.",
        {"table": {"type": "string"}}, inspect_schema),
    "count_affected_users": _tool(
        "count_affected_users",
        "Quantify the data exposure: cross-references customer-export requests "
        "found in the access logs with the customers table to estimate how many "
        "customers and which fields are affected.",
        {"criteria": {"type": "string"}}, count_affected_users),
    "lookup_cve": _tool(
        "lookup_cve",
        "Search known CVE bulletins by package name, CVE id or keyword.",
        {"query": {"type": "string"}}, lookup_cve),
    "doc_search": _tool(
        "doc_search",
        "Search the internal document base (incident procedures, GDPR guidance, "
        "notification templates). Returns the 2 most relevant documents with "
        "matching excerpts.",
        {"query": {"type": "string"}}, doc_search),
    "get_incident_report": _tool(
        "get_incident_report",
        "Return the initial incident ticket as raised by monitoring.",
        {}, get_incident_report),
}
