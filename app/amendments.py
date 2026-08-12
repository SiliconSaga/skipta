"""The Amendments tab is the state machine: one row per amendment, draft → signed."""
import re
from dataclasses import astuple, dataclass

from app.google_clients import read_values

TAB = "Amendments"
DATA_RANGE = f"{TAB}!A2:P"


@dataclass
class AmendmentRecord:
    amendment_id: str
    created_at: str
    customer_name: str
    voice_text: str
    extracted_json: str
    line_items_json: str
    total: float
    status: str  # "draft" | "signed"
    pdf_drive_url: str
    signed_at: str
    kind: str = "new"  # "new" work order | "amend" of an existing proposal
    proposal_file_id: str = ""
    proposal_name: str = ""
    original_total: float | None = None
    customer_email: str = ""
    customer_address: str = ""

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


def make_amendment_id(customer_name: str, now) -> str:
    cleaned = re.sub(r"['’]", "", customer_name.lower())  # straight + curly apostrophes: O'Brien → obrien, not o-brien
    slug = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
    return f"amend_{slug}_{now.strftime('%Y%m%d%H%M%S')}"


def append_amendment(sheets, spreadsheet_id: str, record: AmendmentRecord) -> None:
    sheets.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range=DATA_RANGE, valueInputOption="RAW", body={"values": [record.to_row()]}
    ).execute()


def find_amendment(sheets, spreadsheet_id: str, amendment_id: str):
    for index, row in enumerate(read_values(sheets, spreadsheet_id, DATA_RANGE)):
        if row and row[0] == amendment_id:
            return index + 2, AmendmentRecord.from_row(row)  # +2: 1-based rows below the header
    return None


def mark_signed(sheets, spreadsheet_id: str, row: int, pdf_url: str, signed_at: str) -> None:
    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"{TAB}!H{row}:J{row}", valueInputOption="RAW",
        body={"values": [["signed", pdf_url, signed_at]]},
    ).execute()
