import json
from datetime import datetime, timezone

from dashboard.collectors.infra import PassRatePoint
from dashboard.graph_model import GraphEdge
from dashboard.serialization import error_response, json_response


def test_json_response_alias_and_header():
    resp = json_response(GraphEdge(from_node="a", to="b"))
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    assert resp.headers["Cache-Control"] == "no-store"
    body = json.loads(resp.get_data(as_text=True))
    assert body == {"from": "a", "to": "b"}  # by_alias -> "from"


def test_json_response_datetime_iso():
    p = PassRatePoint(timestamp=datetime(2026, 5, 30, 10, 0, 0, tzinfo=timezone.utc), pass_rate=0.5)
    body = json.loads(json_response(p).get_data(as_text=True))
    assert body["timestamp"].startswith("2026-05-30T10:00:00")


def test_json_response_status():
    resp = json_response(GraphEdge(from_node="a", to="b"), status=201)
    assert resp.status_code == 201


def test_error_response():
    resp = error_response("session x not found")
    assert resp.status_code == 404
    assert resp.headers["Cache-Control"] == "no-store"
    assert json.loads(resp.get_data(as_text=True)) == {"error": "session x not found"}
