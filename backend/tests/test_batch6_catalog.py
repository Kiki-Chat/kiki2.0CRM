"""Batch 6 — catalog import dedup / upsert (INV-030).

Covers:
  6.1  Re-importing a CSV with a matching article_number UPDATEs the existing
       row instead of inserting a duplicate.
  6.2  A new article_number that does not yet exist in the catalog is INSERTed.
  6.3  Intra-file duplicate article_numbers keep the LAST occurrence (last row
       in the CSV wins).
  6.4  Rows with NO article_number are de-duped within the file by name
       (last wins) and are always inserted.
  6.5  Rows with an empty name are counted as skipped (uebersprungen).
  6.6  Return dict keys are German: hinzugefuegt / aktualisiert / uebersprungen.

All DB access is mocked — no network, no real Supabase.
"""
from __future__ import annotations

import io
import csv
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Minimal mock Supabase client
# ─────────────────────────────────────────────────────────────────────────────

class _Query:
    """Chainable PostgREST-style query backed by an in-memory store.

    Supports the subset used by _import_csv:
    select / eq / insert / update / execute.
    """

    def __init__(self, store: "_Store", table: str):
        self._store = store
        self._table = table
        self._eq_filters: list[tuple[str, object]] = []
        self._update_fields: dict | None = None
        self._insert_payload: list[dict] | dict | None = None

    # ---- filter builders ------------------------------------------------
    def select(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        return self

    def eq(self, col, val):
        self._eq_filters.append((col, val))
        return self

    # ---- mutation builders -----------------------------------------------
    def insert(self, payload):
        """Accept list[dict] or dict; store in _store.inserts and table."""
        rows = payload if isinstance(payload, list) else [payload]
        self._store.inserts.setdefault(self._table, []).extend(rows)
        new_rows = []
        for row in rows:
            new = {
                "id": f"{self._table}_{len(self._store.tables.get(self._table, []))}",
                **row,
            }
            self._store.tables.setdefault(self._table, []).append(new)
            new_rows.append(new)
        # Return a new query object that already knows what was inserted
        q = _Query(self._store, self._table)
        q._insert_payload = new_rows
        return q

    def update(self, fields: dict):
        q = _Query(self._store, self._table)
        q._update_fields = fields
        q._eq_filters = list(self._eq_filters)
        q._store = self._store
        q._table = self._table
        return q

    # ---- terminal --------------------------------------------------------
    def _match(self, row: dict) -> bool:
        for col, val in self._eq_filters:
            if row.get(col) != val:
                return False
        return True

    def execute(self):
        # If this is the result of an insert() call, return the inserted rows.
        if self._insert_payload is not None:
            return SimpleNamespace(data=list(self._insert_payload))

        # If this is the result of an update() call, apply the update.
        if self._update_fields is not None:
            updated = []
            for row in self._store.tables.get(self._table, []):
                if self._match(row):
                    row.update(self._update_fields)
                    self._store.updates.setdefault(self._table, []).append(dict(row))
                    updated.append(dict(row))
            return SimpleNamespace(data=updated)

        # Plain select.
        rows = [r for r in self._store.tables.get(self._table, []) if self._match(r)]
        return SimpleNamespace(data=[dict(r) for r in rows])


class _Store:
    def __init__(self, tables: dict[str, list[dict]] | None = None):
        self.tables: dict[str, list[dict]] = {
            k: [dict(row) for row in v] for k, v in (tables or {}).items()
        }
        self.inserts: dict[str, list[dict]] = {}
        self.updates: dict[str, list[dict]] = {}

    def client(self) -> MagicMock:
        c = MagicMock()
        c.table.side_effect = lambda name: _Query(self, name)
        return c


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

ORG = "org-test-001"


def _make_csv(*rows: dict) -> bytes:
    """Build a semicolon-delimited CSV from a list of dicts using German headers."""
    fieldnames = [
        "Artikelnummer", "Bezeichnung", "Beschreibung", "Kategorie",
        "Einheit", "MwSt", "Verkaufspreis", "Einkaufspreis", "Aktiv",
    ]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, delimiter=";")
    w.writeheader()
    for row in rows:
        full = {f: "" for f in fieldnames}
        full.update(row)
        w.writerow(full)
    return buf.getvalue().encode("utf-8")


def _run_import(store: _Store, csv_bytes: bytes) -> dict:
    """Patch get_service_client and run _import_csv."""
    from app.api.routes.catalog import _import_csv

    with patch("app.api.routes.catalog.get_service_client", return_value=store.client()):
        return _import_csv(ORG, csv_bytes)


# ─────────────────────────────────────────────────────────────────────────────
# 6.1  Re-import: matching article_number → UPDATE, not INSERT
# ─────────────────────────────────────────────────────────────────────────────

def test_reimport_updates_existing_article_number():
    """Uploading a CSV where article_number already exists must UPDATE the row."""
    existing_id = "item-existing-001"
    store = _Store(
        tables={
            "catalog_items": [
                {
                    "id": existing_id,
                    "org_id": ORG,
                    "article_number": "ART-001",
                    "name": "Altes Produkt",
                    "unit_price": 10.0,
                    "is_active": True,
                }
            ]
        }
    )

    csv_bytes = _make_csv(
        {"Artikelnummer": "ART-001", "Bezeichnung": "Neues Produkt", "Verkaufspreis": "25.00"}
    )
    result = _run_import(store, csv_bytes)

    # Must report 0 inserts, 1 update.
    assert result["hinzugefuegt"] == 0
    assert result["aktualisiert"] == 1
    assert result["uebersprungen"] == 0

    # The catalog_items table should still have only 1 row, now with updated name.
    items = store.tables.get("catalog_items", [])
    assert len(items) == 1
    assert items[0]["name"] == "Neues Produkt"

    # No new inserts to catalog_items.
    assert "catalog_items" not in store.inserts or store.inserts.get("catalog_items", []) == []


