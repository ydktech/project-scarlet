"""
Scarlett Maid-Bot — CLI Client (Rich TUI)

Usage:
    uv run cli.py                # Start chat
    uv run cli.py --no-memory    # Start without HyperMemory
    uv run cli.py --reset        # Reset memory and start fresh
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from scarlett.config import MAX_HISTORY, MEMORY_PATH, MEM0_DB_PATH, MODEL
from scarlett.llm import create_client, stream_chat
from scarlett.memory import HyperMemory, try_extract_name
from scarlett.prompt import load_system_prompt
from scarlett.semantic import (
    get_all_memories,
    init_mem0,
    recall_memories,
    store_conversation,
)

console = Console()


def print_banner(memory: HyperMemory | None, has_mem0: bool = False) -> None:
    banner = Text()
    banner.append("\u300cKujou Scarlett\u300d", style="bold red")
    banner.append(" \u2014 Personal Maid-Bot\n", style="dim")
    banner.append(f"  Model: {MODEL}\n", style="dim")
    if memory:
        phase_names = {1: "\u89b3\u5bdf", 2: "\u8a8d\u5b9a", 3: "\u57f7\u7740", 4: "\u4fe1\u983c"}
        phase = memory.data["relationship_phase"]
        sessions = memory.data["session_count"]
        banner.append(
            f"  Memory: ON (Phase {phase}: {phase_names.get(phase, '?')}, {sessions} sessions)\n",
            style="dim cyan",
        )
        if has_mem0:
            banner.append("  mem0: ON (semantic memory active)\n", style="dim cyan")
        if memory.data.get("master_name"):
            banner.append(f"  Master: {memory.data['master_name']}\n", style="dim cyan")
    else:
        banner.append("  Memory: OFF\n", style="dim yellow")
    banner.append("\n  Commands: /quit /reset /memory /save /recall <query>", style="dim")
    console.print(Panel(banner, border_style="red", padding=(1, 2)))


def run_chat(use_memory: bool = True) -> None:
    client = create_client()

    # Memory systems
    memory = HyperMemory() if use_memory else None
    mem0_memory = None

    if use_memory and memory:
        memory.bump_session()
        try:
            console.print("[dim]  Initializing mem0 (first run downloads embedder model ~80MB)...[/dim]")
            import os
            mem0_memory = init_mem0(os.environ.get("CEREBRAS_API_KEY", ""))
            console.print("[dim green]  mem0 ready.[/dim green]")
        except Exception as e:
            console.print(f"[dim yellow]  mem0 init failed: {e}[/dim yellow]")
            console.print("[dim yellow]  Continuing without semantic memory.[/dim yellow]")

    # System prompt
    system_prompt = load_system_prompt(memory)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    print_banner(memory, has_mem0=mem0_memory is not None)
    console.print()

    msg_count = 0

    while True:
        try:
            user_input = console.input("[bold white]Master > [/bold white]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n")
            user_input = "/quit"

        if not user_input:
            continue

        # ── Commands ────────────────────────────────
        if user_input.startswith("/"):
            cmd_parts = user_input.split(maxsplit=1)
            cmd = cmd_parts[0].lower()

            if cmd == "/quit":
                if memory:
                    if mem0_memory:
                        console.print("[dim]  Storing conversation to mem0...[/dim]")
                        store_conversation(mem0_memory, messages)
                    memory.save()
                    console.print("[dim green]  Memory saved.[/dim green]")
                console.print("[dim red]  Scarlett disconnected.[/dim red]\n")
                break

            elif cmd == "/reset":
                if memory:
                    memory.data = dict(HyperMemory.DEFAULT)
                    memory.save()
                    console.print("[dim yellow]  Metadata memory reset.[/dim yellow]")
                if mem0_memory:
                    try:
                        from scarlett.config import USER_ID
                        mem0_memory.delete_all(user_id=USER_ID)
                        console.print("[dim yellow]  Semantic memory cleared.[/dim yellow]")
                    except Exception:
                        pass
                messages = [{"role": "system", "content": load_system_prompt(memory)}]
                console.print("[dim yellow]  Conversation cleared.[/dim yellow]")
                continue

            elif cmd == "/memory":
                if memory:
                    console.print(Panel(
                        json.dumps(memory.data, ensure_ascii=False, indent=2),
                        title="HyperMemory \u2014 L3 Metadata",
                        border_style="cyan",
                    ))
                if mem0_memory:
                    all_mems = get_all_memories(mem0_memory)
                    if all_mems:
                        mem_lines = []
                        for m in all_mems:
                            text = m.get("memory", "") if isinstance(m, dict) else str(m)
                            if text:
                                mem_lines.append(f"  \u00b7 {text}")
                        console.print(Panel(
                            "\n".join(mem_lines) if mem_lines else "(empty)",
                            title=f"mem0 \u2014 Semantic Memories ({len(mem_lines)})",
                            border_style="magenta",
                        ))
                    else:
                        console.print("[dim]  No semantic memories stored yet.[/dim]")
                continue

            elif cmd == "/save":
                if mem0_memory:
                    store_conversation(mem0_memory, messages)
                    console.print("[dim green]  Conversation stored to mem0.[/dim green]")
                if memory:
                    memory.save()
                    console.print("[dim green]  Metadata saved.[/dim green]")
                continue

            elif cmd == "/recall":
                query = cmd_parts[1] if len(cmd_parts) > 1 else ""
                if not query:
                    console.print("[dim]  Usage: /recall <query>[/dim]")
                    continue
                if mem0_memory:
                    recalled = recall_memories(mem0_memory, query)
                    if recalled:
                        console.print(Panel(recalled, title="Recalled Memories", border_style="magenta"))
                    else:
                        console.print("[dim]  No relevant memories found.[/dim]")
                else:
                    console.print("[dim yellow]  mem0 not active.[/dim yellow]")
                continue

            else:
                console.print(f"[dim]  Unknown command: {cmd}[/dim]")
                continue

        # ── Name extraction ────────────────────────
        if memory:
            try_extract_name(user_input, memory)

        # ── Recall relevant memories for context ───
        recall_block = ""
        if mem0_memory:
            recall_block = recall_memories(mem0_memory, user_input)

        # ── Build messages with memory context ─────
        messages.append({"role": "user", "content": user_input})

        send_messages = list(messages)
        if recall_block:
            send_messages.insert(-1, {"role": "system", "content": recall_block})

        # Trim history
        if len(messages) > MAX_HISTORY * 2 + 1:
            if mem0_memory:
                old_messages = messages[1:-(MAX_HISTORY * 2)]
                store_conversation(mem0_memory, old_messages, turn_count=len(old_messages))
            messages = [messages[0]] + messages[-(MAX_HISTORY * 2):]

        # ── Stream response ────────────────────────
        console.print()
        console.print("[bold red]Scarlett > [/bold red]", end="")

        full_response = ""
        try:
            for chunk in stream_chat(client, send_messages):
                console.print(chunk, end="", highlight=False)
                full_response += chunk
        except Exception as e:
            console.print(f"\n[red]  Error: {e}[/red]\n")
            if not full_response:
                messages.pop()  # remove failed user message
            else:
                messages.append({"role": "assistant", "content": full_response})
            continue

        console.print("\n")

        if full_response:
            messages.append({"role": "assistant", "content": full_response})
            msg_count += 1
            if mem0_memory and msg_count % 10 == 0:
                store_conversation(mem0_memory, messages)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scarlett Maid-Bot Chat")
    parser.add_argument("--no-memory", action="store_true", help="Disable all memory")
    parser.add_argument("--reset", action="store_true", help="Reset all memory and start fresh")
    args = parser.parse_args()

    if args.reset:
        if MEMORY_PATH.exists():
            MEMORY_PATH.unlink()
        if MEM0_DB_PATH.exists():
            shutil.rmtree(MEM0_DB_PATH, ignore_errors=True)
        console.print("[dim yellow]  All memory cleared.[/dim yellow]")

    run_chat(use_memory=not args.no_memory)


if __name__ == "__main__":
    main()
