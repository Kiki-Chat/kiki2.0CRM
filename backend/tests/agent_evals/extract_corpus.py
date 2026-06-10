"""Pulls the curated real-call corpus out of the `calls` table into corpus.json
(read-only; phone numbers and email local-parts are masked before anything is
written to the repo).

Usage (from backend/): python -m tests.agent_evals.extract_corpus

The curated call set covers the brief's scenario buckets with REAL transcripts:
identification (known/unknown), booking, emergency/Notdienst, reschedule,
cancellation, price talk, off-topic, voicemail/short calls. Selection is by
call id (stable); re-running refreshes corpus.json deterministically.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

HERE = Path(__file__).parent

# call_id -> bucket (curated 2026-06-10 from summary_title + transcript review)
CURATED: dict[str, str] = {}  # filled below by title query in main()

# (org_short, summary_title, started_at_prefix) -> bucket
CURATED_BY_TITLE = [
    ("c4dbf596", "Heizung Notdienst Transfer", "2026-06-09", "emergency"),
    ("c4dbf596", "Rohrbruch Notfall Weiterleitung", "2026-06-04", "emergency"),
    ("c4dbf596", "Rohrbruch Notdienst", "2026-06-04", "emergency"),
    ("04acd916", "Toilet Emergency Inquiry", "2026-06-08", "emergency"),
    ("04acd916", "Ceiling Water Leak", "2026-06-08", "emergency"),
    ("c4dbf596", "Heizung Reparatur Termin", "2026-06-09T10:13", "booking"),
    ("c4dbf596", "Heizung Reparatur Termin", "2026-06-09T10:09", "booking"),
    ("c4dbf596", "Heater Repair Appointment", "2026-06-09", "booking"),
    ("c4dbf596", "Heizung Reparatur Termin", "2026-06-04", "booking_price"),
    ("04acd916", "Toilet Repair Appointment", "2026-06-10", "booking"),
    ("04acd916", "Dachreparatur Terminbuchung", "2026-06-09", "booking"),
    ("04acd916", "Heizung Wartung Termin", "2026-06-03", "booking"),
    ("04acd916", "Appointment Booking: Leakage", "2026-06-05", "booking"),
    ("04acd916", "Reschedule Roof Repair", "2026-06-09", "reschedule"),
    ("04acd916", "Reschedule Appointment Heating", "2026-06-03", "reschedule"),
    ("04acd916", "Termin umbuchen", "2026-06-10", "reschedule_outbound"),
    ("04acd916", "Cancel Appointment", "2026-06-09", "cancel"),
    ("04acd916", "Appointment Cancellation", "2026-06-03", "cancel"),
    ("04acd916", "Off-topic Humor Request", "2026-06-03", "offtopic"),
    ("04acd916", "Broken device report", "2026-06-05", "identification_new"),
    ("04acd916", "Warm Water Outage", "2026-06-03", "identification"),
    ("c4dbf596", "Terminbestätigung", "2026-06-09", "outbound_confirm"),
    ("04acd916", "Appointment Confirmation Voicemail", "2026-06-09", "voicemail"),
]

MASK_PHONE = re.compile(r"\+?\d[\d \-/]{6,}\d")
MASK_EMAIL = re.compile(r"\b[\w.+-]+@")


def _mask(text: str | None) -> str | None:
    if not text:
        return text
    text = MASK_PHONE.sub(lambda m: m.group(0)[:4] + "…MASKED", text)
    return MASK_EMAIL.sub("masked@", text)


def _slim_turn(t: dict) -> dict:
    calls = []
    for x in t.get("tool_calls") or []:
        calls.append(x if isinstance(x, str) else (x.get("tool_name") or x.get("name")))
    return {
        "role": t.get("role"),
        "message": _mask(t.get("message")),
        "tool_calls": calls,
        "t": t.get("time_in_call_secs"),
    }


def main() -> None:
    env = HERE.parent.parent / ".env"
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v.strip().strip('"'))
    from supabase import create_client  # local import: repo tooling only

    db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    rows = (
        db.table("calls")
        .select("id, org_id, direction, started_at, duration_seconds, summary_title, transcript, data_collection")
        .order("started_at", desc=True)
        .limit(250)
        .execute()
        .data
    )
    picked = []
    used = set()
    for org8, title, prefix, bucket in CURATED_BY_TITLE:
        for r in rows:
            if (
                r["id"] not in used
                and r["org_id"].startswith(org8)
                and (r.get("summary_title") or "") == title
                and (r.get("started_at") or "").startswith(prefix)
            ):
                used.add(r["id"])
                picked.append({
                    "call_id": r["id"],
                    "org": org8,
                    "bucket": bucket,
                    "title": title,
                    "direction": r.get("direction"),
                    "started_at": r.get("started_at"),
                    "duration_seconds": r.get("duration_seconds"),
                    "turns": [_slim_turn(t) for t in (r.get("transcript") or [])],
                    "data_collection_keys": sorted((r.get("data_collection") or {}).keys()),
                })
                break
        else:
            print(f"NOT FOUND: {org8} {title} {prefix}")
    out = HERE / "corpus.json"
    out.write_text(json.dumps({
        "_doc": "Curated REAL call transcripts (masked) for retrospective rubric scoring. Extracted read-only from the calls table by extract_corpus.py.",
        "calls": picked,
    }, ensure_ascii=False, indent=1))
    print(f"wrote {out} with {len(picked)} calls")


if __name__ == "__main__":
    main()
