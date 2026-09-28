"""Claude Code: its launched conversation, followed across clears by its own hooks.

An alternate login also needs the seat's trust and hooks in its own config directory.
"""

from pathlib import Path
import codecs
import json
import os
import re
import sys
import tempfile

SOURCE = "claude-hook"


def transcript_path(record, conversation):
    account = record.get("account")
    directory = Path.home() / (f".claude-{account}" if account and account != "default"
                               else ".claude")
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(record["cwd"]))
    return directory / "projects" / slug / f"{conversation}.jsonl"


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
    cache = config.STATE / f"title-{name}.json" if name else None
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


def account_config(check=False):
    """Keep the owner's configuration beside an alternate login's own credentials.

    Claude's config override moves both its user settings and its global .claude.json.
    Validate before respawning the pane; prepare trust again in the launch's actual cwd.
    Every seat runs bypass permissions: an accepted auto-mode offer writes `auto` into
    the settings, so each launch pins it back and leaves the offer answered.
    """
    account = os.environ.get("AGENTKIT_ACCOUNT")
    if not account:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        home = Path.home()
        paths = (home / ".claude/settings.json", home / ".claude.json")
        values = [json.loads(path.read_text()) if path.exists() else {} for path in paths]
        if not all(isinstance(value, dict) for value in values):
            raise ValueError("Claude settings and global config must be JSON objects")
        if check:
            return
        permissions = values[0].setdefault("permissions", {})
        if not isinstance(permissions, dict):
            permissions = values[0]["permissions"] = {}
        permissions["defaultMode"] = "bypassPermissions"
        values[1]["hasSeenAutoDefaultNudge"] = True
        paths[0].parent.mkdir(parents=True, exist_ok=True)
        for path, data in zip(paths, values):
            _write(path, data)
        return
    home = Path.home()
    directory = home / f".claude-{account}"
    settings = home / ".claude/settings.json"
    paths = (settings, directory / ".claude.json", directory / "settings.json")
    values = [json.loads(path.read_text()) if path.exists() else {} for path in paths]
    if not all(isinstance(value, dict) for value in values):
        raise ValueError("Claude settings and global config must be JSON objects")
    if check:
        return
    directory.mkdir(parents=True, exist_ok=True)
    try:
        usual = json.loads((home / ".claude.json").read_text())
    except (OSError, ValueError):
        usual = {}
    if not isinstance(usual, dict):
        usual = {}
    for path, data in zip(paths[1:], values[1:]):
        if path.name == ".claude.json":
            # A notice answered once is answered everywhere: only `true` flags travel,
            # so the named login keeps its own account, ids, caches and projects.
            for key, value in usual.items():
                if value is True:
                    data[key] = True
            data["hasSeenAutoDefaultNudge"] = True
            data.setdefault("theme", "dark")
            data["hasCompletedOnboarding"] = True
            project = data.setdefault("projects", {}).setdefault(str(Path.cwd().resolve()), {})
            project["hasTrustDialogAccepted"] = True
        else:
            data.update(values[0])
            # Hooks belong to the current installation, not every past checkout.
            data["hooks"] = values[0].get("hooks", {})
            permissions = data.setdefault("permissions", {})
            if not isinstance(permissions, dict):
                permissions = data["permissions"] = {}
            permissions["defaultMode"] = "bypassPermissions"
        _write(path, data)
    for name in ("CLAUDE.md", "agents", "skills", "commands", "plugins"):
        source, target = home / ".claude" / name, directory / name
        if source.exists() and not target.exists() and not target.is_symlink():
            target.symlink_to(source, target_is_directory=source.is_dir())
    os.environ["CLAUDE_CONFIG_DIR"] = str(directory)


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
