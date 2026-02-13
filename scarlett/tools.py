"""Tool schemas (OpenAI function-calling format) and execution dispatcher."""

from __future__ import annotations

import asyncio
import ast
import json
import logging
import math
import operator
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import httpx

from .config import (
    GOOGLE_CAL_SCOPES,
    GOOGLE_CAL_TOKEN_PATH,
    GOOGLE_OAUTH_CLIENT_SECRET_PATH,
    ROOT,
)

log = logging.getLogger("scarlett.tools")

# ── OpenAI function-calling schemas ───────────────────

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information using Tavily. Use when the user asks about recent events, news, facts you're unsure of, or anything requiring up-to-date information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch and read the text content of a URL. Use when the user shares a link or asks about a specific webpage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch",
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "Maximum characters to return (default 5000)",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current date and time. Use when the user asks about the current time, date, or day of the week.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "Timezone as UTC offset like '+09:00' for JST/KST, '+00:00' for UTC. Default is '+09:00'.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a mathematical expression safely. Use when the user asks for calculations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Math expression to evaluate, e.g. '1024 * 768', 'sqrt(144)', '2**10'",
                    },
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_calendar_events",
            "description": "Read upcoming events from Google Calendar. Use when the user asks about schedule, appointments, or upcoming plans. Returns event IDs that can be used with delete_calendar_event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "How many days to look ahead from now. Default 7.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of events to return. Default 10.",
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Google Calendar ID. Default is 'primary'.",
                    },
                    "start_offset_days": {
                        "type": "integer",
                        "description": "Start offset in days from now. Use 1 for tomorrow.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_calendar_event",
            "description": (
                "Request deletion of a Google Calendar event. "
                "IMPORTANT: This tool does NOT delete immediately — it queues a deletion request "
                "that Master must confirm or deny via the UI. You MUST first use get_calendar_events "
                "to look up the event ID before calling this tool. "
                "NEVER call this tool without Master explicitly asking to delete an event."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "The Google Calendar event ID to delete (from get_calendar_events output).",
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Google Calendar ID. Default is 'primary'.",
                    },
                },
                "required": ["event_id"],
            },
        },
    },
]


# ── Tool execution dispatcher ─────────────────────────

async def execute_tool(name: str, args: dict[str, Any]) -> str:
    """Dispatch a tool call and return its result as a string."""
    try:
        if name == "web_search":
            return await _web_search(args.get("query", ""))
        elif name == "fetch_url":
            return await _fetch_url(args.get("url", ""), args.get("max_length", 5000))
        elif name == "get_current_time":
            return _get_current_time(args.get("timezone", "+09:00"))
        elif name == "calculate":
            return _calculate(args.get("expression", ""))
        elif name == "get_calendar_events":
            return await _get_calendar_events(
                days=args.get("days", 7),
                max_results=args.get("max_results", 10),
                calendar_id=args.get("calendar_id", "primary"),
                start_offset_days=args.get("start_offset_days", 0),
            )
        elif name == "delete_calendar_event":
            return await _delete_calendar_event(
                event_id=args.get("event_id", ""),
                calendar_id=args.get("calendar_id", "primary"),
            )
        else:
            return f"Unknown tool: {name}"
    except Exception as e:
        log.error("Tool %s error: %s", name, e)
        return f"Error executing {name}: {e}"


# ── Individual tool implementations ───────────────────

async def _web_search(query: str) -> str:
    """Search the web using Tavily REST API."""
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return "Error: TAVILY_API_KEY is not set."
    if not query.strip():
        return "Error: Empty search query."

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": 5,
                "include_answer": True,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    parts: list[str] = []

    answer = data.get("answer")
    if answer:
        parts.append(f"Summary: {answer}")

    for r in data.get("results", [])[:5]:
        title = r.get("title", "")
        url = r.get("url", "")
        snippet = r.get("content", "")[:200]
        parts.append(f"- [{title}]({url}): {snippet}")

    return "\n".join(parts) if parts else "No results found."


async def _fetch_url(url: str, max_length: int = 5000) -> str:
    """Fetch a URL and extract readable text using BeautifulSoup."""
    if not url.strip():
        return "Error: Empty URL."

    from bs4 import BeautifulSoup

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ScarletBot/1.0)"},
        )
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove scripts, styles, navs
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    if len(text) > max_length:
        text = text[:max_length] + "\n...(truncated)"

    return text if text else "No readable content found."


