# Project Scarlet

Personal AI assistant built on Cerebras inference engine running Qwen3-235B with an agentic tool-calling system.

## Structure

```
scarlett/
  config.py      # Constants and paths
  llm.py         # Cerebras LLM client (streaming)
  agent.py       # Agent loop (tool detection → execution → final response)
  tools.py       # Tool schemas + executors (web_search, fetch_url, calculate, get_current_time)
  memory.py      # L3 metadata store (sessions, relationship phase)
  semantic.py    # mem0 semantic memory (vector search)
  prompt.py      # System prompt loader + mode/expression detection
modules/         # System prompt modules (.md)
server.py        # FastAPI backend (SSE streaming, TTS)
static/          # Frontend (single HTML)
build.py         # Prompt builder (modules/ → setting.txt)
```

## Features

- **Agentic tool calling** — Web search (Tavily), URL fetching, calculator, current time
- **3-tier memory** — Session history / JSON metadata / Vector DB semantic memory
- **Real-time SSE streaming** — Token-by-token typewriter effect
- **TTS** — Fish Audio API speech synthesis with sentence-level prefetch playback
- **Dual personality mode** — Angel / Psycho, keyword-triggered auto-switching with UI reflection

## Getting Started

```bash
cp .env.example .env
# Fill in your API keys in .env

uv sync
uv run python build.py   # Build system prompt
uv run server.py          # localhost:8000
```

## Required API Keys

| Key | Purpose | Provider |
|-----|---------|----------|
| `CEREBRAS_API_KEY` | LLM inference | [cerebras.ai](https://cerebras.ai) |
| `FISH_API_KEY` | TTS speech synthesis | [fish.audio](https://fish.audio) |
| `TAVILY_API_KEY` | Web search tool | [tavily.com](https://tavily.com) |
