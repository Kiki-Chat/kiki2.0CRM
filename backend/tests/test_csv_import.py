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

    def range(self, *a, **k):
        # Paged reads (fetch_all_rows) call .range(); the fake returns the full
        # set in one page, so a single pass terminates (test data is < 1 page).
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
    "first_name": "Name",
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
    assert out["corrected"] == 1
    assert out["corrections"][0]["action"] == "phone_salvaged_from_email"


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
    # A legacy numeric Kundennummer (101005) is NOT in the KI- namespace, so a row
    # without a number gets the first auto KI- number, KI-000001 (no collision).
    no_num = "Name,Mail\nNeu Kunde,neu@x.de\n".encode("utf-8")
    db = _DB({"customers": [{"email": None, "phone": None, "customer_number": "101005"}]})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", no_num, {"first_name": "Name", "email": "Mail"})
    assert out["imported"] == 1
    assert db.inserted("customers")[0]["customer_number"] == "KI-000001"


# ─── phone classification + 3-key dedup (mobile unique, landline+name) ───────
@pytest.mark.parametrize(
    "e164,expected",
    [
        ("+491758771486", "mobile"),   # 015x
        ("+491608177777", "mobile"),   # 016x
        ("+491701234567", "mobile"),   # 017x
        ("+494059466635", "landline"), # Hamburg area code
        ("+4941617220742", "landline"),
        ("+4930123456", "landline"),   # Berlin
        ("+43123456789", "unknown"),   # non-German
        (None, "unknown"),
    ],
)
def test_classify_phone(e164, expected):
    assert csv_import.classify_phone(e164) == expected


def test_mobile_dedup_collapses_same_person(monkeypatch):
    # A MOBILE is unique to one person, so a second row with that mobile is a dupe
    # even if the name differs (mobile alone, no name needed).
    csv_bytes = (
        "Kundennummer,Name,Mail,Telefon,Mobil,Strasse,PLZ,Ort,Bemerkung\n"
        "200,Max Mobil,,,0175 8771486,,,,\n"
    ).encode("utf-8")
    db = _DB({"customers": [
        {"email": None, "phone": "+491758771486", "phone2": None, "full_name": "Anna Andere"},
    ]})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", csv_bytes, _CUST_MAP)
    assert out["imported"] == 0 and out["skipped_duplicate"] == 1
    assert out["results"][0]["reason"] == "Mobilnummer existiert bereits"


def test_landline_plus_name_is_duplicate(monkeypatch):
    db = _DB({"customers": [
        {"email": None, "phone": "+494059466635", "phone2": None, "full_name": "Heiko Adam"},
    ]})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", _cust_csv(), _CUST_MAP)  # CSV row = Heiko Adam
    assert out["imported"] == 0 and out["skipped_duplicate"] == 1
    assert out["results"][0]["reason"] == "Festnetz + Name existiert bereits"


def test_two_people_one_landline_kept_vs_existing(monkeypatch):
    # Existing "Heike" on a landline; CSV "Werner" on the SAME landline → kept.
    couple = "201,Werner Breuhahn,,04164 812949,,Weg 1,21680,Stade,Ehemann\n"
    csv_bytes = ("Kundennummer,Name,Mail,Telefon,Mobil,Strasse,PLZ,Ort,Bemerkung\n" + couple).encode("utf-8")
    db = _DB({"customers": [
        {"email": None, "phone": "+494164812949", "phone2": None, "full_name": "Heike Breuhahn"},
    ]})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", csv_bytes, _CUST_MAP)
    assert out["imported"] == 1 and out["skipped_duplicate"] == 0


def test_reimport_same_file_is_idempotent(monkeypatch):
    db = _DB({"customers": []})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    csv_bytes = _cust_csv()
    first = csv_import.import_customers("org-1", csv_bytes, _CUST_MAP)
    assert first["imported"] == 1
    # Seed the "existing" rows from what the first run inserted, then re-import.
    db.rows["customers"] = db.inserted("customers")
    second = csv_import.import_customers("org-1", csv_bytes, _CUST_MAP)
    assert second["imported"] == 0 and second["skipped_duplicate"] == 1


# ─── address stranded in notes → salvaged ────────────────────────────────────
def test_address_from_notes_salvaged(monkeypatch):
    csv_bytes = (
        "Kundennummer,Name,Mail,Telefon,Mobil,Strasse,PLZ,Ort,Bemerkung\n"
        '300,Klaus Klein,,,,,,,"Rübker Str. 22b, 21640 Buxtehude"\n'
    ).encode("utf-8")
    db = _DB({"customers": []})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", csv_bytes, _CUST_MAP)
    rec = db.inserted("customers")[0]
    assert rec["address"] == {"street": "Rübker Str. 22b", "postal_code": "21640", "city": "Buxtehude"}
    assert out["corrections"][0]["action"] == "address_from_notes"


