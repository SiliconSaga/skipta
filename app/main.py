"""Skipta — field amendment service. Routes only; logic lives in the sibling modules."""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app import amendments, pricing
from app import drive as drive_mod
from app.amendments import AmendmentRecord
from app.config import Settings
from app.extraction import ExtractionError, extract_amendment
from app.google_clients import build_drive, build_sheets, get_credentials, make_model_factory, read_values
from app.pdf import render_amendment_html, render_pdf

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("skipta")

app = FastAPI(title="Skipta")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

limiter = Limiter(key_func=get_remote_address, default_limits=[])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_settings: Settings | None = None
_clients: dict = {}


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def get_sheets():
    if "sheets" not in _clients:
        _clients["sheets"] = build_sheets(get_credentials())
    return _clients["sheets"]


def get_drive():
    if "drive" not in _clients:
        _clients["drive"] = build_drive(get_credentials())
    return _clients["drive"]


def get_extract():
    def _extract(voice_text: str, settings: Settings):
        factory = make_model_factory(settings.project_id, settings.region)
        return extract_amendment(
            voice_text, model_factory=factory, model_names=settings.model_names, max_output_tokens=settings.max_output_tokens
        )

    return _extract


class CreateAmendmentRequest(BaseModel):
    voice_text: str = Field(..., min_length=1, max_length=4000)
    customer_name: str | None = Field(default=None, max_length=200)

    @field_validator("voice_text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("voice_text cannot be blank")
        return v.strip()

    @field_validator("customer_name")
    @classmethod
    def blank_to_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


@app.get("/healthz")
def healthz():
    return {"status": "healthy"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/api/v1/amendments", status_code=201)
@limiter.limit(lambda: f"{get_settings().rate_limit_per_minute}/minute")
def create_amendment(
    request: Request,
    body: CreateAmendmentRequest,
    settings: Settings = Depends(get_settings),
    sheets=Depends(get_sheets),
    extract=Depends(get_extract),
):
    try:
        payload = extract(body.voice_text, settings)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=f"Could not understand the change order: {exc}") from exc
    customer_name = body.customer_name or payload.customer_name.strip()
    if not customer_name:
        raise HTTPException(status_code=422, detail="No customer name — provide customer_name or mention the customer in the note")
    payload = payload.model_copy(update={"customer_name": customer_name})

    panels = pricing.parse_panels(read_values(sheets, settings.spreadsheet_id, "Panels!A2:D"))
    breakers = pricing.parse_breakers(read_values(sheets, settings.spreadsheet_id, "Breakers!A2:E"))
    result = pricing.price_amendment(payload, panels, breakers)

    now = datetime.now(timezone.utc)
    amendment_id = amendments.make_amendment_id(payload.customer_name, now)
    record = AmendmentRecord(
        amendment_id=amendment_id, created_at=now.isoformat(), customer_name=payload.customer_name,
        voice_text=body.voice_text, extracted_json=payload.model_dump_json(),
        line_items_json=json.dumps(result.items_as_dicts()), total=result.total, status="draft",
        pdf_drive_url="", signed_at="",
    )
    amendments.append_amendment(sheets, settings.spreadsheet_id, record)
    logger.info("amendment %s created (unmatched=%s, total=%.2f)", amendment_id, result.has_unmatched, result.total)
    return {"amendment_id": amendment_id, "signing_url": f"{settings.base_url}/amendments/{amendment_id}"}


@app.get("/amendments/{amendment_id}", response_class=HTMLResponse)
def signing_page(request: Request, amendment_id: str, settings: Settings = Depends(get_settings), sheets=Depends(get_sheets)):
    found = amendments.find_amendment(sheets, settings.spreadsheet_id, amendment_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Unknown amendment")
    _, record = found
    items = json.loads(record.line_items_json)
    return templates.TemplateResponse(
        request, "sign.html",
        {"record": record, "items": items, "has_unmatched": any(not i["matched"] for i in items), "already_signed": record.status == "signed"},
    )


class SignRequest(BaseModel):
    crew_signature_base64: str
    customer_signature_base64: str

    @field_validator("crew_signature_base64", "customer_signature_base64")
    @classmethod
    def must_be_png_data_url(cls, v: str) -> str:
        if not v.startswith("data:image/png;base64,"):
            raise ValueError("signature must be a PNG data URL")
        return v


@app.post("/api/v1/amendments/{amendment_id}/sign")
@limiter.limit(lambda: f"{get_settings().rate_limit_per_minute}/minute")
def sign_amendment(
    request: Request,
    amendment_id: str,
    body: SignRequest,
    settings: Settings = Depends(get_settings),
    sheets=Depends(get_sheets),
    drive=Depends(get_drive),
):
    found = amendments.find_amendment(sheets, settings.spreadsheet_id, amendment_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Unknown amendment")
    row, record = found
    if record.status == "signed":
        raise HTTPException(status_code=409, detail="Amendment already signed")

    signed_at = datetime.now(timezone.utc)
    record.signed_at = signed_at.isoformat()
    items = json.loads(record.line_items_json)
    html = render_amendment_html(record, items, crew_signature=body.crew_signature_base64, customer_signature=body.customer_signature_base64)
    try:
        pdf_bytes = render_pdf(html)
    except OSError as exc:
        raise HTTPException(status_code=502, detail=f"PDF rendering unavailable: {exc}") from exc

    created_ts = amendment_id.rsplit("_", 1)[-1]
    filename = f"{record.customer_name.replace(' ', '_')}_Amendment_{created_ts}.pdf"  # deterministic per amendment — a retry reuses the same name
    try:
        folder_id = drive_mod.ensure_customer_folder(drive, settings.drive_folder_id, record.customer_name)
        pdf_url = drive_mod.find_file_in_folder(drive, folder_id, filename) or drive_mod.upload_pdf(drive, folder_id, filename, pdf_bytes)
        amendments.mark_signed(sheets, settings.spreadsheet_id, row, pdf_url, record.signed_at)
    except HTTPException:
        raise
    except Exception as exc:  # Drive/Sheets upstream failure — surface honestly
        logger.error("sign flow failed for %s: %s", amendment_id, exc)
        raise HTTPException(status_code=502, detail=f"Google API failure: {exc}") from exc
    logger.info("amendment %s signed → %s", amendment_id, pdf_url)
    return {"pdf_drive_url": pdf_url}
