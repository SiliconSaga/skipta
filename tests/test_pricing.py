from app.extraction import AmendmentPayload
from app.pricing import parse_breakers, parse_panels, price_amendment

PANEL_ROWS = [["P-200A-01", "200", "200A Main Lug Panel 30-Space", "245.00"]]
BREAKER_ROWS = [
    ["B-20A-1P", "20", "1", "20A Single-Pole Type BR", "7.50"],
    ["B-30A-2P", "30", "2", "30A Double-Pole Type BR", "18.00"],
]


def payload(**kw):
    base = {"customer_name": "Smith", "breakers": [{"amps": 20, "poles": 1, "quantity": 3}], "panel": {"max_amperage": 200}}
    base.update(kw)
    return AmendmentPayload.model_validate(base)


def test_full_match_totals():
    result = price_amendment(payload(), parse_panels(PANEL_ROWS), parse_breakers(BREAKER_ROWS))
    assert result.has_unmatched is False
    assert result.total == 245.00 + 3 * 7.50
    panel_item = next(i for i in result.line_items if i.kind == "panel")
    assert panel_item.matched and panel_item.unit_cost == 245.00


def test_unmatched_breaker_flags_result():
    result = price_amendment(
        payload(breakers=[{"amps": 50, "poles": 2, "quantity": 1}]), parse_panels(PANEL_ROWS), parse_breakers(BREAKER_ROWS)
    )
    assert result.has_unmatched is True
    item = next(i for i in result.line_items if i.kind == "breaker")
    assert item.matched is False and item.unit_cost is None and item.subtotal == 0.0
    assert "50A" in item.spec and "2-pole" in item.spec


def test_no_panel_no_panel_item():
    result = price_amendment(payload(panel=None), parse_panels(PANEL_ROWS), parse_breakers(BREAKER_ROWS))
    assert all(i.kind != "panel" for i in result.line_items)