def test_plain_note_not_mangled(monkeypatch):
    csv_bytes = (
        "Kundennummer,Name,Mail,Telefon,Mobil,Strasse,PLZ,Ort,Bemerkung\n"
        '301,Otto Ohneadresse,,030 111222,,,,,"Messihaushalt, nur auf Mobil anrufen!"\n'
    ).encode("utf-8")
    db = _DB({"customers": []})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", csv_bytes, _CUST_MAP)
    rec = db.inserted("customers")[0]
    assert rec["address"] is None
    assert "Messihaushalt" in rec["notes"]
    assert out["corrected"] == 0


def test_extract_address_unit():
    assert csv_import.extract_address("Rübker Str. 22b, 21640 Buxtehude") == {
        "street": "Rübker Str. 22b", "postal_code": "21640", "city": "Buxtehude"
    }
    assert csv_import.extract_address("nur eine Notiz ohne Adresse") is None
    assert csv_import.extract_address(None) is None


# ─── content-aware column detection + mapping ────────────────────────────────
def test_detect_column_type():
    d = csv_import.detect_column_type
    assert d(["a@b.de", "c@d.com", "e@f.net"])["type"] == "email"
    assert d(["0175 8771486", "0160 1234567"])["type"] == "mobile"
    assert d(["040 734170", "04161 713810"])["type"] == "landline"
    assert d(["21035", "21147", "21640"])["type"] == "postal_code"   # NOT phone
    assert d(["101001", "101002", "101003"])["type"] == "customer_number"  # NOT phone
    assert d(["Wischenwinkel 17", "Rübker Str. 22b"])["type"] == "street"
    # Cities repeat heavily across rows (low distinctness) → city; names are distinct.
    assert d(["Hamburg", "Hamburg", "Hamburg", "Buxtehude", "Hamburg"])["type"] == "city"
    assert d(["Max Mustermann", "Erika Meier", "Klaus Klein"])["type"] == "person_name"
    assert d([])["type"] == "empty"


def test_suggest_mapping_content_overrides_header():
    # The 'Mail'-headed column actually holds PHONES; the real emails are under a
    # weirdly-named header. Content must win: email maps to the email column, and the
    # phone-typed 'Mail' column is NOT mapped to email.
    columns = {
        "Mail": csv_import.detect_column_type(["0175 111", "0176 222", "0177 333"]),
        "Kontakt": csv_import.detect_column_type(["a@b.de", "c@d.de", "e@f.de"]),
        "Telefon": csv_import.detect_column_type(["040 111", "040 222"]),
        "Name": csv_import.detect_column_type(["Max Mustermann", "Erika Meier"]),
    }
    m = csv_import.suggest_mapping(columns)
    assert m.get("email") == "Kontakt"      # content-detected email column
    assert m.get("email") != "Mail"         # the phone-filled 'Mail' is NOT email
    assert m.get("first_name") == "Name"


def test_suggest_mapping_avoids_datev_decoys():
    # Wide DATEV-style headers: split Vorname+Name when both exist; city to Ort not
    # Titel; phone to Telefon not Titel.
    cols = {
        "Suchwort": csv_import.detect_column_type(["ADAMHH", "MEIERHH"]),
        "Kurzname": csv_import.detect_column_type(["Adam, Wischenwinkel 17", "Meier, Hauptstr 2"]),
        "Titel": csv_import.detect_column_type(["Dr.", "Dr.", "Prof."]),
        "Vorname": csv_import.detect_column_type(["Heiko", "Erika"]),
        "Name": csv_import.detect_column_type(["Adam", "Meier"]),
        "Titel+Vorname+Name": csv_import.detect_column_type(["Heiko Adam", "Erika Meier"]),
        "Telefon": csv_import.detect_column_type(["040 734170", "04161 713810"]),
        "Mail": csv_import.detect_column_type(["a@b.de", "c@d.de"]),
        "PLZ": csv_import.detect_column_type(["21035", "21147"]),
        "Ort": csv_import.detect_column_type(["Hamburg", "Buxtehude"]),
    }
    m = csv_import.suggest_mapping(cols)
    assert m["first_name"] == "Vorname"
    assert m["last_name"] == "Name"
    assert m["phone"] == "Telefon"
    assert m["postal_code"] == "PLZ"
    assert m["city"] == "Ort"
    assert m["email"] == "Mail"


