"""Deterministic pricing: match extracted requirements against the Panels/Breakers tabs. An unmatched requirement stays visible (UNMATCHED) and blocks signing — this is the guard against LLM-invented parts."""
from dataclasses import asdict, dataclass, field

from app.extraction import AmendmentPayload


@dataclass(frozen=True)
class LineItem:
    kind: str  # "panel" | "breaker"
    spec: str
    description: str
    quantity: int
    unit_cost: float | None
    subtotal: float
    matched: bool


@dataclass(frozen=True)
class PricingResult:
    line_items: list[LineItem] = field(default_factory=list)
    total: float = 0.0
    has_unmatched: bool = False

    def items_as_dicts(self) -> list[dict]:
        return [asdict(i) for i in self.line_items]


def parse_panels(rows):
    return [
        {"panel_id": r[0], "max_amperage": int(r[1]), "description": r[2], "unit_cost": float(r[3])}
        for r in rows
        if len(r) >= 4
    ]


def parse_breakers(rows):
    return [
        {"breaker_id": r[0], "amps": int(r[1]), "poles": int(r[2]), "description": r[3], "unit_cost": float(r[4])}
        for r in rows
        if len(r) >= 5
    ]


def price_amendment(payload: AmendmentPayload, panels: list[dict], breakers: list[dict]) -> PricingResult:
    items: list[LineItem] = []
    if payload.panel is not None:
        match = next((p for p in panels if p["max_amperage"] == payload.panel.max_amperage), None)
        items.append(_line_item("panel", f"{payload.panel.max_amperage}A panel", match, 1))
    for req in payload.breakers:
        if req.poles is None:
            amp_matches = [b for b in breakers if b["amps"] == req.amps]
            match = amp_matches[0] if len(amp_matches) == 1 else None
            spec = f"{req.amps}A breaker"
        else:
            match = next((b for b in breakers if b["amps"] == req.amps and b["poles"] == req.poles), None)
            spec = f"{req.amps}A {req.poles}-pole breaker"
        items.append(_line_item("breaker", spec, match, req.quantity))
    total = round(sum(i.subtotal for i in items), 2)
    return PricingResult(line_items=items, total=total, has_unmatched=any(not i.matched for i in items))


def _line_item(kind, spec, match, quantity) -> LineItem:
    if match is None:
        return LineItem(kind, spec, "UNMATCHED — no pricing row", quantity, None, 0.0, False)
    return LineItem(kind, spec, match["description"], quantity, match["unit_cost"], round(match["unit_cost"] * quantity, 2), True)
