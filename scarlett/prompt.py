"""System prompt loading + mode detection."""

from __future__ import annotations

import re
import sys

from .config import PROMPT_PATH
from .memory import HyperMemory


def load_system_prompt(memory: HyperMemory | None = None) -> str:
    """Load setting.txt and append memory context block if available."""
    if not PROMPT_PATH.exists():
        print("setting.txt not found. Run `uv run build.py` first.", file=sys.stderr)
        sys.exit(1)
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    if memory:
        prompt += f"\n\n---\n\n{memory.to_context_block()}"
    return prompt


# ── Mode / Expression detection from response text ────

_PSYCHO_PATTERNS = re.compile(
    r"(\u3042\u3089\u3042\u3089|\u304f\u3075\u3075|\u306d\u3047|\u2026\u3078\u3048|\u58ca\u3057|\u6bba\u3057|\u304a\u3057\u304a\u304d|"
    r"\u30b5\u30a4\u30b3|\u30d1\u30cb\u30c3\u30af|\u30e4\u30f3\u30c7\u30ec|\u5d29\u58ca|\u7cbe\u795e|"
    r"\u2026\u306d\u3047|\u3075\u3075\u3075|\u304f\u3059\u304f\u3059|\u304e\u3083\u306f\u306f|"
    r"\u3010PSYCHO\u3011|\u3010\u30b5\u30a4\u30b3\u3011|\u25c8 PSYCHO)",
    re.IGNORECASE,
)

_EXPRESSION_HINTS = {
    # psycho mode expressions
    "angry": re.compile(r"(\u6012|\u8150|\u304f\u305d|\u3080\u304b\u3064\u304f|\u3044\u3089\u3044\u3089|\u304a\u3053|\u6012\u308a|\u30a4\u30e9)", re.IGNORECASE),
    "scared": re.compile(r"(\u6016|\u304a\u305d|\u3053\u308f|\u3076\u308b\u3076\u308b|\u304c\u304f\u304c\u304f|\u3072\u3043|\u6016\u304f)", re.IGNORECASE),
    "surprised": re.compile(r"(\u9a5a|\u3048\u3063|\u3078\u3047|\u307e\u3042|\u3046\u305d|\u304a\u304a|\u306a\u3093\u3068|\u3073\u3063\u304f\u308a|\uff01\uff01|\uff01\uff1f)", re.IGNORECASE),
    "sad": re.compile(r"(\u6ce3|\u304b\u306a\u3057|\u3055\u307f\u3057|\u3064\u3089|\u3050\u3059\u3093|\u6dea|\u3046\u3046\u3063|\u60b2\u3057)", re.IGNORECASE),
    "laugh": re.compile(r"(\u7b11|\u3042\u306f\u306f|\u3075\u3075|\u304f\u3059\u304f\u3059|\u304e\u3083\u306f|\u30b1\u30e9\u30b1\u30e9|\u30cb\u30e4|\u7b11\u3044|\u30ef\u30ed\u30bf)", re.IGNORECASE),
    "wink": re.compile(r"(\u30a6\u30a3\u30f3\u30af|\u3075\u3075\u3093|\u306d\u3063|\u3058\u30fc|\u7d4c\u3063|\u304a\u307e\u304b\u305b|\u4efb\u305b\u3066)", re.IGNORECASE),
    "sleep": re.compile(r"(\u7720|\u306d\u3080|\u3059\u3084\u3059\u3084|\u304a\u3084\u3059\u307f|\u30b0\u30fc|\u3046\u3068\u3046\u3068)", re.IGNORECASE),
    "smile": re.compile(r"(\u7b11\u9854|\u306b\u3053|\u30cb\u30b3|\u5b09\u3057|\u305f\u306e\u3057|\u3088\u304b\u3063\u305f|\u3088\u308d\u3057|\u2764|\u3067\u3059\u3088\u266a)", re.IGNORECASE),
}


def detect_mode(text: str) -> str:
    """Detect Angel or Psycho mode from response text."""
    if _PSYCHO_PATTERNS.search(text):
        return "psycho"
    return "angel"


def detect_expression(text: str, mode: str) -> str:
    """Detect the most fitting expression from response text."""
    # Check for specific expression cues
    for expr, pattern in _EXPRESSION_HINTS.items():
        if pattern.search(text):
            return expr

    # Defaults
    if mode == "psycho":
        return "angry"
    return "neutral"
