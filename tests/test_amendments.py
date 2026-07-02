from datetime import datetime, timezone

from app.amendments import AmendmentRecord, append_amendment, find_amendment, make_amendment_id, mark_signed


class FakeValues:
    def __init__(self, store):
        self.store = store  # list of rows for the Amendments tab (no header)

    def append(self, spreadsheetId, range, valueInputOption, body):
        self.store.extend(body["values"])
        return self

    def get(self, spreadsheetId, range):
        self._result = {"values": self.store}
        return self

    def update(self, spreadsheetId, range, valueInputOption, body):
        # range like "Amendments!H3:J3" — row 3 is store index 1 (row 1 = header)
        row = int(range.split("!")[1][1:].split(":")[0])
        self.store[row - 2][7:10] = body["values"][0]
        return self

    def execute(self):
        return getattr(self, "_result", {})


class FakeSheets:
    def __init__(self, store):
        self._values = FakeValues(store)

    def spreadsheets(self):
        return self

    def values(self):
        return self._values


def record(aid="amend_smith_20260701120000"):
    return AmendmentRecord(
        amendment_id=aid, created_at="2026-07-01T12:00:00+00:00", customer_name="Smith", voice_text="v",
        extracted_json="{}", line_items_json="[]", total=22.5, status="draft", pdf_drive_url="", signed_at="",
    )


def test_amendment_id_slug():
    aid = make_amendment_id("O'Brien Jr.", datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc))
    assert aid == "amend_obrien-jr_20260701120000"
    aid_curly = make_amendment_id("O’Brien Jr.", datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc))
    assert aid_curly == "amend_obrien-jr_20260701120000"


def test_append_and_find_roundtrip():
    store = []
    sheets = FakeSheets(store)
    append_amendment(sheets, "sid", record())
    found = find_amendment(sheets, "sid", "amend_smith_20260701120000")
    assert found is not None
    row, rec = found
    assert row == 2 and rec.customer_name == "Smith" and rec.total == 22.5 and rec.status == "draft"


def test_find_missing_returns_none():
    assert find_amendment(FakeSheets([]), "sid", "nope") is None


def test_mark_signed_updates_status_columns():
    store = []
    sheets = FakeSheets(store)
    append_amendment(sheets, "sid", record())
    mark_signed(sheets, "sid", 2, "https://drive/x", "2026-07-01T13:00:00+00:00")
    _, rec = find_amendment(sheets, "sid", "amend_smith_20260701120000")
    assert rec.status == "signed" and rec.pdf_drive_url == "https://drive/x"
