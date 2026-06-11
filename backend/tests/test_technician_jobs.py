"""Technician job-link service — token lifecycle + report validation.

DB is a MagicMock routed per table; what we assert is the BEHAVIOUR contract:
revoked/closed-case links die with German messages, submit enforces the
mandatory description + photo-when-finished rules, and a re-dispatch revokes
the prior live link.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services import technician_jobs as tj


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


def _link_row(**over):
    row = {
        "id": "l1", "org_id": "org1", "appointment_id": "a1", "inquiry_id": "i1",
        "employee_id": "e1", "token": "tok", "photo_paths": [],
        "started_at": None, "finished_at": None, "submitted_at": None, "revoked_at": None,
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


def _patch_client(monkeypatch, tables):
    client = _Client(tables)
    monkeypatch.setattr(tj, "get_service_client", lambda: client)
    return client


def test_revoked_link_is_rejected(monkeypatch):
    _patch_client(monkeypatch, {"technician_job_links": _chain([_link_row(revoked_at="x")])})
    with pytest.raises(tj.JobLinkError, match="ersetzt"):
        tj.get_job_for_token("tok")


def test_closed_case_kills_link(monkeypatch):
    _patch_client(monkeypatch, _ctx_tables(_link_row(), inquiry_status="completed"))
    with pytest.raises(tj.JobLinkError, match="abgeschlossen"):
        tj.get_job_for_token("tok")


def test_cancelled_appointment_kills_link(monkeypatch):
    _patch_client(monkeypatch, _ctx_tables(_link_row(), appt_status="cancelled"))
    with pytest.raises(tj.JobLinkError, match="storniert"):
        tj.get_job_for_token("tok")


def test_submitted_link_still_viewable_after_close(monkeypatch):
    # Already-submitted reports stay viewable even when the case closed since.
    row = _link_row(submitted_at="2026-06-10T10:00:00+00:00", report={"description": "ok"})
    _patch_client(monkeypatch, _ctx_tables(row, inquiry_status="completed"))
    job = tj.get_job_for_token("tok")
    assert job["submitted_at"]


def test_submit_requires_description(monkeypatch):
    _patch_client(monkeypatch, _ctx_tables(_link_row()))
    with pytest.raises(tj.JobLinkError, match="beschreiben"):
        tj.submit_job("tok", {"description": "  ", "job_finished": False})


def test_submit_finished_requires_photo(monkeypatch):
    _patch_client(monkeypatch, _ctx_tables(_link_row(photo_paths=[])))
    with pytest.raises(tj.JobLinkError, match="Foto"):
        tj.submit_job("tok", {"description": "Alles erledigt", "job_finished": True})


def test_submit_ok_stamps_timestamps(monkeypatch):
    tables = _ctx_tables(_link_row(photo_paths=["p1"]))
    _patch_client(monkeypatch, tables)
    out = tj.submit_job("tok", {
        "description": "Ventil getauscht", "job_finished": True,
        "experience_good": True, "needs": ["Mehr Zeit"],
    })
    assert out["submitted_at"]
    update_arg = tables["technician_job_links"].update.call_args[0][0]
    assert update_arg["report"]["description"] == "Ventil getauscht"
    assert update_arg["report"]["job_finished"] is True
    assert update_arg["started_at"]  # auto-stamped when never started
    assert update_arg["finished_at"]


def test_double_submit_rejected(monkeypatch):
    row = _link_row(submitted_at="2026-06-10T10:00:00+00:00")
    _patch_client(monkeypatch, _ctx_tables(row))
    with pytest.raises(tj.JobLinkError, match="bereits abgeschlossen"):
        tj.submit_job("tok", {"description": "x", "job_finished": False})


def test_create_revokes_prior_links(monkeypatch):
    appts = _chain([{"id": "a1", "inquiry_id": "i1", "status": "confirmed"}])
    links = _chain([_link_row()])
    _patch_client(monkeypatch, {"appointments": appts, "technician_job_links": links})
    out = tj.create_job_link(org_id="org1", appointment_id="a1", employee_id="e1")
    assert out["token"] == "tok"  # mock returns the chain rows
    # First call on the links table revoked prior un-submitted links.
    assert links.update.called
    revoke_arg = links.update.call_args_list[0][0][0]
    assert "revoked_at" in revoke_arg
    # And a fresh token was inserted.
    insert_arg = links.insert.call_args[0][0]
    assert insert_arg["appointment_id"] == "a1" and len(insert_arg["token"]) > 30


def test_job_events_shapes(monkeypatch):
    links = _chain([
        _link_row(started_at="2026-06-10T09:00:00+00:00",
                  submitted_at="2026-06-10T10:00:00+00:00",
                  report={"job_finished": True, "description": "ok"},
                  photo_paths=["a", "b"]),
    ])
    emps = _chain([{"id": "e1", "display_name": "Tobi"}])
    _patch_client(monkeypatch, {"technician_job_links": links, "employees": emps})
    events = tj.job_events_for_inquiry("org1", "i1")
    kinds = [e["kind"] for e in events]
    assert kinds == ["technician_dispatched", "technician_job_started", "technician_report_submitted"]
    submitted = events[-1]
    assert "Tobi" in submitted["description"]
    assert submitted["extras"]["photo_count"] == 2
