"""The spoken-naming prompt region (#11): the FEAT:suggest_employee block in the
agent template is kept when the toggle is ON and removed when OFF (default), with
no leftover markers either way — in lock-step with the slot tool's name gating."""
import pathlib

from app.services import agent_config


def _template() -> str:
    return pathlib.Path(agent_config.__file__).with_name("agent_prompt_template.txt").read_text(
        encoding="utf-8"
    )


def test_suggest_employee_region_present_in_template():
    text = _template()
    assert "<!-- FEAT:suggest_employee -->" in text
    assert "<!-- /FEAT:suggest_employee -->" in text


def test_suggest_employee_region_on_keeps_naming_guidance():
    on = agent_config._apply_feature_regions(
        _template(), {"notdienst": True, "suggest_employee": True}
    )
    assert "employeeName" in on  # the naming instruction survives when ON
    assert "FEAT:" not in on      # markers stripped, none leak into the live prompt


def test_suggest_employee_region_off_removes_naming_guidance():
    off = agent_config._apply_feature_regions(
        _template(), {"notdienst": True, "suggest_employee": False}
    )
    assert "employeeName" not in off  # naming guidance gone when OFF (default)
    assert "FEAT:" not in off
