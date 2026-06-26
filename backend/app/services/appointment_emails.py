"""Appointment outbound EMAILS (Cluster B): confirmation / cancellation /
reschedule.

Built on the shared branded shell (``email_templates.render_message_email`` —
white-label header/footer already carry the sending company's identity). This
module only assembles the per-occasion German subject + body and renders it; the
TRANSPORT (``email_send.send_email``) is UNCHANGED — that's Amber's email-send
track. The recipient is scope-guarded at the dispatch chokepoint (forced to
OUTBOUND_TEST_EMAIL while the guard is on).
"""
from __future__ import annotations

# de_long_date / de_time live in outbound_occasions (the single source of German
# date formatting). outbound_occasions reaches THIS module only via a lazy import
# inside its email_render bridge, so importing them here creates no cycle.
from app.services.email_templates import addr_line, render_message_email
from app.services.outbound_occasions import de_long_date, de_time


def render_appointment_email(
    occasion: str, appointment: dict, customer: dict | None, org: dict
) -> tuple[str, str]:
    """Return ``(subject, body_html)`` for an appointment-occasion email."""
    company = org.get("name") or "Dein Dienstleister"
    name = (customer or {}).get("full_name") or ""
    sched = appointment.get("scheduled_at")
    datum = de_long_date(sched) if sched else ""
    uhr = de_time(sched) if sched else ""
    titel = (appointment.get("title") or "").strip()
    titel_clause = f" ({titel})" if titel else ""
    greet = f"Hallo {name}," if name else "Hallo,"
    sign = f"Mit freundlichen Grüßen\n{company}"

    if occasion == "appointment_confirmation":
        subject = f"Terminbestätigung – {datum} um {uhr} Uhr"
        body = (
            f"{greet}\n\n"
            f"hiermit bestätigen wir deinen Termin am {datum} um {uhr} Uhr{titel_clause}.\n\n"
            "Solltest du den Termin verschieben oder absagen müssen, melde dich bitte "
            "kurz bei uns.\n\n"
            f"{sign}"
        )
    elif occasion == "appointment_cancellation":
        subject = f"Terminabsage – {datum} um {uhr} Uhr"
        body = (
            f"{greet}\n\n"
            f"leider müssen wir deinen Termin am {datum} um {uhr} Uhr{titel_clause} absagen. "
            "Wir bitten um dein Verständnis.\n\n"
            "Gerne vereinbaren wir einen neuen Termin – melde dich einfach bei uns.\n\n"
            f"{sign}"
        )
    elif occasion == "appointment_reschedule":
        alt = appointment.get("alternative_start_time")
        if alt:
            neu = f"{de_long_date(alt)} um {de_time(alt)} Uhr"
            subject = f"Terminverschiebung – neuer Vorschlag: {neu}"
            body = (
                f"{greet}\n\n"
                f"wir müssen deinen Termin am {datum} um {uhr} Uhr{titel_clause} leider verschieben "
                f"und schlagen dir einen neuen Termin vor: {neu}.\n\n"
                "Bitte gib uns kurz Bescheid, ob dir der neue Termin passt – alternativ "
                "finden wir gerne einen anderen Termin.\n\n"
                f"{sign}"
            )
        else:
            subject = f"Terminverschiebung – {datum} um {uhr} Uhr"
            body = (
                f"{greet}\n\n"
                f"wir müssen deinen Termin am {datum} um {uhr} Uhr{titel_clause} leider verschieben. "
                "Wir melden uns in Kürze, um gemeinsam einen neuen Termin zu finden.\n\n"
                f"{sign}"
            )
    else:
        raise ValueError(f"unknown appointment occasion: {occasion!r}")

    body_html = render_message_email(
        company_name=company,
        message_text=body,
        contact_email=org.get("email"),
        address=addr_line(org.get("address")),
    )
    return subject, body_html
