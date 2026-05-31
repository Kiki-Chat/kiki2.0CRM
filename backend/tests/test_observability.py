"""Item 4 — request-context observability (hermetic).

Covers the middleware (request-id generate/echo, access log with timing, error
logging) and the JSON formatter (request_id + curated extras).
"""
import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging_config import JsonFormatter
from app.core.observability import RequestContextMiddleware, request_id_var


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    return app


def test_request_id_header_generated():
    r = TestClient(_app()).get("/ping")
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID")  # one was generated


def test_request_id_header_is_echoed_when_supplied():
    r = TestClient(_app()).get("/ping", headers={"X-Request-ID": "trace-abc"})
    assert r.headers.get("X-Request-ID") == "trace-abc"


def test_access_log_emitted_with_fields(caplog):
    with caplog.at_level(logging.INFO, logger="app.request"):
        TestClient(_app()).get("/ping")
    recs = [r for r in caplog.records if r.name == "app.request" and r.getMessage() == "request"]
    assert recs, "expected an access log line"
    rec = recs[-1]
    assert rec.method == "GET"
    assert rec.path == "/ping"
    assert rec.status == 200
    assert isinstance(rec.duration_ms, float)


def test_error_is_logged_and_500(caplog):
    client = TestClient(_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.INFO, logger="app.request"):
        r = client.get("/boom")
    assert r.status_code == 500
    assert any(rec.getMessage() == "request_error" for rec in caplog.records)


def test_json_formatter_includes_request_id_and_extras():
    fmt = JsonFormatter()
    token = request_id_var.set("rid-123")
    try:
        rec = logging.LogRecord("app.request", logging.INFO, __file__, 1, "request", None, None)
        rec.method, rec.path, rec.status, rec.duration_ms = "GET", "/x", 200, 1.2
        out = json.loads(fmt.format(rec))
    finally:
        request_id_var.reset(token)
    assert out["request_id"] == "rid-123"
    assert (out["method"], out["path"], out["status"]) == ("GET", "/x", 200)
    assert out["level"] == "INFO" and out["msg"] == "request"


def test_json_formatter_omits_request_id_outside_request():
    fmt = JsonFormatter()
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hi", None, None)
    out = json.loads(fmt.format(rec))
    assert "request_id" not in out
    assert out["msg"] == "hi"
