"""Batch 9.1 — save-time validation on free-text fields rendered verbatim into agent prompts.

Hermetic unit tests — no network, no DB.

Coverage:
  - CategoryCreate.name: strips whitespace; >80 chars → ValidationError with German message
  - CategoryCreate.description: strips whitespace; >500 chars → ValidationError with German message
  - CategoryUpdate.name: strips whitespace; >80 chars → ValidationError with German message
  - CategoryUpdate.description: strips whitespace; >500 chars → ValidationError with German message
  - ContextUpdate.trade: strips whitespace; >120 chars → ValidationError with German message
  - ContextUpdate.knowledge_text: strips whitespace; >2000 chars → ValidationError with German message
  - ProblemDescriptionUpdate.problem_description: strips; >2000 chars → ValidationError with German message
  - At-cap values are accepted (boundary test)
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.routes.kiki_zentrale import (
    CategoryCreate,
    CategoryUpdate,
    ContextUpdate,
    ProblemDescriptionUpdate,
)


# ─── CategoryCreate ───────────────────────────────────────────────────────────

class TestCategoryCreateName:
    def test_trims_whitespace(self):
        m = CategoryCreate(name="  Heizung  ")
        assert m.name == "Heizung"

    def test_at_cap_ok(self):
        m = CategoryCreate(name="x" * 80)
        assert len(m.name) == 80

    def test_over_cap_raises_422(self):
        with pytest.raises(ValidationError) as exc_info:
            CategoryCreate(name="x" * 81)
        assert "80 Zeichen" in str(exc_info.value)

    def test_german_error_message(self):
        with pytest.raises(ValidationError) as exc_info:
            CategoryCreate(name="ü" * 81)
        errors = exc_info.value.errors()
        assert any("Kategoriename" in (e.get("msg") or "") for e in errors)


class TestCategoryCreateDescription:
    def test_trims_whitespace(self):
        m = CategoryCreate(name="Test", description="  Beschreibung  ")
        assert m.description == "Beschreibung"

    def test_none_is_ok(self):
        m = CategoryCreate(name="Test", description=None)
        assert m.description is None

    def test_at_cap_ok(self):
        m = CategoryCreate(name="Test", description="x" * 500)
        assert len(m.description) == 500

    def test_over_cap_raises_422(self):
        with pytest.raises(ValidationError) as exc_info:
            CategoryCreate(name="Test", description="x" * 501)
        assert "500 Zeichen" in str(exc_info.value)

    def test_german_error_message(self):
        with pytest.raises(ValidationError) as exc_info:
            CategoryCreate(name="Test", description="ä" * 501)
        errors = exc_info.value.errors()
        assert any("Kategoriebeschreibung" in (e.get("msg") or "") for e in errors)


# ─── CategoryUpdate ───────────────────────────────────────────────────────────

class TestCategoryUpdateName:
    def test_trims_whitespace(self):
        m = CategoryUpdate(name="  Sanitär  ")
        assert m.name == "Sanitär"

    def test_none_is_ok(self):
        m = CategoryUpdate(name=None)
        assert m.name is None

    def test_at_cap_ok(self):
        m = CategoryUpdate(name="y" * 80)
        assert len(m.name) == 80

    def test_over_cap_raises_422(self):
        with pytest.raises(ValidationError) as exc_info:
            CategoryUpdate(name="y" * 81)
        assert "80 Zeichen" in str(exc_info.value)

    def test_german_error_message(self):
        with pytest.raises(ValidationError) as exc_info:
            CategoryUpdate(name="z" * 81)
        errors = exc_info.value.errors()
        assert any("Kategoriename" in (e.get("msg") or "") for e in errors)


class TestCategoryUpdateDescription:
    def test_trims_whitespace(self):
        m = CategoryUpdate(description="  Details  ")
        assert m.description == "Details"

    def test_none_is_ok(self):
        m = CategoryUpdate(description=None)
        assert m.description is None

    def test_at_cap_ok(self):
        m = CategoryUpdate(description="a" * 500)
        assert len(m.description) == 500

    def test_over_cap_raises_422(self):
        with pytest.raises(ValidationError) as exc_info:
            CategoryUpdate(description="a" * 501)
        assert "500 Zeichen" in str(exc_info.value)

    def test_german_error_message(self):
        with pytest.raises(ValidationError) as exc_info:
            CategoryUpdate(description="b" * 501)
        errors = exc_info.value.errors()
        assert any("Kategoriebeschreibung" in (e.get("msg") or "") for e in errors)


# ─── ContextUpdate ────────────────────────────────────────────────────────────

class TestContextUpdateTrade:
    def test_trims_whitespace(self):
        m = ContextUpdate(trade="  Elektriker  ")
        assert m.trade == "Elektriker"

    def test_none_is_ok(self):
        m = ContextUpdate(trade=None)
        assert m.trade is None

    def test_at_cap_ok(self):
        m = ContextUpdate(trade="t" * 120)
        assert len(m.trade) == 120

    def test_over_cap_raises_422(self):
        with pytest.raises(ValidationError) as exc_info:
            ContextUpdate(trade="t" * 121)
        assert "120 Zeichen" in str(exc_info.value)

    def test_german_error_message(self):
        with pytest.raises(ValidationError) as exc_info:
            ContextUpdate(trade="ö" * 121)
        errors = exc_info.value.errors()
        assert any("Branche" in (e.get("msg") or "") or "Gewerk" in (e.get("msg") or "") for e in errors)


class TestContextUpdateKnowledgeText:
    def test_trims_whitespace(self):
        m = ContextUpdate(knowledge_text="  Wissen  ")
        assert m.knowledge_text == "Wissen"

    def test_none_is_ok(self):
        m = ContextUpdate(knowledge_text=None)
        assert m.knowledge_text is None

    def test_at_cap_ok(self):
        m = ContextUpdate(knowledge_text="k" * 2000)
        assert len(m.knowledge_text) == 2000

    def test_over_cap_raises_422(self):
        with pytest.raises(ValidationError) as exc_info:
            ContextUpdate(knowledge_text="k" * 2001)
        assert "2000 Zeichen" in str(exc_info.value)

    def test_german_error_message(self):
        with pytest.raises(ValidationError) as exc_info:
            ContextUpdate(knowledge_text="ü" * 2001)
        errors = exc_info.value.errors()
        assert any("Wissenstext" in (e.get("msg") or "") or "Kontext" in (e.get("msg") or "") for e in errors)


# ─── ProblemDescriptionUpdate ─────────────────────────────────────────────────

class TestProblemDescriptionUpdate:
    def test_trims_whitespace(self):
        m = ProblemDescriptionUpdate(problem_description="  Schaden  ")
        assert m.problem_description == "Schaden"

    def test_none_is_ok(self):
        m = ProblemDescriptionUpdate(problem_description=None)
        assert m.problem_description is None

    def test_at_cap_ok(self):
        m = ProblemDescriptionUpdate(problem_description="p" * 2000)
        assert len(m.problem_description) == 2000

    def test_over_cap_raises_422(self):
        with pytest.raises(ValidationError) as exc_info:
            ProblemDescriptionUpdate(problem_description="p" * 2001)
        assert "2000 Zeichen" in str(exc_info.value)

    def test_german_error_message(self):
        with pytest.raises(ValidationError) as exc_info:
            ProblemDescriptionUpdate(problem_description="q" * 2001)
        errors = exc_info.value.errors()
        assert any("Problembeschreibung" in (e.get("msg") or "") for e in errors)
