"""All runtime settings come from environment variables (see .env.example).

Every AWS integration has a local fallback so the full demo runs on a laptop
with no AWS access: AGENT_MODE=mock, STORE=memory, ROUTING=haversine, NOTIFY=inapp.
"""
import os
from pathlib import Path


def _load_dotenv() -> None:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


# Agent: "mock" runs a deterministic planner over the same tools; "bedrock" runs the Strands agent on Claude.
AGENT_MODE = _env("AGENT_MODE", "mock")
AWS_REGION = _env("AWS_REGION", "me-central-1")
BEDROCK_REGION = _env("BEDROCK_REGION", AWS_REGION)
BEDROCK_MODEL_ID = _env("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
# If Bedrock fails before the agent's first tool call, fall back to the mock planner so the demo continues.
BEDROCK_FALLBACK = _env("BEDROCK_FALLBACK", "true").lower() in ("1", "true", "yes")

# Storage: "memory" (single process) or "dynamodb".
STORE = _env("STORE", "memory")
DDB_TABLE = _env("DDB_TABLE", "plenty-demo")

# Routing: "haversine" (straight line x road factor) or "location" (Amazon Location Service Routes).
ROUTING = _env("ROUTING", "haversine")
AVG_SPEED_KMH = float(_env("AVG_SPEED_KMH", "32"))
ROAD_FACTOR = float(_env("ROAD_FACTOR", "1.35"))
STOP_SERVICE_MIN = float(_env("STOP_SERVICE_MIN", "5"))
MAX_DRIVE_MIN = float(_env("MAX_DRIVE_MIN", "35"))

# Notifications: "inapp" (screens only) or "sns" (also publishes to an SNS topic).
NOTIFY = _env("NOTIFY", "inapp")
SNS_TOPIC_ARN = _env("SNS_TOPIC_ARN", "")

# Photos: saved to S3 when PHOTO_BUCKET is set, otherwise kept in memory.
PHOTO_BUCKET = _env("PHOTO_BUCKET", "")

# Food safety and demo timing.
SERVE_BUFFER_MIN = float(_env("SERVE_BUFFER_MIN", "60"))
OFFER_TIMEOUT_SECONDS = float(_env("OFFER_TIMEOUT_SECONDS", "60"))
SIM_RESPONSE_SECONDS = float(_env("SIM_RESPONSE_SECONDS", "3"))
DEMO_CLOCK = _env("DEMO_CLOCK", "")  # e.g. "19:40" pins the Dubai clock for a repeatable demo
TIMEZONE = _env("TIMEZONE", "Asia/Dubai")

# Impact.
KG_PER_PORTION = float(_env("KG_PER_PORTION", "0.35"))
CO2E_PER_KG_FOOD = float(_env("CO2E_PER_KG_FOOD", "2.5"))
CO2E_SOURCE = _env("CO2E_SOURCE", "placeholder factor: replace with a cited source before the pitch")

PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL", "")
