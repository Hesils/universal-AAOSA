from aaosa.schemas.task import Task

TASK_FIX_CSS_HOVER = Task(
    description="Fix bug: CSS hover state not applying on mobile",
    required_tags={"css": 70},
    metadata={"context": """\
/* components/Button.css */
.btn {
  background: #007bff;
  color: white;
  padding: 8px 16px;
  border-radius: 4px;
}
/* hover works on desktop but is ignored on touch devices */
.btn:hover {
  background: #0056b3;
}
/* reported on iOS Safari 16 and Android Chrome 112 */"""},
)

TASK_WRITE_PYTHON_TESTS = Task(
    description="Write Python unit tests for the auth module (authenticate + generate_token)",
    required_tags={"python": 40, "testing": 30},
    metadata={"context": """\
# auth/service.py
def authenticate(username: str, password: str) -> bool:
    user = db.get_user(username)
    if not user:
        return False
    return check_password(password, user.password_hash)

def generate_token(user_id: str, expires_in: int = 3600) -> str:
    payload = {"sub": user_id, "exp": time.time() + expires_in}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")"""},
)

TASK_REFACTOR_REST_API = Task(
    description="Refactor user endpoints to comply with OpenAPI 3.1 (proper status codes, schema validation, no raw SQL)",
    required_tags={"backend": 80, "python": 70},
    metadata={"context": """\
# api/users.py — current non-compliant implementation
@app.route("/users", methods=["GET"])
def get_users():
    return jsonify(db.query("SELECT * FROM users"))  # no pagination, exposes all fields

@app.route("/users/<id>", methods=["DELETE"])
def delete_user(id):
    db.execute(f"DELETE FROM users WHERE id={id}")  # SQL injection risk
    return "", 204  # should be 200 with body or 404 if not found"""},
)

TASK_SECURITY_AUDIT = Task(
    description="Perform full security audit of the authentication middleware",
    required_tags={"security": 80},
    metadata={"context": """\
# auth/middleware.py
def verify_token(token: str) -> dict:
    # signature verification disabled for "performance"
    return jwt.decode(token, options={"verify_signature": False})

SESSION_SECRET = "password123"  # hardcoded in source
_sessions: dict = {}            # in-memory, no expiry, no invalidation"""},
)

TASK_OPTIMIZE_SQL = Task(
    description="Optimize slow SQL queries in the reporting module (p99 > 8s on production)",
    required_tags={"database": 40},
    metadata={"context": """\
-- reporting/queries.py  (2M users, 15M orders, 60M order_items — no indexes on FK columns)
SELECT u.name, u.email, COUNT(o.id) AS order_count, SUM(oi.price) AS total_spent
FROM users u, orders o, order_items oi
WHERE u.id = o.user_id
  AND o.id = oi.order_id
  AND o.created_at > '2024-01-01'
GROUP BY u.id
ORDER BY total_spent DESC;
-- EXPLAIN shows: full table scan on all three tables, no index usage"""},
)

TASK_BUILD_DASHBOARD_UI = Task(
    description="Build analytics dashboard: revenue bar chart + daily active users line chart using Chart.js",
    required_tags={"frontend": 60, "javascript": 50},
    metadata={"context": """\
<!-- dashboard.html — placeholder only, charts not yet implemented -->
<div id="revenue-chart" style="height:300px"></div>
<div id="dau-chart"     style="height:300px"></div>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
// API available: GET /api/stats/revenue?period=30d  → [{date, amount}]
//                GET /api/stats/dau?period=30d       → [{date, count}]
// TODO: fetch both endpoints, render bar + line charts, handle loading/error states
</script>"""},
)

TASK_DOCUMENT_API = Task(
    description="Write API reference documentation with request/response examples for the public endpoints",
    required_tags={"writing": 30},
    acquirable_tags={"backend": 20},
    metadata={"context": """\
# api/endpoints.py — 4 undocumented public endpoints
@app.post("/auth/login")          # body: {username, password} → {token, expires_at}
def login(body: LoginRequest): ...

@app.get("/users/{id}")           # header: Authorization: Bearer <token> → User object
def get_user(id: str): ...

@app.get("/users/{id}/orders")    # query: page (int, default 1) → {items, total, page}
def get_user_orders(id: str, page: int = 1): ...

@app.delete("/users/{id}")        # admin only → 204 or 404
def delete_user(id: str): ..."""},
)

TASK_OPTIMIZE_API = Task(
    description="Optimize REST API middleware: reduce p99 latency from 4200ms to under 200ms",
    required_tags={"backend": 87},
    metadata={"context": """\
# api/middleware.py — profiling shows 95% of latency comes from this function
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    # synchronous DB call on every request, no connection pool, no cache
    user = db.execute(f"SELECT * FROM users WHERE token='{token}'").fetchone()
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    request.state.user = user
    return await call_next(request)
# p99 breakdown: DB query 3800ms avg (no index on token column, 2M rows)"""},
)

DEMO_TASKS = [
    TASK_FIX_CSS_HOVER,
    TASK_WRITE_PYTHON_TESTS,
    TASK_REFACTOR_REST_API,
    TASK_SECURITY_AUDIT,
    TASK_OPTIMIZE_SQL,
    TASK_BUILD_DASHBOARD_UI,
    TASK_DOCUMENT_API,
    TASK_OPTIMIZE_API,
]
