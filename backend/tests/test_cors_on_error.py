"""An unhandled 500 must still carry CORS headers.

Without the _json_500_with_cors middleware, Starlette's ServerErrorMiddleware emits
the 500 OUTSIDE the CORS layer, so the response lacks Access-Control-Allow-Origin and
the browser reports a confusing "blocked by CORS policy" (net::ERR_FAILED) — which the
frontend can't read or retry. This locks in that a transient/unexpected 500 comes back
as a readable, CORS-tagged error.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

ALLOWED_ORIGIN = "http://localhost:5173"  # settings.cors_origin_list default


@app.get("/__boom_test__")
def _boom():  # pragma: no cover - exercised via the test client below
    raise RuntimeError("boom")


def test_unhandled_500_includes_cors_header():
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/__boom_test__", headers={"Origin": ALLOWED_ORIGIN})
    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert r.json()["detail"] == "Internal Server Error"
