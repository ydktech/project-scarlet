"""Constants, paths, and model configuration."""

from __future__ import annotations

from pathlib import Path

# ── Paths ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
PROMPT_PATH = ROOT / "setting.txt"
MEMORY_PATH = ROOT / "memory.json"
MEM0_DB_PATH = ROOT / "memory_db"
STATIC_DIR = ROOT / "static"

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
