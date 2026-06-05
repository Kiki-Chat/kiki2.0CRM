"""P2 / Wave 4 — CSV import for customers + employees.

Hermetic (no DB): a fake supabase client returns existing rows (for dedup +
numbering) and captures inserts. Covers parse (delimiter + encoding), phone
normalization, the customer mapping (customer_type='regular', Kundennummer kept,
Bemerkung verbatim, Mobil preserved, address built), dedup (existing + in-batch),
numbering continuation, and the employee mapping + dedup.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services import csv_import
from app.services.common import gen_customer_number


# ─── fake supabase client ────────────────────────────────────────────────────
class _Chain:
    def __init__(self, table, db):
        self.table = table
        self.db = db
        self._op = None
        self._payload = None

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        self.db.inserts.append((self.table, payload))
        return self

    def execute(self):
        r = MagicMock()
        if self._op == "insert":
            r.data = self._payload if isinstance(self._payload, list) else [self._payload]
        else:
            r.data = list(self.db.rows.get(self.table, []))
        r.count = len(r.data)
        return r


class _DB:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.inserts: list = []

    def inserted(self, table):
        out = []
        for t, p in self.inserts:
            if t == table:
                out.extend(p if isinstance(p, list) else [p])
        return out

    def table(self, name):
        return _Chain(name, self)


_CUST_MAP = {
    "full_name": "Name",
    "email": "Mail",
    "phone": "Telefon",
    "phone2": "Mobil",
    "street": "Strasse",
    "postal_code": "PLZ",
    "city": "Ort",
    "notes": "Bemerkung",
    "customer_number": "Kundennummer",
}


def _cust_csv(extra_rows: str = "") -> bytes:
    head = "Kundennummer,Name,Mail,Telefon,Mobil,Strasse,PLZ,Ort,Bemerkung\n"
    base = (
        '101002,Heiko Adam,adam@adamweb.de,040 59466635 nicht anrufe,0175 8771486,'
        'Wischenwinkel 17,21147,Hamburg,"Messihaushalt, nur auf Mobil anrufen!"\n'
    )
    return (head + base + extra_rows).encode("utf-8")


# ─── parse ───────────────────────────────────────────────────────────────────
def test_parse_csv_comma_with_umlauts():
    headers, rows = csv_import.parse_csv(_cust_csv())
    assert "Kundennummer" in headers and "Bemerkung" in headers
    assert rows[0]["Name"] == "Heiko Adam"
    assert "Messihaushalt" in rows[0]["Bemerkung"]


def test_parse_csv_semicolon_and_cp1252():
    content = "Name;Ort\nMüller;Köln\n".encode("cp1252")
    headers, rows = csv_import.parse_csv(content)
    assert headers == ["Name", "Ort"]
    assert rows[0] == {"Name": "Müller", "Ort": "Köln"}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("040 59466635 nicht anrufe", "+494059466635"),  # trailing note dropped
        ("0175 8771486", "+491758771486"),
        ("+4915734432281", "+4915734432281"),
        ("", None),
        ("-", None),  # no digits → None
    ],
)
def test_clean_phone(raw, expected):
    assert csv_import.clean_phone(raw) == expected


# ─── customers ───────────────────────────────────────────────────────────────
def test_import_customers_happy_path(monkeypatch):
    db = _DB({"customers": []})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", _cust_csv(), _CUST_MAP)

    assert out["imported"] == 1 and out["skipped_duplicate"] == 0 and out["errors"] == 0
    rec = db.inserted("customers")[0]
    assert rec["full_name"] == "Heiko Adam"
    assert rec["email"] == "adam@adamweb.de"
    assert rec["phone"] == "+494059466635"  # trailing "nicht anrufe" dropped
    assert rec["customer_type"] == "regular"  # CSV → Stammkunde, never "new"
    assert rec["identified_by"] == "csv_import"
    assert rec["customer_number"] == "101002"  # CSV Kundennummer kept
    assert rec["address"] == {"street": "Wischenwinkel 17", "postal_code": "21147", "city": "Hamburg"}
    assert "Messihaushalt, nur auf Mobil anrufen!" in rec["notes"]  # Bemerkung verbatim
    assert rec["phone2"] == "+491758771486"  # Mobil → its own phone2 column


def test_import_customers_skips_existing_email(monkeypatch):
    db = _DB({"customers": [{"email": "adam@adamweb.de", "phone": None, "customer_number": "101001"}]})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", _cust_csv(), _CUST_MAP)
    assert out["imported"] == 0 and out["skipped_duplicate"] == 1
    assert db.inserted("customers") == []
    assert out["results"][0]["status"] == "skipped_duplicate"


def test_import_customers_skips_existing_phone_same_name(monkeypatch):
    # Same phone AND same name as an existing row → genuine duplicate, skipped.
    db = _DB({"customers": [
        {"email": None, "phone": "+494059466635", "full_name": "Heiko Adam", "customer_number": "1"},
    ]})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", _cust_csv(), _CUST_MAP)
    assert out["imported"] == 0 and out["skipped_duplicate"] == 1


def test_import_customers_same_phone_different_name_is_kept(monkeypatch):
    # SHARED-LANDLINE BUG FIX: a married couple (or property manager) shares one
    # phone but is two distinct people — the second MUST NOT be dropped as a dupe.
    db = _DB({"customers": [
        {"email": None, "phone": "+494059466635", "full_name": "Heike Adam", "customer_number": "1"},
    ]})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", _cust_csv(), _CUST_MAP)  # CSV row = "Heiko Adam"
    assert out["imported"] == 1 and out["skipped_duplicate"] == 0
    assert db.inserted("customers")[0]["full_name"] == "Heiko Adam"


def test_import_two_people_one_phone_within_batch(monkeypatch):
    # Two different names, same phone, in the SAME file → both imported.
    couple = (
        '101003,Werner Breuhahn,,04164 812949,,Weg 1,21680,Stade,Ehemann\n'
        '101004,Heike Breuhahn,,04164 812949,,Weg 1,21680,Stade,Ehefrau\n'
    )
    csv_bytes = (
        "Kundennummer,Name,Mail,Telefon,Mobil,Strasse,PLZ,Ort,Bemerkung\n" + couple
    ).encode("utf-8")
    db = _DB({"customers": []})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", csv_bytes, _CUST_MAP)
    assert out["imported"] == 2 and out["skipped_duplicate"] == 0


def test_import_customers_phone_in_email_field(monkeypatch):
    # The source 'Mail' column held a mobile number (real HUD data). It must NOT be
    # stored as an email; with no Mobil set, it is salvaged into phone2.
    row = (
        '122015,Tierschutzverein,0171 697 3333,04161 5409977,,Str 1,21614,Buxtehude,note\n'
    )
    csv_bytes = (
        "Kundennummer,Name,Mail,Telefon,Mobil,Strasse,PLZ,Ort,Bemerkung\n" + row
    ).encode("utf-8")
    db = _DB({"customers": []})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", csv_bytes, _CUST_MAP)
    assert out["imported"] == 1
    rec = db.inserted("customers")[0]
    assert rec["email"] is None  # phone number is NOT stored as an email
    assert rec["phone"] == "+4941615409977"
    assert rec["phone2"] == "+491716973333"  # salvaged from the bogus Mail value


def test_import_customers_dedup_within_batch(monkeypatch):
    # Same email twice in the file → second is a duplicate.
    dup = (
        '101099,Heiko Adam 2,adam@adamweb.de,030 111,,Str 1,10000,Berlin,note2\n'
    )
    db = _DB({"customers": []})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", _cust_csv(dup), _CUST_MAP)
    assert out["imported"] == 1 and out["skipped_duplicate"] == 1


def test_import_customers_empty_row_is_error(monkeypatch):
    csv_bytes = (
        "Kundennummer,Name,Mail,Telefon,Mobil,Strasse,PLZ,Ort,Bemerkung\n"
        ",,,,,,,,\n"
    ).encode("utf-8")
    db = _DB({"customers": []})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", csv_bytes, _CUST_MAP)
    assert out["errors"] == 1 and out["imported"] == 0


def test_import_customers_generates_number_when_missing(monkeypatch):
    # Existing max numeric = 101005 → a row without Kundennummer gets 101006.
    no_num = "Name,Mail\nNeu Kunde,neu@x.de\n".encode("utf-8")
    db = _DB({"customers": [{"email": None, "phone": None, "customer_number": "101005"}]})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", no_num, {"full_name": "Name", "email": "Mail"})
    assert out["imported"] == 1
    assert db.inserted("customers")[0]["customer_number"] == "101006"


# ─── real DATEV export (B5 field-test regression) ────────────────────────────
# Wide DATEV header with the decoy columns (Suchwort/Titel/Kurzname) that the OLD
# frontend auto-mapper mis-bound (city→Suchwort, phone→Titel, name→Kurzname). This
# locks the BACKEND parse + the CORRECT mapping the fixed exact-match-first mapper
# now produces — including a quoted Bemerkung that spans physical lines.
_DATEV_HEADER = (
    "Adressnummer,Kundennummer,Suchwort,Kurzname,Anrede,Titel,Vorname,Name,"
    "Titel+Vorname+Name,Strasse,Land,PLZ,Ort,Telefon,Fax,Mail,Mobil,Internet,Bemerkung\n"
)
_DATEV_MAP = {
    "full_name": "Titel+Vorname+Name",
    "email": "Mail",
    "phone": "Telefon",
    "phone2": "Mobil",
    "street": "Strasse",
    "postal_code": "PLZ",
    "city": "Ort",
    "notes": "Bemerkung",
    "customer_number": "Kundennummer",
}


def _datev_csv() -> bytes:
    # One person row with a MULTI-LINE quoted Bemerkung (embedded newline) + a quoted
    # Kurzname containing commas — exactly the shapes that broke naive parsing.
    row = (
        '101003,101003,ADASCHBUXTEHUDE,"Adasch Henjek, Rübker Str.22b, Buxtehude",'
        "Herr,,Henjek,Adasch,Henjek Adasch,Rübker Str. 22 b,D,21640,Buxtehude,"
        "04161 713810,,test@example.de,0178 8239629,,"
        '"WV-15119\nBitte nicht Hr. Hillermann schicken"\n'
    )
    return (_DATEV_HEADER + row).encode("utf-8")


def test_import_customers_real_datev_mapping(monkeypatch):
    db = _DB({"customers": []})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", _datev_csv(), _DATEV_MAP)
    assert out["imported"] == 1 and out["errors"] == 0
    rec = db.inserted("customers")[0]
    assert rec["full_name"] == "Henjek Adasch"  # NOT the Suchwort/Kurzname
    assert rec["email"] == "test@example.de"
    assert rec["phone"] == "+494161713810"  # Telefon, NOT "Titel"
    # Ort → city (NOT Suchwort "ADASCHBUXTEHUDE"); street/plz correct.
    assert rec["address"] == {"street": "Rübker Str. 22 b", "postal_code": "21640", "city": "Buxtehude"}
    assert rec["customer_number"] == "101003"
    # Multi-line Bemerkung preserved across the embedded newline.
    assert "WV-15119" in rec["notes"] and "Bitte nicht Hr. Hillermann" in rec["notes"]
    assert rec["phone2"] == "+491788239629"  # Mobil → its own phone2 column


# ─── numbering unification ───────────────────────────────────────────────────
def test_gen_customer_number_is_numeric_continue(monkeypatch):
    db = _DB({"customers": [{"customer_number": "101008"}, {"customer_number": "KD-9"}]})
    assert gen_customer_number(db, "org-1") == "101009"  # ignores non-numeric, max+1
    empty = _DB({"customers": []})
    assert gen_customer_number(empty, "org-1") == "101001"  # seed


# ─── employees ───────────────────────────────────────────────────────────────
_EMP_MAP = {
    "display_name": "name",
    "email": "email",
    "access_role": "role",
    "activity_area": "Areas of Activity",
}


def _emp_csv() -> bytes:
    return (
        "name,email,role,Areas of Activity,access\n"
        "Valerie Klingschat,accounting@husmann-dreier.de,Employees,Buchhaltung,Login\n"
        "Dennis Dreier,dd@husmann-dreier.de,Admin,Chefsachen,Login\n"
        "Ole Hillermann,-,-,Wenn Ole genannt wird,Master data\n"
    ).encode("utf-8")


def test_import_employees_happy_path(monkeypatch):
    db = _DB({"employees": []})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_employees("org-1", _emp_csv(), _EMP_MAP)
    assert out["imported"] == 3 and out["errors"] == 0
    recs = {r["display_name"]: r for r in db.inserted("employees")}
    assert recs["Valerie Klingschat"]["access_role"] == "employee"
    assert recs["Valerie Klingschat"]["activity_area"] == "Buchhaltung"
    assert recs["Dennis Dreier"]["access_role"] == "admin"
    assert recs["Ole Hillermann"]["email"] is None  # "-" treated as empty
    assert recs["Ole Hillermann"]["activity_area"] == "Wenn Ole genannt wird"
    assert recs["Valerie Klingschat"]["auto_assign"] is False  # column absent → default


def test_import_employees_skips_existing_email(monkeypatch):
    db = _DB({"employees": [{"email": "dd@husmann-dreier.de", "display_name": "Dennis Dreier"}]})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_employees("org-1", _emp_csv(), _EMP_MAP)
    assert out["skipped_duplicate"] == 1 and out["imported"] == 2
