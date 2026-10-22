"""OpenCode: the session a seat's own plugin reported, kept in a receipt of that launch's own.

Everything else about this harness is data -- adapters/opencode.sh and adapters/opencode.toml.
Its TUI cannot be told the id of a session it has not opened yet, so a seat's conversation is
learned rather than issued: every launch gets a receipt, a directory named in its environment,
and hooks/opencode-seat writes into it the id OpenCode made for the session that seat is talking
in -- whole, renamed over the last one, so an interrupted write leaves the last good id.  The
receipt's token is kept in the seat's record, so it follows a rename, and no other seat -- not
one in the same directory -- reads or writes it.  Nothing here asks which session of a
directory is the latest.

OpenCode ends no session, and keeps each as rows of its database: gc ends a top-level one
nobody updated for 30 days with OpenCode's own delete, which takes its children along.

How MiMo is paid is learned from where OpenCode's own global config sends it: that outranks
whatever mode agentkit's config was given, and anything short of a plain token-plan URL is payg.
"""

import json
import os
import re
import shutil
import subprocess
import urllib.parse
import uuid
from pathlib import Path

from .. import config

RECEIPT_ENV = "AGENTKIT_OPENCODE_RECEIPT"
SESSION = re.compile(r"ses_[0-9A-Za-z]+")     # OpenCode's own: `ses_` and its id, never a flag
PLAN_HOST = re.compile(r"token-plan[\w-]*\.xiaomimimo\.com")   # MiMo's token plan, per region


def path_for(record):
    token = record.get("opencode_launch")
    if isinstance(token, str) and re.fullmatch(r"[0-9a-f]{32}", token):
        return config.STATE / f"opencode-launch-{token}"
    return None


def conversation(record, cwd=None):
    """The session this seat's launch reported, or None where it reported none yet."""
    path = path_for(record)
    try:
        sid = (path / "session").read_text(encoding="utf-8").strip() if path else ""
    except OSError:
        return None
    return sid if SESSION.fullmatch(sid) else None


def resumable(record, cwd, conversation):
    """The receipt is the whole answer: the launcher never issues an OpenCode id."""
    return bool(conversation)


def forget(record):
    """Remove that launch's receipt, moved aside first: a write the plugin has in flight then
    finds no directory to land in, and cannot leave one behind half removed."""
    path = path_for(record)
    if path:
        gone = path.with_name(f"{path.name}.gone")
        try:
            path.rename(gone)
        except OSError:
            return
        shutil.rmtree(gone, ignore_errors=True)


retire = forget   # the receipt is all a seat's launch keeps


def launched(name, cwd, conversation):
    """A receipt of this launch's own, for the seat plugin to write its session into.

    A resumed session is in it from the start, so a seat that dies again before its next
    turn still comes back to it.  The receipt of the launch before stays until this one starts.
    """
    token = uuid.uuid4().hex
    path = path_for({"opencode_launch": token})
    path.mkdir(mode=0o700)
    if conversation:
        (path / "session").write_text(conversation, encoding="utf-8")
    config.update_session(name, opencode_launch=token, session_title=None)
    sync_title(name, {"opencode_launch": token})
    return {RECEIPT_ENV: str(path)}


def sync_title(name, record):
    """Ask this launch's plugin; only its read-back of this request confirms the title.

    OpenCode 2.0.14 stores owner and generated titles in the same field and emits the same
    event for both. There is deliberately no session_title hook: neither can rename a seat.
    """
    path = path_for(record)
    if not path:
        return False
    try:
        request = config._read_json(path / "title-request.json")
        if not isinstance(request, dict) or request.get("title") != name:
            request = {"title": name, "id": uuid.uuid4().hex}
            config._write_json(path / "title-request.json", request, prepare=False)
        applied = config._read_json(path / "title-applied.json")
        sid = conversation(record)
        return bool(sid and applied == {**request, "sessionID": sid})
    except (config.Error, OSError, ValueError):
        return False


def _urls(value):
    """Every endpoint a provider table names anywhere inside it: `baseURL`, and legacy `api`."""
    items = (value.items() if isinstance(value, dict)
             else enumerate(value) if isinstance(value, list) else ())
    for key, item in items:
        if key in ("baseURL", "api"):
            yield item
        else:
            yield from _urls(item)


