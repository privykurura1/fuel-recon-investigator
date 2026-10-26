"""Settings read from .env. Nothing secret is ever printed."""
import os

from dotenv import load_dotenv

load_dotenv()


def need(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name} in .env (see .env.example)")
    return value


ZETARIS_REST_URL = os.environ.get("ZETARIS_REST_URL", "http://localhost:8888/api/v1.0").rstrip("/")
ZETARIS_ORG_ID = os.environ.get("ZETARIS_ORG_ID", "1")
METERLESS_BASE_URL = os.environ.get("METERLESS_BASE_URL", "http://127.0.0.1:8088/v1").rstrip("/")
METERLESS_MODEL = os.environ.get("METERLESS_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
METERLESS_REPORT_MODEL = os.environ.get("METERLESS_REPORT_MODEL", "") or METERLESS_MODEL
APP_NAME = "fuel-recon-investigator"

MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "20"))
ROWS_TO_MODEL = 40          # rows shown to the model per query
LLM_TIMEOUT_S = 180         # Nemotron "thinks" first, so allow time
