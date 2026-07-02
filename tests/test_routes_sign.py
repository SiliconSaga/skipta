import pytest

SIG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="


@pytest.fixture
def signed_body():
    return {"crew_signature_base64": SIG, "customer_signature_base64": SIG}


@pytest.fixture
def created(client):
    return client.post("/api/v1/amendments", json={"voice_text": "x"}).json()


def test_sign_uploads_pdf_and_marks_signed(client, fakes, created, signed_body, monkeypatch):
    monkeypatch.setattr("app.main.render_pdf", lambda html: b"%PDF-fake")
    resp = client.post(f"/api/v1/amendments/{created['amendment_id']}/sign", json=signed_body)
    assert resp.status_code == 200
    assert resp.json()["pdf_drive_url"].startswith("https://drive.google.com/")
    row = fakes["sheets"]._values.store[0]
    assert row[7] == "signed" and row[8].startswith("https://drive.google.com/")
    assert fakes["drive"].files().created["body"]["parents"] == ["folder-smith"]


def test_double_sign_409(client, fakes, created, signed_body, monkeypatch):
    monkeypatch.setattr("app.main.render_pdf", lambda html: b"%PDF-fake")
    client.post(f"/api/v1/amendments/{created['amendment_id']}/sign", json=signed_body)
    assert client.post(f"/api/v1/amendments/{created['amendment_id']}/sign", json=signed_body).status_code == 409


def test_sign_unknown_404(client, signed_body):
    assert client.post("/api/v1/amendments/amend_no_1/sign", json=signed_body).status_code == 404


def test_sign_rejects_non_png_payload(client, created):
    bad = {"crew_signature_base64": "data:text/html;base64,PGI+", "customer_signature_base64": SIG}
    assert client.post(f"/api/v1/amendments/{created['amendment_id']}/sign", json=bad).status_code == 422


def test_sign_creates_missing_customer_folder(client, fakes, created, signed_body, monkeypatch):
    monkeypatch.setattr("app.main.render_pdf", lambda html: b"%PDF-fake")
    fakes["drive"].files().listing.clear()
    resp = client.post(f"/api/v1/amendments/{created['amendment_id']}/sign", json=signed_body)
    assert resp.status_code == 200
    assert fakes["drive"].files().created["body"]["parents"] == ["new-id"]  # upload landed in the just-created folder


def test_sign_retry_reuses_existing_pdf(client, fakes, created, signed_body, monkeypatch):
    monkeypatch.setattr("app.main.render_pdf", lambda html: b"%PDF-fake")
    fakes["drive"].files().listing[0]["webViewLink"] = "https://drive.google.com/file/d/existing/view"
    resp = client.post(f"/api/v1/amendments/{created['amendment_id']}/sign", json=signed_body)
    assert resp.status_code == 200
    assert resp.json()["pdf_drive_url"] == "https://drive.google.com/file/d/existing/view"
    assert fakes["drive"].files().created is None  # neither folder nor PDF was re-created
