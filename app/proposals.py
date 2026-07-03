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
