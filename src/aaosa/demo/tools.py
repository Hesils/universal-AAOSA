"""Toolbox stubbée déterministe pour la démo V3 (A5).

Les fn retournent des données figées mais réalistes (str). Attachées
programmatiquement (callables non sérialisables → impossibles dans agents.yaml).
"""

from aaosa.core.agent import Agent
from aaosa.core.tool import ToolDef

_FILES = {
    "api/middleware.py": (
        "async def auth_middleware(request, call_next):\n"
        "    token = request.headers.get('Authorization', '').removeprefix('Bearer ')\n"
        "    user = db.execute(f\"SELECT * FROM users WHERE token='{token}'\").fetchone()\n"
        "    # synchronous DB call on every request, no index on token (2M rows)\n"
    ),
    "reporting/queries.py": (
        "SELECT u.name, COUNT(o.id) FROM users u, orders o\n"
        "WHERE u.id = o.user_id GROUP BY u.id;  -- no index on o.user_id\n"
    ),
}


def read_file(path: str) -> str:
    return _FILES.get(path, f"[file not found: {path}]")


def grep_codebase(pattern: str) -> str:
    hits = [f"{p}: matches {pattern!r}" for p, c in _FILES.items() if pattern in c]
    return "\n".join(hits) if hits else f"no matches for {pattern!r}"


def run_tests(path: str) -> str:
    return (
        f"collected 3 items from {path}\n"
        "test_auth_middleware_uses_index PASSED\n"
        "test_reporting_query_fast PASSED\n"
        "test_no_regression PASSED\n"
        "3 passed in 0.42s\n"
    )


def explain_query_plan(sql: str) -> str:
    return (
        "Seq Scan on users  (cost=0.00..38221.00 rows=2000000)\n"
        "Seq Scan on orders (cost=0.00..51234.00 rows=15000000)\n"
        "-> no index used; full table scans on FK columns\n"
        "Recommendation: CREATE INDEX idx_orders_user_id ON orders(user_id);\n"
        "Recommendation: CREATE INDEX idx_users_token ON users(token);\n"
        "Estimated p99 after indexing: < 200ms (currently > 8s)\n"
    )


def _tool(name: str, description: str, props: dict, fn) -> ToolDef:
    return ToolDef(
        name=name,
        description=description,
        parameters={"type": "object", "properties": props, "required": list(props)},
        fn=fn,
    )


TOOLBOX: dict[str, ToolDef] = {
    "read_file": _tool(
        "read_file", "Read the full contents of a source file by path.",
        {"path": {"type": "string"}}, read_file),
    "grep_codebase": _tool(
        "grep_codebase", "Search the codebase for a substring pattern.",
        {"pattern": {"type": "string"}}, grep_codebase),
    "run_tests": _tool(
        "run_tests", "Run the test suite under a given path and return the output.",
        {"path": {"type": "string"}}, run_tests),
    "explain_query_plan": _tool(
        "explain_query_plan", "Return the EXPLAIN plan for a SQL query.",
        {"sql": {"type": "string"}}, explain_query_plan),
}

_ASSIGNMENT: dict[str, list[str]] = {
    "Backend": ["read_file", "grep_codebase", "run_tests", "explain_query_plan"],
    "Frontend": ["read_file", "grep_codebase"],
    "Fullstack": ["read_file", "run_tests"],
    "DevOps": ["read_file"],
}


def attach_tools(agents: list[Agent]) -> None:
    """Mute agent.tools en place selon le nom (identifiant stable)."""
    for agent in agents:
        names = _ASSIGNMENT.get(agent.name, [])
        agent.tools = [TOOLBOX[n] for n in names]
