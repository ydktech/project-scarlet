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
) -> Any:
    """Make a non-streaming LLM call with tools. Returns the ChatCompletion response."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_completion_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            tools=TOOL_SCHEMAS,
            stream=False,
        ),
    )


async def _stream_final_response(
    client: Cerebras,
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    """Stream the final LLM response (no tools) as text chunks."""
    loop = asyncio.get_event_loop()

    # Create streaming completion without tools
    stream = await loop.run_in_executor(
        None,
        lambda: client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_completion_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            stream=True,
        ),
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
            response = await _call_llm_non_streaming(client, work_messages)
        except Exception as e:
            log.error("LLM non-streaming call failed: %s", e)
            raise

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
    async for chunk in _stream_final_response(client, work_messages):
        yield chunk

    # Yield a sentinel with tools_used info
    if tools_used:
        yield ToolEvent(
            kind="tools_summary",
            tool="",
            call_id="",
            summary=json.dumps(tools_used),
        )
