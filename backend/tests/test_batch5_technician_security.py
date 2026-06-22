"""Batch 5 / 5.3 — technician link integrity (AUTH-029) + public rate-limit.

The per-job capability token (/job/<token>) and the standing portal token
(/techniker/<token>) are the ONLY credential on these unauthenticated routes.
These tests pin the AUTH-029 contract:

  * an EXPIRED per-job link dies with the German "Dieser Link ist abgelaufen.",
    a non-expired one still serves;
  * first_viewed_at is stamped exactly ONCE (on the first GET);
  * submit captures the client IP + User-Agent (forensic audit);
  * rotate-technician-token re-mints the portal token (admin-only) and never
    leaks the raw token, only the URL;
  * the public token routes are per-IP rate-limited (429 past the window).

DB is a MagicMock routed per table (same harness as test_technician_jobs);
the welcome email is mocked, never sent.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.main import app
from app.services import ratelimit
from app.services import technician_jobs as tj


# ─── DB fake (mirrors test_technician_jobs) ──────────────────────────────────
def _chain(rows):
    chain = MagicMock()
    for m in ("select", "eq", "neq", "in_", "is_", "limit", "order", "insert", "update"):
        getattr(chain, m).return_value = chain
    chain.execute.return_value = MagicMock(data=rows)
    return chain


class _Client:
    def __init__(self, tables: dict):
        self.tables = tables
        self.storage = MagicMock()

    def table(self, name):
        return self.tables.get(name) or _chain([])


def _patch_client(monkeypatch, tables):
    client = _Client(tables)
    monkeypatch.setattr(tj, "get_service_client", lambda: client)
    return client


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _link_row(**over):
    row = {
        "id": "l1", "org_id": "org1", "appointment_id": "a1", "inquiry_id": "i1",
        "employee_id": "e1", "token": "tok", "photo_paths": [],
        "started_at": None, "finished_at": None, "submitted_at": None, "revoked_at": None,
        "expires_at": None, "first_viewed_at": None,
        "created_at": "2026-06-10T08:00:00+00:00",
    }
    row.update(over)
    return row


def _ctx_tables(link_row, *, appt_status="confirmed", inquiry_status="open"):
    return {
        "technician_job_links": _chain([link_row]),
        "appointments": _chain([
            {"id": "a1", "title": "Heizung", "scheduled_at": "2026-06-11T08:00:00+00:00",
             "duration_minutes": 60, "status": appt_status, "location": None,
             "notes": None, "customer_id": "c1", "inquiry_id": "i1"}
        ]),
        "inquiries": _chain([{"id": "i1", "number": "K-1", "subject": "Heizung", "title": None,
                              "status": inquiry_status}]),
        "customers": _chain([{"id": "c1", "full_name": "Max", "phone": "1", "address": None}]),
        "organizations": _chain([{"id": "org1", "name": "Betrieb"}]),
        "employees": _chain([{"id": "e1", "display_name": "Tobi"}]),
    }


# ─── 1. Expiry: AUTH-029 ─────────────────────────────────────────────────────
def test_expired_link_rejected(monkeypatch):
    past = _iso(datetime.now(timezone.utc) - timedelta(days=1))
    _patch_client(monkeypatch, _ctx_tables(_link_row(expires_at=past)))
    with pytest.raises(tj.JobLinkError, match="abgelaufen"):
        tj.get_job_for_token("tok")


def test_non_expired_link_ok(monkeypatch):
    future = _iso(datetime.now(timezone.utc) + timedelta(days=10))
    _patch_client(monkeypatch, _ctx_tables(_link_row(expires_at=future)))
    job = tj.get_job_for_token("tok")
    assert job["case_number"] == "K-1"  # served normally


def test_null_expiry_treated_as_no_expiry(monkeypatch):
    # Legacy rows (created before the column existed) have NULL → never expire.
    _patch_client(monkeypatch, _ctx_tables(_link_row(expires_at=None)))
    job = tj.get_job_for_token("tok")
    assert job["case_number"] == "K-1"


def test_create_link_stamps_expiry(monkeypatch):
    appts = _chain([{"id": "a1", "inquiry_id": "i1", "status": "confirmed"}])
    links = _chain([_link_row()])
    _patch_client(monkeypatch, {"appointments": appts, "technician_job_links": links})
    tj.create_job_link(org_id="org1", appointment_id="a1", employee_id="e1")
    insert_arg = links.insert.call_args[0][0]
    assert "expires_at" in insert_arg and "created_at" in insert_arg
    created = datetime.fromisoformat(insert_arg["created_at"])
    expires = datetime.fromisoformat(insert_arg["expires_at"])
    assert (expires - created).days == tj.LINK_TTL_DAYS


# ─── 2. first_viewed_at stamped once ─────────────────────────────────────────
def test_first_viewed_at_stamped_on_first_get(monkeypatch):
    tables = _ctx_tables(_link_row(first_viewed_at=None))
    _patch_client(monkeypatch, tables)
    tj.get_job_for_token("tok")
    # An update to first_viewed_at was issued (guarded by is_ first_viewed_at null).
    update_calls = [c[0][0] for c in tables["technician_job_links"].update.call_args_list]
    assert any("first_viewed_at" in u for u in update_calls)


def test_first_viewed_at_not_restamped(monkeypatch):
    already = "2026-06-10T09:00:00+00:00"
    tables = _ctx_tables(_link_row(first_viewed_at=already))
    _patch_client(monkeypatch, tables)
    tj.get_job_for_token("tok")
    update_calls = [c[0][0] for c in tables["technician_job_links"].update.call_args_list]
    assert not any("first_viewed_at" in u for u in update_calls)


# ─── 3. submit captures ip + user-agent ──────────────────────────────────────
def test_submit_captures_ip_and_ua(monkeypatch):
    tables = _ctx_tables(_link_row(photo_paths=["p1"]))
    _patch_client(monkeypatch, tables)
    out = tj.submit_job(
        "tok",
        {"description": "Ventil getauscht", "job_finished": True},
        submitted_ip="203.0.113.7",
        submitted_user_agent="Mozilla/5.0 (iPhone)",
    )
    assert out["submitted_at"]
    update_arg = tables["technician_job_links"].update.call_args[0][0]
    assert update_arg["submitted_ip"] == "203.0.113.7"
    assert update_arg["submitted_user_agent"] == "Mozilla/5.0 (iPhone)"


def test_submit_without_ip_ua_still_works(monkeypatch):
    # Defaults are None — no audit fields written, submit still succeeds.
    tables = _ctx_tables(_link_row(photo_paths=["p1"]))
    _patch_client(monkeypatch, tables)
    out = tj.submit_job("tok", {"description": "ok", "job_finished": False})
    assert out["submitted_at"]
    update_arg = tables["technician_job_links"].update.call_args[0][0]
    assert "submitted_ip" not in update_arg
    assert "submitted_user_agent" not in update_arg


# ─── 4. rotate_portal_token (service) ────────────────────────────────────────
def _emp_row(**over):
    row = {
        "id": "e1", "org_id": "org1", "display_name": "Tobi", "email": "tobi@example.de",
        "is_technician": True, "deleted": False, "technician_portal_token": "old_token",
    }
    row.update(over)
    return row


def test_rotate_remints_token_and_notifies(monkeypatch):
    emps = _chain([_emp_row()])
    tables = {"employees": emps, "organizations": _chain([{"id": "org1", "name": "Betrieb"}])}
    _patch_client(monkeypatch, tables)
    notified = {}

    def _fake_notify(org_id, org_name, name, email, url):
        notified.update(org_id=org_id, name=name, email=email, url=url)

    out = tj.rotate_portal_token("org1", "e1", notify=_fake_notify)
    # A brand-new token was written (not the old one).
    update_arg = emps.update.call_args[0][0]
    new_token = update_arg["technician_portal_token"]
    assert new_token and new_token != "old_token" and len(new_token) > 30
    # The response carries the URL (built from the new token), NOT the raw token.
    assert out["technician_portal_url"].endswith(new_token)
    assert "technician_portal_token" not in out
    assert out["email_sent"] is True
    # The email path was triggered with the freshly-minted URL.
    assert notified["email"] == "tobi@example.de"
    assert notified["url"].endswith(new_token)


def test_rotate_unknown_employee_rejected(monkeypatch):
    _patch_client(monkeypatch, {"employees": _chain([])})
    with pytest.raises(tj.JobLinkError, match="nicht gefunden"):
        tj.rotate_portal_token("org1", "ghost", notify=lambda *a: None)


def test_rotate_non_technician_rejected(monkeypatch):
    _patch_client(monkeypatch, {"employees": _chain([_emp_row(is_technician=False)])})
    with pytest.raises(tj.JobLinkError, match="kein Techniker"):
        tj.rotate_portal_token("org1", "e1", notify=lambda *a: None)


def test_rotate_no_email_skips_notify(monkeypatch):
    emps = _chain([_emp_row(email=None)])
    _patch_client(monkeypatch, {"employees": emps, "organizations": _chain([{"id": "org1", "name": "B"}])})
    calls = []
    out = tj.rotate_portal_token("org1", "e1", notify=lambda *a: calls.append(a))
    assert out["email_sent"] is False
    assert calls == []  # no email when the technician has no address


# ─── 5. rotate endpoint (route) — admin-gated, mocked email ──────────────────
client = TestClient(app)


def _admin(org_id="org1", role="org_admin"):
    return deps.CurrentUser(id="u1", email="a@a.de", org_id=org_id, role=role, full_name=None)


def test_rotate_endpoint_admin_remints(monkeypatch):
    from app.api.routes import employees as emp_routes

    captured = {}

    def _fake_rotate(org_id, employee_id, *, notify=None):
        captured["notify"] = notify  # the route must wire the welcome-email path
        return {"id": employee_id, "technician_portal_url": "http://x/techniker/NEW", "email_sent": True}

    monkeypatch.setattr(emp_routes.technician_jobs, "rotate_portal_token", _fake_rotate)
    app.dependency_overrides[deps.require_org_admin] = lambda: _admin()
    try:
        resp = client.post("/api/employees/e1/rotate-technician-token")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["technician_portal_url"].endswith("/NEW")
    assert "technician_portal_token" not in body  # raw token never leaked
    # The route passed the existing welcome-email helper as the notifier.
    assert captured["notify"] is emp_routes._send_technician_welcome


def test_rotate_endpoint_requires_admin(monkeypatch):
    # require_org_admin raises 403 for a plain employee — assert the dependency
    # is the gate (no override → real dep runs, and with no auth header → 401/403).
    resp = client.post("/api/employees/e1/rotate-technician-token")
    assert resp.status_code in (401, 403)


def test_rotate_endpoint_unknown_employee_404(monkeypatch):
    from app.api.routes import employees as emp_routes

    def _raise(org_id, employee_id, *, notify=None):
        raise tj.JobLinkError("Mitarbeiter nicht gefunden.")

    monkeypatch.setattr(emp_routes.technician_jobs, "rotate_portal_token", _raise)
    app.dependency_overrides[deps.require_org_admin] = lambda: _admin()
    try:
        resp = client.post("/api/employees/ghost/rotate-technician-token")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 404


# ─── 6. public route rate-limit (per-IP) ─────────────────────────────────────
def test_public_job_get_rate_limited(monkeypatch):
    ratelimit.reset()
    # Make the service a no-op success so we isolate the throttle behaviour.
    monkeypatch.setattr(
        "app.api.routes.public_jobs.get_job_for_token", lambda token: {"ok": True}
    )
    # public_job_get window is 60/60s — the 61st from the same IP must 429.
    last = None
    for _ in range(61):
        last = client.get("/api/public/jobs/sometoken")
    assert last.status_code == 429
    assert "warten" in last.json()["detail"].lower()
    ratelimit.reset()


def test_public_technician_rate_limited(monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(
        "app.api.routes.public_technician.get_technician_portal",
        lambda token: {"jobs": []},
    )
    last = None
    for _ in range(61):
        last = client.get("/api/public/technician/sometoken")
    assert last.status_code == 429
    ratelimit.reset()
