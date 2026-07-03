"""Amend-side pipeline: find the referenced proposal in the shared Skipta/ tree, fetch its bytes. Reads only — consumer-account service accounts cannot own Drive content, but shared reads are unaffected."""
import io
import logging
import re
from dataclasses import dataclass

from googleapiclient.http import MediaIoBaseDownload
from pydantic import BaseModel, ValidationError

FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"
MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_CANDIDATES = 5

logger = logging.getLogger("skipta.proposals")


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
