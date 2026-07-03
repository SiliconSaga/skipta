from app.extraction import AmendmentPayload
from app.proposals import ProposalFetchError

AMEND_PAYLOAD = {
    "customer_name": "Smith", "intent": "amend", "proposal_hint": "span quote",
    "breakers": [{"amps": 20, "poles": 1, "quantity": 4}],
}


def amendify(client):
    client.extraction_state["payload"] = AmendmentPayload.model_validate(AMEND_PAYLOAD)


def test_amend_intent_returns_candidates(client):
    amendify(client)
    resp = client.post("/api/v1/amendments", json={"voice_text": "amend the span quote"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "choose_proposal"
    assert data["candidates"][0]["name"] == "span-quote.pdf"


def test_amend_resolved_writes_amend_row(client, fakes):
    amendify(client)
    resp = client.post("/api/v1/amendments", json={"voice_text": "amend the span quote", "proposal_file_id": "p1"})
    assert resp.status_code == 201
    row = fakes["sheets"]._values.store[0]
    assert row[10] == "amend" and row[11] == "p1" and row[12] == "span-quote.pdf"
    assert row[13] == "12345.67" and row[14] == "s@x.com"


def test_empty_file_id_proceeds_as_new(client, fakes):
    amendify(client)
    resp = client.post("/api/v1/amendments", json={"voice_text": "amend the span quote", "proposal_file_id": ""})
    assert resp.status_code == 201
    assert fakes["sheets"]._values.store[0][10] == "new"


def test_new_intent_never_asks(client, fakes):
    resp = client.post("/api/v1/amendments", json={"voice_text": "new panel for Smith"})
    assert resp.status_code == 201
    assert fakes["sheets"]._values.store[0][10] == "new"


def test_no_candidates_still_offers_proceed(client, fakes):
    amendify(client)
    fakes["drive"].files_by_folder["f-smith"] = []
    resp = client.post("/api/v1/amendments", json={"voice_text": "amend the span quote"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidates"] == [] and "note" in data


def test_fetch_failure_returns_502_and_writes_no_row(client, fakes, monkeypatch):
    amendify(client)

    def boom(drive, file_id):
        raise ProposalFetchError("kaboom")

    monkeypatch.setattr("app.main.proposals.fetch_pdf", boom)
    resp = client.post("/api/v1/amendments", json={"voice_text": "amend", "proposal_file_id": "p1"})
    assert resp.status_code == 502
    assert fakes["sheets"]._values.store == []  # honest failure leaves no draft behind


def test_signing_page_shows_provenance_and_grand_total(client, fakes):
    amendify(client)
    client.post("/api/v1/amendments", json={"voice_text": "amend", "proposal_file_id": "p1"})
    aid = fakes["sheets"]._values.store[0][0]
    page = client.get(f"/amendments/{aid}").text
    assert "span-quote.pdf" in page and "12345.67" in page
    assert "Grand total" in page and "12375.67" in page  # 12345.67 + 30.00 (4 × 7.50)


def test_signing_page_omits_grand_total_when_original_missing(client, fakes):
    amendify(client)
    fakes["facts"] = fakes["facts"].model_copy(update={"original_total": None})
    client.post("/api/v1/amendments", json={"voice_text": "amend", "proposal_file_id": "p1"})
    aid = fakes["sheets"]._values.store[0][0]
    page = client.get(f"/amendments/{aid}").text
    assert "not found in document" in page
    assert "Grand total" not in page
