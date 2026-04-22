"""
One-off script: add ## TL;DR sections to concept files that are missing them.

For each concept file without ## TL;DR:
  - Extracts title + opening paragraph + Key Points section
  - Asks Claude for 3-5 distilled bullets
  - Inserts ## TL;DR between the opening paragraph and ## Key Points

Usage:
    uv run python scripts/backfill_tldr.py
    uv run python scripts/backfill_tldr.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
CONCEPTS_DIR = ROOT_DIR / "knowledge" / "concepts"


def get_files_missing_tldr() -> list[Path]:
    return [
        p for p in sorted(CONCEPTS_DIR.glob("*.md"))
        if "## TL;DR" not in p.read_text(encoding="utf-8")
    ]


def extract_context(content: str) -> str:
    """Pull title line, opening paragraph, and Key Points for the prompt."""
    lines = content.splitlines()
    # Skip frontmatter
    if lines and lines[0].strip() == "---":
        end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), None)
        lines = lines[end + 1:] if end is not None else lines

    # Collect up through ## Key Points (first 40 lines max keeps prompt tight)
    collected = []
    for line in lines[:60]:
        collected.append(line)
        if line.startswith("## Key Points"):
            # grab next 15 lines of bullets
            idx = lines.index(line)
            collected.extend(lines[idx + 1: idx + 16])
            break
    return "\n".join(collected).strip()


def insert_tldr(content: str, bullets: str) -> str:
    """Insert ## TL;DR section after the opening paragraph, before ## Key Points."""
    tldr_block = f"## TL;DR\n\n{bullets}\n\n"
    # Insert just before the first ## heading that isn't the title
    match = re.search(r"\n(## (?!TL;DR))", content)
    if match:
        pos = match.start() + 1  # keep the leading newline before ##
        return content[:pos] + tldr_block + content[pos:]
    # Fallback: append before end
    return content.rstrip() + "\n\n" + tldr_block


async def generate_tldr(context: str) -> str:
    from claude_agent_sdk import ClaudeAgentOptions, AssistantMessage, TextBlock, query

    prompt = f"""You are writing a ## TL;DR section for a knowledge base concept article.

Write exactly 3–5 bullet points that distill the actionable core of this article.
Rules:
- Each bullet must be self-contained (readable without the rest of the article)
- Lead with the key constraint, rule, or decision — not background
- Bold the most important term or phrase in each bullet
- No sub-bullets, no headers, no preamble

Output ONLY the bullet lines (starting with "- "), nothing else.

Article context:
{context}"""

    text = ""
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            cwd=str(ROOT_DIR),
            allowed_tools=[],
            max_turns=2,
        ),
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text += block.text

    # Normalise: keep only lines starting with "- "
    bullets = "\n".join(
        line for line in text.strip().splitlines()
        if line.strip().startswith("- ")
    )
    return bullets


async def main_async(dry_run: bool) -> None:
    files = get_files_missing_tldr()
    if not files:
        print("All concept files already have ## TL;DR. Nothing to do.")
        return

    print(f"{'[DRY RUN] ' if dry_run else ''}Files missing ## TL;DR: {len(files)}")
    for f in files:
        print(f"  - {f.name}")

    if dry_run:
        return

    print()
    total_cost = 0.0
    for i, path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {path.name} ...", end=" ", flush=True)
        content = path.read_text(encoding="utf-8")
        context = extract_context(content)
        try:
            bullets = await generate_tldr(context)
            if not bullets:
                print("SKIP (empty response)")
                continue
            updated = insert_tldr(content, bullets)
            path.write_text(updated, encoding="utf-8")
            print("done")
        except Exception as e:
            print(f"ERROR: {e}")

    print(f"\nBackfill complete. {len(files)} files updated.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill ## TL;DR into concept files")
    parser.add_argument("--dry-run", action="store_true", help="List files without modifying them")
    args = parser.parse_args()
    asyncio.run(main_async(args.dry_run))


if __name__ == "__main__":
    main()
