import pytest
from fastapi.testclient import TestClient

from app.extraction import AmendmentPayload
from app.main import app, get_drive, get_extract, get_settings, get_sheets
from app.config import Settings
from tests.test_amendments import FakeSheets
from tests.test_drive import FakeDrive

PANEL_ROWS = [["P-200A-01", "200", "200A Main Lug Panel 30-Space", "245.00"]]
BREAKER_ROWS = [["B-20A-1P", "20", "1", "20A Single-Pole Type BR", "7.50"]]


class RoutedFakeSheets(FakeSheets):
    """Serves pricing tabs read-only and the Amendments tab read/write, keyed by A1 range."""

    def __init__(self, store):
        super().__init__(store)
        self._values.get = self._routed_get

    def _routed_get(self, spreadsheetId, range):
        if range.startswith("Panels"):
            self._values._result = {"values": PANEL_ROWS}
        elif range.startswith("Breakers"):
            self._values._result = {"values": BREAKER_ROWS}
        else:
            self._values._result = {"values": self._values.store}
        return self._values


@pytest.fixture
def fakes():
    return {"sheets": RoutedFakeSheets([]), "drive": FakeDrive([{"id": "folder-smith", "name": "Smith"}])}


@pytest.fixture
def client(fakes):
    payload = AmendmentPayload.model_validate(
        {"customer_name": "Smith", "panel": {"max_amperage": 200}, "breakers": [{"amps": 20, "poles": 1, "quantity": 3}]}
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        project_id="p", region="r", spreadsheet_id="sid", drive_folder_id="root", base_url="http://testserver",
        model_names=["fake"], max_output_tokens=64, rate_limit_per_minute=1000,
    )
    app.dependency_overrides[get_sheets] = lambda: fakes["sheets"]
    app.dependency_overrides[get_drive] = lambda: fakes["drive"]
    app.dependency_overrides[get_extract] = lambda: (lambda voice_text, settings: payload)
    yield TestClient(app)
    app.dependency_overrides.clear()
