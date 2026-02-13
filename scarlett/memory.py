"""HyperMemory — L3 Core metadata tracker + name extraction."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import MEMORY_PATH


class HyperMemory:
    """
    L3 Core Memory — lightweight metadata that persists via JSON.
    Tracks: name, relationship phase, session count, mistake counts.
    """

    DEFAULT: dict = {
        "master_name": None,
        "relationship_phase": 1,
        "session_count": 0,
        "mistake_counts": {},
        "last_session": None,
    }

    def __init__(self, path: Path = MEMORY_PATH):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                return {**self.DEFAULT, **stored}
            except (json.JSONDecodeError, KeyError):
                return dict(self.DEFAULT)
        return dict(self.DEFAULT)

    def save(self) -> None:
        self.data["last_session"] = datetime.now().isoformat()
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def bump_session(self) -> None:
        self.data["session_count"] += 1
        sessions = self.data["session_count"]
        if sessions >= 30:
            self.data["relationship_phase"] = max(self.data["relationship_phase"], 4)
        elif sessions >= 15:
            self.data["relationship_phase"] = max(self.data["relationship_phase"], 3)
        elif sessions >= 5:
            self.data["relationship_phase"] = max(self.data["relationship_phase"], 2)

    def to_context_block(self) -> str:
        lines = ["[HYPERMEMORY — L3 Core Metadata]"]
        if self.data["master_name"]:
            lines.append(f"- Master's name: {self.data['master_name']}")
        if self.data["mistake_counts"]:
            for k, v in self.data["mistake_counts"].items():
                lines.append(f"- Repeat mistake '{k}': {v} times")
        phase = self.data["relationship_phase"]
        phase_names = {1: "\u89b3\u5bdf", 2: "\u8a8d\u5b9a", 3: "\u57f7\u7740", 4: "\u4fe1\u983c"}
        lines.append(f"- Relationship phase: Phase {phase} ({phase_names.get(phase, '?')})")
        lines.append(f"- Total sessions: {self.data['session_count']}")
        return "\n".join(lines)


def try_extract_name(text: str, memory: HyperMemory) -> None:
    """Simple heuristic to detect name introductions."""
    if memory.data["master_name"]:
        return
    lower = text.lower()
    for pattern in [
        "my name is ", "i'm ", "call me ",
        "\ub098\ub294 ", "\ub0b4 \uc774\ub984\uc740 ",
        "\u50d5\u306f", "\u4ffa\u306f", "\u79c1\u306f",
    ]:
        if pattern in lower:
            idx = lower.index(pattern) + len(pattern)
            rest = text[idx:].strip().split()[0] if text[idx:].strip() else ""
            name = rest.rstrip(".,!?\u3002\u3001\uff01\uff1f\u3060\u3088\u3067\u3059")
            if name and len(name) < 20:
                memory.data["master_name"] = name
                break
