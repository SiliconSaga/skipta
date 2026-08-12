# Skipta Phase 2 — Proposal-Aware Amendments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Amend Rasmus' SPAN panel proposal…" works end to end: intent detection, Drive proposal search with tech confirmation, Gemini multimodal PDF parsing with visible provenance, and amendments presenting Original / This amendment / Grand total — with the phase-1 flow intact as `kind=new`.

**Architecture:** Deterministic two-step API (spec: `docs/plans/2026-07-02-skipta-proposal-amendments-design.md`). Pass-1 extraction grows intent + proposal_hint; amend intent without a chosen file returns a synchronous `choose_proposal` pick-list; the re-POST carries `proposal_file_id` and triggers Drive fetch + a second Gemini pass over the PDF bytes. One new module (`app/proposals.py`) owns the amend-side pipeline; everything else is measured growth of existing modules with the same fake-injection testing.

**Tech Stack:** unchanged from phase 1 (FastAPI, Pydantic v2, vertexai generative_models incl. multimodal `Part`, google-api-python-client Drive v3 reads, Jinja2, WeasyPrint, pytest/ruff).

## Global Constraints

- Branch: `feat/proposal-amendments` (exists, spec committed; based on main `b558a85`).
- Request contract: `proposal_file_id` ABSENT (None) → amend intent returns `choose_proposal`; EMPTY STRING → proceed as new work order; non-empty → resolve that proposal.
- Amendments tab columns K–P exactly: `kind, proposal_file_id, proposal_name, original_total, customer_email, customer_address`. Legacy 10-column rows must read back with `kind="new"` and empty proposal fields.
- Parsed facts are never invented: missing → empty/None → templates render "not found in document"; grand total renders only when `original_total` is not None.
- Poles-unspecified breakers match by amps iff exactly one Breakers row has those amps; otherwise UNMATCHED. Phase-1 anti-hallucination guard unchanged.
- PDF fetch hard cap 10 MB (`ProposalTooLarge`); Google Docs export as PDF so pass 2 is uniform.
- GDD workspace rules as phase 1: `ws commit`/`ws push`/`ws cr`, one shell command per call (no `&&`/`;`/`|`, even inside quoted args), bodyfiles at workspace `.commits/`, `ws test skipta`/`ws lint skipta` only, sub-agent co-author files.
- Local pushes: batch commits; push ONLY at the end-of-plan review checkpoint.
- Suite baseline on the branch: 29 passed + 1 skipped (WeasyPrint skip on this host is expected; CI runs it).

## Prerequisites (human-side)

Before live smoke (not before coding): add headers `kind, proposal_file_id, proposal_name, original_total, customer_email, customer_address` in K1–P1 of the Amendments tab. The real proposal PDF should sit in a customer subfolder of `Skipta/` (e.g. `Rasmus/`).

---

### Task 1: Extraction pass 1 — intent, proposal_hint, optional poles

**Files:**
- Modify: `components/skipta/app/extraction.py`
- Test: `components/skipta/tests/test_extraction.py` (append)

**Interfaces:**
- Consumes: existing `extract_amendment` contract.
- Produces: `AmendmentPayload.intent: str` (`"new"`|`"amend"`, default `"new"`), `AmendmentPayload.proposal_hint: str` (default `""`), `BreakerRequirement.poles: int | None` (now optional). Existing callers unchanged (defaults preserve behavior).

- [ ] **Step 1: Append failing tests** to `tests/test_extraction.py`:

```python
AMEND_JSON = (
    '{"customer_name": "Rasmus", "intent": "amend", "proposal_hint": "SPAN panel proposal", '
    '"breakers": [{"amps": 20, "poles": 1, "quantity": 4}, {"amps": 30, "quantity": 2}]}'
)


def test_amend_intent_and_hint_extracted():
    factory = factory_for([FakeModel(text=AMEND_JSON)])
    payload = extract_amendment("amend the proposal", model_factory=factory, model_names=["m1"], max_output_tokens=512)
    assert payload.intent == "amend"
    assert payload.proposal_hint == "SPAN panel proposal"
    assert payload.breakers[1].poles is None  # poles unspecified survives validation


def test_intent_defaults_to_new_when_absent():
    factory = factory_for([FakeModel(text=VALID_JSON)])
    payload = extract_amendment("x", model_factory=factory, model_names=["m1"], max_output_tokens=512)
    assert payload.intent == "new"
    assert payload.proposal_hint == ""
```

- [ ] **Step 2: Run, expect FAIL** — `ws test skipta` (ValidationError: intent not a field / poles required).

- [ ] **Step 3: Implement** — in `app/extraction.py`:

Change `BreakerRequirement.poles` to:

```python
    poles: int | None = Field(default=None, description="Number of poles, usually 1 or 2; None when the note doesn't say")
```

