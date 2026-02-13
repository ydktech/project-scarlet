"""Constants, paths, and model configuration."""

from __future__ import annotations

import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
PROMPT_PATH = ROOT / "setting.txt"
MEMORY_PATH = ROOT / "memory.json"
MEM0_DB_PATH = ROOT / "memory_db"
STATIC_DIR = ROOT / "static"
GOOGLE_OAUTH_CLIENT_SECRET_PATH = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_PATH", "")
GOOGLE_CAL_TOKEN_PATH = Path(
    os.environ.get("GOOGLE_CAL_TOKEN_PATH", str(ROOT / "google_token.json")),
)
GOOGLE_CAL_SCOPES = ("https://www.googleapis.com/auth/calendar.events",)

# ── Model ──────────────────────────────────────────────
MODEL = "qwen-3-235b-a22b-instruct-2507"
MAX_HISTORY = 50
MAX_TOKENS = 8192
TEMPERATURE = 0.45
TOP_P = 0.95
USER_ID = "master"

# ── Agent ──────────────────────────────────────────────
MAX_TOOL_ROUNDS = 5

# ── Expressions ────────────────────────────────────────
EXPRESSIONS = [
    "smile", "angry", "surprised",
    "sad", "wink", "scared",
    "laugh", "neutral", "sleep",
]
