"""Environment-driven settings. A .env at the component root is honored for local dev."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODELS = "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash-001"


@dataclass(frozen=True)
class Settings:
    project_id: str
    region: str
    spreadsheet_id: str
    drive_folder_id: str
    base_url: str
    gcs_bucket: str = ""
    model_names: list[str] = field(default_factory=list)
    max_output_tokens: int = 1024
    rate_limit_per_minute: int = 10

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            project_id=os.getenv("GCP_PROJECT_ID", ""),
            region=os.getenv("GCP_REGION", "us-east1"),
            spreadsheet_id=os.getenv("SKIPTA_SPREADSHEET_ID", ""),
            drive_folder_id=os.getenv("SKIPTA_DRIVE_FOLDER_ID", ""),
            base_url=os.getenv("SKIPTA_BASE_URL", "http://localhost:8000"),
            gcs_bucket=os.getenv("SKIPTA_GCS_BUCKET", ""),
            model_names=[m.strip() for m in os.getenv("SKIPTA_MODEL_NAMES", DEFAULT_MODELS).split(",") if m.strip()],
            max_output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS", "1024")),
            rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "10")),
        )
