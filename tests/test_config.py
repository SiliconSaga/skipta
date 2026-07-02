from app.config import Settings


def test_from_env_reads_and_splits(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "proj")
    monkeypatch.setenv("GCP_REGION", "us-east1")
    monkeypatch.setenv("SKIPTA_SPREADSHEET_ID", "sheet123")
    monkeypatch.setenv("SKIPTA_DRIVE_FOLDER_ID", "folder123")
    monkeypatch.setenv("SKIPTA_BASE_URL", "https://skipta.cmdbee.org")
    monkeypatch.setenv("SKIPTA_MODEL_NAMES", "gemini-2.5-flash, gemini-2.0-flash-001")
    s = Settings.from_env()
    assert s.project_id == "proj"
    assert s.model_names == ["gemini-2.5-flash", "gemini-2.0-flash-001"]
    assert s.max_output_tokens == 1024
    assert s.rate_limit_per_minute == 10
