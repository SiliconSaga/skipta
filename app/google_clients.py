"""All Google client construction lives here; everything downstream takes injected clients."""
import google.auth
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


def get_credentials():
    creds, _ = google.auth.default(scopes=SCOPES)
    return creds


def build_sheets(creds):
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def build_storage(creds, project_id: str):
    from google.cloud import storage

    return storage.Client(project=project_id, credentials=creds)


def make_model_factory(project_id: str, region: str):
    def factory(model_name: str):
        import vertexai
        from vertexai.generative_models import GenerativeModel

        vertexai.init(project=project_id, location=region)
        return GenerativeModel(model_name)

    return factory


def read_values(sheets, spreadsheet_id: str, a1_range: str):
    result = sheets.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=a1_range).execute()
    return result.get("values", [])
