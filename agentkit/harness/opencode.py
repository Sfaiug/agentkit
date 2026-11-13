"""OpenCode: the session a seat's own OpenCode last took a prompt into, kept in its record and
in a receipt of that launch's own.

Everything else about this harness is data -- adapters/opencode.sh and adapters/opencode.toml.
Its TUI cannot be told the id of a session it has not opened yet, so a seat's conversation is
learned rather than issued: the plugin's prompt fact names the session it went into, and the
seat follows it there (`follow`) -- its first, or another the owner opened in the seat's screen
(`/new`, or one from its list).  Every launch also gets a receipt, a directory named in its
environment, and ak alone writes into it the id of the session that seat is in, as the launch
resumes it and as the seat follows a prompt: the session hooks/opencode-seat puts ak's title
on, and the one a seat whose record names none yet comes back to.  The receipt's token is kept
in the seat's record, so it follows a rename, and no other seat -- not one in the same
directory -- reads or writes it.  Nothing here asks which session of a directory is the latest.

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
from datetime import datetime, timezone
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
    """The session the seat followed to (`follow`), else the one its launch's receipt names, or
    None where neither names one yet."""
    from . import unread
    if isinstance(record.get("conversation"), str) and SESSION.fullmatch(record["conversation"]):
        return record["conversation"]
    path = path_for(record)
    try:
        sid = (path / "session").read_text(encoding="utf-8").strip() if path else ""
    except OSError as exc:
        unread(exc)
        return None
    return sid if SESSION.fullmatch(sid) else None


def resumable(record, cwd, conversation):
    """The receipt or the record is the whole answer: the launcher never issues an OpenCode id."""
    return bool(conversation)


def reconcile(record):
    """Nothing to drop: a session the record names is one the seat's own OpenCode took a prompt
    into (`follow`)."""
    return {}


def follow(launched, payload, pid):
    """A prompt the seat's own OpenCode took into a top-level session moves the seat there
    (`claim`), whoever typed it, its first one too.  opencode.db says which, read as the prompt
    is reported: a subagent's session names the session that started it there, and is never
    followed.  OpenCode keeps every session in that one database, that session's file too.
    2.2.7's TUI runs its server, the plugin reporting the prompt in it, as a child of its own,
    `opencode serve --stdio`: a process whose command starts so, and which an OpenCode started
    straight, is counted from that OpenCode up, so a server started under the seat's own is a
    second, and moves nothing.  Any other OpenCode counts itself: a server whose parent is a
    tool's shell, and a TUI whose `--prompt` names that command.

    The session the seat is in then goes into its launch's receipt: whole, renamed over the last
    one, and only into the launch's own directory, which a seat stopped since has had removed.
    Only what `claim` left in the record goes there, never a session it refused."""
    from .. import orch
    from . import claim, rows
    session = payload.get("session_id") if isinstance(payload, dict) else None
    if (isinstance(session, str) and SESSION.fullmatch(session)
            and payload.get("hook_event_name") == "UserPromptSubmit"
            and rows(database(), "SELECT 1 FROM session_v2 WHERE id = ? AND parent_id IS NULL",
                     session)):
        table, opencode = orch.processes() or {}, lambda words: orch.program(words) == "opencode"
        parent, words = table.get(pid, (pid, []))
        if opencode(words) and opencode(table.get(parent, (parent, []))[1]):
            command = words.index(orch.program(words, full=True)) + 1
            if words[command:command + 2] == ["serve", "--stdio"]:
                pid = parent
        claim(launched, "opencode", session, str(database()),
              lambda record, session: database(), pid, opencode)
        record = config.session_records().get(config.resolve_session(launched), {})
        path, current = path_for(record), record.get("conversation")
        if path and isinstance(current, str) and SESSION.fullmatch(current):
            try:
                (path / "session.next").write_text(current, encoding="utf-8")
                (path / "session.next").replace(path / "session")
            except OSError:
                pass        # the receipt says what it said before


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


def switchable(model, effort):
    """Whether the running TUI can move to `model` at `effort` by `/ak-model`: not where the
    variant a launch would run -- the id's own `#variant`, else the effort -- is one a launch
    defines itself (adapters/opencode.sh `variants`), which OpenCode reads only as it starts.
    An answer that cannot be read restarts too: a launch defines whatever it needs."""
    try:
        done = config.run_adapter([str(config.adapter("opencode")), "variants", model], 10,
                                  env=config.child_env())
        defined = {variant for provider in json.loads(done.stdout)["provider"].values()
                   for entry in provider["models"].values() for variant in entry["variants"]}
    except (config.Error, OSError, subprocess.TimeoutExpired, ValueError, TypeError,
            KeyError, AttributeError):
        return False
    return done.returncode == 0 and (model.partition("#")[2] or effort) not in defined


def launched(name, cwd, conversation):
    """A receipt of this launch's own, which keeps the seat's session (`follow`) for its plugin.

    A resumed session is in it from the start, so a seat that dies again before its next
    turn still comes back to it.  A resume opens on the session the seat is in, whichever
    names it, so the record is left as it is: a launch that replaces a live harness refuses
    itself on a record changed meanwhile (`watch.between_turns`).  A new session drops the
    one the record followed to (`follow`).  The receipt of the launch before stays until this
    one starts.
    """
    token = uuid.uuid4().hex
    path = path_for({"opencode_launch": token})
    path.mkdir(mode=0o700)
    if conversation:
        (path / "session").write_text(conversation, encoding="utf-8")
    config.update_session(name, opencode_launch=token, session_title=None,
                          **({} if conversation else {"conversation": None}))
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


def _session_rows(conversation):
    """opencode.db keeps a session's messages as rows in order, a subagent's in its own session:
    each user and assistant row as (its type, when it was written in milliseconds, its data, and
    an assistant row's parts beside it -- text, reasoning, tool calls).  None where there is
    none."""
    from . import rows
    if not isinstance(conversation, str) or not SESSION.fullmatch(conversation):
        return None
    found = rows(database(),
                 "SELECT type, time_created, data FROM session_message WHERE session_id = ?"
                 " AND type IN ('user', 'assistant') ORDER BY seq", conversation)
    if found is None:
        return None
    read = []
    for kind, created, data in found:
        try:
            message = json.loads(data)
        except (TypeError, ValueError):
            continue
        message = message if isinstance(message, dict) else {}
        parts = message.get("content") if kind == "assistant" else None
        read.append((kind, created, message, [part for part in parts if isinstance(part, dict)]
                     if isinstance(parts, list) else []))
    return read


def messages(conversation):
    """A user row's `text` and an assistant row's text parts, each as (who, when it was written
    in Unix seconds, its text).  None where there is none."""
    found = _session_rows(conversation)
    if found is None:
        return None
    said = []
    for kind, created, message, parts in found:
        text = message.get("text") if kind == "user" else "\n".join(
            part["text"] for part in parts
            if part.get("type") == "text" and isinstance(part.get("text"), str))
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


def answers(record, cwd, conversation):
    """Each question the owner answered on a card of OpenCode's `question` tool, which keeps
    their answers in the call's own state, not as a message of theirs: one list per question,
    in the order asked -- the label picked, the words typed instead, or the labels ticked, joined
    as OpenCode's reply to the model joins them -- dated when they submitted the card.  A
    question left unanswered holds an empty list, and a card put down with Esc ends `error`."""
    for *_, parts in _session_rows(conversation) or ():
        for part in parts:
            try:    # a part of any other shape answers nothing
                state, at = part["state"], part["time"]["completed"]
                if (part["type"] != "tool" or part["name"] != "question"
                        or state["status"] != "completed" or not isinstance(at, (int, float))):
                    continue
                for asked, given in zip(state["input"]["questions"], state["metadata"]["answers"]):
                    if isinstance(given, list):
                        yield {"at": at / 1000, "question": asked["question"],
                               "answer": ", ".join(given), "choices": [
                                   {"label": option["label"],
                                    "description": option.get("description", "")}
                                   for option in asked.get("options") or ()]}
            except (AttributeError, KeyError, TypeError):
                continue


def running(record, cwd, conversation):
    """The model and effort of that session's latest answer: OpenCode records them on each
    (`model`, its `variant` the effort, `default` where none was set), so `/model` typed in the
    seat shows at its next answer -- one that failed too, sent to the model just picked."""
    from . import rows
    if not isinstance(conversation, str) or not SESSION.fullmatch(conversation):
        return None
    found = rows(database(), "SELECT time_created, data FROM session_message"
                 " WHERE session_id = ? AND type = 'assistant' ORDER BY seq DESC LIMIT 1",
                 conversation)
    try:
        created, data = found[0]
        model = json.loads(data)["model"]
        effort = model.get("variant")
        return (f"{model['providerID']}/{model['id']}",
                None if effort == "default" else effort, created / 1000)
    except (TypeError, IndexError, ValueError, KeyError, AttributeError):
        return None


def error(record, cwd, conversation):
    """The error OpenCode recorded as the end of that session's last turn, "" where the turn
    ended otherwise or a prompt came after it, None where opencode.db holds none of the session.

    OpenCode ends every turn in an `idle` row whose `outcome` says how; a failed one holds its own
    error -- the `provider.*` type, the status and the message the seat shows behind `Error: `
    -- which no model's answer is and no terminal width wraps.  One that names its wait
    (`retryAfterMs`, from the row's own stamp: 2.2.3's free limit) says when, as
    `turns.try_again_at` reads it."""
    from . import rows
    if not isinstance(conversation, str) or not SESSION.fullmatch(conversation):
        return None
    found = rows(database(), "SELECT type, time_created, data FROM session_message"
                 " WHERE session_id = ? AND type IN ('user', 'idle') ORDER BY seq DESC LIMIT 1",
                 conversation)
    if not found:
        return None
    kind, created, data = found[0]
    try:
        ended = json.loads(data)
    except (TypeError, ValueError):
        return ""
    failed = ended.get("error") if kind == "idle" and isinstance(ended, dict) else None
    if not isinstance(failed, dict):
        return ""
    said = "Error: " + " ".join(str(failed[key]) for key in ("type", "status", "message")
                                if failed.get(key) is not None)
    wait = failed.get("retryAfterMs")
    if isinstance(wait, (int, float)) and isinstance(created, (int, float)):
        reset = datetime.fromtimestamp((created + wait) / 1000, timezone.utc)
        said += f" try again at {reset.isoformat(timespec='milliseconds')}"
    return said
