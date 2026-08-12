import pytest
from fastapi.testclient import TestClient

from app.extraction import AmendmentPayload
from app.main import app, get_drive, get_extract, get_parse_proposal, get_settings, get_sheets, get_storage
from app.config import Settings
from app.proposals import ProposalFacts
from tests.test_amendments import FakeSheets
from tests.test_gcs import FakeStorageClient
from tests.test_proposals import FakeDrive

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
    drive = FakeDrive(
        folders=[{"id": "f-smith", "name": "Smith"}],
        files_by_folder={"f-smith": [{"id": "p1", "name": "span-quote.pdf", "mimeType": "application/pdf"}]},
        records={"p1": {"name": "span-quote.pdf", "mimeType": "application/pdf", "content": b"%PDF-real"}},
    )
    return {
        "sheets": RoutedFakeSheets([]),
        "storage": FakeStorageClient(),
        "drive": drive,
        "facts": ProposalFacts(proposal_title="SPAN Panel Upgrade", original_total=12345.67, customer_email="s@x.com", customer_address="1 Main St"),
    }


@pytest.fixture
def client(fakes):
    payload = AmendmentPayload.model_validate(
        {"customer_name": "Smith", "panel": {"max_amperage": 200}, "breakers": [{"amps": 20, "poles": 1, "quantity": 3}]}
    )
    state = {"payload": payload}
    app.dependency_overrides[get_settings] = lambda: Settings(
        project_id="p", region="r", spreadsheet_id="sid", drive_folder_id="root", base_url="http://testserver",
        gcs_bucket="test-bucket", model_names=["fake"], max_output_tokens=64, rate_limit_per_minute=1000,
    )
    app.dependency_overrides[get_sheets] = lambda: fakes["sheets"]
    app.dependency_overrides[get_storage] = lambda: fakes["storage"]
    app.dependency_overrides[get_drive] = lambda: fakes["drive"]
    app.dependency_overrides[get_extract] = lambda: (lambda voice_text, settings: state["payload"])
    app.dependency_overrides[get_parse_proposal] = lambda: (lambda pdf_bytes, settings: fakes["facts"])
    # The limiter's limit-lambda calls get_settings() directly, outside Depends resolution,
    # so dependency_overrides can't reach it — the suite would share one real 10/min budget.
    app.state.limiter.enabled = False
    client = TestClient(app)
    client.extraction_state = state  # tests flip intent by swapping state["payload"]
    yield client
    app.state.limiter.enabled = True
    app.dependency_overrides.clear()
