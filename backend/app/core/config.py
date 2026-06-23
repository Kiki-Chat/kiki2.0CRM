from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Canonical public base URL of the customer-facing CRM frontend. EVERY link
# emailed to a human (employee set-password/login link, technician job link,
# Stripe billing-portal return) is built from this. Override per environment via
# the FRONTEND_PUBLIC_URL env var — this is the ONLY place the default lives, so a
# missing/empty env var can never emit a localhost or stale link in production.
# Tracks the CURRENT live frontend domain; the FRONTEND_PUBLIC_URL env var is the
# lever to flip it (crm.kikichat.de today → crm.heykiki.de after the migration).
DEFAULT_PUBLIC_APP_URL = "https://crm.kikichat.de"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Deployment environment. Set APP_ENV=production in Railway prod so startup
    # validation can FAIL FAST on missing security-critical secrets instead of
    # silently running open. Anything other than "production" is treated as dev.
    app_env: str = Field(default="development", validation_alias="APP_ENV")

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    # Shared secret for the master/provision + post-call webhook gates. Default is
    # EMPTY (fail-closed): with no secret set, the verifiers reject every request
    # rather than accept a well-known fallback string. MUST be set in production —
    # validate_runtime_config() refuses to start the app if it is empty there.
    master_webhook_secret: str = Field(default="", validation_alias="MASTER_WEBHOOK_SECRET")
    post_call_webhook_secret: str = ""

    # TTL (seconds) for the cached Supabase JWKS. Default 5 min (was a hardcoded
    # 1 h) so a rotated/revoked signing key stops being trusted within one refresh
    # window instead of up to an hour. Lower per-env via JWKS_TTL_SECONDS.
    jwks_ttl_seconds: int = Field(default=300, validation_alias="JWKS_TTL_SECONDS")

    cors_origins: str = "http://localhost:5173"

    elevenlabs_api_key: str = ""

    # ── Twilio (raw call-forwarding for emergency/staff transfers) ────────
    # Used by the hk_transferCall tool to redirect the LIVE inbound call to a
    # human via the Twilio REST API. Dormant when blank: the tool still returns
    # the number + spoken line, just no actual bridge.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""

    # ── OpenAI copilot ("Kiki Assistent") — Phase 0, dormant by default ────
    # The centralized AI service (app/services/ai) + the in-app copilot. Ships
    # INERT: with no OPENAI_API_KEY the AI client is disabled (every call is a
    # clean no-op / "not configured"), and the copilot router is only mounted
    # when COPILOT_ENABLED=1 — so a fresh deploy behaves exactly as today until
    # it is switched on. The key already exists in Railway prod (dormant).
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    # Master on/off for the whole copilot surface (router + UI). Off by default.
    copilot_enabled: bool = Field(default=False, validation_alias="COPILOT_ENABLED")
    # Copilot model — upgraded 2026-06-04 to gpt-4o for far more reliable tool-calling
    # + reasoning (the mini tier dropped confirm-cards / disambiguation). Override per
    # env; the client also tolerates "thinking" o-series models (o1/o3/o4) — see ai/client.
    # Classifiers (emergency / employee auto-assign) stay on the cheap mini tier.
    openai_copilot_model: str = Field(default="gpt-4o", validation_alias="OPENAI_COPILOT_MODEL")
    openai_classifier_model: str = Field(default="gpt-4o-mini", validation_alias="OPENAI_CLASSIFIER_MODEL")
    # Network timeout (seconds) for OpenAI calls.
    openai_timeout_seconds: float = Field(default=30.0, validation_alias="OPENAI_TIMEOUT_SECONDS")
    # Soft per-org monthly spend cap (USD) across all AI features, enforced via the
    # ai_usage_log ledger. 0 = no cap. Surfaced later in KI-Nutzung.
    copilot_monthly_cost_cap_usd: float = Field(
        default=25.0, validation_alias="COPILOT_MONTHLY_COST_CAP_USD"
    )

    # Symmetric key (Fernet) for encrypting stored third-party credentials.
    settings_enc_key: str = ""

    # OAuth (P1.8) — credentials per provider. Placeholders until set per
    # P1.8_OAUTH_SETUP.md. When any *_client_id is empty, the corresponding
    # /api/settings/oauth/{provider}/authorize returns 503.
    google_client_id: str = ""
    google_client_secret: str = ""
    ms_client_id: str = ""
    ms_client_secret: str = ""
    # Calendly (P3 calendar sync) — calendar-only OAuth provider.
    calendly_client_id: str = ""
    calendly_client_secret: str = ""
    # Used to build OAuth redirect URIs at runtime. Must match the value
    # registered with Google + Azure (see §1.4 / §2.1 of P1.8_OAUTH_SETUP.md).
    backend_public_url: str = "http://localhost:8000"
    # Which ElevenLabs ENVIRONMENT this backend represents. Each deployment sets
    # its own: the UAT Railway service sets EL_ENVIRONMENT=uat, the prod service
    # sets EL_ENVIRONMENT=production. Returned by the conversation-init webhook so
    # ElevenLabs resolves {{system__env_api_host}} (a shared tool's URL host) to
    # THIS backend. Default 'uat' is the safe choice — a mis-set backend routes to
    # UAT, never accidentally to prod. The `production` env always exists in EL; a
    # `uat` environment must be created in the EL workspace.
    el_environment: str = "uat"
    # Public base URL of the customer CRM frontend — used for EVERY link emailed
    # to a human (employee set-password/login link, technician job link, Stripe
    # billing return). Env-overridable via FRONTEND_PUBLIC_URL; set it in Railway
    # to the live domain. For the set-password/recovery link to resolve, the URL
    # must also be on Supabase Auth's Redirect-URL allow-list. Defaults to the live
    # domain so a missing env var never emits a localhost/stale link. Read it via
    # the `public_app_url` property (trims the slash + guards an empty value).
    frontend_public_url: str = DEFAULT_PUBLIC_APP_URL

    # ── Brevo SMTP relay (P1.8 Phase 3 / Wave 1.2) ─────────────────────────
    # Final fallback in the email_send.py chain when an org has no OAuth and
    # no customer SMTP configured (or both upstream tiers failed). Production
    # values live in Railway env vars; placeholders here so the backend
    # boots locally without them — chain raises only at send time when the
    # fallback is actually attempted with empty creds.
    brevo_smtp_host: str = "smtp-relay.brevo.com"
    brevo_smtp_port: int = 587
    brevo_smtp_username: str = "a232fd001@smtp-brevo.com"
    # The SMTP key is stored in Railway as BREVO_SMTP_KEY (NOT BREVO_SMTP_PASSWORD);
    # read it from that existing env name. The key stays in env — never hardcoded.
    brevo_smtp_password: str = Field(default="", validation_alias="BREVO_SMTP_KEY")
    brevo_smtp_from_address: str = Field(
        default="info@kiki-zusammenfassung.de", validation_alias="BREVO_SMTP_FROM_ADDRESS"
    )
    brevo_smtp_from_name: str = "HeyKiki"
    # Brevo transactional HTTP API key (api.brevo.com/v3/smtp/email, HTTPS/443).
    # Tier-3 fallback sends via the HTTP API instead of SMTP/587 (Railway egress
    # blocks outbound SMTP — connect-timeout on 587). Stored in Railway as
    # BREVO_API_KEY. The key stays in env — never hardcoded.
    brevo_api_key: str = Field(default="", validation_alias="BREVO_API_KEY")

    # ── Redis cache + observability (Item 4 — dormant until set) ───────────
    # The cache layer (app/core/cache.py) is DISABLED while redis_url is empty:
    # every operation is a no-op / cache-miss, so the app behaves exactly as it
    # does today. Set REDIS_URL (e.g. the Railway Redis add-on's private URL) to
    # activate caching. NEVER hardcode the URL — it carries a password.
    redis_url: str = Field(default="", validation_alias="REDIS_URL")
    # Namespace prefix so two environments can share one Redis without collisions.
    cache_prefix: str = "kj"
    # Default TTL (seconds) for cached entries when a caller doesn't specify one.
    cache_default_ttl: int = 300
    # Gate for the structured-logging + request-context middleware (off by default
    # so it ships dormant and only activates under supervision).
    observability_enabled: bool = Field(default=False, validation_alias="OBSERVABILITY_ENABLED")

    # ── Appointment-epic outbound SCOPE GUARD (safety) ─────────────────────
    # While ON (the default), every appointment-epic outbound CALL is forced to
    # OUTBOUND_TEST_NUMBER and every EMAIL to OUTBOUND_TEST_EMAIL, and any send
    # for an org NOT in OUTBOUND_TEST_ORG_IDS is REFUSED (OutOfScopeError). Flip
    # to 0 only for go-live to real customers (see DEPLOY RUNBOOK). Default ON so
    # a fresh deploy can never accidentally reach a real customer.
    outbound_test_scope_only: bool = Field(default=True, validation_alias="OUTBOUND_TEST_SCOPE_ONLY")
    outbound_test_number: str = Field(default="+917879997839", validation_alias="OUTBOUND_TEST_NUMBER")
    outbound_test_email: str = Field(default="agrawalamber01@gmail.com", validation_alias="OUTBOUND_TEST_EMAIL")
    # Comma-separated org UUIDs allowed to send while the scope guard is ON.
    outbound_test_org_ids: str = Field(
        default="c4dbf596-86fd-4484-88d9-095b2c082afb", validation_alias="OUTBOUND_TEST_ORG_IDS"
    )
    # Cluster C: attach an email to the EXISTING 7 outbound occasions. OFF by
    # default so that wiring ships INERT until Amber enables it post-review.
    outbound_occasion_emails_enabled: bool = Field(
        default=False, validation_alias="OUTBOUND_OCCASION_EMAILS_ENABLED"
    )

    # ── Stripe billing (Phase 1 — read-first; ships INERT) ─────────────────
    # The whole billing surface (customer + super-admin routers + webhook) is
    # mounted ONLY when STRIPE_BILLING_ENABLED=1, and every Stripe call reads
    # the key from env — so with no key + the gate off, a fresh deploy behaves
    # exactly as today. Use TEST keys (sk_test_… / whsec_…) until go-live.
    # The usage-reporting WRITE path is independently gated by
    # STRIPE_USAGE_REPORTING_ENABLED so reads can go live while billing writes
    # stay disarmed. See the Phase-1 plan / STRIPE_INTEGRATION_HANDOVER.md.
    stripe_secret_key: str = Field(default="", validation_alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = Field(default="", validation_alias="STRIPE_WEBHOOK_SECRET")
    stripe_billing_enabled: bool = Field(default=False, validation_alias="STRIPE_BILLING_ENABLED")
    stripe_usage_reporting_enabled: bool = Field(
        default=False, validation_alias="STRIPE_USAGE_REPORTING_ENABLED"
    )
    # Return URL for the Stripe billing-portal session. Falls back to
    # frontend_public_url + '/settings/abrechnung' when blank.
    billing_portal_return_url: str = Field(default="", validation_alias="BILLING_PORTAL_RETURN_URL")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def outbound_test_org_id_set(self) -> set[str]:
        return {o.strip() for o in self.outbound_test_org_ids.split(",") if o.strip()}

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in ("production", "prod")

    @property
    def public_app_url(self) -> str:
        """Public frontend base URL for emailed links, trailing slash trimmed.
        Falls back to DEFAULT_PUBLIC_APP_URL when FRONTEND_PUBLIC_URL is present
        but empty, so a misconfigured env var never yields a relative/localhost
        link. This is the single accessor every link builder should use."""
        return (self.frontend_public_url or DEFAULT_PUBLIC_APP_URL).rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_runtime_config(s: "Settings | None" = None) -> list[str]:
    """Return a list of fatal config problems for the current environment.

    Called once at startup (app.main). In production a non-empty list aborts boot —
    a loud crash is strictly safer than silently running with auth wide open or with
    no DB. In dev it only warns, so local boot stays frictionless. Returns the list
    (also handy to unit-test) so the caller decides how to react.
    """
    s = s or get_settings()
    problems: list[str] = []
    if s.is_production:
        if not s.master_webhook_secret:
            problems.append(
                "MASTER_WEBHOOK_SECRET is empty — webhook auth would reject all "
                "requests. Set a strong secret in the production environment."
            )
        if not s.supabase_url or not s.supabase_service_role_key:
            problems.append("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY must be set in production.")
    # Stripe go-live guards — a LIVE key charges real customers, so running it
    # without webhook verification (subscription state-sync) is never acceptable.
    if s.stripe_secret_key.startswith("sk_live"):
        if not s.stripe_webhook_secret:
            problems.append(
                "STRIPE_SECRET_KEY is a LIVE key but STRIPE_WEBHOOK_SECRET is empty — "
                "subscription state-sync would be unverifiable. Configure the live "
                "webhook endpoint secret before using live billing."
            )
        if not s.stripe_billing_enabled:
            problems.append(
                "STRIPE_SECRET_KEY is a LIVE key but STRIPE_BILLING_ENABLED=0 — "
                "remove the live key or enable billing; a half-configured live key "
                "invites accidental ad-hoc calls."
            )
    if s.stripe_usage_reporting_enabled and not s.stripe_billing_enabled:
        problems.append(
            "STRIPE_USAGE_REPORTING_ENABLED=1 requires STRIPE_BILLING_ENABLED=1."
        )
    return problems


settings = get_settings()
