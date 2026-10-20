"""Claude Code: its launched conversation, followed across clears by its own hooks.

An alternate login also needs the seat's trust in its own config directory; it reads the usual
login's settings through a link (adapters/claude.sh's `share`).
"""

from pathlib import Path
import codecs
import json
import math
import os
import re
import sys
import tempfile

SOURCE = "claude-hook"
TMP_CLAUDE_AGE = 86400          # a gone session's scratch folder goes after a day
PROJECT_CUT = 200               # Claude Code ends a project name past this with a hash of the path


# What Claude Code writes as the conversation's last message when the owner interrupts a turn
# with Esc after it said anything, the turn's only end it reports: no Stop comes.
INTERRUPTS = ("[Request interrupted by user]", "[Request interrupted by user for tool use]")


def project(cwd):
    """The folder Claude Code files a working directory's conversations and scratch under.

    Its JavaScript replaces each UTF-16 unit that is not an ASCII letter or digit, so a
    character beyond the BMP leaves two hyphens.  A longer name keeps its start and ends with
    the path's 31-times string hash, as a signed 32-bit number's magnitude in base 36, so two
    long paths sharing that start stay apart.
    """
    text = str(cwd)
    name = re.sub(r"[^A-Za-z0-9]", lambda m: "--" if ord(m[0]) > 0xFFFF else "-", text)
    if len(name) <= PROJECT_CUT:
        return name
    units = text.encode("utf-16-be", "surrogatepass")
    value = 0
    for at in range(0, len(units), 2):
        value = (value * 31 + int.from_bytes(units[at:at + 2], "big")) & 0xFFFFFFFF
    value = abs(value - (value >> 31 << 32))
    digits = ""
    while value or not digits:
        value, digit = divmod(value, 36)
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"[digit] + digits
    return f"{name[:PROJECT_CUT]}-{digits}"


def transcript_path(record, conversation):
    account = record.get("account")
    directory = Path.home() / (f".claude-{account}" if account and account != "default"
                               else ".claude")
    return directory / "projects" / project(record["cwd"]) / f"{conversation}.jsonl"


def transcript(record, cwd, conversation):
    """The transcript the new orchestrator reads the last exchange from.

    Only where the harness has written one: a conversation nobody typed into has no
    file, and the handover says so instead of pointing at it.
    """
    if not conversation or not record.get("cwd"):
        return None
    path = transcript_path(record, conversation)
    return str(path) if path.exists() else None


# Lines no one said here: bookkeeping, a compaction's summary, a subagent's, view-only ones.
UNSAID = ("isMeta", "isCompactSummary", "isSidechain", "isVisibleInTranscriptOnly")


def prompt(entry):
    """The owner's words one transcript line holds, or None for anything else."""
    if any(entry.get(key) for key in UNSAID):
        return None
    if entry.get("type") == "attachment":
        attachment = entry.get("attachment")
        if not isinstance(attachment, dict) or attachment.get("type") != "queued_command":
            return None
        origin = attachment.get("origin")
        if (not isinstance(origin, dict) or origin.get("kind") != "human"
                or attachment.get("commandMode", "prompt") != "prompt"):
            return None
        content = attachment.get("prompt")
    elif entry.get("type") == "user":
        origin = entry.get("origin")
        if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
            return None
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("role") != "user":
            return None
        content = message.get("content")
    else:
        return None
    if isinstance(content, list):
        if any(isinstance(part, dict) and part.get("type") == "tool_result"
               for part in content):
            return None
        content = "\n".join(part["text"] for part in content if isinstance(part, dict)
                            and part.get("type") == "text" and isinstance(part.get("text"), str))
    # Claude renders command results and interrupts as unmarked user entries.
    # These protocol frames are bookkeeping even when isMeta is absent.
    if entry.get("type") == "user" and isinstance(content, str) and (
            content.startswith(("<command-name>", "<local-command-stdout>",
                "<local-command-stderr>", "<local-command-caveat>", "<task-notification>"))
            or content in INTERRUPTS):
        return None
    return content if isinstance(content, str) and content else None


