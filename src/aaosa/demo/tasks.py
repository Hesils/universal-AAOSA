from aaosa.schemas.task import Task

TASK_FIX_CSS_HOVER = Task(
    description="Fix bug CSS hover state not applying on mobile",
    required_tags={"css": 70},
)

TASK_WRITE_PYTHON_TESTS = Task(
    description="Write Python unit tests for the auth module",
    required_tags={"python": 40, "testing": 30},
)

TASK_REFACTOR_REST_API = Task(
    description="Refactor REST API to follow OpenAPI 3.1 spec",
    required_tags={"backend": 80, "python": 70},
)

TASK_SECURITY_AUDIT = Task(
    description="Perform full security audit of the authentication layer",
    required_tags={"security": 80},
)

TASK_OPTIMIZE_SQL = Task(
    description="Optimize slow SQL queries in the reporting module",
    required_tags={"database": 40},
)

TASK_BUILD_DASHBOARD_UI = Task(
    description="Build analytics dashboard UI with charts",
    required_tags={"frontend": 60, "javascript": 50},
)

TASK_DOCUMENT_API = Task(
    description="Write API documentation with examples",
    required_tags={"writing": 30},
    acquirable_tags={"backend": 20},
)

DEMO_TASKS = [
    TASK_FIX_CSS_HOVER,
    TASK_WRITE_PYTHON_TESTS,
    TASK_REFACTOR_REST_API,
    TASK_SECURITY_AUDIT,
    TASK_OPTIMIZE_SQL,
    TASK_BUILD_DASHBOARD_UI,
    TASK_DOCUMENT_API,
]
