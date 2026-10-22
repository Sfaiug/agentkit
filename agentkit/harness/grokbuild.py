"""Grok Build's shared settings, launcher-issued conversation, pinned session title and
the sessions nobody wrote to for 30 days."""

import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
from urllib.parse import quote

from .. import config
from . import LAUNCHER


def share_settings(usual, directory):
    """Keep credentials private while every login uses the usual user preferences.

    Grok Build 1.0.46's bundled Configuration guide names these two files. Its user
    config writer follows leaf symlinks, unlike its project config writer. Checked
    in a temporary HOME with user-scoped MCP saves, /vim-mode, and /settings'
    Respect manual folds toggle (which saves pager.toml): both links survive.
    """
    from ..config import _toml_key, _toml_value

    def fill(shared, own):
        changed = False
        for key, value in own.items():
            if key not in shared:
                shared[key] = value
                changed = True
            elif isinstance(shared[key], dict) and isinstance(value, dict):
                changed = fill(shared[key], value) or changed
        return changed

    usual, directory = Path(usual).resolve(), Path(directory)
    # Serialize first launches across logins without creating another state file.
    lock = os.open(usual, os.O_RDONLY)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for name in ("config.toml", "pager.toml"):
            source, link = usual / name, directory / name
            if link.is_symlink() and link.resolve() == source.resolve():
                continue
            if link.exists():
                own_text = link.read_text()
                own = tomllib.loads(own_text)
                target = source.resolve()
                if target.exists():
                    shared = tomllib.loads(target.read_text())
                    changed = fill(shared, own)
                    text = "".join(f"{_toml_key(key)} = {_toml_value(value)}\n"
                                   for key, value in shared.items()) if changed else None
                else:
                    text = own_text
                if text is not None:
                    tomllib.loads(text)
                    fd, temporary = tempfile.mkstemp(dir=target.parent)
                    temporary = Path(temporary)
                    try:
                        with os.fdopen(fd, "w") as handle:
                            handle.write(text)
                        if target.exists():
                            temporary.chmod(target.stat().st_mode & 0o777)
                        temporary.replace(target)
                    finally:
                        temporary.unlink(missing_ok=True)
            link.unlink(missing_ok=True)
            link.symlink_to(source)
    finally:
        os.close(lock)


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


def messages(record, cwd, conversation):
    """The durable UI record's messages, oldest first, as (who, {at, text}), chunks joined and
    host turns, shell commands and other updates left out; it outlives model-context compaction."""
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
        who = {"user_message_chunk": "user", "agent_message_chunk": "model"}.get(
            update.get("sessionUpdate"))
        spoken = (entry.get("method") == "session/update"
                  and params.get("sessionId") == conversation
                  and who and not meta.get("hostTurn"))
        chunk_key = (who, meta.get("promptIndex"), meta.get("interjection", False))
        if current and (not spoken or chunk_key != key or meta.get("interjection")):
            yield key[0], current
            current = None
        if not spoken or content.get("type") != "text":
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
        yield key[0], current


def user_messages(record, cwd, conversation):
    return (message for who, message in messages(record, cwd, conversation) if who == "user")


def said(record, cwd, conversation):
    """Read from the UI record, not chat_history.jsonl: that is the model's context, which a
    compaction rewrites and which wraps every prompt in tags of its own."""
    where = cwd or record.get("cwd")
    if not conversation or not where or not session_dir(where, conversation).is_dir():
        return None
    return [{"who": who, "text": message["text"]}
            for who, message in messages(record, cwd, conversation)]

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


def conversation_stores():
    """Each login home's own sessions folder, a folder per session under its url-encoded cwd:
    Grok ends none unless its owner sets `storage.cleanup_ttl_days`.  An account's home links
    its sessions to ~/.grok's unless Grok made the folder first; a linked one is scanned there."""
    from .. import gc
    # tmp_listdir, not glob: planning leaves HOME's atime alone.
    homes = [Path.home() / name for name in (".grok", *(name for name in gc.tmp_listdir(Path.home())
                                                        if name.startswith(".grok-")))]
    return [{"root": home / "sessions", "pattern": "*/*/"} for home in homes
            if not (home / "sessions").is_symlink()]


def end_conversation(path, ends):
    """`grok sessions delete`, which takes the session's folder and its session_search.sqlite
    row, run on the home that keeps it.  In 1.0.46 it needs no leader, login or answer, and
    takes none of the session's .lock files, so there is no lock to hold first; a session it
    cannot read it reports missing and exits 0, so a folder still there is a failure too."""
    folder = Path(path)
    if not ends():
        return
    subprocess.run([config.harness_binary("grok") or "grok", "sessions", "delete", folder.name],
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
                   env={**os.environ, "GROK_HOME": str(folder.parents[2])}, check=True)
    if folder.exists():
        raise OSError(f"grok sessions delete left {folder}")