def test_preview_customers_smoke():
    csv_bytes = (
        "Kundennummer;Titel+Vorname+Name;Mail;Telefon;Mobil;Strasse;PLZ;Ort;Bemerkung\n"
        "101001;Heiko Adam;adam@x.de;040 734170;0175 8771486;Wischenwinkel 17;21147;Hamburg;Notiz\n"
    ).encode("utf-8")
    pv = csv_import.preview_customers(csv_bytes)
    assert pv["row_count"] == 1
    assert pv["suggested_mapping"]["email"] == "Mail"
    assert pv["suggested_mapping"]["postal_code"] == "PLZ"
    assert pv["columns"]["Mobil"]["type"] == "mobile"


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
    "first_name": "Vorname",
    "last_name": "Name",
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
def test_gen_customer_number_is_ki_tagged(monkeypatch):
    # Auto numbers are AI-tagged 'KI-NNNNNN' and live in their own namespace so they
    # never collide with the business's own numbers. Legacy numeric ('101008') and
    # manual-prefix ('KD-9') numbers do NOT advance the KI- sequence.
    db = _DB({"customers": [{"customer_number": "101008"}, {"customer_number": "KD-9"}]})
    assert gen_customer_number(db, "org-1") == "KI-000001"
    empty = _DB({"customers": []})
    assert gen_customer_number(empty, "org-1") == "KI-000001"  # seed
    # Only existing KI- numbers advance the sequence (max+1), legacy ignored.
    mixed = _DB({"customers": [
        {"customer_number": "101008"},
        {"customer_number": "KI-000004"},
        {"customer_number": "KI-000002"},
    ]})
    assert gen_customer_number(mixed, "org-1") == "KI-000005"


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


# ─── split name import / export ──────────────────────────────────────────────
def test_resolve_import_full_name_split():
    row = {"Vorname": "Heiko", "Nachname": "Adam"}
    mapping = {"first_name": "Vorname", "last_name": "Nachname"}
    assert csv_import.resolve_import_full_name(row, mapping) == "Heiko Adam"


def test_resolve_import_full_name_combined_column():
    row = {"Full": "Heiko Adam"}
    mapping = {"first_name": "Full"}
    assert csv_import.resolve_import_full_name(row, mapping) == "Heiko Adam"


def test_resolve_import_full_name_single_token():
    row = {"Name": "Thomas"}
    mapping = {"first_name": "Name"}
    assert csv_import.resolve_import_full_name(row, mapping) == "Thomas"


def test_resolve_import_full_name_legacy():
    row = {"Name": "Max Mustermann"}
    mapping = {"full_name": "Name"}
    assert csv_import.resolve_import_full_name(row, mapping) == "Max Mustermann"


@pytest.mark.parametrize(
    "full, vorname, nachname",
    [
        ("Max Mustermann", "Max", "Mustermann"),
        ("Acme GmbH", "Acme", "GmbH"),
        ("Thomas", "Thomas", ""),
        ("", "", ""),
    ],
)
def test_split_export_name(full, vorname, nachname):
    assert csv_import.split_export_name(full) == (vorname, nachname)


def test_import_customers_split_name_columns(monkeypatch):
    csv_bytes = (
        "Vorname,Nachname,Mail\n"
        "Heiko,Adam,adam@x.de\n"
    ).encode("utf-8")
    mapping = {"first_name": "Vorname", "last_name": "Nachname", "email": "Mail"}
    db = _DB({"customers": []})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_customers("org-1", csv_bytes, mapping)
    assert out["imported"] == 1
    assert db.inserted("customers")[0]["full_name"] == "Heiko Adam"


def test_suggest_mapping_combined_only():
    cols = {
        "Titel+Vorname+Name": csv_import.detect_column_type(["Heiko Adam", "Erika Meier"]),
        "Mail": csv_import.detect_column_type(["a@b.de", "c@d.de"]),
    }
    m = csv_import.suggest_mapping(cols)
    assert m["first_name"] == "Titel+Vorname+Name"
    assert "last_name" not in m


def test_import_employees_skips_existing_email(monkeypatch):
    db = _DB({"employees": [{"email": "dd@husmann-dreier.de", "display_name": "Dennis Dreier"}]})
    monkeypatch.setattr(csv_import, "get_service_client", lambda: db)
    out = csv_import.import_employees("org-1", _emp_csv(), _EMP_MAP)
    assert out["skipped_duplicate"] == 1 and out["imported"] == 2
