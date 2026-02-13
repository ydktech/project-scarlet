"""
Scarlett Maid-Bot — FastAPI Backend (SSE Streaming)

Usage:
    uv run server.py              # Start on localhost:8000
    uv run server.py --port 3000  # Custom port
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
import msgpack
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from scarlett.config import (
    ENV_PATH,
    MAX_HISTORY,
    MEMORY_PATH,
    MEM0_DB_PATH,
    MODEL,
    STATIC_DIR,
    USER_ID,
)
from scarlett.agent import ToolEvent, run_agent_loop
from scarlett.llm import create_client, stream_chat
from scarlett.memory import HyperMemory, try_extract_name
from scarlett.prompt import detect_expression, detect_mode, load_system_prompt
from scarlett.semantic import (
    get_all_memories,
    init_mem0,
    recall_memories,
    store_conversation,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("scarlett.server")

# ── Fish Audio TTS ─────────────────────────────────────
FISH_API_URL = "https://api.fish.audio/v1/tts"
FISH_VOICE_ID = "825c9e9870494118ad93b6853a22d5e7"

# ── Global session state (single-user) ────────────────
_session: dict[str, Any] = {}


def _init_session() -> None:
    """Initialize the global single-user session."""
    load_dotenv(ENV_PATH)
    cerebras_api_key = os.environ.get("CEREBRAS_API_KEY", "")
    disable_mem0 = os.environ.get("DISABLE_MEM0", "").strip().lower() in {"1", "true", "yes", "on"}

    client = create_client()
    memory = HyperMemory()
    memory.bump_session()

    mem0_memory = None
    if disable_mem0:
        log.info("mem0 disabled by DISABLE_MEM0")
    else:
        try:
            log.info("Initializing mem0...")
            mem0_memory = init_mem0(cerebras_api_key)
            log.info("mem0 ready")
        except Exception as e:
            log.warning("mem0 init failed: %s", e)

    system_prompt = load_system_prompt(memory)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    _session.update({
        "client": client,
        "memory": memory,
        "mem0_memory": mem0_memory,
        "messages": messages,
        "msg_count": 0,
        "current_mode": "angel",
        "current_expression": "neutral",
    })


def _friendly_stream_error(exc: Exception) -> str:
    text = str(exc)
    lower = text.lower()
    if "queue_exceeded" in lower or "too_many_requests_error" in lower:
        return (
            "Cerebras 쪽 혼잡으로 잠시 대기 중입니다. 잠시 후 다시 시도해 주세요. "
            "(provider queue_exceeded)"
        )
    if "503" in lower:
        return "LLM 공급자 상태가 일시적으로 불안정합니다. 잠시 후 다시 시도해 주세요."
    return text


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_session()
    yield
    # Cleanup: save memory on shutdown
    memory = _session.get("memory")
    mem0_memory = _session.get("mem0_memory")
    if memory:
        if mem0_memory:
            store_conversation(mem0_memory, _session.get("messages", []))
        memory.save()
        log.info("Memory saved on shutdown")


app = FastAPI(title="Scarlett Maid-Bot", lifespan=lifespan)


# ── Routes ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.post("/api/chat")
async def chat(request: Request):
    """SSE streaming chat endpoint."""
    body = await request.json()
    user_input = body.get("message", "").strip()
    if not user_input:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    client = _session["client"]
    memory: HyperMemory = _session["memory"]
    mem0_memory = _session["mem0_memory"]
    messages: list[dict] = _session["messages"]

    # Name extraction
    try_extract_name(user_input, memory)

    # Recall relevant memories
    recall_block = ""
    if mem0_memory:
        recall_block = await asyncio.to_thread(recall_memories, mem0_memory, user_input)

    # Build messages
    messages.append({"role": "user", "content": user_input})

    send_messages = list(messages)
    if recall_block:
        send_messages.insert(-1, {"role": "system", "content": recall_block})

    # Trim history
    if len(messages) > MAX_HISTORY * 2 + 1:
        if mem0_memory:
            old_messages = messages[1:-(MAX_HISTORY * 2)]
            await asyncio.to_thread(
                store_conversation, mem0_memory, old_messages, len(old_messages),
            )
        _session["messages"] = [messages[0]] + messages[-(MAX_HISTORY * 2):]
        messages = _session["messages"]

    async def event_generator():
        full_response = ""
        tools_used: list[str] = []
        try:
            async for item in run_agent_loop(client, send_messages):
                if isinstance(item, ToolEvent):
                    if item.kind == "tool_start":
                        yield {
                            "event": "tool_start",
                            "data": json.dumps({
                                "tool": item.tool,
                                "args": item.args,
                                "call_id": item.call_id,
                            }),
                        }
                    elif item.kind == "tool_done":
                        yield {
                            "event": "tool_done",
                            "data": json.dumps({
                                "tool": item.tool,
                                "call_id": item.call_id,
                                "summary": item.summary,
                            }),
                        }
                    elif item.kind == "llm_retry":
                        yield {
                            "event": "llm_retry",
                            "data": json.dumps({
                                "attempt": (item.args or {}).get("attempt"),
                                "max_retries": (item.args or {}).get("max_retries"),
                                "wait_seconds": (item.args or {}).get("wait_seconds"),
                                "error": (item.args or {}).get("error"),
                            }),
                        }
                    elif item.kind == "confirm_action":
                        yield {
                            "event": "confirm_action",
                            "data": json.dumps(item.args or {}),
                        }
                    elif item.kind == "tools_summary":
                        tools_used = json.loads(item.summary or "[]")
                else:
                    # str chunk from final streaming response
                    full_response += item
                    yield {"event": "token", "data": json.dumps({"token": item})}

            # Detect mode and expression
            mode = detect_mode(full_response)
            expression = detect_expression(full_response, mode)
            _session["current_mode"] = mode
            _session["current_expression"] = expression

            # Finalize
            if full_response:
                messages.append({"role": "assistant", "content": full_response})
                _session["msg_count"] += 1
                if mem0_memory and _session["msg_count"] % 10 == 0:
                    await asyncio.to_thread(store_conversation, mem0_memory, messages)

            done_data: dict[str, Any] = {
                "mode": mode,
                "expression": expression,
                "full_response": full_response,
            }
            if tools_used:
                done_data["tools_used"] = tools_used

            yield {
                "event": "done",
                "data": json.dumps(done_data),
            }

        except Exception as e:
            log.error("Stream error: %s", e)
            if not full_response:
                messages.pop()  # remove failed user message
            yield {"event": "error", "data": json.dumps({"error": _friendly_stream_error(e)})}

    return EventSourceResponse(event_generator())


@app.get("/api/status")
async def status():
    """Session status."""
    memory: HyperMemory = _session.get("memory")
    phase_names = {1: "\u89b3\u5bdf", 2: "\u8a8d\u5b9a", 3: "\u57f7\u7740", 4: "\u4fe1\u983c"}
    return {
        "model": MODEL,
        "mode": _session.get("current_mode", "angel"),
        "expression": _session.get("current_expression", "neutral"),
        "phase": memory.data["relationship_phase"] if memory else 1,
        "phase_name": phase_names.get(memory.data["relationship_phase"], "?") if memory else "?",
        "session_count": memory.data["session_count"] if memory else 0,
        "master_name": memory.data.get("master_name") if memory else None,
        "msg_count": _session.get("msg_count", 0),
        "has_mem0": _session.get("mem0_memory") is not None,
    }


@app.get("/api/memory")
async def get_memory():
    """Get metadata + semantic memories."""
    memory: HyperMemory = _session.get("memory")
    mem0_memory = _session.get("mem0_memory")

    result: dict[str, Any] = {}
    if memory:
        result["metadata"] = memory.data
    if mem0_memory:
        all_mems = await asyncio.to_thread(get_all_memories, mem0_memory)
        result["semantic"] = [
            m.get("memory", "") if isinstance(m, dict) else str(m)
            for m in all_mems if m
        ]
    else:
        result["semantic"] = []
    return result


@app.post("/api/memory/reset")
async def reset_memory():
    """Reset all memory."""
    memory: HyperMemory = _session.get("memory")
    mem0_memory = _session.get("mem0_memory")

    if memory:
        memory.data = dict(HyperMemory.DEFAULT)
        memory.save()
    if mem0_memory:
        try:
            await asyncio.to_thread(mem0_memory.delete_all, user_id=USER_ID)
        except Exception:
            pass

    # Reset conversation
    _session["messages"] = [{"role": "system", "content": load_system_prompt(memory)}]
    _session["msg_count"] = 0
    _session["current_mode"] = "angel"
    _session["current_expression"] = "neutral"

    return {"status": "reset"}


@app.post("/api/memory/save")
async def save_memory():
    """Manual save."""
    memory: HyperMemory = _session.get("memory")
    mem0_memory = _session.get("mem0_memory")
    messages = _session.get("messages", [])

    if mem0_memory:
        await asyncio.to_thread(store_conversation, mem0_memory, messages)
    if memory:
        memory.save()

    return {"status": "saved"}


@app.get("/api/memory/recall")
async def recall(q: str = Query(..., min_length=1)):
    """Semantic search."""
    mem0_memory = _session.get("mem0_memory")
    if not mem0_memory:
        return {"results": [], "error": "mem0 not active"}

    recalled = await asyncio.to_thread(recall_memories, mem0_memory, q)
    if recalled:
        lines = [l.lstrip("- ") for l in recalled.split("\n") if l.startswith("- ")]
        return {"results": lines}
    return {"results": []}


# ── Pending Action Confirmation ────────────────────────

@app.post("/api/confirm-action/{action_id}")
async def confirm_action(action_id: str):
    """Confirm and execute a pending action (e.g. calendar delete)."""
    from scarlett.tools import execute_pending_action
    result = await execute_pending_action(action_id)
    status_code = 200 if result.get("status") == "completed" else 400
    return JSONResponse(result, status_code=status_code)


@app.post("/api/cancel-action/{action_id}")
async def cancel_action_endpoint(action_id: str):
    """Cancel a pending action."""
    from scarlett.tools import cancel_pending_action
    return cancel_pending_action(action_id)


# ── TTS ────────────────────────────────────────────────

@app.post("/api/tts")
async def tts(request: Request):
    """Stream PCM audio from Fish Audio TTS for real-time playback."""
    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "Empty text"}, status_code=400)

    fish_key = os.environ.get("FISH_API_KEY", "")
    if not fish_key:
        return JSONResponse({"error": "FISH_API_KEY not set"}, status_code=500)

    if len(text) > 2000:
        text = text[:2000]

    payload = msgpack.packb({
        "text": text,
        "reference_id": FISH_VOICE_ID,
        "format": "mp3",
        "mp3_bitrate": 128,
        "latency": "balanced",
    })

    client = httpx.AsyncClient(timeout=60.0)
    try:
        resp = await client.send(
            client.build_request(
                "POST",
                FISH_API_URL,
                headers={
                    "Authorization": f"Bearer {fish_key}",
                    "Content-Type": "application/msgpack",
                    "model": "s1",
                },
                content=payload,
            ),
            stream=True,
        )
    except httpx.TimeoutException:
        await client.aclose()
        log.error("Fish TTS timeout")
        return JSONResponse({"error": "TTS request timed out"}, status_code=504)
    except Exception as e:
        await client.aclose()
        log.error("Fish TTS exception: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)

    if resp.status_code != 200:
        err_body = (await resp.aread()).decode(errors="replace")[:500]
        await resp.aclose()
        await client.aclose()
        log.error("Fish TTS error %s: %s", resp.status_code, err_body)
        return JSONResponse(
            {"error": f"Fish TTS returned {resp.status_code}"},
            status_code=502,
        )

    async def stream_audio():
        try:
            async for chunk in resp.aiter_bytes(chunk_size=8192):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(stream_audio(), media_type="audio/mpeg")


# Static files MUST be mounted after API routes
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Entry point ────────────────────────────────────────

def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Scarlett Maid-Bot Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
