"""One-shot access check: prints tab names of the shared spreadsheet via impersonated ADC."""
import os
import sys

import google.auth
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

creds, _ = google.auth.default(scopes=SCOPES)
sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
meta = sheets.spreadsheets().get(spreadsheetId=sys.argv[1] if len(sys.argv) > 1 else os.environ["SKIPTA_SPREADSHEET_ID"]).execute()
print([s["properties"]["title"] for s in meta["sheets"]])
