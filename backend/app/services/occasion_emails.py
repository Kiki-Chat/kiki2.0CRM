"""Cluster C — emails for the EXISTING 7 outbound occasions.

Companion to appointment_emails (the 3 appointment occasions). These render the
written German email for the reminder/kva/payment/satisfaction/review/maintenance/
missed-callback occasions, on the same branded shell. They are wired onto the
occasion specs with ``email_always=False``, so the dispatch chokepoint only sends
them when ``OUTBOUND_OCCASION_EMAILS_ENABLED`` is set — i.e. they ship INERT and
are enabled only after Amber reviews the diff (see APPOINTMENT_BUILD.md).

Transport (email_send.send_email) is unchanged — Amber's email-send track.
"""
from __future__ import annotations

# de_* formatters live in outbound_occasions (single source); that module reaches
# THIS one only via a lazy import inside its email_render bridge → no cycle.
from app.services.email_templates import addr_line, render_message_email
from app.services.outbound_occasions import de_eur, de_long_date, de_short_date, de_time


def _shell(org: dict, body: str) -> str:
    company = org.get("name") or "Dein Dienstleister"
    return render_message_email(
        company_name=company,
        message_text=body,
        contact_email=org.get("email"),
        address=addr_line(org.get("address")),
    )


def render_occasion_email(occasion: str, record: dict, customer: dict | None, org: dict) -> tuple[str, str]:
    """Return ``(subject, body_html)`` for one of the existing 7 occasions."""
    company = org.get("name") or "Dein Dienstleister"
    name = (customer or {}).get("full_name") or ""
    greet = f"Hallo {name}," if name else "Hallo,"
    sign = f"Mit freundlichen Grüßen\n{company}"
    r = record or {}

    if occasion == "appointment_reminder":
        datum, uhr = de_long_date(r["scheduled_at"]), de_time(r["scheduled_at"])
        titel = (r.get("title") or "").strip()
        tc = f" ({titel})" if titel else ""
        subject = f"Terminerinnerung – {datum} um {uhr} Uhr"
        body = (
            f"{greet}\n\nwir möchten dich an deinen Termin am {datum} um {uhr} Uhr{tc} erinnern.\n\n"
            "Falls du den Termin verschieben oder absagen möchtest, melde dich bitte kurz "
            f"bei uns.\n\n{sign}"
        )
    elif occasion == "kva_followup":
        nr = (r.get("number") or "").strip()
        betreff = (r.get("subject") or "").strip()
        ref = f"Angebot {nr}" if nr else "Angebot"
        bc = f" zum Thema „{betreff}“" if betreff else ""
        summe = f" über {de_eur(r['total'])} Euro" if r.get("total") is not None else ""
        subject = f"Nachfrage zu deinem {ref}"
        body = (
            f"{greet}\n\nwir möchten kurz zu deinem {ref}{bc}{summe} nachfragen, ob dazu noch "
            "Fragen offen sind oder wie du verfahren möchtest.\n\nFür Rückfragen stehen wir "
            f"dir gerne zur Verfügung.\n\n{sign}"
        )
    elif occasion == "payment_reminder":
        nr = (r.get("number") or "").strip()
        ref = f"Rechnung {nr}" if nr else "Rechnung"
        summe = f" über {de_eur(r['total'])} Euro" if r.get("total") is not None else ""
        faellig = f" (fällig seit dem {de_short_date(r['due_date'])})" if r.get("due_date") else ""
        subject = f"Freundliche Zahlungserinnerung – {ref}"
        body = (
            f"{greet}\n\ndürfen wir dich freundlich an unsere offene {ref}{summe}{faellig} "
            "erinnern? Falls deine Zahlung bereits unterwegs ist, betrachte diese "
            f"Erinnerung selbstverständlich als gegenstandslos.\n\n{sign}"
        )
    elif occasion == "satisfaction_survey":
        titel = (r.get("title") or "").strip()
        bc = f" „{titel}“" if titel else ""
        subject = "War alles zu deiner Zufriedenheit?"
        body = (
            f"{greet}\n\nwir haben kürzlich deinen Auftrag{bc} abgeschlossen und möchten gerne "
            "wissen: War alles zu deiner Zufriedenheit? Über eine kurze Rückmeldung freuen wir "
            f"uns sehr.\n\n{sign}"
        )
    elif occasion == "review_request":
        titel = (r.get("title") or "").strip()
        bc = f" „{titel}“" if titel else ""
        subject = "deine Bewertung würde uns sehr freuen"
        body = (
            f"{greet}\n\nvielen Dank, dass wir deinen Auftrag{bc} für dich erledigen durften. "
            "Wenn du zufrieden warst, würden wir uns sehr über eine kurze Online-Bewertung "
            f"freuen.\n\n{sign}"
        )
    elif occasion == "maintenance_due":
        subject = "deine nächste Wartung steht an"
        body = (
            f"{greet}\n\nbei dir steht die nächste regelmäßige Wartung an. Gerne vereinbaren "
            f"wir dafür einen Termin – melde dich einfach bei uns.\n\n{sign}"
        )
    elif occasion == "missed_callback":
        subject = "Wir haben deinen Anruf verpasst"
        body = (
            f"{greet}\n\nwir haben deinen Anruf leider verpasst und möchten uns gerne bei dir "
            "zurückmelden. Ruf uns gerne wieder an oder antworte kurz auf diese "
            f"E-Mail.\n\n{sign}"
        )
    else:
        raise ValueError(f"unknown occasion: {occasion!r}")

    return subject, _shell(org, body)