Add to `AmendmentPayload` (after `customer_name`):

```python
    intent: str = Field(default="new", pattern="^(new|amend)$")
    proposal_hint: str = ""
```

In `AMENDMENT_SCHEMA`: add to `properties`:

```python
        "intent": {
            "type": "STRING",
            "enum": ["new", "amend"],
            "description": "amend when the note references an existing proposal/quote/document to modify; otherwise new",
        },
        "proposal_hint": {
            "type": "STRING",
            "description": "The document reference exactly as spoken, e.g. \"Rasmus' SPAN panel proposal\"; empty when none",
        },
```

and change the breakers item `"required"` list from `["amps", "poles", "quantity"]` to `["amps", "quantity"]`.

Replace `PROMPT` with:

```python
PROMPT = (
    "You are extracting a field change-order for a residential electrical job from a technician's dictated note. "
    "Extract ONLY parts the note explicitly mentions — never invent parts, quantities, or a customer name. "
    "Set intent to 'amend' only when the note references an existing proposal, quote, or document to modify, and "
    "copy that reference into proposal_hint exactly as spoken; otherwise intent is 'new' and proposal_hint is empty. "
    "Omit poles when the note does not state them.\n\nNote:\n{voice_text}"
)
```

- [ ] **Step 4: Run tests, expect PASS** — `ws test skipta` (all prior tests still green — defaults keep old canned JSON valid). `ws lint skipta` clean.

