"""Cerebras LLM client + streaming generator."""

from __future__ import annotations

import logging
import time
from collections.abc import Generator

from cerebras.cloud.sdk import Cerebras
from dotenv import load_dotenv

from .config import ENV_PATH, MAX_TOKENS, MODEL, TEMPERATURE, TOP_P

log = logging.getLogger("scarlett.llm")


def create_client() -> Cerebras:
    """Load .env and return a Cerebras client."""
    load_dotenv(ENV_PATH)
    return Cerebras()


def stream_chat(
    client: Cerebras,
    messages: list[dict],
    *,
    max_retries: int = 3,
) -> Generator[str, None, str]:
    """
    Sync generator that yields text chunks from the LLM.

    Yields each token as it arrives. Returns the full accumulated response.
    Handles retries internally for transient errors.
    """
    full_response = ""

    for attempt in range(max_retries):
        try:
            stream = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                max_completion_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                top_p=TOP_P,
                stream=True,
            )

            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    full_response += delta.content
                    yield delta.content

            return full_response

        except Exception as e:
            is_retryable = any(
                k in str(e) for k in ("StreamReset", "stream", "502", "503", "429")
            )
            if is_retryable and attempt < max_retries - 1:
                wait = (attempt + 1) * 1.5
                log.warning(
                    "Connection error, retrying in %.0fs... (%d/%d)",
                    wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
                continue

            log.error("LLM error: %s", e)
            raise

    return full_response
