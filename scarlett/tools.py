"""Tool schemas (OpenAI function-calling format) and execution dispatcher."""

from __future__ import annotations

import ast
import logging
import math
import operator
import os
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx

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
