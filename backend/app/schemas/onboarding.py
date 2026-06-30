"""Public paid-onboarding funnel schemas (no auth). See PAID_ONBOARDING_FUNNEL_BUILD.md.

The funnel is the ONLY pre-payment surface; the org does not exist yet, so the binding
key is the lead `token` (used as the Stripe client_reference_id), never an org id.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

# The Gewerk dropdown (Q1) — 18 trades, German. Kept here so the funnel can fetch it
# and the backend can validate against the same list.
TRADES: list[str] = [
    "Dachdecker",
    "Zimmerer",
    "Tischler",
    "Hausmeisterservice",
    "Gebäudereiniger",
    "KFZ-Mechaniker",
    "SHK-Installateure",
    "Elektrotechniker",
    "Maler und Lackierer",
    "Klempner",
    "Fliesenleger",
    "Maurer",
    "Garten- und Landschaftsbauer",
    "Solarteur",
    "Schlosser",
    "Isolierer",
    "Raumausstatter",
    "Hausverwalter",
]


class OnboardingStartRequest(BaseModel):
    """Step 1 — the 6-question signup form. No org exists yet."""

    trade: str = Field(..., min_length=1)                 # Q1 Gewerk
    contact_name: str = Field(..., min_length=1)          # Q2 vollständiger Name
    company_name: str = Field(..., min_length=1)          # Q3 Firmenname
    email: EmailStr                                       # Q4 Email (dup-checked)
    phone: str = Field(..., min_length=3)                 # Q5 Telefonnummer (E.164)
    password: str = Field(..., min_length=8)              # Q6 Passwort (≥8)


class OnboardingStartResponse(BaseModel):
    token: str


class CheckEmailRequest(BaseModel):
    email: EmailStr


class CheckEmailResponse(BaseModel):
    available: bool


class OnboardingCheckoutRequest(BaseModel):
    token: str
    plan_title: str
    interval: str = "month"                              # 'month' | 'year'
    # window.location.origin of the funnel, so Stripe returns to the same app.
    return_origin: str | None = None


class OnboardingCheckoutResponse(BaseModel):
    url: str
    session_id: str
