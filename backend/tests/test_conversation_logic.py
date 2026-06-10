"""Gesprächslogik — validation + deterministic compiler."""

import pytest

from app.schemas.conversation_logic import (
    ConversationLogic,
    LogicError,
    compile_conversation_logic,
    validate_conversation_logic,
)
from app.services import agent_config as ac


def _autoteile_tree() -> dict:
    """The user's Kfz-Werkstatt example, expressed as a rule tree."""
    return {
        "version": 1,
        "blocks": [
            {
                "branches": [
                    {
                        "kind": "wenn",
                        "conditions": [
                            "ein Dienstleister, Lieferant oder Steuerberater ruft an (kein Kunde)"
                        ],
                        "condition_op": "und",
                        "actions": [
                            {"type": "ask", "text": "Worum geht es bei Ihrem Anliegen?"},
                            {"type": "goto", "target": "abschluss"},
                        ],
                    }
                ]
            },
            {
                "branches": [
                    {
                        "kind": "wenn",
                        "conditions": ["es ist eine Kundenanfrage"],
                        "condition_op": "und",
                        "actions": [
                            {"type": "ask", "text": "Warst du schonmal mit deinem Fahrzeug bei uns?"},
                            {
                                "type": "subrule",
                                "rule": {
                                    "branches": [
                                        {
                                            "kind": "wenn",
                                            "conditions": ["Ja"],
                                            "condition_op": "und",
                                            "actions": [
                                                {"type": "ask", "text": "Kennzeichen, Vor- und Zuname sowie Telefonnummer?"},
                                            ],
                                        },
                                        {
                                            "kind": "sonst",
                                            "conditions": [],
                                            "actions": [
                                                {"type": "ask", "text": "Was für ein Fahrzeug (Hersteller, Modell)?"},
                                                {"type": "say", "text": "Bitte ein Foto des Fahrzeugscheins per WhatsApp senden."},
                                            ],
                                        },
                                    ]
                                },
                            },
                            {"type": "goto", "target": "schritt_2"},
                        ],
                    }
                ]
            },
        ],
    }


def test_compiler_produces_numbered_german_block():
    logic = ConversationLogic.model_validate(_autoteile_tree())
    validate_conversation_logic(logic)
    out = compile_conversation_logic(logic)
    assert out.startswith("1. Wenn ein Dienstleister")
    assert "1.1 Frage: „Worum geht es bei Ihrem Anliegen?“" in out
    assert "Gehe danach direkt zu zum Abschluss" in out
    assert "2. Wenn es ist eine Kundenanfrage" in out or "2. Wenn es" in out
    # Subrule branches keep the n.k numbering with dash bullets.
    assert "2.2 Wenn Ja:" in out
    assert "- Frage: „Kennzeichen, Vor- und Zuname sowie Telefonnummer?“" in out
    assert "Sonst:" in out
    # Deterministic: same input → same output.
    assert out == compile_conversation_logic(ConversationLogic.model_validate(_autoteile_tree()))


def test_or_conditions_join_with_oder():
    logic = ConversationLogic.model_validate({
        "version": 1,
        "blocks": [{
            "branches": [{
                "kind": "wenn",
                "conditions": ["der Anrufer ist Mieter", "der Anrufer ist Hausverwaltung"],
                "condition_op": "oder",
                "actions": [{"type": "say", "text": "Objektadresse zuerst erfragen."}],
            }]
        }],
    })
    out = compile_conversation_logic(logic)
    assert "Mieter ODER der Anrufer ist Hausverwaltung" in out


def test_validation_rejects_sonst_first_and_deep_nesting():
    with pytest.raises(LogicError):
        validate_conversation_logic(ConversationLogic.model_validate({
            "version": 1,
            "blocks": [{"branches": [{"kind": "sonst", "conditions": [], "actions": [{"type": "say", "text": "x"}]}]}],
        }))
    nested = {
        "version": 1,
        "blocks": [{
            "branches": [{
                "kind": "wenn", "conditions": ["a"], "condition_op": "und",
                "actions": [{"type": "subrule", "rule": {"branches": [{
                    "kind": "wenn", "conditions": ["b"], "condition_op": "und",
                    "actions": [{"type": "subrule", "rule": {"branches": [{
                        "kind": "wenn", "conditions": ["c"], "condition_op": "und",
                        "actions": [{"type": "say", "text": "x"}],
                    }]}}],
                }]}}],
            }]
        }],
    }
    with pytest.raises(LogicError):
        validate_conversation_logic(ConversationLogic.model_validate(nested))


def test_render_block_disabled_or_empty_is_empty():
    assert ac.render_conversation_logic_block({}) == ""
    assert ac.render_conversation_logic_block({"conversation_logic_enabled": False, "conversation_logic": _autoteile_tree()}) == ""
    assert ac.render_conversation_logic_block({"conversation_logic": {"version": 1, "blocks": []}}) == ""


def test_render_block_wraps_with_schritt_1a_header():
    out = ac.render_conversation_logic_block({
        "conversation_logic_enabled": True,
        "conversation_logic": _autoteile_tree(),
    })
    assert out.startswith("## Schritt 1a — Firmenspezifische Gesprächslogik")
    assert "1. Wenn ein Dienstleister" in out
