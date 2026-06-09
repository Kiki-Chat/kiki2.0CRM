from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import (
    actions,
    appointments,
    calendar_settings,
    calls,
    catalog,
    conversation_init,
    cost_estimates,
    customers,
    dashboard,
    documents,
    employees,
    health,
    inquiries,
    invoices,
    kiki_zentrale,
    me,
    oauth,
    outbound,
    planning_board,
    post_call,
    projects,
    provision,
    super_admin,
    text_modules,
    tool_assets,
    users,
    vehicles,
)
from app.api.routes import settings as settings_routes
from app.api.routes.tools import (
    book_appointment,
    cancel_appointment,
    change_appointment,
    create_inquiry,
    draft_cost_estimate,
    get_available_slots,
    identify_customer,
    query_knowledge_base,
    search_inquiries,
    transfer_call,
    update_customer,
)
from app.core.config import settings, validate_runtime_config

# Fail fast on missing security-critical config in production (empty webhook
# secret, no DB creds). In dev these only warn so local boot stays frictionless.
import logging as _logging

_config_problems = validate_runtime_config(settings)
if _config_problems:
    _msg = "Invalid runtime config:\n  - " + "\n  - ".join(_config_problems)
    if settings.is_production:
        raise RuntimeError(_msg)
    _logging.getLogger(__name__).warning("%s\n(non-fatal in non-production)", _msg)

app = FastAPI(title="HeyKiki Portal API", version="0.1.0")

# Observability (Item 4) — dormant unless OBSERVABILITY_ENABLED=1. Structured
# JSON logging + a request-context middleware (request id, timing, access log).
if settings.observability_enabled:
    from app.core.logging_config import configure_logging
    from app.core.observability import RequestContextMiddleware

    configure_logging()
    app.add_middleware(RequestContextMiddleware)

# Catch unhandled exceptions and return a JSON 500. Registered BEFORE CORSMiddleware
# so it sits INNER to it: a bare Starlette ServerErrorMiddleware 500 is emitted
# outside the CORS layer and therefore lacks `Access-Control-Allow-Origin`, so the
# browser reports a confusing "blocked by CORS policy" (net::ERR_FAILED) instead of a
# readable 500 — and the frontend can't handle/retry it. By returning the error from
# here, the response flows back out through CORSMiddleware and gets the CORS header.
@app.middleware("http")
async def _json_500_with_cors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:  # noqa: BLE001 — last-resort guard; logged with stack below
        _logging.getLogger(__name__).exception(
            "Unhandled error on %s %s", request.method, request.url.path
        )
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(provision.router)
app.include_router(dashboard.router)
app.include_router(me.router)
app.include_router(calls.router)
app.include_router(customers.router)
app.include_router(employees.router)
app.include_router(inquiries.router)
app.include_router(appointments.router)
app.include_router(calendar_settings.router)
app.include_router(vehicles.router)
app.include_router(tool_assets.router)
app.include_router(planning_board.router)
app.include_router(projects.router)
app.include_router(cost_estimates.router)
app.include_router(invoices.router)
app.include_router(kiki_zentrale.router)
app.include_router(catalog.router)
app.include_router(catalog.items_router)
app.include_router(text_modules.router)
app.include_router(documents.router)
app.include_router(settings_routes.router)
app.include_router(users.router)
app.include_router(super_admin.router)
app.include_router(oauth.router)
app.include_router(outbound.router)
app.include_router(actions.router)

# ElevenLabs tool webhooks — LIVE: org-scoped handlers the agent calls mid-call
# (identify customer, create inquiry, book/cancel/change appointment, etc.).
app.include_router(identify_customer.router)
app.include_router(update_customer.router)
app.include_router(create_inquiry.router)
app.include_router(get_available_slots.router)
app.include_router(book_appointment.router)
app.include_router(cancel_appointment.router)
app.include_router(change_appointment.router)
app.include_router(search_inquiries.router)
app.include_router(query_knowledge_base.router)
app.include_router(transfer_call.router)
app.include_router(draft_cost_estimate.router)

# Conversation Initiation Webhook (fires on call connect, before the agent speaks).
app.include_router(conversation_init.router)

# Post-call webhook (forwarded from N8N after the call ends).
app.include_router(post_call.router)

# Kiki copilot ("Kiki Assistent") — mounted ONLY when COPILOT_ENABLED=1.
# Phase 0 ships it OFF/inert, so the app behaves exactly as before by default.
if settings.copilot_enabled:
    from app.api.routes import copilot

    app.include_router(copilot.router)

# Stripe billing — mounted ONLY when STRIPE_BILLING_ENABLED=1 (Phase 1, read-first).
# Ships OFF/inert by default; the usage-reporting WRITE path is independently gated
# by STRIPE_USAGE_REPORTING_ENABLED (see app/api/routes/post_call.py).
if settings.stripe_billing_enabled:
    from app.api.routes import billing, billing_admin, stripe_webhook

    app.include_router(billing.router)
    app.include_router(billing_admin.router)
    app.include_router(stripe_webhook.router)


@app.get("/")
async def root() -> dict:
    return {"service": "HeyKiki Portal API", "docs": "/docs"}
