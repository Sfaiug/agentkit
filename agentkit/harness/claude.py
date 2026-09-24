"""Claude Code: a launcher-issued conversation, and the transcript it writes for it.

Everything else about this harness is data -- adapters/claude.sh and adapters/claude.toml --
so the one hook here is the one thing that needs a path rule: where its transcripts live.
"""

from pathlib import Path
import re


def opened(cwd, conversation):
    """Has Claude Code written that conversation down yet, where it keeps them?

    Its directory per workspace: every character that is not a letter or a digit becomes a
    dash, and each transcript is named for the session it holds.  Claude Code writes the
    transcript at the first message and not at the prompt, so a seat nobody typed into has
    nothing to resume, and `--resume` on it is an error rather than a conversation.
    """
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    return (Path.home() / ".claude" / "projects" / slug / f"{conversation}.jsonl").exists()
