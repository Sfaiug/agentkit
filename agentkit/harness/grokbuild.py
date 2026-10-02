"""Grok Build's launcher-issued conversation and its manually pinned session title."""

import json
import os
from pathlib import Path
from urllib.parse import quote

from . import LAUNCHER


def session_dir(cwd, conversation):
    home = Path(os.environ.get("GROK_HOME") or Path.home() / ".grok")
    return home / "sessions" / quote(str(cwd), safe="") / str(conversation)


def transcript(record, cwd, conversation):
    """The chat history the new orchestrator reads the last exchange from.

    Only where the harness has written one: a conversation nobody typed into has no
    file, and the handover says so instead of pointing at it.
    """
    where = cwd or record.get("cwd")
    if not conversation or not where:
        return None
    path = session_dir(where, conversation) / "chat_history.jsonl"
    return str(path) if path.exists() else None


def user_messages(record, cwd, conversation):
    """The durable UI record keeps prompts and times through model-context compaction."""
    from . import entries, user_message
    where = cwd or record.get("cwd")
    if not conversation or not where:
        return
    current, key = None, None
    for entry in entries(session_dir(where, conversation) / "updates.jsonl"):
        params = entry.get("params")
        params = params if isinstance(params, dict) else {}
        update = params.get("update")
        update = update if isinstance(update, dict) else {}
        meta = update.get("_meta")
        meta = meta if isinstance(meta, dict) else {}
        content = update.get("content")
        content = content if isinstance(content, dict) else {}
        human = (entry.get("method") == "session/update"
                 and params.get("sessionId") == conversation
                 and update.get("sessionUpdate") == "user_message_chunk"
                 and not meta.get("hostTurn"))
        chunk_key = (meta.get("promptIndex"), meta.get("interjection", False))
        if current and (not human or chunk_key != key or meta.get("interjection")):
            yield current
            current = None
        if not human or content.get("type") != "text":
            continue
        content_meta = content.get("_meta")
        content_meta = content_meta if isinstance(content_meta, dict) else {}
        if content_meta.get("bashCommand") is not None:
            continue
        text = content_meta.get("displayText", content.get("text"))
        kept = user_message(entry.get("timestamp"), text)
        if kept:
            if current:
                current["text"] += kept["text"]
            else:
                current, key = kept, chunk_key
    if current:
        yield current

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
