import pytest

from app.amendments import AmendmentRecord

try:
    weasyprint = pytest.importorskip("weasyprint")
except OSError as exc:
    weasyprint = None
    pytestmark = pytest.mark.skip(reason=f"weasyprint system libs unavailable: {exc}")


def test_render_pdf_produces_pdf_bytes():
    from app.pdf import render_amendment_html, render_pdf

    record = AmendmentRecord(
        amendment_id="amend_smith_20260701120000", created_at="2026-07-01T12:00:00+00:00", customer_name="Smith",
        voice_text="Add three 20 amp single pole breakers", extracted_json="{}",
        line_items_json="[]", total=22.5, status="draft", pdf_drive_url="", signed_at="",
    )
    items = [{"kind": "breaker", "spec": "20A 1-pole breaker", "description": "20A Single-Pole Type BR", "quantity": 3, "unit_cost": 7.5, "subtotal": 22.5, "matched": True}]
    html = render_amendment_html(record, items, crew_signature=None, customer_signature=None)
    try:
        pdf = render_pdf(html)
    except OSError as exc:  # missing pango/cairo on the host
        pytest.skip(f"weasyprint system libs unavailable: {exc}")
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1000