# ─────────────────────────────────────────────────────────────────────────────
# 6.2  New article_number → INSERT
# ─────────────────────────────────────────────────────────────────────────────

def test_new_article_number_inserts():
    """A CSV row with an article_number not yet in the catalog must be INSERTed."""
    store = _Store(tables={"catalog_items": []})

    csv_bytes = _make_csv(
        {"Artikelnummer": "ART-NEW", "Bezeichnung": "Neues Teil", "Verkaufspreis": "50.00"}
    )
    result = _run_import(store, csv_bytes)

    assert result["hinzugefuegt"] == 1
    assert result["aktualisiert"] == 0
    assert result["uebersprungen"] == 0

    # Row should now be in the table.
    items = store.tables.get("catalog_items", [])
    assert len(items) == 1
    assert items[0]["article_number"] == "ART-NEW"


# ─────────────────────────────────────────────────────────────────────────────
# 6.3  Intra-file duplicate article_numbers — last occurrence wins
# ─────────────────────────────────────────────────────────────────────────────

def test_intrafile_duplicate_article_number_keeps_last():
    """When the same article_number appears twice in the CSV, the LAST row wins."""
    store = _Store(tables={"catalog_items": []})

    csv_bytes = _make_csv(
        {"Artikelnummer": "ART-DUP", "Bezeichnung": "Erster Eintrag", "Verkaufspreis": "10.00"},
        {"Artikelnummer": "ART-DUP", "Bezeichnung": "Letzter Eintrag", "Verkaufspreis": "99.00"},
    )
    result = _run_import(store, csv_bytes)

    # Only 1 insert (the de-duped last occurrence), not 2.
    assert result["hinzugefuegt"] == 1
    assert result["aktualisiert"] == 0

    inserts = store.inserts.get("catalog_items", [])
    # The single inserted batch should contain only 1 row.
    assert len(inserts) == 1
    assert inserts[0]["name"] == "Letzter Eintrag"
    assert inserts[0]["unit_price"] == 99.0


# ─────────────────────────────────────────────────────────────────────────────
# 6.4  No article_number: de-dup by name, always insert
# ─────────────────────────────────────────────────────────────────────────────

def test_no_article_number_deduped_by_name_and_inserted():
    """Rows without article_number are de-duped by name (last wins) and INSERTed."""
    store = _Store(tables={"catalog_items": []})

    csv_bytes = _make_csv(
        {"Artikelnummer": "", "Bezeichnung": "Pauschale", "Verkaufspreis": "5.00"},
        {"Artikelnummer": "", "Bezeichnung": "Pauschale", "Verkaufspreis": "8.00"},  # dup
        {"Artikelnummer": "", "Bezeichnung": "Anfahrt", "Verkaufspreis": "15.00"},
    )
    result = _run_import(store, csv_bytes)

    # "Pauschale" appears twice → de-duped to 1; "Anfahrt" = 1 → total 2 inserts.
    assert result["hinzugefuegt"] == 2

    inserts = store.inserts.get("catalog_items", [])
    names = [r["name"] for r in inserts]
    assert "Pauschale" in names
    assert "Anfahrt" in names
    # The last "Pauschale" row (8.00) wins.
    pauschale = next(r for r in inserts if r["name"] == "Pauschale")
    assert pauschale["unit_price"] == 8.0


# ─────────────────────────────────────────────────────────────────────────────
# 6.5  Empty name → skipped
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_name_is_skipped():
    """Rows where Bezeichnung is empty must be counted as uebersprungen."""
    store = _Store(tables={"catalog_items": []})

    csv_bytes = _make_csv(
        {"Artikelnummer": "ART-OK", "Bezeichnung": "Gültiger Artikel", "Verkaufspreis": "10.00"},
        {"Artikelnummer": "ART-BAD", "Bezeichnung": "", "Verkaufspreis": "5.00"},
    )
    result = _run_import(store, csv_bytes)

    assert result["hinzugefuegt"] == 1
    assert result["aktualisiert"] == 0
    assert result["uebersprungen"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 6.6  Mixed: some updates + some inserts in a single CSV
# ─────────────────────────────────────────────────────────────────────────────

def test_mixed_update_and_insert():
    """A single CSV with both known and new article_numbers produces correct counts."""
    store = _Store(
        tables={
            "catalog_items": [
                {
                    "id": "item-A",
                    "org_id": ORG,
                    "article_number": "ART-A",
                    "name": "Artikel A alt",
                    "unit_price": 1.0,
                    "is_active": True,
                }
            ]
        }
    )

    csv_bytes = _make_csv(
        {"Artikelnummer": "ART-A", "Bezeichnung": "Artikel A neu", "Verkaufspreis": "2.00"},
        {"Artikelnummer": "ART-B", "Bezeichnung": "Artikel B neu", "Verkaufspreis": "3.00"},
    )
    result = _run_import(store, csv_bytes)

    assert result["hinzugefuegt"] == 1
    assert result["aktualisiert"] == 1
    assert result["uebersprungen"] == 0

    # Verify the update actually changed the name.
    items = {r["id"]: r for r in store.tables["catalog_items"]}
    assert items["item-A"]["name"] == "Artikel A neu"
