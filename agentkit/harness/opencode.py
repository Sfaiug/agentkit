"""OpenCode: the session a seat's own plugin reported, kept in a receipt of that launch's own.

Everything else about this harness is data -- adapters/opencode.sh and adapters/opencode.toml.
Its TUI cannot be told the id of a session it has not opened yet, so a seat's conversation is
learned rather than issued: every launch gets a receipt, a directory named in its environment,
and hooks/opencode-seat writes into it the id OpenCode made for the session that seat is talking
in -- whole, renamed over the last one, so an interrupted write leaves the last good id.  The
receipt's token is kept in the seat's record, so it follows a rename, and no other seat -- not
one in the same directory -- reads or writes it.  Nothing here asks which session of a
directory is the latest.

How MiMo is paid is learned from where OpenCode's own global config sends it: that outranks
whatever mode agentkit's config was given, and anything short of a plain token-plan URL is payg.
"""

import json
import os
import re
import shutil
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


def launched(name, cwd, conversation):
    """A receipt of this launch's own, for the seat plugin to write its session into.

    A resumed session is in it from the start, so a seat that dies again before its next
    turn still comes back to it.  The receipt of the launch before is dropped: one seat, one.
    """
    record = config.session_records().get(name, {})
    token = uuid.uuid4().hex
    path = path_for({"opencode_launch": token})
    path.mkdir(mode=0o700)
    if conversation:
        (path / "session").write_text(conversation, encoding="utf-8")
    config.update_session(name, opencode_launch=token)
    forget(record)
    return {RECEIPT_ENV: str(path)}


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
