"""Grok Build's launcher-issued conversation and its manually pinned session title."""

import json
import os
from pathlib import Path
from urllib.parse import quote

from . import LAUNCHER


def session_dir(cwd, conversation):
    home = Path(os.environ.get("GROK_HOME") or Path.home() / ".grok")
    return home / "sessions" / quote(str(cwd), safe="") / str(conversation)


def opened(cwd, conversation):
    """Has Grok written that conversation down yet, where it keeps them?

    One directory per workspace under its sessions, named for the url-encoded working
    directory, each conversation a directory of its own inside it.  A directory that
    exists is resumed; one that does not is opened fresh under the same id, which is what
    `--session-id` demands: a valid UUID that does not already exist.
    """
    return session_dir(cwd, conversation).is_dir()


def title_command(name):
    return f"/rename {name}"


def title_ready(record, state):
    # A responding turn can queue input. Wait for the prompt, including our held line,
    # and for this conversation's summary to exist before touching the composer.
    return state in ("at_prompt", "draft") and session_title(record) is not None


def session_title(record):
    """Only a manual title in this conversation's summary can name or confirm the seat."""
    conversation, cwd = record.get("conversation"), record.get("cwd")
    if not conversation or not cwd or record.get("id_source") != LAUNCHER:
        return None
    try:
        data = json.loads((session_dir(cwd, conversation) / "summary.json").read_text(
            encoding="utf-8"))
        if data.get("info") != {"id": conversation, "cwd": str(cwd)}:
            return None
        if data.get("title_is_manual") is not True:
            return ""
        title = data.get("generated_title")
        return title if isinstance(title, str) and title.strip() else ""
    except (OSError, ValueError, AttributeError):
        return None