def answer(entry):
    """The model's visible words one transcript line holds, or None for its thinking, its tool
    calls, a subagent's, and an API error Claude Code wrote in its place."""
    message = entry.get("message")
    if (entry.get("type") != "assistant" or entry.get("isApiErrorMessage")
            or any(entry.get(key) for key in UNSAID) or not isinstance(message, dict)
            or not isinstance(message.get("content"), list)):
        return None
    return "\n".join(part["text"] for part in message["content"] if isinstance(part, dict)
                     and part.get("type") == "text" and isinstance(part.get("text"), str)) or None


def said(record, cwd, conversation):
    from . import turns
    return turns(transcript(record, cwd, conversation), prompt, answer)


def user_messages(record, cwd, conversation):
    from . import entries, user_message
    for entry in entries(transcript(record, cwd, conversation)):
        kept = user_message(entry.get("timestamp"), prompt(entry))
        if kept:
            yield kept


def error(record, cwd, conversation):
    """The API error Claude Code recorded as that conversation's last message, or None.

    A request that failed ends in an entry of its own, `isApiErrorMessage`, holding the text
    the seat showed; a prompt or an answer after it is the conversation going on.  Its other
    entries -- titles, modes, queue operations -- are bookkeeping and say neither.
    """
    from . import last_entry
    path = transcript(record, cwd, conversation)
    entry = path and last_entry(path, lambda entry: entry.get("type") in ("user", "assistant"))
    message = entry.get("message") if entry and entry.get("isApiErrorMessage") is True else None
    content = message.get("content") if isinstance(message, dict) else None
    parts = content if isinstance(content, list) else [{"text": content}]
    return "\n".join(part["text"] for part in parts if isinstance(part, dict)
                     and isinstance(part.get("text"), str)).strip() or None


def interrupted(record, cwd, conversation):
    """When the owner interrupted that conversation's turn, where that is its last message, or
    None: a prompt or an answer after it is the conversation going on."""
    from . import last_entry, user_message
    path = transcript(record, cwd, conversation)
    entry = path and last_entry(path, lambda entry: entry.get("type") in ("user", "assistant"))
    message = entry.get("message") if entry and entry.get("type") == "user" else None
    content = message.get("content") if isinstance(message, dict) else None
    parts = content if isinstance(content, list) else [{"text": content}]
    said = next((part["text"] for part in parts if isinstance(part, dict)
                 and part.get("text") in INTERRUPTS), None)
    kept = said and user_message(entry.get("timestamp"), said)
    return kept["at"] if kept else None


def wrapped_up(record, cwd, conversation):
    """When Claude Code told that conversation's turn its usage limit was reached, where no prompt
    came after it, or None.  Its note of its own (`usageLimitNote: wrap_up`, 2.1.292) asks the
    model to finish the piece in hand and stop, so the turn ends with nothing refused; the next
    prompt, with room again, brings its `release` note."""
    from . import last_entry, user_message
    path = transcript(record, cwd, conversation)
    entry = path and last_entry(path, lambda entry: entry.get("usageLimitNote") == "wrap_up"
                                or prompt(entry) is not None)
    kept = (entry and entry.get("usageLimitNote") == "wrap_up"
            and user_message(entry.get("timestamp"), "wrap_up"))
    return kept["at"] if kept else None


def unanswered(record, cwd, conversation):
    """The owner's prompt that is that conversation's last message, as {at, text}, or None: one
    nothing has answered or interrupted yet.  An Esc before any answer leaves it so (2.1.292),
    and puts it back in the composer."""
    from . import last_entry, user_message
    path = transcript(record, cwd, conversation)
    entry = path and last_entry(path, lambda entry: entry.get("type") in ("user", "assistant"))
    said = entry and entry.get("type") == "user" and prompt(entry)
    return user_message(entry.get("timestamp"), said) if said else None


def resumable(record, cwd, conversation):
    from . import LAUNCHER
    return bool(conversation) and record.get("id_source") in (LAUNCHER, SOURCE)


def reconcile(record):
    return ({"conversation": None, "resumable": False}
            if record.get("conversation") and not resumable(record, None, record["conversation"])
            else {})


