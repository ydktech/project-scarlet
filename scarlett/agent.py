"""Agentic loop: non-streaming tool detection rounds + streaming final response."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from cerebras.cloud.sdk import Cerebras

from .config import MAX_TOKENS, MAX_TOOL_ROUNDS, MODEL, TEMPERATURE, TOP_P
from .tools import TOOL_SCHEMAS, execute_tool

log = logging.getLogger("scarlett.agent")


def _is_retryable_llm_error(exc: Exception) -> bool:
    text = str(exc).lower()
    retry_markers = (
        "queue_exceeded",
        "too_many_requests_error",
        "too many requests",
        "rate limit",
        "429",
        "502",
        "503",
        "timeout",
        "temporarily unavailable",
        "streamreset",
    )
    return any(marker in text for marker in retry_markers)


async def _create_completion_with_retry(
    client: Cerebras,
    *,
    messages: list[dict],
    stream: bool,
    tools: list[dict] | None = None,
    max_retries: int = 5,
) -> tuple[Any, list[dict[str, Any]]]:
    """Create chat completion with retry/backoff for transient provider failures."""
    loop = asyncio.get_event_loop()
    retry_events: list[dict[str, Any]] = []

    for attempt in range(max_retries):
        try:
            kwargs: dict[str, Any] = {
                "model": MODEL,
                "messages": messages,
                "max_completion_tokens": MAX_TOKENS,
                "temperature": TEMPERATURE,
                "top_p": TOP_P,
                "stream": stream,
            }
            if tools is not None:
                kwargs["tools"] = tools

            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(**kwargs),
            )
            return response, retry_events
        except Exception as e:
            if _is_retryable_llm_error(e) and attempt < max_retries - 1:
                wait_s = min(12.0, 1.5 * (2 ** attempt))
                retry_events.append({
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "wait_seconds": wait_s,
                    "error": str(e),
                })
                log.warning(
                    "LLM transient error; retrying in %.1fs (%d/%d): %s",
                    wait_s,
                    attempt + 1,
                    max_retries,
                    e,
                )
                await asyncio.sleep(wait_s)
                continue
            raise

    raise RuntimeError("LLM completion failed after retries")


@dataclass
class ToolEvent:
    """Represents a tool execution event for SSE."""

    kind: str  # "tool_start" or "tool_done"
    tool: str
    call_id: str
    args: dict[str, Any] | None = None
    summary: str | None = None


async def _call_llm_non_streaming(
    client: Cerebras,
    messages: list[dict],
) -> tuple[Any, list[dict[str, Any]]]:
    """Make a non-streaming LLM call with tools. Returns the ChatCompletion response."""
    return await _create_completion_with_retry(
        client,
        messages=messages,
        stream=False,
        tools=TOOL_SCHEMAS,
    )


async def _stream_final_response(
    client: Cerebras,
    messages: list[dict],
) -> AsyncGenerator[ToolEvent | str, None]:
    """Stream the final LLM response (no tools) as text chunks."""
    loop = asyncio.get_event_loop()

    # Create streaming completion without tools
    stream, retry_events = await _create_completion_with_retry(
        client,
        messages=messages,
        stream=True,
    )
    for retry in retry_events:
        yield ToolEvent(
            kind="llm_retry",
            tool="llm",
            call_id="llm",
            args=retry,
        )

    def _next(s):
        try:
            return next(s)
        except StopIteration:
            return None

    while True:
        chunk = await loop.run_in_executor(None, _next, stream)
        if chunk is None:
            break
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content


async def run_agent_loop(
    client: Cerebras,
    messages: list[dict],
) -> AsyncGenerator[ToolEvent | str, None]:
    """
    Agentic loop: yields ToolEvent objects during tool execution,
    then yields str chunks for the final streaming response.

    The messages list passed here is the full send_messages (with system prompt,
    history, and current user message). Tool messages are appended during the loop
    but NOT persisted to the caller's history.
    """
    # Work on a copy so tool messages don't leak into persistent history
    work_messages = list(messages)
    tools_used: list[str] = []

    for round_num in range(MAX_TOOL_ROUNDS):
        log.info("Agent round %d/%d", round_num + 1, MAX_TOOL_ROUNDS)

        try:
            response, retry_events = await _call_llm_non_streaming(client, work_messages)
        except Exception as e:
            log.error("LLM non-streaming call failed: %s", e)
            raise
        for retry in retry_events:
            yield ToolEvent(
                kind="llm_retry",
                tool="llm",
                call_id="llm",
                args=retry,
            )

        choice = response.choices[0]

        # If no tool calls, break to streaming final response
        if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
            # The model produced a text response without tools.
            # We'll discard this and re-call with streaming for the typewriter effect.
            break

        # Process tool calls
        # First, add the assistant's tool_calls message
        assistant_msg = {
            "role": "assistant",
            "content": choice.message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in choice.message.tool_calls
            ],
        }
        work_messages.append(assistant_msg)

        for tc in choice.message.tool_calls:
            tool_name = tc.function.name
            call_id = tc.id

            try:
                tool_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            # Emit tool_start
            yield ToolEvent(
                kind="tool_start",
                tool=tool_name,
                call_id=call_id,
                args=tool_args,
            )

            # Execute tool
            start = time.monotonic()
            result = await execute_tool(tool_name, tool_args)
            elapsed = time.monotonic() - start

            # Check for pending actions requiring user confirmation
            try:
                parsed_result = json.loads(result)
                if isinstance(parsed_result, dict) and parsed_result.get("status") == "pending_confirmation":
                    yield ToolEvent(
                        kind="confirm_action",
                        tool=tool_name,
                        call_id=call_id,
                        args=parsed_result,
                    )
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

            # Truncate result for summary
            summary = result[:150] + "..." if len(result) > 150 else result

            # Emit tool_done
            yield ToolEvent(
                kind="tool_done",
                tool=tool_name,
                call_id=call_id,
                summary=summary,
            )

            tools_used.append(tool_name)
            log.info("Tool %s completed in %.1fs", tool_name, elapsed)

            # Add tool result to messages
            work_messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": result,
            })

    # Final streaming response (re-call with all context including tool results)
    async for item in _stream_final_response(client, work_messages):
        yield item

    # Yield a sentinel with tools_used info
    if tools_used:
        yield ToolEvent(
            kind="tools_summary",
            tool="",
            call_id="",
            summary=json.dumps(tools_used),
        )
