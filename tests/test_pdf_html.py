from app.amendments import AmendmentRecord


def test_render_amendment_html_contents():
    from app.pdf import render_amendment_html

    record = AmendmentRecord(
        amendment_id="a", created_at="c", customer_name="Smith", voice_text="v", extracted_json="{}",
        line_items_json="[]", total=22.5, status="draft", pdf_drive_url="", signed_at="",
    )
    html = render_amendment_html(record, [], crew_signature=None, customer_signature=None)
    assert "Smith" in html and "22.50" in html