def _resolve_google_client_secret_path() -> Path | None:
    """Resolve OAuth client secret path from env or project root."""
    if GOOGLE_OAUTH_CLIENT_SECRET_PATH:
        p = Path(GOOGLE_OAUTH_CLIENT_SECRET_PATH).expanduser()
        if p.exists():
            return p
    candidates = sorted(ROOT.glob("client_secret_*.json"))
    return candidates[0] if candidates else None


def _format_calendar_dt(start: dict[str, Any]) -> str:
    """Format calendar datetime/date fields for output."""
    dt = start.get("dateTime")
    d = start.get("date")
    if dt:
        try:
            parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            return parsed.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return dt
    if d:
        return f"{d} (all-day)"
    return "unknown time"


def _get_calendar_service():
    """Get authenticated Google Calendar service (shared by read/delete)."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    scopes = list(GOOGLE_CAL_SCOPES)
    token_path = GOOGLE_CAL_TOKEN_PATH
    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        except Exception:
            creds = None

    # Force re-auth if token scopes don't include required scope
    if creds and creds.scopes:
        if not set(scopes).issubset(set(creds.scopes)):
            log.info("Calendar token scope mismatch, re-authenticating")
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                log.warning("Token refresh failed, will re-authenticate")
                creds = None
        if not creds:
            secret_path = _resolve_google_client_secret_path()
            if not secret_path:
                raise RuntimeError(
                    "OAuth client secret file not found. "
                    "Set GOOGLE_OAUTH_CLIENT_SECRET_PATH or place client_secret_*.json in project root."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), scopes)
            creds = flow.run_local_server(port=0, open_browser=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _get_calendar_events_sync(
    *,
    days: int = 7,
    max_results: int = 10,
    calendar_id: str = "primary",
    start_offset_days: int = 0,
) -> str:
    """Read events from Google Calendar."""
    try:
        service = _get_calendar_service()
    except ImportError:
        return "Error: Google Calendar dependencies are missing. Run dependency sync first."
    except Exception as e:
        return f"Error: {e}"

    days = max(1, min(int(days), 31))
    max_results = max(1, min(int(max_results), 50))
    start_offset_days = max(-7, min(int(start_offset_days), 365))

    now = datetime.now(timezone.utc) + timedelta(days=start_offset_days)
    end = now + timedelta(days=days)

    result = service.events().list(
        calendarId=calendar_id or "primary",
        timeMin=now.isoformat(),
        timeMax=end.isoformat(),
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = result.get("items", [])
    if not events:
        return f"No events found in the next {days} day(s)."

    lines = [f"Upcoming events ({len(events)}):"]
    for ev in events:
        when = _format_calendar_dt(ev.get("start", {}))
        title = ev.get("summary", "(no title)")
        event_id = ev.get("id", "")
        location = ev.get("location")
        parts = [f"- [{event_id}] {when} | {title}"]
        if location:
            parts[0] += f" @ {location}"
        lines.append(parts[0])
    return "\n".join(lines)


async def _get_calendar_events(
    *,
    days: int = 7,
    max_results: int = 10,
    calendar_id: str = "primary",
    start_offset_days: int = 0,
) -> str:
    """Async wrapper for Google Calendar read."""
    return await asyncio.to_thread(
        _get_calendar_events_sync,
        days=days,
        max_results=max_results,
        calendar_id=calendar_id,
        start_offset_days=start_offset_days,
    )


# ── Calendar deletion (pending-action pattern) ──────

_pending_actions: dict[str, dict[str, Any]] = {}


def _delete_calendar_event_sync(event_id: str, calendar_id: str = "primary") -> str:
    """Look up event and create a pending deletion (requires user confirmation)."""
    if not event_id.strip():
        return json.dumps({"status": "error", "message": "Event ID is required."})

    try:
        service = _get_calendar_service()
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

    try:
        event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Event not found: {e}"})

    title = event.get("summary", "(no title)")
    event_time = _format_calendar_dt(event.get("start", {}))

    action_id = uuid.uuid4().hex[:8]
    _pending_actions[action_id] = {
        "type": "delete_calendar_event",
        "event_id": event_id,
        "calendar_id": calendar_id,
        "title": title,
        "time": event_time,
    }

    return json.dumps({
        "status": "pending_confirmation",
        "action_id": action_id,
        "title": title[:50],
        "time": event_time,
    }, ensure_ascii=False)


async def _delete_calendar_event(event_id: str, calendar_id: str = "primary") -> str:
    """Async wrapper for calendar delete."""
    return await asyncio.to_thread(_delete_calendar_event_sync, event_id, calendar_id)


def execute_pending_action_sync(action_id: str) -> dict[str, Any]:
    """Execute a confirmed pending action. Called from server endpoint."""
    action = _pending_actions.pop(action_id, None)
    if not action:
        return {"status": "error", "message": "Action not found or already executed."}

    if action["type"] == "delete_calendar_event":
        try:
            service = _get_calendar_service()
            service.events().delete(
                calendarId=action["calendar_id"],
                eventId=action["event_id"],
            ).execute()
            return {
                "status": "completed",
                "message": f"'{action['title']}' 이벤트가 삭제되었습니다.",
            }
        except Exception as e:
            error_msg = str(e)
            if "403" in error_msg or "insufficient" in error_msg.lower():
                return {
                    "status": "error",
                    "message": (
                        "캘린더 쓰기 권한이 없습니다. "
                        f"'{GOOGLE_CAL_TOKEN_PATH}' 파일을 삭제 후 다시 인증해주세요."
                    ),
                }
            return {"status": "error", "message": f"삭제 실패: {e}"}

    return {"status": "error", "message": f"Unknown action type: {action['type']}"}


async def execute_pending_action(action_id: str) -> dict[str, Any]:
    """Async wrapper for pending action execution."""
    return await asyncio.to_thread(execute_pending_action_sync, action_id)


def cancel_pending_action(action_id: str) -> dict[str, Any]:
    """Cancel a pending action."""
    action = _pending_actions.pop(action_id, None)
    if action:
        return {"status": "cancelled", "message": f"'{action.get('title', '')}' 삭제가 취소되었습니다."}
    return {"status": "error", "message": "Action not found or already executed."}


def _get_current_time(tz_str: str = "+09:00") -> str:
    """Return the current date/time in the given UTC offset."""
    try:
        # Parse offset string like "+09:00" or "-05:00"
        sign = 1 if tz_str.startswith("+") else -1
        parts = tz_str.lstrip("+-").split(":")
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
        offset = timedelta(hours=sign * hours, minutes=sign * minutes)
        tz = timezone(offset)
    except (ValueError, IndexError):
        tz = timezone(timedelta(hours=9))  # Default to JST/KST

    now = datetime.now(tz)
    return now.strftime(f"%Y-%m-%d %H:%M:%S (UTC{tz_str}) %A")


# ── Sandboxed math evaluator ─────────────────────────

_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_SAFE_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "pi": math.pi,
    "e": math.e,
    "ceil": math.ceil,
    "floor": math.floor,
    "factorial": math.factorial,
}


def _safe_eval(node: ast.AST) -> float | int:
    """Recursively evaluate an AST node with only safe operations."""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant: {node.value!r}")
    elif isinstance(node, ast.BinOp):
        op = _SAFE_OPERATORS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        # Guard against excessively large exponents
        if isinstance(node.op, ast.Pow) and isinstance(right, (int, float)) and right > 10000:
            raise ValueError("Exponent too large")
        return op(left, right)
    elif isinstance(node, ast.UnaryOp):
        op = _SAFE_OPERATORS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op(_safe_eval(node.operand))
    elif isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in _SAFE_FUNCTIONS:
            fn = _SAFE_FUNCTIONS[node.func.id]
            if callable(fn):
                args = [_safe_eval(a) for a in node.args]
                return fn(*args)
            return fn  # constants like pi, e
        raise ValueError(f"Unsupported function: {ast.dump(node.func)}")
    elif isinstance(node, ast.Name):
        if node.id in _SAFE_FUNCTIONS:
            val = _SAFE_FUNCTIONS[node.id]
            if not callable(val):
                return val  # constants
        raise ValueError(f"Unsupported name: {node.id}")
    else:
        raise ValueError(f"Unsupported expression: {type(node).__name__}")


def _calculate(expression: str) -> str:
    """Safely evaluate a math expression."""
    if not expression.strip():
        return "Error: Empty expression."

    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _safe_eval(tree)
        return f"{expression.strip()} = {result}"
    except Exception as e:
        return f"Error evaluating '{expression}': {e}"
