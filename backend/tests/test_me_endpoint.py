"""/api/me returns the white-label company identity (name + contact email + logo
+ address) used by the sidebar badge, the footer, personal settings, and the
settings restricted-page role check."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import deps
from app.api.routes import me as me_route
from app.main import app

client = TestClient(app)


class _FakeOrgClient:
    def __init__(self, row):
        self._row = row

    def table(self, _name):
        outer = self

        class _T:
            def select(self, *a, **k):
                return self

            def eq(self, *a, **k):
                return self

            def limit(self, *a, **k):
                return self

            def execute(self):
                class _R:
                    data = [outer._row]
                return _R()

        return _T()


def test_me_includes_org_identity(monkeypatch):
    row = {
        "name": "Muster Heizungsbau GmbH",
        "email": "info@muster-heizung.de",
        "logo_url": "https://cdn.example/logo.png",
        "address": {"street": "Hauptstr. 1", "postal_code": "12345", "city": "Berlin"},
    }
    monkeypatch.setattr(me_route, "get_service_client", lambda: _FakeOrgClient(row))
    app.dependency_overrides[deps.get_current_user] = lambda: deps.CurrentUser(
        id="u1", email="emp@a.de", org_id="org-A", role="employee", full_name="Emp"
    )
    try:
        r = client.get("/api/me")
        assert r.status_code == 200
        body = r.json()
        assert body["org_name"] == "Muster Heizungsbau GmbH"
        assert body["org_email"] == "info@muster-heizung.de"
        assert body["org_logo_url"] == "https://cdn.example/logo.png"
        assert body["org_address"]["city"] == "Berlin"
        assert body["role"] == "employee"
        assert body["org_id"] == "org-A"
    finally:
        app.dependency_overrides.clear()


def test_me_org_name_null_without_org(monkeypatch):
    # A user with no org (e.g. super-admin) → org_name None, no DB call needed.
    called = {"n": 0}
    monkeypatch.setattr(me_route, "get_service_client", lambda: called.__setitem__("n", called["n"] + 1))
    app.dependency_overrides[deps.get_current_user] = lambda: deps.CurrentUser(
        id="sa", email="sa@x.de", org_id=None, role="super_admin", full_name="SA"
    )
    try:
        r = client.get("/api/me")
        assert r.status_code == 200
        body = r.json()
        assert body["org_name"] is None
        assert body["org_email"] is None
        assert body["org_logo_url"] is None
        assert body["org_address"] is None
        assert called["n"] == 0  # short-circuits when org_id is None
    finally:
        app.dependency_overrides.clear()