def _dig(value, *keys):
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def mode(entry):
    """`subscription` where OpenCode sends this MiMo model to a token-plan host, `payg` wherever
    that is not certain, and None for a model of any other provider.

    The endpoint is what the tokens are paid from, so it outranks config.toml's `mode`: a config
    written while MiMo shipped as payg picks it as the plan it runs on, with no edit.  It is read
    from one place, the global `opencode.json` adapters/opencode.sh reads its key from, since the
    adapter launches OpenCode with project config off.  A plan is a plain `https://` token-plan
    URL there, native `providers.mimo.settings.baseURL` or legacy `provider.mimo.options.baseURL`,
    with no other endpoint under either table.  Anything that could send the model elsewhere
    unseen -- OPENCODE_CONFIG set, an `opencode.jsonc` merged over it, a file that is not plain
    JSON or cannot be read, a `{env:}` or `{file:}` substitution, another scheme or a port that
    is no number, a backslash, a user part or a character past ASCII (which OpenCode's own URL
    parser can read as another host than Python's does), a second endpoint -- is payg, which
    never spends money unasked.  OPENCODE_CONFIG_CONTENT is not among them: the adapter unsets
    it before every launch and passes only its own rulebook document, so an OpenCode seat's own
    never reaches a turn, and `ak run` from that seat's shell reads MiMo the way every other
    seat does.
    """
    if str(entry.get("model") or "").partition("/")[0] != "mimo":
        return None
    home = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    folder = Path(os.environ.get("OPENCODE_CONFIG_DIR") or Path(home, "opencode"))
    if os.environ.get("OPENCODE_CONFIG"):
        return "payg"
    try:
        if (folder / "opencode.jsonc").exists():
            return "payg"
        doc = json.loads((folder / "opencode.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "payg"
    url = (_dig(doc, "providers", "mimo", "settings", "baseURL")
           or _dig(doc, "provider", "mimo", "options", "baseURL"))
    urls = [*_urls(_dig(doc, "providers", "mimo")), *_urls(_dig(doc, "provider", "mimo"))]
    if (not isinstance(url, str) or not url.isascii() or "{" in url or "\\" in url
            or any(other != url for other in urls)):
        return "payg"
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port                          # a port that is no number raises here
    except ValueError:
        return "payg"
    plan = (parts.scheme == "https" and "@" not in parts.netloc
            and PLAN_HOST.fullmatch(parts.hostname or ""))
    return "subscription" if plan else "payg"


def database():
    """opencode.db, which keeps every session: $OPENCODE_DB, a name under OpenCode's data folder
    or a path of its own, the way OpenCode resolves it."""
    share = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return share / "opencode" / os.environ.get("OPENCODE_DB", "opencode.db")


def idle_conversations(before):
    """The top-level sessions opencode.db last updated before then, read only."""
    from . import rows
    found = rows(database(), "SELECT id FROM session_v2 WHERE parent_id IS NULL"
                 " AND time_updated < ?", before * 1000)     # OpenCode stamps milliseconds
    return [session for session, in found or ()]


def end_conversation(session, ends):
    """`opencode session delete`, which takes the session with its children and messages.  In
    2.1.1 it asks nothing and exits 1 for a session it cannot find; `--standalone` runs it on
    a private server over the database `idle_conversations` read, never on the background
    service on its one port, which may serve another.  The database is the one part of it ak
    can judge.  OpenCode's only writer lock is SQLite's, which the command takes itself, so
    `ends` is asked right before it starts: a session resumed in that instant, after 30 days
    untouched, may still go, the gap `codex delete` leaves too; closing it would mean deleting
    OpenCode's rows ourselves."""
    if not SESSION.fullmatch(session) or not ends(database()):
        return False
    subprocess.run([config.harness_binary("opencode") or "opencode", "session", "delete",
                    "--standalone", session], stdin=subprocess.DEVNULL, capture_output=True,
                   timeout=60, env=config.child_env(), check=True)
    return True


def messages(conversation):
    """opencode.db keeps a session's messages as rows in order, a subagent's in its own session:
    a user row's `text`, an assistant row's text parts beside its reasoning and tool parts, each
    yielded as (who, when it was written in Unix seconds, its text).  None where there is none."""
    from . import rows
    if not isinstance(conversation, str) or not SESSION.fullmatch(conversation):
        return None
    found = rows(database(),
                 "SELECT type, time_created, data FROM session_message WHERE session_id = ?"
                 " AND type IN ('user', 'assistant') ORDER BY seq", conversation)
    if found is None:
        return None
    said = []
    for kind, created, data in found:
        try:
            message = json.loads(data)
        except (TypeError, ValueError):
            continue
        message = message if isinstance(message, dict) else {}
        if kind == "user":
            text = message.get("text")
        else:
            parts = message.get("content")
            parts = parts if isinstance(parts, list) else []
            text = "\n".join(part["text"] for part in parts if isinstance(part, dict)
                             and part.get("type") == "text" and isinstance(part.get("text"), str))
        if isinstance(text, str) and text:
            # OpenCode stamps its rows in milliseconds.
            at = created / 1000 if isinstance(created, (int, float)) else None
            said.append(("user" if kind == "user" else "model", at, text))
    return said


def said(record, cwd, conversation):
    found = messages(conversation)
    return None if found is None else [{"who": who, "text": text} for who, _, text in found]


def user_messages(record, cwd, conversation):
    from . import user_message
    for who, at, text in messages(conversation) or ():
        kept = user_message(at, text) if who == "user" else None
        if kept:
            yield kept
