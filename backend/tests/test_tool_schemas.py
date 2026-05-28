"""Regression tests for ElevenLabs tool schemas + null-input handling.

Guards against:
  - underscore system-field aliases silently failing to map (the reported, but
    false, "broken alias on 3.13" concern), and
  - identifyCustomer / conversation-init crashing on a missing Caller-ID
    (e.g. Viber calls arrive with no Caller-ID).

These tests are hermetic — no network/DB. The DB client is stubbed and asserted
NOT to be queried on the null-caller paths.
"""

from types import SimpleNamespace

import pytest

from app.schemas.tools import CreateInquiryRequest, IdentifyCustomerRequest
from app.services import identify
from app.services.conversation_init import conversation_init


def test_system_field_aliases_map():
    m = IdentifyCustomerRequest.model_validate(
        {
            "_toolName": "identifyCustomer",
            "_callerNumber": "+4917663181301",
            "_conversationId": "conv_x",
            "_agentId": "agent_x",
            "_callSid": "CA1",
        }
    )
    assert m.tool_name == "identifyCustomer"
    assert m.caller_number == "+4917663181301"
    assert m.conversation_id == "conv_x"
    assert m.agent_id == "agent_x"
    assert m.call_sid == "CA1"
    # Aliased keys are consumed by the fields, not leaked into extras.
    assert m.model_extra == {}


def test_tool_specific_aliases_map():
    m = CreateInquiryRequest.model_validate(
        {
            "_agentId": "agent_x",
            "inquiryTitle": "Broken boiler",
            "message": "No hot water",
            "name": "Hans",
            "callbackRequested": True,
        }
    )
    assert m.agent_id == "agent_x"
    assert m.inquiry_title == "Broken boiler"
    assert m.callback_requested is True


class _NoDBClient:
    """Stub that fails loudly if any DB access is attempted."""

    def table(self, *args, **kwargs):  # noqa: D401
        raise AssertionError("DB must not be queried when Caller-ID is absent")


@pytest.mark.parametrize(
    "payload",
    [
        {"_agentId": "agent_x", "_callerNumber": None},
        {"_agentId": "agent_x"},  # omitted
        {"_agentId": "agent_x", "_callerNumber": ""},
    ],
)
def test_identify_null_caller_returns_new_customer(monkeypatch, payload):
    monkeypatch.setattr(identify, "get_service_client", lambda: _NoDBClient())
    req = IdentifyCustomerRequest.model_validate(payload)
    res = identify.identify_customer("org-x", req)
    assert res["status"] == "NEW_CUSTOMER"
    assert res["customerId"] is None


class _FakeQuery:
    """Fluent stub mimicking the supabase-py query builder. Every chainable
    method returns self; ``execute`` yields the canned rows."""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def ilike(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows)


class _FakeDBClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, *a, **k):
        return _FakeQuery(self._rows)


@pytest.mark.parametrize(
    "stored_address, expected_address",
    [
        # The shape get_or_create_customer / updateCustomerData / the CRM admin
        # UI all write. This is the regression: identify used to drop it to None
        # because its private _format_address had no "raw" branch, so the agent
        # never received the address and re-asked the returning caller for it.
        ({"raw": "Stader Str. 3-5, 21614 Buxtehude"}, "Stader Str. 3-5, 21614 Buxtehude"),
        # Structured shape must still format.
        (
            {"street": "Hauptstraße 12", "postal_code": "60311", "city": "Frankfurt"},
            "Hauptstraße 12, 60311 Frankfurt",
        ),
        # Plain string passes through.
        ("Musterweg 1, 10115 Berlin", "Musterweg 1, 10115 Berlin"),
    ],
)
def test_identify_returns_stored_customer_fields(monkeypatch, stored_address, expected_address):
    """hk_identifyCustomer must surface the stored name/email/address for a known
    customer so the agent can skip re-collecting them on a repeat call."""
    row = {
        "id": "cust-1",
        "full_name": "Maria Schmidt",
        "phone": "+4917663181301",
        "email": "maria@example.de",
        "customer_number": "KD-00042",
        "address": stored_address,
    }
    monkeypatch.setattr(identify, "get_service_client", lambda: _FakeDBClient([row]))
    req = IdentifyCustomerRequest.model_validate(
        {"_agentId": "agent_x", "phoneNumber": "+4917663181301"}
    )
    res = identify.identify_customer("org-x", req)

    assert res["status"] == "EXISTING_CUSTOMER"
    assert res["customerId"] == "cust-1"
    assert res["name"] == "Maria Schmidt"
    assert res["email"] == "maria@example.de"
    assert res["address"] == expected_address


@pytest.mark.parametrize("caller", [None, ""])
def test_conversation_init_empty_when_no_phone(caller):
    res = conversation_init("org-x", caller)
    assert res["type"] == "conversation_initiation_client_data"
    dv = res["dynamic_variables"]
    assert dv["customer_found"] is False
    assert dv["customer_id"] == ""
    assert dv["customer_name"] == ""
    assert dv["customer_number"] == ""
    assert dv["customer_address"] == ""
    assert dv["customer_email"] == ""


def test_post_call_payload_extraction_handles_all_shapes():
    from app.services.post_call import _extract, _normalize

    # N8N item array → body.data envelope
    n8n = [{"headers": {}, "body": {"type": "post_call_transcription",
            "data": {"conversation_id": "c1", "agent_id": "a1"}}}]
    items = _normalize(n8n)
    assert len(items) == 1
    data, fmt = items[0]
    assert fmt == "envelope" and data["conversation_id"] == "c1"

    # Bare ElevenLabs envelope
    data, fmt = _extract({"type": "post_call_transcription",
                          "data": {"conversation_id": "c2"}})
    assert fmt == "envelope" and data["conversation_id"] == "c2"

    # Flat payload (handover bug #4 guard)
    data, fmt = _extract({"conversation_id": "c3", "agent_id": "a3"})
    assert fmt == "flat" and data["conversation_id"] == "c3"

    # Unparseable
    data, fmt = _extract({"nope": 1})
    assert data is None and fmt == "unknown"
