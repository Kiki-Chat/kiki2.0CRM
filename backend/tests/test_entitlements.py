"""Entitlement enforcement: read-only preview vs mutation block."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import deps
from app.api.routes import cost_estimates as ce_route
from app.main import app

client = TestClient(app)

ORG = "org-basis"
USER = deps.CurrentUser(
    id="u1", email="a@a.de", org_id=ORG, role="org_admin", full_name="Admin"
)


class _FakeOrgClient:
    """Minimal fake: organizations → Kiki Basis; cost_estimates list → one row."""

    def table(self, name: str):
        outer = self

        class _T:
            def select(self, *a, **k):
                return self

            def eq(self, *a, **k):
                return self

            def in_(self, *a, **k):
                return self

            def order(self, *a, **k):
                return self

            def limit(self, *a, **k):
                return self

            def insert(self, *a, **k):
                return self

            def execute(self):
                class _R:
                    pass

                r = _R()
                if name == "organizations":
                    r.data = [{"billing_plan_title": "Kiki Basis"}]
                elif name == "cost_estimates":
                    r.data = [
                        {
                            "id": "ce-1",
                            "number": "KVA-001",
                            "type": "kva",
                            "status": "draft",
                            "subject": "Test",
                            "customer_id": None,
                            "inquiry_id": None,
                            "is_binding": False,
                            "tolerance_pct": 20,
                            "valid_until": None,
                            "subtotal": 100,
                            "vat_amount": 19,
                            "total": 119,
                            "sent_at": None,
                            "accepted_at": None,
                            "rejected_at": None,
                            "created_at": "2026-06-01T00:00:00+00:00",
                        }
                    ]
                else:
                    r.data = []
                return r

        return _T()


def _override_user():
    app.dependency_overrides[deps.get_current_user] = lambda: USER
    app.dependency_overrides[deps.require_org] = lambda: USER
    app.dependency_overrides[deps.require_org_admin] = lambda: USER


def test_locked_feature_allows_get_blocks_post(monkeypatch):
    fake = _FakeOrgClient()
    monkeypatch.setattr("app.db.supabase_client.get_service_client", lambda: fake)
    monkeypatch.setattr(ce_route, "get_service_client", lambda: fake)
    monkeypatch.setattr("app.core.config.settings.entitlements_enforced", True)
    _override_user()
    try:
        r_get = client.get("/api/cost-estimates")
        assert r_get.status_code == 200
        assert len(r_get.json()) == 1

        r_post = client.post(
            "/api/cost-estimates",
            json={"type": "kva", "subject": "Neu", "positions": []},
        )
        assert r_post.status_code == 402
        body = r_post.json()["detail"]
        assert body["error"] == "feature_locked"
        assert body["feature"] == "finance"
        assert body["min_plan"] == "Kiki Enterprise"
    finally:
        app.dependency_overrides.clear()
