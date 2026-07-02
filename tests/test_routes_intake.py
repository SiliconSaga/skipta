def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "healthy"}


def test_index_serves_form(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "dictate" in resp.text.lower()


def test_create_amendment_returns_signing_url(client, fakes):
    resp = client.post("/api/v1/amendments", json={"voice_text": "Smith wants a 200A panel and three 20A single pole breakers"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["amendment_id"].startswith("amend_smith_")
    assert data["signing_url"] == f"http://testserver/amendments/{data['amendment_id']}"
    assert len(fakes["sheets"]._values.store) == 1  # draft row persisted


def test_signing_page_renders_items(client):
    created = client.post("/api/v1/amendments", json={"voice_text": "x"}).json()
    page = client.get(f"/amendments/{created['amendment_id']}")
    assert page.status_code == 200
    assert "20A Single-Pole Type BR" in page.text
    assert "Enact" in page.text


def test_unknown_amendment_404(client):
    assert client.get("/amendments/amend_nobody_20260101000000").status_code == 404


def test_blank_voice_text_422(client):
    assert client.post("/api/v1/amendments", json={"voice_text": "   "}).status_code == 422


def test_whitespace_customer_name_falls_back_to_extraction(client):
    resp = client.post("/api/v1/amendments", json={"voice_text": "x", "customer_name": "   "})
    assert resp.status_code == 201
    assert resp.json()["amendment_id"].startswith("amend_smith_")
