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
    # Resume the SAME lead (idempotent). The funnel carries this in the URL as
    # ?s=<token> so a refresh / back / aborted session never spawns a duplicate and the
    # token stays the single signup→Stripe→org binding key. None on a first submit.
    token: str | None = None
    # Marketing attribution captured from the landing URL (utm_source/medium/campaign/
    # term/content). Free-form dict so new UTM keys need no schema change.
    utm: dict | None = None
    referral_code: str | None = None                      # inviter code (?ref=…), future


class OnboardingStartResponse(BaseModel):
    token: str


class OnboardingSessionResponse(BaseModel):
    """Resume payload for the funnel — safe lead fields only (never the password)."""

    token: str
    status: str
    company_name: str | None = None
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    trade: str | None = None
    plan_title: str | None = None
    interval: str | None = None


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
