"""mem0 semantic memory — init / store / recall / get_all."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .config import MEM0_DB_PATH, MODEL, USER_ID

if TYPE_CHECKING:
    from mem0 import Memory

log = logging.getLogger("scarlett.semantic")


# ── Cerebras compatibility patch ──────────────────────
def _patch_cerebras_compat(mem0_instance: Memory) -> None:
    """Strip 'store' param that Cerebras doesn't support."""
    original_create = mem0_instance.llm.client.chat.completions.create

    def patched_create(**kwargs):
        kwargs.pop("store", None)
        return original_create(**kwargs)

    mem0_instance.llm.client.chat.completions.create = patched_create


def init_mem0(cerebras_api_key: str) -> Memory:
    """Initialize mem0 with Cerebras LLM + Huggingface local embedder."""
    import contextlib
    import io
    import os
    import warnings

    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    warnings.filterwarnings("ignore", category=FutureWarning)
    for logger_name in (
        "sentence_transformers", "transformers",
        "huggingface_hub", "safetensors",
    ):
        logging.getLogger(logger_name).setLevel(logging.ERROR)

    os.environ.setdefault("OPENAI_API_KEY", "unused")

    with contextlib.redirect_stderr(io.StringIO()):
        from mem0 import Memory

    config = {
        "llm": {
            "provider": "openai",
            "config": {
                "model": MODEL,
                "api_key": cerebras_api_key,
                "openai_base_url": "https://api.cerebras.ai/v1",
                "temperature": 0.1,
                "max_tokens": 2048,
            },
        },
        "embedder": {
            "provider": "huggingface",
            "config": {
                "model": "multi-qa-MiniLM-L6-cos-v1",
                "embedding_dims": 384,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": "scarlett_memory",
                "embedding_model_dims": 384,
                "path": str(MEM0_DB_PATH),
            },
        },
        "version": "v1.1",
    }

    with contextlib.redirect_stderr(io.StringIO()):
        m = Memory.from_config(config)
    _patch_cerebras_compat(m)
    log.info("mem0 initialized")
    return m


def store_conversation(
    mem0_memory: Memory, messages: list[dict], turn_count: int = 10,
) -> None:
    """Store recent conversation turns into mem0."""
    recent = [m for m in messages[-turn_count * 2:] if m["role"] != "system"]
    if len(recent) < 2:
        return
    try:
        mem0_memory.add(recent, user_id=USER_ID)
    except Exception as e:
        log.warning("mem0 store warning: %s", e)


def recall_memories(mem0_memory: Memory, query: str, limit: int = 5) -> str:
    """Search mem0 for relevant memories and format as context block."""
    try:
        results = mem0_memory.search(query=query, user_id=USER_ID, limit=limit)
        if not results or not results.get("results"):
            return ""
        memories = results["results"]
        if not memories:
            return ""
        lines = ["[HYPERMEMORY — Recalled Memories]"]
        for mem in memories:
            text = mem.get("memory", "")
            if text:
                lines.append(f"- {text}")
        return "\n".join(lines)
    except Exception as e:
        log.warning("mem0 recall warning: %s", e)
        return ""


def get_all_memories(mem0_memory: Memory) -> list[dict]:
    """Get all stored memories for display."""
    try:
        results = mem0_memory.get_all(user_id=USER_ID)
        if isinstance(results, dict):
            return results.get("results", [])
        return results or []
    except Exception:
        return []