def capture(launched, payload, pid):
    """Only the seat's interactive process can report its replacement conversation.

    Run while the hook's parent is still alive: an inherited seat name and pane alone
    cannot distinguish a nested Claude from the one the owner is talking to.
    """
    from .. import config, notify, orch
    if (os.environ.get("AK_RUN_ROLE") == "worker" or not isinstance(payload, dict)
            or payload.get("agent_id") or payload.get("agent_type")
            or payload.get("hook_event_name") != "SessionStart" or payload.get("source") != "clear"):
        return
    conversation, transcript = payload.get("session_id"), payload.get("transcript_path")
    if (not isinstance(conversation, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", conversation)
            or conversation.startswith("-") or not isinstance(transcript, str)):
        return
    record = config.session_records().get(config.resolve_session(launched), {})
    if orch.seat_harness(record) != "claude" or record.get("conversation") == conversation:
        return
    with notify.session_lock(launched) as name:
        record = config.session_records().get(name, {})
        if (orch.seat_harness(record) != "claude" or not record.get("cwd")
                or record.get("conversation") == conversation
                or not resumable(record, record.get("cwd"), record.get("conversation"))
                or Path(transcript).resolve() != transcript_path(record, conversation).resolve()):
            return
        session = orch.find(name)
        if session and orch.owns_hook(session, pid, is_process):
            config.update_session(name, conversation=conversation, id_source=SOURCE)


def is_process(words):
    """Both the native executable and npm's Node entry point run the seat's client."""
    from .. import orch
    program = orch.program(words, full=True)
    return (Path(program).name == "claude"
            or program.endswith("/@anthropic-ai/claude-code/cli.js"))


def tmp_claude_live(table):
    """What live clients may still use, as (sessions, projects), or None without an inventory.

    A client is named by its pid record: Claude updates it after /clear, and procStart must
    match too, so a reused pid or a stale record in another account cannot stand in for the
    live client.  A headless turn writes none; it is named by its stdout, the event stream ak
    launched it writing to.  A client neither names, or a process of an unknown program, keeps
    its working directory's project, the only one its scratch can be under.
    """
    from .. import retention, worker
    if table is None:
        return None
    try:
        roots = [path for path in Path.home().glob(".claude*") if path.is_dir()]
        if os.environ.get("CLAUDE_CONFIG_DIR"):
            roots.append(Path(os.environ["CLAUDE_CONFIG_DIR"]))
        sessions, projects = set(), set()
        for pid, row in table.items():
            if row["uid"] != os.getuid() or (row["args"] and not is_process(row["args"])):
                continue
            stream = row.get("stdout")
            found = ({worker.recovered_session(Path(stream).parent)}
                     if stream and Path(stream).name == "events.jsonl" else set())
            for root in roots:
                record = retention.read_json(root / "sessions" / f"{pid}.json") or {}
                if record.get("pid") == pid and str(record.get("procStart")) == row["start"]:
                    found.add(record.get("sessionId"))
            found = {session for session in found
                     if isinstance(session, str) and re.fullmatch(r"[A-Za-z0-9_-]+", session)}
            if found:
                sessions |= found
            else:
                projects.add(project(row["cwd"]))
        return sessions, projects
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def tmp_claude_session_stale(path, now, paths, live):
    """Why that Claude session folder goes, or None when it stays.

    Its session is gone, untouched for a day, and held by nobody.
    """
    from .. import gc, retention
    if (retention.busy(path, paths) or live is None or path.name in live[0]
            or path.parent.name in live[1]):
        return None
    newest = gc.tmp_tree_newest(path)
    if newest is None or not retention.expired(newest, now, TMP_CLAUDE_AGE):
        return None
    days = int((now - newest) // 86400)
    return f"session {path.name} is gone, untouched for {days} day{'s' if days != 1 else ''}"


def tmp_top_stale(path, now, paths, live):
    """Why that top-level /tmp entry goes whole, or None.

    The same live-client protection covers both whole trees and session folders.
    """
    from .. import gc
    name = path.name
    if name.startswith("claude-") and name[7:].isdigit():
        if live is None:
            return None
        sessions, projects = live
        try:
            if any(folder in projects
                   or any((path / folder / session).is_dir() for session in sessions)
                   for folder in gc.tmp_listdir(path)):
                return None
        except OSError:
            return None
    return gc.tmp_entry_stale(path, now, paths)


def tmp_session_entries(path, now, paths, live):
    """Gone session folders inside this user's scratch tree, unless the whole tree goes."""
    from .. import gc, retention
    if path.name != f"claude-{os.getuid()}" or live is None or not retention.safe(path):
        return
    try:
        projects = gc.tmp_listdir(path)
    except OSError:
        return
    for project in projects:
        if gc.tmp_protected(project):
            continue
        project_path = path / project
        try:
            if not project_path.is_dir() or project_path.is_symlink():
                continue
            sessions = gc.tmp_listdir(project_path)
        except OSError:
            continue
        for session_id in sessions:
            if gc.tmp_protected(session_id):
                continue
            session_path = project_path / session_id
            try:
                if not session_path.is_dir() or session_path.is_symlink():
                    continue
            except OSError:
                continue
            why = tmp_claude_session_stale(session_path, now, paths, live)
            if why:
                yield {"action": "remove", "kind": "claude-session",
                       "path": str(session_path), "why": why}


def tmp_rule(table):
    """Protect live clients in scratch trees and collect gone sessions within our own."""
    live = tmp_claude_live(table)

    def rule(path, now, paths, *, top):
        if top:
            if not (path.name.startswith("claude-") and path.name[7:].isdigit()):
                return None
            return (tmp_top_stale(path, now, paths, live),
                    tmp_session_entries(path, now, paths, live))
        if path.parents[1].name == f"claude-{os.getuid()}":
            return tmp_claude_session_stale(path, now, paths, live), ()
        return None

    return rule


def title_command(name):
    """Remote Control takes /rename live, including while a turn is running."""
    return f"/rename {name}"


def session_title(record):
    """Read only this seat's conversation, under the login its launch selected."""
    from .. import config

    # The old conversation notes had no seat to collect them.
    for old in config.STATE.glob("claude-title-*.json"):
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass
    conversation, cwd = record.get("conversation"), record.get("cwd")
    if not conversation or not cwd:
        return None
    path = transcript_path(record, conversation)
    try:
        found = path.stat()
    except OSError:
        return None
    stamp = [found.st_dev, found.st_ino, found.st_size, found.st_mtime_ns, found.st_ctime_ns]
    # Cron starts a fresh process each tick, so the last reading lives on disk.
    name = next((name for name, seat in config.session_records().items()
                 if all(seat.get(key) == record.get(key)
                        for key in ("cwd", "conversation", "account"))), None)
    cache = config.title_path(name) if name else None
    try:
        cached = json.loads(cache.read_text(encoding="utf-8")) if cache else None
    except (OSError, ValueError):
        cached = None
    title, offset, readable = None, 0, True
    # An older note cannot tell an absent title from a failed read.
    if (isinstance(cached, dict) and cached.get("path") == str(path)
            and isinstance(cached.get("readable"), bool)):
        before, stop = cached.get("stamp"), cached.get("offset")
        if (isinstance(before, list) and len(before) == len(stamp)
                and isinstance(before[2], int) and isinstance(stop, int)
                and 0 <= stop <= before[2]):
            if before == stamp:
                if not cached["readable"]:
                    return None
                title = cached.get("title")
                return title if isinstance(title, str) and title.strip() else ""
            if before[:2] == stamp[:2] and before[2] < stamp[2]:
                title, offset, readable = cached.get("title"), stop, cached["readable"]
    try:
        with path.open("rb") as transcript:
            transcript.seek(offset)
            # A pending line may split UTF-8; keep its byte offset until the newline arrives.
            while offset < found.st_size:
                line = transcript.readline(found.st_size - offset)
                if not line.endswith(b"\n"):
                    # A split codepoint can finish later; corrupt bytes still mean unreadable.
                    codecs.utf_8_decode(line, "strict", False)
                    break
                offset = transcript.tell()
                line = line.decode("utf-8")
                if '"custom-title"' not in line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if (isinstance(event, dict) and event.get("type") == "custom-title"
                        and event.get("sessionId") == conversation):
                    title = event.get("customTitle")
    except OSError:
        return None
    except UnicodeError:
        readable = False
    title = (title if isinstance(title, str) and title.strip() else "") if readable else None
    try:
        if cache:
            _write(cache, {"path": str(path), "stamp": stamp, "offset": offset,
                           "title": title, "readable": readable})
    except OSError:
        pass        # a cache that cannot be written must not hide the title
    return title


def opened(cwd, conversation):
    """Has Claude Code written that conversation down yet, where it keeps them?

    Its directory per workspace: every character that is not a letter or a digit becomes a
    dash, and each transcript is named for the session it holds.  Claude Code writes the
    transcript at the first message and not at the prompt, so a seat nobody typed into has
    nothing to resume, and `--resume` on it is an error rather than a conversation.
    """
    from .. import config
    # The exact owned id, rather than this caller's environment, selects the seat's login.
    record = next((record for record in config.session_records().values()
                   if record.get("conversation") == conversation and record.get("cwd") == str(cwd)),
                  {"cwd": cwd})
    return transcript_path(record, conversation).exists()


def _write(path, data):
    """Replace a config file from a temp file no other launch shares.

    Seats open side by side, so a fixed temp name collides: one launch renames
    it away while another is still writing.  A replace inherits the temp file's
    mode rather than the old one's, so an existing file keeps the mode it had
    and a new one stays as mkstemp made it, 0600.
    """
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(data) + "\n")
        if path.exists():
            os.chmod(name, path.stat().st_mode & 0o777)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def config_entries():
    """The user-scope ~/.claude.json: `register_mcp` and `account_config` write there."""
    return {"file": Path.home() / ".claude.json", "trust": "projects", "mcp": "mcpServers"}


def register_mcp(servers):
    """Put `servers` into ~/.claude.json's top-level mcpServers, user scope, in place.

    A URL is Claude's `http` server and a command its `stdio` one.  An entry of the same name
    from before is replaced whole, leaving no stale command behind.
    """
    from .. import config
    path = config_entries()["file"]      # user scope lives at the top level
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise config.Error(f"cannot read {path}: {exc}") from None
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise config.Error(f"{path}: {exc}") from None
        if not isinstance(data, dict):
            raise config.Error(f"{path}: expected a JSON object")
    existing = data.get("mcpServers")
    if existing is not None and not isinstance(existing, dict):
        raise config.Error(f"{path}: mcpServers is not an object")
    wanted = {name: {"type": "http" if "url" in server else "stdio", **server}
              for name, server in servers.items()}
    merged = {**(existing or {}), **wanted}
    if existing == merged:
        return f"already registered in {path} (user scope)"
    data["mcpServers"] = merged
    try:
        _write(path, data)
    except OSError as exc:
        raise config.Error(f"cannot write {path}: {exc}") from None
    return f"registered in {path} (user scope)"


def answered(data):
    """A seat's first-run questions answered in its global config: the theme, the onboarding,
    the auto-mode offer, and trust in the launch's actual cwd, so the TUI opens on the prompt
    rather than on "do you trust this folder?", whose default is "No, exit"."""
    data["hasSeenAutoDefaultNudge"] = True
    data.setdefault("theme", "dark")
    data["hasCompletedOnboarding"] = True
    project = data.setdefault("projects", {}).setdefault(str(Path.cwd().resolve()), {})
    project["hasTrustDialogAccepted"] = True


CHECKED_ENV = "AGENTKIT_CLAUDE_CHECKED"   # the launch has read Claude's settings: adapters/claude.sh


def _settings(account):
    """(paths, what each holds) of the configuration a seat on that login is opened with: the
    owner's settings, which every login reads, and the login's global config.  A file not there
    holds nothing; one that is not a JSON object is a ValueError."""
    home = Path.home()
    paths = (home / ".claude/settings.json",
             home / f".claude-{account}/.claude.json" if account else home / ".claude.json")
    values = []
    for path in paths:
        try:
            values.append(json.loads(path.read_text()) if path.exists() else {})
        except ValueError as exc:
            raise ValueError(f"{path} is not JSON: {exc}") from exc
        if not isinstance(values[-1], dict):
            raise ValueError(f"{path} is not a JSON object")
    return paths, values


def checked(account):
    """Refuse a launch whose settings Claude Code could not be started with, before the pane it
    would replace is touched, and tell the adapter so: it then starts no Python to read them
    again (`--check`, which an adapter run on its own still does)."""
    from .. import config
    try:
        _settings(account)
    except (OSError, ValueError) as exc:
        raise config.Error(f"Claude's settings cannot be read: {exc}") from exc
    return {CHECKED_ENV: "1"}


def account_config(check=False):
    """Keep the owner's configuration beside an alternate login's own credentials.

    Claude's config override moves both its user settings and its global .claude.json.
    Validate before respawning the pane; on either login, answer the first-run questions
    (`answered`) in the launch's actual cwd.  What every seat runs with comes on its command
    line (adapters/claude.sh's PINS), so the usual login's settings are never rewritten here.
    """
    account = os.environ.get("AGENTKIT_ACCOUNT")
    paths, values = _settings(account)
    if check:
        return
    if not account:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        answered(values[1])
        _write(paths[1], values[1])
        return
    home = Path.home()
    directory = home / f".claude-{account}"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        usual = json.loads((home / ".claude.json").read_text())
    except (OSError, ValueError):
        usual = {}
    if not isinstance(usual, dict):
        usual = {}
    # A notice answered once is answered everywhere: only `true` flags travel,
    # so the named login keeps its own account, ids, caches and projects.
    for key, value in usual.items():
        if value is True:
            values[1][key] = True
    answered(values[1])
    _write(paths[1], values[1])
    for name in ("CLAUDE.md", "agents", "skills", "commands", "plugins"):
        source, target = home / ".claude" / name, directory / name
        if source.exists() and not target.exists() and not target.is_symlink():
            target.symlink_to(source, target_is_directory=source.is_dir())
    os.environ["CLAUDE_CONFIG_DIR"] = str(directory)


def turn_meters(out):
    """The account's limits this turn printed in its own stream, as endpoint meters, or [].

    Every `claude -p` turn prints `rate_limit_event`s carrying the account's five-hour
    and seven-day utilizations (0 to 1) with their resets. The last one is the reading:
    `five_hour` is the session meter and `seven_day` the weekly_all one, so the turn's
    own account is measured with no request. A turn without the event, or with no valid
    window in it, says nothing.
    """
    path = Path(out)
    path = path if path.is_file() else path / "events.jsonl"
    found = None
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if "rate_limit_event" not in line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or event.get("type") != "rate_limit_event":
                    continue
                info = event.get("rate_limit_info")
                windows = info.get("unifiedWindows") if isinstance(info, dict) else None
                if not isinstance(windows, dict):
                    continue
                meters = []
                # The session window is usage.SESSION_SECS; the week is seven days, as
                # adapters/claude.sh names them off the endpoint's groups.
                for key, name, window in (("five_hour", "session", 18000),
                                          ("seven_day", "weekly_all", 604800)):
                    reading = windows.get(key)
                    if not isinstance(reading, dict):
                        continue
                    share, resets = reading.get("utilization"), reading.get("resetsAt")
                    if (isinstance(share, bool) or not isinstance(share, (int, float))
                            or not math.isfinite(share) or not 0 <= share <= 1):
                        continue
                    if (isinstance(resets, bool) or not isinstance(resets, (int, float))
                            or not math.isfinite(resets) or resets <= 0):
                        continue
                    meters.append({"name": name, "used": float(share) * 100.0,
                                   "resets_at": resets, "window_secs": window})
                if meters:
                    found = meters
    except OSError:
        return []
    return found or []


if __name__ == "__main__":
    if sys.argv[1:2] == ["--hook"]:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from agentkit.harness.claude import capture
        capture(os.environ["AGENTKIT_SESSION"], json.load(sys.stdin), int(sys.argv[2]))
        sys.exit(0)
    checking = sys.argv[1:] == ["--check"]
    account_config(check=checking)
    if not checking:
        os.execvp(sys.argv[2], sys.argv[2:])
