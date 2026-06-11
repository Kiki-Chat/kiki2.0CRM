"""Hermetic tests for the NL → Gesprächslogik generator.

The LLM is a scripted fake (ai.client.set_test_client); usage logging is
patched out, so no DB/network is touched. What matters: the generated tree is
validated + compiled by the SAME code path as the manual editor, invalid model
output gets exactly one repair round-trip, and failures surface German errors.
"""
import json

import pytest

from app.services import conversation_logic_ai as gen
from app.services.ai import client as ai_client


class _Usage:
    prompt_tokens = 10
    completion_tokens = 5


class _Resp:
    def __init__(self, content):
        msg = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"message": msg})()]
        self.usage = _Usage()
        self.model = "gpt-4o"


class _Completions:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kwargs):
        self.outer.calls.append(kwargs)
        return self.outer.responses.pop(0)


class _ScriptedClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.chat = type("Chat", (), {})()
        self.chat.completions = _Completions(self)


VALID_TREE = {
    "version": 1,
    "blocks": [
        {
            "branches": [
                {
                    "kind": "wenn",
                    "conditions": ["der Anrufer ist ein Lieferant"],
                    "condition_op": "und",
                    "actions": [
                        {"type": "ask", "text": "Wie lautet Ihre Lieferantennummer?"},
                        {"type": "goto", "target": "abschluss"},
                    ],
                },
                {
                    "kind": "sonst",
                    "actions": [{"type": "ask", "text": "Wie lautet Ihre Kundennummer?"}],
                },
            ]
        }
    ],
}


@pytest.fixture(autouse=True)
def _no_usage(monkeypatch):
    monkeypatch.setattr(gen, "log_usage", lambda **kw: None)
    yield
    ai_client.set_test_client(None)


def _generate(description="Lieferanten nach Lieferantennummer fragen, Kunden nach Kundennummer."):
    return gen.generate_logic_from_text(
        org_id="org1", user_id="u1", description=description
    )


def test_valid_tree_is_compiled_and_gets_ids():
    ai_client.set_test_client(_ScriptedClient([_Resp(json.dumps(VALID_TREE))]))
    out = _generate()
    assert "Lieferantennummer" in out["text"]
    assert out["text"].startswith("1. Wenn der Anrufer ist ein Lieferant")
    # Every node got an id for the manual editor.
    rule = out["logic"]["blocks"][0]
    assert rule["id"] and all(b["id"] for b in rule["branches"])
    assert all(a["id"] for b in rule["branches"] for a in b["actions"])


def test_invalid_tree_gets_one_repair_attempt():
    broken = {"version": 1, "blocks": [{"branches": [{"kind": "sonst", "actions": []}]}]}
    scripted = _ScriptedClient([_Resp(json.dumps(broken)), _Resp(json.dumps(VALID_TREE))])
    ai_client.set_test_client(scripted)
    out = _generate()
    assert "Lieferantennummer" in out["text"]
    # Second call carried the German validator error back to the model.
    repair_msgs = scripted.calls[1]["messages"]
    assert any("ungültig" in (m.get("content") or "") for m in repair_msgs if m["role"] == "user")


def test_two_invalid_rounds_raise_german_error():
    broken = json.dumps({"version": 1, "blocks": [{"branches": []}]})
    ai_client.set_test_client(_ScriptedClient([_Resp(broken), _Resp(broken)]))
    with pytest.raises(gen.GenerationFailed) as exc:
        _generate()
    assert "konnten nicht erstellt werden" in str(exc.value)


def test_empty_compilation_is_rejected():
    empty = json.dumps({"version": 1, "blocks": []})
    ai_client.set_test_client(_ScriptedClient([_Resp(empty), _Resp(empty)]))
    with pytest.raises(gen.GenerationFailed):
        _generate()


def test_code_fenced_json_is_tolerated():
    fenced = "```json\n" + json.dumps(VALID_TREE) + "\n```"
    ai_client.set_test_client(_ScriptedClient([_Resp(fenced)]))
    out = _generate()
    assert out["logic"]["blocks"]


def test_ask_field_tree_compiles_with_field_reference():
    tree = {
        "version": 1,
        "blocks": [{
            "branches": [{
                "kind": "wenn", "conditions": ["der Anrufer ein Kunde ist"], "condition_op": "und",
                "actions": [{"type": "ask_field", "field_key": "customer_number", "text": "Kundennummer"}],
            }],
        }],
    }
    ai_client.set_test_client(_ScriptedClient([_Resp(json.dumps(tree))]))
    out = _generate()
    assert "Leitfaden-Feld **Kundennummer**" in out["text"]
    assert out["logic"]["blocks"][0]["branches"][0]["actions"][0]["field_key"] == "customer_number"


def test_guide_fields_are_offered_to_the_model():
    scripted = _ScriptedClient([_Resp(json.dumps(VALID_TREE))])
    ai_client.set_test_client(scripted)
    gen.generate_logic_from_text(
        org_id="org1", user_id="u1", description="Kunden nach der Kundennummer fragen.",
        fields=[{"field_key": "name", "label": "Name"}, {"field_key": "customer_number", "label": "Kundennummer"}],
    )
    user_msg = scripted.calls[0]["messages"][1]["content"]
    assert 'field_key "customer_number": Kundennummer' in user_msg


def test_ask_field_without_field_key_is_invalid():
    broken = {
        "version": 1,
        "blocks": [{
            "branches": [{
                "kind": "wenn", "conditions": ["x"], "condition_op": "und",
                "actions": [{"type": "ask_field", "text": "Kundennummer"}],
            }],
        }],
    }
    ai_client.set_test_client(_ScriptedClient([_Resp(json.dumps(broken)), _Resp(json.dumps(VALID_TREE))]))
    out = _generate()  # repair round-trip fixes it
    assert "Lieferantennummer" in out["text"]


def test_existing_rules_are_passed_to_the_model():
    scripted = _ScriptedClient([_Resp(json.dumps(VALID_TREE))])
    ai_client.set_test_client(scripted)
    gen.generate_logic_from_text(
        org_id="org1", user_id="u1",
        description="Ergänze: Notfälle sofort zu Schritt 3.",
        existing=VALID_TREE,
    )
    user_msg = scripted.calls[0]["messages"][1]["content"]
    assert "Bestehende Regeln" in user_msg
