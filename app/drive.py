"""Drive integration: locate (or create) the customer's subfolder under the shared Skipta folder, upload signed PDFs idempotently."""
import io

from googleapiclient.http import MediaIoBaseUpload

FOLDER_MIME = "application/vnd.google-apps.folder"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_customer_folder(drive, root_folder_id: str, customer_name: str):
    query = (
        f"'{_escape(root_folder_id)}' in parents and mimeType = '{FOLDER_MIME}' "
        f"and name = '{_escape(customer_name)}' and trashed = false"
    )
    result = drive.files().list(q=query, fields="files(id, name)", pageSize=5).execute()
    files = result.get("files", [])
    return files[0]["id"] if files else None


def ensure_customer_folder(drive, root_folder_id: str, customer_name: str) -> str:
    existing = find_customer_folder(drive, root_folder_id, customer_name)
    if existing:
        return existing
    created = drive.files().create(
        body={"name": customer_name, "mimeType": FOLDER_MIME, "parents": [root_folder_id]}, fields="id"
    ).execute()
    return created["id"]


def find_file_in_folder(drive, folder_id: str, filename: str):
    query = f"'{_escape(folder_id)}' in parents and name = '{_escape(filename)}' and trashed = false"
    result = drive.files().list(q=query, fields="files(id, webViewLink)", pageSize=1).execute()
    files = result.get("files", [])
    return files[0].get("webViewLink") if files else None


def upload_pdf(drive, folder_id: str, filename: str, pdf_bytes: bytes) -> str:
    media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf")
    created = drive.files().create(
        body={"name": filename, "parents": [folder_id]}, media_body=media, fields="webViewLink"
    ).execute()
    return created["webViewLink"]
