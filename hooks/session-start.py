"""
SessionStart hook - injects knowledge base context into every conversation.

This is the "context injection" layer. When Claude Code starts a session,
this hook reads the knowledge base index and recent daily log, then injects
them as additional context so Claude always "remembers" what it has learned.

Configure in .claude/settings.json:
{
    "hooks": {
        "SessionStart": [{
            "matcher": "",
            "command": "uv run python hooks/session-start.py"
        }]
    }
}
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Paths relative to project root
ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge"
DAILY_DIR = ROOT / "daily"
INDEX_FILE = KNOWLEDGE_DIR / "index.md"

# KIT-PATCH: also inject the wiki's static memory layer + recent wiki/log.md events.
# This compiler is bundled inside integrations-wiki, so ROOT.parent is the wiki root
# and `memory/MEMORY.md` + `wiki/log.md` live there.
WIKI_ROOT = ROOT.parent
WIKI_MEMORY_INDEX = WIKI_ROOT / "memory" / "MEMORY.md"
WIKI_ACTIVITY_LOG = WIKI_ROOT / "wiki" / "log.md"
WIKI_LOG_TAIL_LINES = 40

MAX_CONTEXT_CHARS = 20_000
MAX_LOG_LINES = 30


def get_recent_log() -> str:
    """Read the most recent daily log (today or yesterday)."""
    today = datetime.now(timezone.utc).astimezone()

    for offset in range(2):
        date = today - timedelta(days=offset)
        log_path = DAILY_DIR / f"{date.strftime('%Y-%m-%d')}.md"
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8").splitlines()
            # Return last N lines to keep context small
            recent = lines[-MAX_LOG_LINES:] if len(lines) > MAX_LOG_LINES else lines
            return "\n".join(recent)

    return "(no recent daily log)"


def build_context() -> str:
    """Assemble the context to inject into the conversation."""
    parts = []

    # Today's date
    today = datetime.now(timezone.utc).astimezone()
    parts.append(f"## Today\n{today.strftime('%A, %B %d, %Y')}")

    # KIT-PATCH: wiki's static memory layer (always loaded; complements the
    # compiler's accumulated knowledge layer). This is the human-authored seed
    # (feedback rules, user/project/reference memories) that sits alongside the
    # auto-grown knowledge base.
    if WIKI_MEMORY_INDEX.exists():
        wiki_memory = WIKI_MEMORY_INDEX.read_text(encoding="utf-8")
        parts.append(f"## Wiki Memory (static)\n\n{wiki_memory}")

    # Knowledge base index (the core retrieval mechanism)
    if INDEX_FILE.exists():
        index_content = INDEX_FILE.read_text(encoding="utf-8")
        parts.append(f"## Knowledge Base Index\n\n{index_content}")
    else:
        parts.append("## Knowledge Base Index\n\n(empty - no articles compiled yet)")

    # Recent daily log
    recent_log = get_recent_log()
    parts.append(f"## Recent Daily Log\n\n{recent_log}")

    # KIT-PATCH: tail of the wiki's activity log (wiki/log.md) — recent
    # ingest/query events, including survey-trail / negative-provenance lines.
    if WIKI_ACTIVITY_LOG.exists():
        try:
            log_lines = WIKI_ACTIVITY_LOG.read_text(encoding="utf-8").splitlines()
            tail = "\n".join(log_lines[-WIKI_LOG_TAIL_LINES:])
            parts.append(f"## Wiki Activity Log (recent)\n\n{tail}")
        except Exception:
            pass

    context = "\n\n---\n\n".join(parts)

    # Truncate if too long
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n\n...(truncated)"

    return context


def main():
    context = build_context()

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }

    print(json.dumps(output))


if __name__ == "__main__":
    main()
