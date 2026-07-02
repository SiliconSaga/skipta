"""The Amendments tab is the state machine: one row per amendment, draft → signed."""
import re
from dataclasses import astuple, dataclass

from app.google_clients import read_values

TAB = "Amendments"
DATA_RANGE = f"{TAB}!A2:J"


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

    def to_row(self) -> list:
        row = list(astuple(self))
        row[6] = f"{self.total:.2f}"
        return row

    @classmethod
    def from_row(cls, row: list) -> "AmendmentRecord":
        padded = list(row) + [""] * (10 - len(row))
        padded[6] = float(padded[6] or 0)
        return cls(*padded)


def make_amendment_id(customer_name: str, now) -> str:
    cleaned = re.sub(r"['']", "", customer_name.lower())  # O'Brien → obrien, not o-brien
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
