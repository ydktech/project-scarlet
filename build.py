"""
Scarlett Prompt Builder
Assembles modular prompt files into a single system prompt.

Usage:
    uv run build.py              # Build with default config
    uv run build.py --stats      # Build and show token/char stats
    uv run build.py --dry-run    # Preview without writing output
    uv run build.py --out FILE   # Custom output path
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).parent
DEFAULT_CONFIG = ROOT / "config.toml"
DEFAULT_OUTPUT = ROOT / "setting.txt"
MODULES_DIR = ROOT / "modules"

SEPARATOR = "\n\n---\n\n"


def load_config(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def resolve_modules(config: dict) -> list[Path]:
    """Resolve enabled modules in order from config."""
    modules_cfg = config.get("modules", {})
    order: list[str] = modules_cfg.get("order", [])
    disabled: set[str] = set(modules_cfg.get("disabled", []))

    resolved = []
    for name in order:
        if name in disabled:
            continue
        path = MODULES_DIR / name
        if not path.exists():
            print(f"  ⚠ Module not found, skipping: {name}", file=sys.stderr)
            continue
        resolved.append(path)

    return resolved


def auto_discover_modules() -> list[Path]:
    """Fallback: discover all .md files in modules/ sorted by name."""
    if not MODULES_DIR.exists():
        return []
    return sorted(MODULES_DIR.glob("*.md"))


def assemble(modules: list[Path], header: str | None = None) -> str:
    """Read and concatenate module files."""
    parts: list[str] = []

    if header:
        parts.append(header)

    for mod in modules:
        content = mod.read_text(encoding="utf-8").strip()
        if content:
            parts.append(content)

    return SEPARATOR.join(parts)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (chars / 3.5 for mixed KR/EN content)."""
    return int(len(text) / 3.5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scarlett Prompt Builder")
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG, help="Config file path"
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Output file path"
    )
    parser.add_argument(
        "--stats", action="store_true", help="Show token/character statistics"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without writing"
    )
    parser.add_argument(
        "--list", action="store_true", dest="list_modules", help="List modules and exit"
    )
    args = parser.parse_args()

    # Load config
    if args.config.exists():
        config = load_config(args.config)
    else:
        config = {}
        print(f"  ⚠ Config not found at {args.config}, using auto-discovery", file=sys.stderr)

    # Resolve output path
    output_path = args.out or Path(config.get("build", {}).get("output", str(DEFAULT_OUTPUT)))

    # Resolve header
    prompt_cfg = config.get("prompt", {})
    version = prompt_cfg.get("version", "3.0")
    codename = prompt_cfg.get("codename", "Ghost in the Kujou")
    header = f"# 「Kujou Scarlett」 — Personal Maid-Bot System Prompt\n# Version {version} | Codename: {codename}"

    # Resolve modules
    if config.get("modules", {}).get("order"):
        modules = resolve_modules(config)
    else:
        modules = auto_discover_modules()

    if not modules:
        print("  ✗ No modules found.", file=sys.stderr)
        sys.exit(1)

    # List mode
    if args.list_modules:
        disabled = set(config.get("modules", {}).get("disabled", []))
        print(f"\n  Modules ({len(modules)} enabled):\n")
        for mod in modules:
            status = "✗ DISABLED" if mod.name in disabled else "✓"
            lines = len(mod.read_text(encoding="utf-8").splitlines())
            print(f"    {status} {mod.name:<25} ({lines} lines)")
        print()
        return

    # Assemble
    result = assemble(modules, header=header)

    # Stats
    chars = len(result)
    lines = result.count("\n") + 1
    tokens_est = estimate_tokens(result)

    print(f"\n  ╔══════════════════════════════════════╗")
    print(f"  ║   Scarlett Prompt Builder v{version:<10}║")
    print(f"  ╚══════════════════════════════════════╝\n")
    print(f"  Modules:  {len(modules)} loaded")
    for mod in modules:
        print(f"            ├─ {mod.name}")
    print(f"  Lines:    {lines}")
    print(f"  Chars:    {chars:,}")
    print(f"  Tokens:   ~{tokens_est:,} (estimated)")
    print()

    if args.dry_run:
        print("  [DRY RUN] No file written.\n")
        if args.stats:
            print(result[:500] + "\n  ...")
        return

    # Write output
    output_path.write_text(result, encoding="utf-8")
    print(f"  ✓ Written to: {output_path}\n")


if __name__ == "__main__":
    main()
