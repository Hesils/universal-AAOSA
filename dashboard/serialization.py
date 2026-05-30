import json

from flask import Response
from pydantic import BaseModel


def json_response(model: BaseModel, status: int = 200) -> Response:
    body = json.dumps(model.model_dump(by_alias=True, mode="json"))
    resp = Response(body, status=status, mimetype="application/json")
    resp.headers["Cache-Control"] = "no-store"
    return resp


def error_response(msg: str, status: int = 404) -> Response:
    resp = Response(json.dumps({"error": msg}), status=status, mimetype="application/json")
    resp.headers["Cache-Control"] = "no-store"
    return resp