- [ ] **Step 5: Commit** — bodyfile `.commits/skipta-p2-extraction.md` (message `feat: extraction detects amend intent, proposal hint, optional poles`, add: `app/extraction.py`, `tests/test_extraction.py`; body: one short paragraph — intent/hint feed the proposal search, poles become optional so "2 30 amp breakers" doesn't force an invented pole count).

### Task 2: Pricing — amps-unique matching for unspecified poles

**Files:**
- Modify: `components/skipta/app/pricing.py`
- Test: `components/skipta/tests/test_pricing.py` (append)

**Interfaces:**
- Consumes: `BreakerRequirement.poles: int | None` (Task 1).
- Produces: unchanged signatures; `price_amendment` handles `poles=None`.

- [ ] **Step 1: Append failing tests** to `tests/test_pricing.py`:

```python
def test_poles_unspecified_matches_unique_amps():
    result = price_amendment(
        payload(panel=None, breakers=[{"amps": 30, "quantity": 2}]), parse_panels(PANEL_ROWS), parse_breakers(BREAKER_ROWS)
    )
    item = result.line_items[0]
    assert item.matched is True and item.unit_cost == 18.00 and item.subtotal == 36.00


def test_poles_unspecified_ambiguous_amps_is_unmatched():
    rows = BREAKER_ROWS + [["B-30A-1P", "30", "1", "30A Single-Pole Type BR", "11.00"]]
    result = price_amendment(
        payload(panel=None, breakers=[{"amps": 30, "quantity": 2}]), parse_panels(PANEL_ROWS), parse_breakers(rows)
    )
    assert result.line_items[0].matched is False
    assert result.has_unmatched is True
```

- [ ] **Step 2: Run, expect FAIL** — `ws test skipta` (pydantic accepts poles=None after Task 1; matching returns wrong result / KeyError-free failure on the equality check).

- [ ] **Step 3: Implement** — in `app/pricing.py`, replace the breaker-matching loop body:

```python
    for req in payload.breakers:
        if req.poles is None:
            amp_matches = [b for b in breakers if b["amps"] == req.amps]
            match = amp_matches[0] if len(amp_matches) == 1 else None
            spec = f"{req.amps}A breaker"
        else:
            match = next((b for b in breakers if b["amps"] == req.amps and b["poles"] == req.poles), None)
            spec = f"{req.amps}A {req.poles}-pole breaker"
        items.append(_line_item("breaker", spec, match, req.quantity))
```

- [ ] **Step 4: Run tests, expect PASS**; `ws lint skipta` clean.

- [ ] **Step 5: Commit** — bodyfile `.commits/skipta-p2-pricing.md` (message `feat: amps-unique matching when poles unspecified`, add: `app/pricing.py`, `tests/test_pricing.py`; body: one sentence — deterministic inference only when unambiguous, everything else stays UNMATCHED).

### Task 3: AmendmentRecord columns K–P

**Files:**
- Modify: `components/skipta/app/amendments.py`
- Test: `components/skipta/tests/test_amendments.py` (append + adjust `record()` helper)

**Interfaces:**
- Consumes: nothing new.
- Produces: `AmendmentRecord` gains `kind: str = "new"`, `proposal_file_id: str = ""`, `proposal_name: str = ""`, `original_total: float | None = None`, `customer_email: str = ""`, `customer_address: str = ""` (in this order, after `signed_at`). `DATA_RANGE` becomes `Amendments!A2:P`. `to_row()` emits 16 columns (`original_total` → `""` when None else `f"{v:.2f}"`); `from_row()` pads to 16, maps blank kind → `"new"`, blank original_total → None. `mark_signed` (H:J) unchanged.

- [ ] **Step 1: Append failing tests** to `tests/test_amendments.py`:

```python
def test_amend_row_roundtrip_with_proposal_fields():
    store = []
    sheets = FakeSheets(store)
    rec = record()
    rec.kind = "amend"
    rec.proposal_file_id = "file123"
    rec.proposal_name = "span-quote.pdf"
    rec.original_total = 12345.67
    rec.customer_email = "smith@example.com"
    rec.customer_address = "1 Main St"
    append_amendment(sheets, "sid", rec)
    _, back = find_amendment(sheets, "sid", rec.amendment_id)
    assert back.kind == "amend" and back.proposal_name == "span-quote.pdf"
    assert back.original_total == 12345.67 and back.customer_address == "1 Main St"


def test_legacy_ten_column_row_reads_as_new():
    row = ["amend_old_20260101000000", "c", "Old", "v", "{}", "[]", "10.00", "draft", "", ""]
    rec = AmendmentRecord.from_row(row)
    assert rec.kind == "new" and rec.proposal_file_id == "" and rec.original_total is None
```

- [ ] **Step 2: Run, expect FAIL** — `ws test skipta` (unknown attributes).

- [ ] **Step 3: Implement** — in `app/amendments.py`:

Change `DATA_RANGE = f"{TAB}!A2:P"`. Append fields to the dataclass after `signed_at`:

```python
    kind: str = "new"  # "new" work order | "amend" of an existing proposal
    proposal_file_id: str = ""
    proposal_name: str = ""
    original_total: float | None = None
    customer_email: str = ""
    customer_address: str = ""
```

Replace `to_row`/`from_row`:

```python
    def to_row(self) -> list:
        row = list(astuple(self))
        row[6] = f"{self.total:.2f}"
        row[13] = "" if self.original_total is None else f"{self.original_total:.2f}"
        return row

    @classmethod
    def from_row(cls, row: list) -> "AmendmentRecord":
        padded = list(row) + [""] * (16 - len(row))
        padded[6] = float(padded[6] or 0)
        padded[10] = padded[10] or "new"
        padded[13] = float(padded[13]) if padded[13] else None
        return cls(*padded[:16])
```

- [ ] **Step 4: Run tests, expect PASS** (existing roundtrip tests keep working — defaults fill the new columns); `ws lint skipta` clean.

- [ ] **Step 5: Commit** — bodyfile `.commits/skipta-p2-record.md` (message `feat: Amendments columns K-P — kind + proposal provenance fields`, add: `app/amendments.py`, `tests/test_amendments.py`; body: one sentence on legacy-row compatibility via padding + kind default).

### Task 4: proposals.py — Drive search + PDF fetch

**Files:**
- Create: `components/skipta/app/proposals.py`
- Test: `components/skipta/tests/test_proposals.py`
- Modify: `components/skipta/app/google_clients.py` (add `build_drive` back)

**Interfaces:**
- Consumes: a Drive v3 service (injected).
- Produces: `Candidate` dataclass (`file_id: str, name: str, folder: str`), `search_proposals(drive, root_folder_id, customer_name, hint) -> list[Candidate]` (max 5, customer-folder matches first, then filename token overlap), `fetch_pdf(drive, file_id) -> bytes` (Docs exported as PDF; >10 MB → `ProposalTooLarge`), exceptions `ProposalTooLarge`, `ProposalFetchError`. `google_clients.build_drive(creds)`. Test module exports `FakeDrive` for conftest reuse.

- [ ] **Step 1: Write the failing tests** — `tests/test_proposals.py`:

```python
import pytest

from app.proposals import Candidate, ProposalTooLarge, fetch_pdf, search_proposals

FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"


class FakeDrive:
    """Routes files.list by query content; serves get/export/media from a dict of file records."""

    def __init__(self, folders=(), files_by_folder=None, records=None):
        self.folders = list(folders)  # [{"id","name"}]
        self.files_by_folder = files_by_folder or {}  # folder_id -> [{"id","name","mimeType"}]
        self.records = records or {}  # file_id -> {"name","mimeType","size","content": bytes}

    def files(self):
        return self

    def list(self, q, fields, pageSize):
        if f"mimeType = '{FOLDER_MIME}'" in q:
            self._result = {"files": self.folders}
        else:
            folder_id = q.split("'")[1]
            self._result = {"files": self.files_by_folder.get(folder_id, [])}
        return self

    def get(self, fileId, fields=""):
        rec = self.records[fileId]
        self._result = {"name": rec["name"], "mimeType": rec["mimeType"], "size": str(rec.get("size", len(rec["content"])))}
        return self

    def get_media(self, fileId):
        self._result = self.records[fileId]["content"]
        return self

    def export_media(self, fileId, mimeType):
        assert mimeType == "application/pdf"
        self._result = b"%PDF-exported-" + self.records[fileId]["content"]
        return self

    def execute(self):
        return self._result


def make_drive():
    return FakeDrive(
        folders=[{"id": "f-rasmus", "name": "Rasmus"}, {"id": "f-smith", "name": "Smith"}],
        files_by_folder={
            "f-rasmus": [
                {"id": "p1", "name": "span-panel-proposal.pdf", "mimeType": "application/pdf"},
                {"id": "p2", "name": "old-invoice.pdf", "mimeType": "application/pdf"},
            ],
            "f-smith": [{"id": "p3", "name": "span-quote.pdf", "mimeType": "application/pdf"}],
        },
        records={
            "p1": {"name": "span-panel-proposal.pdf", "mimeType": "application/pdf", "content": b"%PDF-real"},
            "g1": {"name": "quote-doc", "mimeType": DOC_MIME, "content": b"gdoc-bytes"},
            "big": {"name": "huge.pdf", "mimeType": "application/pdf", "size": 11 * 1024 * 1024, "content": b"x"},
        },
    )


def test_search_prefers_customer_folder_and_hint_tokens():
    got = search_proposals(make_drive(), "root", "Rasmus", "SPAN panel proposal")
    assert [c.file_id for c in got][:2] == ["p1", "p2"]  # Rasmus folder first, hint-matching file on top
    assert got[0].folder == "Rasmus"
    assert all(isinstance(c, Candidate) for c in got)


def test_search_no_customer_folder_still_searches_all():
    got = search_proposals(make_drive(), "root", "Jones", "span quote")
    assert any(c.file_id == "p3" for c in got)


def test_fetch_pdf_plain():
    assert fetch_pdf(make_drive(), "p1") == b"%PDF-real"


def test_fetch_pdf_exports_google_doc():
    assert fetch_pdf(make_drive(), "g1").startswith(b"%PDF-exported-")


def test_fetch_pdf_too_large():
    with pytest.raises(ProposalTooLarge):
        fetch_pdf(make_drive(), "big")
```

- [ ] **Step 2: Run, expect FAIL** — `ws test skipta` (`ModuleNotFoundError: app.proposals`).

- [ ] **Step 3: Implement** — `app/proposals.py`:

```python
"""Amend-side pipeline: find the referenced proposal in the shared Skipta/ tree, fetch its bytes. Reads only — consumer-account service accounts cannot own Drive content, but shared reads are unaffected."""
import io
import re
from dataclasses import dataclass

from googleapiclient.http import MediaIoBaseDownload

FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"
MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_CANDIDATES = 5


class ProposalTooLarge(Exception):
    """Selected proposal exceeds the fetch cap."""


class ProposalFetchError(Exception):
    """Drive download/export failed."""


@dataclass(frozen=True)
class Candidate:
    file_id: str
    name: str
    folder: str


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 2}


def search_proposals(drive, root_folder_id: str, customer_name: str, hint: str) -> list[Candidate]:
    folder_query = f"'{_escape(root_folder_id)}' in parents and mimeType = '{FOLDER_MIME}' and trashed = false"
    folders = drive.files().list(q=folder_query, fields="files(id, name)", pageSize=50).execute().get("files", [])
    customer = customer_name.lower()
    ordered = sorted(folders, key=lambda f: (f["name"].lower() != customer,))
    hint_tokens = _tokens(hint)

    scored: list[tuple[int, int, Candidate]] = []
    for folder_rank, folder in enumerate(ordered):
        file_query = f"'{_escape(folder['id'])}' in parents and mimeType != '{FOLDER_MIME}' and trashed = false"
        children = drive.files().list(q=file_query, fields="files(id, name, mimeType)", pageSize=50).execute().get("files", [])
        for child in children:
            overlap = len(hint_tokens & _tokens(child["name"]))
            scored.append((folder_rank, -overlap, Candidate(child["id"], child["name"], folder["name"])))
    scored.sort(key=lambda t: (t[0], t[1], t[2].name))
    return [c for _, _, c in scored[:MAX_CANDIDATES]]


def fetch_pdf(drive, file_id: str) -> bytes:
    meta = drive.files().get(fileId=file_id, fields="name, mimeType, size").execute()
    if int(meta.get("size") or 0) > MAX_PDF_BYTES:
        raise ProposalTooLarge(f"{meta['name']} exceeds {MAX_PDF_BYTES} bytes")
    request = (
        drive.files().export_media(fileId=file_id, mimeType="application/pdf")
        if meta["mimeType"] == DOC_MIME
        else drive.files().get_media(fileId=file_id)
    )
    try:
        result = request.execute()
        if isinstance(result, bytes):  # fakes and small downloads return bytes directly
            return result
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()
    except (ProposalTooLarge, ProposalFetchError):
        raise
    except Exception as exc:
        raise ProposalFetchError(f"could not download {meta['name']}: {exc}") from exc
```

and in `app/google_clients.py`, add after `build_sheets`:

```python
def build_drive(creds):
    return build("drive", "v3", credentials=creds, cache_discovery=False)
```

- [ ] **Step 4: Run tests, expect PASS**; `ws lint skipta` clean.

- [ ] **Step 5: Commit** — bodyfile `.commits/skipta-p2-proposals.md` (message `feat: proposal search + PDF fetch over shared Drive tree`, add: `app/proposals.py`, `tests/test_proposals.py`, `app/google_clients.py`; body: short paragraph — customer-folder-first then hint-token scoring, capped candidates, uniform PDF bytes via Docs export, size cap).

### Task 5: proposals.py — Gemini multimodal parse

**Files:**
- Modify: `components/skipta/app/proposals.py` (append)
- Test: `components/skipta/tests/test_proposals.py` (append)

**Interfaces:**
- Consumes: model factory contract from extraction (`model_factory(name)` → `.generate_content(contents, generation_config=...)` → `.text`).
- Produces: `ProposalFacts` pydantic model (`proposal_title: str = ""`, `original_total: float | None = None`, `customer_email: str = ""`, `customer_address: str = ""`), `parse_proposal(pdf_bytes, *, model_factory, model_names, max_output_tokens) -> ProposalFacts`, `ProposalParseError`.

- [ ] **Step 1: Append failing tests** to `tests/test_proposals.py`:

```python
from app.proposals import ProposalFacts, ProposalParseError, parse_proposal

FACTS_JSON = '{"proposal_title": "SPAN Panel Upgrade", "original_total": 12345.67, "customer_email": "r@x.com", "customer_address": "1 Main St"}'


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeParseModel:
    def __init__(self, text=None, error=None):
        self.text, self.error = text, error
        self.contents = None

    def generate_content(self, contents, generation_config=None):
        if self.error:
            raise self.error
        self.contents = contents
        return FakeResponse(self.text)


def parse_factory(models):
    calls = []

    def factory(name):
        calls.append(name)
        return models[len(calls) - 1]

    factory.calls = calls
    return factory


def test_parse_proposal_returns_facts_and_sends_pdf_part():
    model = FakeParseModel(text=FACTS_JSON)
    facts = parse_proposal(b"%PDF-real", model_factory=parse_factory([model]), model_names=["m1"], max_output_tokens=512)
    assert facts.original_total == 12345.67 and facts.customer_email == "r@x.com"
    assert isinstance(model.contents, list) and len(model.contents) == 2  # [pdf Part, prompt]


def test_parse_missing_total_is_none():
    model = FakeParseModel(text='{"proposal_title": "T", "customer_email": "", "customer_address": ""}')
    facts = parse_proposal(b"%PDF", model_factory=parse_factory([model]), model_names=["m1"], max_output_tokens=512)
    assert facts.original_total is None


def test_parse_all_models_fail_raises():
    factory = parse_factory([FakeParseModel(text="junk"), FakeParseModel(error=RuntimeError("quota"))])
    with pytest.raises(ProposalParseError):
        parse_proposal(b"%PDF", model_factory=factory, model_names=["m1", "m2"], max_output_tokens=512)
```

- [ ] **Step 2: Run, expect FAIL** — `ws test skipta` (ImportError on new names).

- [ ] **Step 3: Implement** — append to `app/proposals.py` (plus `import logging`, `from pydantic import BaseModel, ValidationError` at top; `logger = logging.getLogger("skipta.proposals")`):

```python
class ProposalFacts(BaseModel):
    proposal_title: str = ""
    original_total: float | None = None
    customer_email: str = ""
    customer_address: str = ""


class ProposalParseError(Exception):
    """Every configured model failed to read the proposal."""


PROPOSAL_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "proposal_title": {"type": "STRING", "description": "The document's own title or heading; empty if none"},
        "original_total": {"type": "NUMBER", "nullable": True, "description": "The proposal's total price; null when not stated"},
        "customer_email": {"type": "STRING", "description": "Customer email as written; empty when absent"},
        "customer_address": {"type": "STRING", "description": "Customer street address as written; empty when absent"},
    },
    "required": [],
}

PARSE_PROMPT = (
    "Read this proposal/quote document. Report ONLY facts stated in the document — "
    "never guess or invent. Leave fields empty (or total null) when the document does not state them."
)


def parse_proposal(pdf_bytes: bytes, *, model_factory, model_names, max_output_tokens) -> ProposalFacts:
    from vertexai.generative_models import GenerationConfig, Part

    config = GenerationConfig(
        response_mime_type="application/json", response_schema=PROPOSAL_SCHEMA, max_output_tokens=max_output_tokens
    )
    pdf_part = Part.from_data(data=pdf_bytes, mime_type="application/pdf")
    for name in model_names:
        try:
            response = model_factory(name).generate_content([pdf_part, PARSE_PROMPT], generation_config=config)
            return ProposalFacts.model_validate_json(response.text)
        except (ValidationError, ValueError) as exc:
            logger.warning("model %s returned schema-invalid proposal facts: %s", name, exc)
        except Exception as exc:
            logger.warning("model %s failed on proposal parse: %s", name, exc)
    raise ProposalParseError(f"all models failed to parse the proposal: {model_names}")
```

Note: `Part.from_data` in the fake path — the fakes never construct a real `Part`; the real class is only touched inside this function, so tests exercise the call shape via `model.contents` length. `Part.from_data` itself is a no-network data object, safe in unit tests (same rationale as `GenerationConfig` in phase 1).

- [ ] **Step 4: Run tests, expect PASS**; `ws lint skipta` clean.

- [ ] **Step 5: Commit** — bodyfile `.commits/skipta-p2-parse.md` (message `feat: Gemini multimodal proposal parsing with never-invent gaps`, add: `app/proposals.py`, `tests/test_proposals.py`; body: one sentence — strict schema, nullable total, same fallback chain as extraction).

### Task 6: Routes — three-way response + amend resolution

**Files:**
- Modify: `components/skipta/app/main.py`, `components/skipta/tests/conftest.py`
- Test: `components/skipta/tests/test_routes_amend.py` (new)

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: `CreateAmendmentRequest.proposal_file_id: str | None = None`; `get_drive` provider (revived); `POST /api/v1/amendments` returns 200 `{"status": "choose_proposal", "candidates": [...], "note": str}` for unresolved amend intent, else 201 as before; resolved amend writes `kind="amend"` + proposal fields; `proposal_file_id=""` forces `kind="new"`.

- [ ] **Step 1: Update conftest** — in `tests/conftest.py`: import and override the drive + pass-2 dependencies. Replace the imports block and `fakes`/`client` fixtures with:

```python
import pytest
from fastapi.testclient import TestClient

from app.extraction import AmendmentPayload
from app.main import app, get_drive, get_extract, get_parse_proposal, get_settings, get_sheets, get_storage
from app.config import Settings
from app.proposals import Candidate, ProposalFacts
from tests.test_amendments import FakeSheets
from tests.test_gcs import FakeStorageClient
from tests.test_proposals import FakeDrive

PANEL_ROWS = [["P-200A-01", "200", "200A Main Lug Panel 30-Space", "245.00"]]
BREAKER_ROWS = [["B-20A-1P", "20", "1", "20A Single-Pole Type BR", "7.50"]]
```

(keep `RoutedFakeSheets` as is) and:

```python
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
```

- [ ] **Step 2: Write the failing tests** — `tests/test_routes_amend.py`:

```python
from app.extraction import AmendmentPayload

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
```

- [ ] **Step 3: Run, expect FAIL** — `ws test skipta` (conftest ImportError on `get_parse_proposal`/`get_drive`).

- [ ] **Step 4: Implement** — in `app/main.py`:

Imports: add `from fastapi.responses import HTMLResponse, JSONResponse`, `from app import proposals`, and extend the google_clients import with `build_drive`. Add providers after `get_storage`:

```python
def get_drive():
    if "drive" not in _clients:
        _clients["drive"] = build_drive(get_credentials())
    return _clients["drive"]


def get_parse_proposal():
    def _parse(pdf_bytes: bytes, settings: Settings):
        factory = make_model_factory(settings.project_id, settings.region)
        return proposals.parse_proposal(
            pdf_bytes, model_factory=factory, model_names=settings.model_names, max_output_tokens=settings.max_output_tokens
        )

    return _parse
```

`CreateAmendmentRequest` gains:

```python
    proposal_file_id: str | None = Field(default=None, max_length=200)
```

In `create_amendment`, add `drive=Depends(get_drive), parse=Depends(get_parse_proposal),` to the signature. After the `payload = payload.model_copy(...)` line, insert:

```python
    facts = None
    proposal_name = ""
    kind = "new"
    if payload.intent == "amend" and body.proposal_file_id is None:
        candidates = proposals.search_proposals(drive, settings.drive_folder_id, payload.customer_name, payload.proposal_hint)
        note = "" if candidates else "Nothing in Drive matched the spoken reference — you can proceed as a new work order."
        return JSONResponse(
            status_code=200,
            content={"status": "choose_proposal", "candidates": [c.__dict__ for c in candidates], "note": note},
        )
    if payload.intent == "amend" and body.proposal_file_id:
        kind = "amend"
        try:
            pdf_bytes = proposals.fetch_pdf(drive, body.proposal_file_id)
            facts = parse(pdf_bytes, settings)
            proposal_name = drive.files().get(fileId=body.proposal_file_id, fields="name, mimeType, size").execute()["name"]
        except (proposals.ProposalTooLarge, proposals.ProposalFetchError, proposals.ProposalParseError) as exc:
            raise HTTPException(status_code=502, detail=f"Could not read the proposal: {exc}") from exc
```

and extend the `AmendmentRecord(...)` construction with:

```python
        kind=kind, proposal_file_id=body.proposal_file_id or "", proposal_name=proposal_name,
        original_total=facts.original_total if facts else None,
        customer_email=facts.customer_email if facts else "", customer_address=facts.customer_address if facts else "",
```

- [ ] **Step 5: Run tests, expect PASS** (prior suites too — `kind=new` regression rides the existing intake/sign tests); `ws lint skipta` clean.

- [ ] **Step 6: Commit** — bodyfile `.commits/skipta-p2-routes.md` (message `feat: three-way intake — choose_proposal, resolved amend, proceed-as-new`, add: `app/main.py`, `tests/conftest.py`, `tests/test_routes_amend.py`; body: short paragraph — synchronous disambiguation with no row until resolved, absent-vs-empty file id semantics, honest 502 on fetch/parse failure).

### Task 7: Templates — pick-list, provenance block, totals ladder

**Files:**
- Modify: `components/skipta/app/templates/index.html`, `components/skipta/app/templates/sign.html`, `components/skipta/app/templates/amendment_pdf.html`, `components/skipta/app/static/skipta.css`
- Test: `components/skipta/tests/test_routes_amend.py` (append)

**Interfaces:**
- Consumes: `choose_proposal` response shape (Task 6), `AmendmentRecord` K–P fields (Task 3).
- Produces: intake pick-list UX; `sign.html`/`amendment_pdf.html` render the Original proposal block and totals ladder for `kind == "amend"`.

- [ ] **Step 1: Append failing tests** to `tests/test_routes_amend.py`:

```python
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
```

- [ ] **Step 2: Run, expect FAIL** — `ws test skipta`.

- [ ] **Step 3: Implement templates.**

`index.html` — replace the `<script>` block with:

```html
<script>
async function submitAmendment(fileId) {
  const result = document.getElementById("result");
  result.textContent = "Working…";
  const body = { voice_text: document.getElementById("voice").value };
  const customer = document.getElementById("customer").value.trim();
  if (customer) body.customer_name = customer;
  if (fileId !== undefined) body.proposal_file_id = fileId;
  const resp = await fetch("/api/v1/amendments", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body) });
  if (!resp.ok) { result.textContent = "Failed: " + (await resp.text()); return; }
  const data = await resp.json();
  if (data.status === "choose_proposal") { renderCandidates(data); return; }
  result.innerHTML = `Amendment created — <a href="${data.signing_url}">open the signing page</a>`;
}
function renderCandidates(data) {
  const result = document.getElementById("result");
  result.innerHTML = "";
  const heading = document.createElement("p");
  heading.textContent = data.note || "Which proposal is being amended?";
  result.appendChild(heading);
  for (const c of data.candidates) {
    const btn = document.createElement("button");
    btn.className = "candidate";
    btn.textContent = `${c.name} (${c.folder})`;
    btn.addEventListener("click", () => submitAmendment(c.file_id));
    result.appendChild(btn);
  }
  const none = document.createElement("button");
  none.className = "candidate none";
  none.textContent = "None of these — proceed as new work order";
  none.addEventListener("click", () => submitAmendment(""));
  result.appendChild(none);
}
document.getElementById("submit").addEventListener("click", () => submitAmendment(undefined));
</script>
```

`skipta.css` — append:

```css
button.candidate { background: #fff; color: #1c1917; border: 1px solid #a8a29e; text-align: left; margin-top: .5rem; }
button.candidate.none { border-style: dashed; color: #57534e; }
.provenance { background: #eff6ff; border: 1px solid #93c5fd; padding: .8rem; border-radius: 6px; margin: 1rem 0; font-size: .9rem; }
```

`sign.html` — insert directly after the `<p>Requested change: …</p>` line:

```html
  {% if record.kind == "amend" %}
  <div class="provenance">
    <strong>Original proposal:</strong> {{ record.proposal_name }}<br>
    Original total: {{ "%.2f"|format(record.original_total) if record.original_total is not none else "not found in document" }}<br>
    Customer email: {{ record.customer_email or "not found in document" }}<br>
    Customer address: {{ record.customer_address or "not found in document" }}
  </div>
  {% endif %}
```

and replace the single total row in the table with:

```html
    {% if record.kind == "amend" %}
    <tr><td colspan="4">Original proposal</td><td>{{ "%.2f"|format(record.original_total) if record.original_total is not none else "—" }}</td></tr>
    <tr class="total"><td colspan="4">This amendment</td><td>{{ "%.2f"|format(record.total) }}</td></tr>
    {% if record.original_total is not none %}
    <tr class="total"><td colspan="4">Grand total</td><td>{{ "%.2f"|format(record.original_total + record.total) }}</td></tr>
    {% endif %}
    {% else %}
    <tr class="total"><td colspan="4">Total</td><td>{{ "%.2f"|format(record.total) }}</td></tr>
    {% endif %}
```

`amendment_pdf.html` — apply the same two fragments (provenance `<div class="provenance">` after the `<blockquote>`, and the same totals-ladder replacement for its total row; add `.provenance { border: 1px solid #999; padding: 8px; margin: 1em 0; }` to its inline styles).

- [ ] **Step 4: Run tests, expect PASS** (whole suite; PDF-html test unaffected — `record.kind` defaults `"new"`); `ws lint skipta` clean.

- [ ] **Step 5: Commit** — bodyfile `.commits/skipta-p2-templates.md` (message `feat: pick-list intake, provenance block, totals ladder`, add: `app/templates/index.html`, `app/templates/sign.html`, `app/templates/amendment_pdf.html`, `app/static/skipta.css`, `tests/test_routes_amend.py`; body: one sentence — DOM-built candidate buttons, provenance names the source file, grand total only when the original was parsed).

### Task 8: README, checkpoint push, CR

**Files:**
- Modify: `components/skipta/README.md`

- [ ] **Step 1: README** — under the intro paragraph, add:

```markdown
## Two flows

- **New work order** — "Smith wants a 200 amp panel and three 20 amp single pole breakers": priced from the sheet, signed, archived.
- **Amend existing proposal** — "Amend Rasmus' SPAN panel proposal to add a sub panel with four 20 amp breakers and 2 30 amp breakers": Skipta finds the proposal PDF in the shared Drive folder (asking when zero or several match), reads it with Gemini for the original total and customer details, and the signed amendment shows Original / This amendment / Grand total with the source document named.
```

- [ ] **Step 2: Full verification** — `ws test skipta` (expect: prior suite + ~12 new, 1 skip) and `ws lint skipta`.

- [ ] **Step 3: Commit** — bodyfile `.commits/skipta-p2-readme.md` (message `docs: two-flow README`, add: `README.md`).

- [ ] **Step 4: Checkpoint push + CR** — `ws push skipta`, then `cp templates/change.md .crs/skipta-p2.md`, fill (Summary: the feature; Test plan: CI + the live Rasmus smoke), `ws cr skipta "feat: proposal-aware amendments — find, confirm, parse, reference" .crs/skipta-p2.md`. Then wait for review (single re-push after triage, per push policy).

### Task 9: Live smoke (after CR merge + deploy)

- [ ] Re-apply base + rollout restart (image rebuilds on merge): `ws k8s apply -k components/skipta/k8s/base -n skipta`, then `ws k8s rollout restart deployment/skipta -n skipta`, then `ws k8s rollout status deployment/skipta -n skipta --timeout=120s`.
- [ ] Human adds K1–P1 headers to the Amendments tab (if not already done).
- [ ] Live Rasmus flow from the phone: dictate the real amend sentence → pick the SPAN proposal from the list → verify the signing page shows the parsed original total/email/address with the source filename → sign → PDF in GCS shows the totals ladder → row has kind=amend + K–P populated.
- [ ] Negative checks: dictate an amend referencing a nonexistent doc (expect empty pick-list + proceed-as-new), and a new-intent sentence (expect no pick-list).
- [ ] Record the verification in README ("Verified" line, current-state phrasing), commit, and fold into the final close-out push.

---

## Self-review notes

- Spec coverage: flow/API three-way (T6), extraction growth (T1), poles rule (T2), K–P schema + legacy rows (T3), search/fetch (T4), multimodal parse (T5), UI/provenance/ladder (T7), README + live smoke (T8–9). Deferred items from the spec stay deferred.
- Type consistency spot-checks: `Candidate.__dict__` serialization matches the frozen dataclass fields used in tests; row indices 10–14 in route tests align with the K–P field order in Task 3; `parse` provider signature `(pdf_bytes, settings)` matches conftest override; sign flow untouched (GCS path from the pivot).
- Judgment calls encoded: fakes return bytes directly from `execute()` while production goes through `MediaIoBaseDownload` (isinstance branch in `fetch_pdf`); `client.extraction_state` lets tests flip intent without re-wiring overrides; `required: []` in the parse schema so Gemini may omit any fact rather than invent one.
