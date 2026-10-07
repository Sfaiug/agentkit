"""A Codex seat owns only the thread reported by its own launch's SessionStart hook.

Receipts are separate from session records so a late hook cannot undo a rename, overwrite
the menu's state, or recreate a stopped seat. No directory or timestamp search is involved.

This is also where the harness hooks the core asks for live -- `conversation`, `resumable`,
`reconcile`, `restart_word`, `launched`, `forget` -- because every one of them is that
receipt: a Codex thread is this seat's only where its own launch reported it.
"""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tomllib
import uuid

from .. import config

RECEIPT_ENV = "AGENTKIT_CODEX_RECEIPT"
CAPTURE_ENV = "AGENTKIT_CODEX_CAPTURE"
SOURCE = "codex-session-start"
# The lifecycle hooks Codex 0.153.4 defines that name a state; adapters/codex.toml maps them.
SEAT_EVENTS = ("UserPromptSubmit", "Stop", "Interrupt", "PermissionRequest")
# ... and what rides the end of a turn beside them.  Codex documents a blocking Stop hook
# (learn.chatgpt.com/docs/hooks#stop), and 0.153.4's own `stop.command.output` schema is
# Claude's -- a `decision` of `block` with the `reason` beside it -- so the end-of-turn rule is
# the one script on both harnesses.
STOP_RULE = "hooks/orchestrator-stop.sh"
FRESH = "Codex ownership unverified; starts fresh"
BEGIN = "# --- agentkit browser bridge: managed by `ak browser mcp-register` ---"
END = "# --- end agentkit browser bridge ---"


def seat_conversations(remote):
    """Where the seat of that remote id keeps its conversations: under the usual ~/.codex, where
    adapters/codex.sh keeps every login's, so the place is the same whichever login the seat
    runs on, and stays after the seat's home is removed."""
    return Path.home() / ".codex" / "agentkit-seats" / remote


def path_for(record):
    token = record.get("codex_launch")
    if isinstance(token, str) and re.fullmatch(r"[0-9a-f]{32}", token):
        return config.STATE / f"codex-launch-{token}.json"
    return None


def read(record):
    path = path_for(record)
    if path:
        try:
            with path.open() as fh:
                fcntl.flock(fh, fcntl.LOCK_SH)
                data = json.load(fh)
            if isinstance(data, dict) and data.get("launch") == record["codex_launch"]:
                return data
        except (OSError, ValueError):
            pass
    return {}


def remote_home(remote):
    """The private home of a seat's remote identity, shared by launch, access and removal."""
    return config.STATE / ("codex-remote-" + remote)


def pairing_home(target):
    """Bare arguments name seats; explicit paths name their already-created homes."""
    home = Path(target)
    if home.name != target:
        return home
    name = config.resolve_session(target)
    remote = read(config.session_records().get(name, {})).get("remote")
    if not remote:
        raise config.Error(f"{name} has no Codex remote connection; open its Codex seat first")
    return remote_home(remote)


def conversation(record, cwd=None):
    """Verify the launch receipt against the exact transcript the harness reported.

    `cwd` is what the hook is handed and what this harness has no use for: the receipt names
    the directory its thread was opened in, and nothing else establishes ownership.
    """
    receipt = read(record)
    event = receipt.get("event")
    if receipt.get("ambiguous") or not isinstance(event, dict):
        return None
    sid = event.get("session_id")
    transcript = event.get("transcript_path")
    cwd = receipt.get("cwd")
    if (not isinstance(sid, str) or not sid or sid.startswith("-")
            or not isinstance(transcript, str) or not Path(transcript).is_absolute()
            or not isinstance(cwd, str) or not Path(cwd).is_absolute()
            or event.get("hook_event_name") != "SessionStart"
            or event.get("source") not in ("startup", "resume")
            or event.get("cwd") != cwd
            or receipt.get("expected") not in (None, sid)):
        return None
    if record.get("id_source") == SOURCE and record.get("conversation") != sid:
        return None
    try:
        with Path(transcript).open(encoding="utf-8") as fh:
            meta = json.loads(fh.readline())
        if (meta.get("type") == "session_meta" and meta["payload"].get("id") == sid
                and meta["payload"].get("cwd") == receipt["cwd"]):
            return sid
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return None


def transcript(record, cwd, conversation):
    """The rollout file the new orchestrator reads the last exchange from.

    Codex names it through the seat's home, whose `sessions` is a link the seat's removal takes
    away; where the link leads stays (tools/codex-seat.py `seat_home`), so that is the path."""
    if not conversation:
        return None
    event = read(record).get("event") or {}
    path = event.get("transcript_path")
    return str(Path(path).resolve()) if isinstance(path, str) and path else None


def prompt(entry):
    """The owner's words one rollout line holds, or None for anything else."""
    payload = entry.get("payload")
    # Response items also contain rules and environment text with the user role.
    # The completed UserMessage item keeps the original prompt exactly once.
    if (entry.get("type") != "event_msg" or not isinstance(payload, dict)
            or payload.get("type") != "item_completed"):
        return None
    item = payload.get("item")
    if not isinstance(item, dict) or item.get("type") != "UserMessage":
        return None
    content = item.get("content")
    if not isinstance(content, list):
        return None
    return "\n".join(part["text"] for part in content if isinstance(part, dict)
                     and part.get("type") == "text" and isinstance(part.get("text"), str)) or None


def user_messages(record, cwd, conversation):
    from . import entries, user_message
    for entry in entries(transcript(record, cwd, conversation)):
        kept = user_message(entry.get("timestamp"), prompt(entry))
        if kept:
            yield kept


def error(record, cwd, conversation):
    """The error Codex recorded as the end of that thread's last turn, or None.

    A turn that failed ends in a `task_complete` event whose `error` holds the message the seat
    showed; a `task_started` after it is a newer prompt.  The last item of a turn still in
    flight says the same, and spares reading the whole turn back to its start.
    """
    from . import last_entry

    def turn(entry):
        payload = entry.get("payload")
        return entry.get("type") == "response_item" or (
            entry.get("type") == "event_msg" and isinstance(payload, dict)
            and payload.get("type") in ("task_started", "task_complete"))
    path = transcript(record, cwd, conversation)
    entry = path and last_entry(path, turn)
    payload = entry.get("payload") if entry and entry.get("type") == "event_msg" else None
    failed = payload.get("error") if payload and payload.get("type") == "task_complete" else None
    message = failed.get("message") if isinstance(failed, dict) else None
    return message.strip() or None if isinstance(message, str) else None


def forget(record):
    """Local cleanup always completes; a failed enrollment DELETE is retried later.

    A seat whose pane already exited deletes its enrollment inline, but chatgpt.com
    may be unreachable or still see the server as online (HTTP 409). Either way the
    home stays behind with its .forgotten marker and deletion receipt, and every
    forget retries all such homes, so `ak stop` never fails on a network error and
    enrollments cannot pile up silently.
    """
    homes = []
    remote = read(record).get("remote")
    if isinstance(remote, str) and re.fullmatch(r"[0-9a-f]{32}", remote):
        homes.append(remote_home(remote))
    for marker in sorted(config.STATE.glob("codex-remote-*.forgotten")):
        if (home := marker.with_suffix("")) not in homes:
            homes.append(home)
    for home in homes:
        try:
            subprocess.run([sys.executable, str(config.REPO / "tools/codex-seat.py"),
                            "--forget", str(home)], check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"orch: Codex remote cleanup for {home.name} failed ({exc}); "
                  "its enrollment stays until the next forget", file=sys.stderr)
    path = path_for(record)
    if path:
        path.unlink(missing_ok=True)


def title_command(name):
    return f"/rename {name}"


def title_ready(record, state):
    if not conversation(record):
        return False
    # Inline /rename works during a turn, but a cleared composer alone can also be a
    # refusal. Without its receipt, wait for the prompt before spending another try.
    attempt = record.get("title_sync") or {}
    return not (state == "working" and attempt.get("tries")
                and not attempt.get("pending", True))


def title_restores(record, title):
    """Whether an acknowledged name absent from the index needs retyping.

    Codex's own naming replaces ak's /rename after the first prompt. An empty receipt
    means the seat's name is gone from its thread; restore it with the same retry cap.
    """
    return title == ""


def session_title(record):
    """Acknowledge ak's names only: Codex stores generated and /rename names alike."""
    sid = conversation(record)
    if not sid:
        return None
    receipt = read(record)
    account = record.get("account")
    home = receipt.get("home") or str(Path.home() / (
        f".codex-{account}" if account and account != config.DEFAULT_ACCOUNT else ".codex"))
    title = ""
    try:
        with (Path(home) / "session_index.jsonl").open(encoding="utf-8") as index:
            for line in index:
                if not line.endswith("\n"):
                    break  # an append in progress is not a receipt yet
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and entry.get("id") == sid:
                    value = entry.get("thread_name")
                    if isinstance(value, str):
                        title = value if value.strip() else ""
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeError):
        return None
    return title if title in (record.get("session_title"),
                              (record.get("title_sync") or {}).get("name")) else ""


def prepare(name, cwd, owned):
    """Save a unique launch receipt before starting the TUI. Preserve previous evidence."""
    record = config.session_records().get(name, {})
    if owned and conversation(record) != owned:
        raise config.Error("Codex ownership changed before launch; reopen the seat to start fresh")
    previous = read(record)
    history = list(record.get("codex_history", []))
    if not owned and (record.get("conversation") or record.get("codex_launch")):
        history.append({key: record[key] for key in
                        ("conversation", "id_source", "codex_launch") if key in record}
                       | {"receipt": previous})
    token = uuid.uuid4().hex
    path = path_for({"codex_launch": token})
    # A resumed thread retains its original transcript cwd even if its checkout was removed.
    receipt = {"launch": token, "cwd": previous.get("cwd", str(Path(cwd).resolve()))
               if owned else str(Path(cwd).resolve()), "expected": owned}
    receipt["remote"] = previous.get("remote") or uuid.uuid4().hex
    if owned:
        receipt["event"] = previous["event"]
        if previous.get("home"):
            receipt["home"] = previous["home"]
    with path.open("x", encoding="utf-8") as fh:
        os.chmod(path, 0o600)
        json.dump(receipt, fh)
    config.update_session(name, codex_launch=token, codex_history=history or None,
                          conversation=owned, id_source=SOURCE if owned else None,
                          resumable=bool(owned))
    old_path = path_for(record)
    if old_path:
        old_path.unlink(missing_ok=True)
    return path


def resumable(record, cwd, conversation):
    """The receipt is the whole answer: a recorded thread alone is not one to resume into."""
    return bool(conversation)


def restart_word(record):
    """A seat whose thread is not proven comes back under its name with no past."""
    return FRESH


def reconcile(record):
    """Keep the evidence, but claim resumability only with a verified launch receipt.

    Unbound legacy ids remain in the record for diagnosis, never for resumption.
    """
    thread = conversation(record)
    fields = {"resumable": bool(thread)}
    if thread:
        fields.update(conversation=thread, id_source=SOURCE)
    return fields


def launched(name, cwd, conversation):
    """A receipt of this invocation's own, for the TUI's SessionStart hook to populate."""
    return {RECEIPT_ENV: str(prepare(name, cwd, conversation))}


def capture(path, event):
    """Record harness input, never an invented id. Conflicting starts invalidate the receipt."""
    if not isinstance(event, dict) or event.get("hook_event_name") != "SessionStart":
        return
    try:
        # In-place under a lock: unlinking on stop wins even if this hook is already running.
        # The hook never creates a file, and only its launch's receipt can be changed.
        with Path(path).open("r+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            receipt = json.load(fh)
            old = receipt.get("event")
            if old and old != event:
                if any(old.get(k) != event.get(k) for k in
                       ("session_id", "transcript_path", "cwd")):
                    receipt["ambiguous"] = True
            else:
                receipt["event"] = event
            # The callback runs under the TUI's actual login, including CODEX_HOME.
            receipt["home"] = str(Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve())
            fh.seek(0)
            json.dump(receipt, fh)
            fh.truncate()
    except (OSError, ValueError, TypeError, AttributeError):
        return


def trust(hooks):
    """The `-c` that trusts exactly these command-line hooks, and nobody else's.

    Codex 0.160 runs a hook only once its hash is trusted and otherwise stops a new seat on
    "Hooks need review" for nobody.  It reads that trust from the command line as well as
    from the user's config.toml, keyed by layer, event, group and position, and hashes the
    hook's sorted JSON (`hook_hash` in codex-rs/hooks/src/engine/discovery.rs).
    """
    state = {}
    for event, handlers in hooks.items():
        label = re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()
        for position, (command, timeout) in enumerate(handlers):
            identity = {"event_name": label, "hooks": [
                {"async": False, "command": command, "timeout": timeout, "type": "command"}]}
            digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"),
                                               ensure_ascii=False).encode()).hexdigest()
            state[f"/<session-flags>/config.toml:{label}:0:{position}"] = "sha256:" + digest
    return "hooks.state={" + ",".join(f"{json.dumps(key)}={{trusted_hash={json.dumps(value)}}}"
                                      for key, value in state.items()) + "}"


def mcp_block(servers):
    """`servers` as the one marked block of ~/.codex/config.toml that `register_mcp` keeps."""
    def string(value):      # a TOML basic string: paths and flags escape as JSON's do
        return json.dumps(value)
    lines = [BEGIN]
    for name, server in servers.items():
        lines.append(f"[mcp_servers.{name}]")
        if "url" in server:
            lines.append(f"url = {string(server['url'])}")
        else:
            env = ", ".join(f"{key} = {string(value)}" for key, value in sorted(server["env"].items()))
            lines += [f"command = {string(server['command'])}",
                      "args = [" + ", ".join(string(arg) for arg in server["args"]) + "]",
                      "env = { " + env + " }"]
        lines.append("")
    return "\n".join([*lines, END]) + "\n"


def config_entries():
    """~/.codex/config.toml: `register_mcp` and `trust_here` write there."""
    return {"file": Path.home() / ".codex" / "config.toml", "trust": "projects",
            "mcp": "mcp_servers"}


def register_mcp(servers):
    """Keep `servers` in one marked block of ~/.codex/config.toml, and nothing else.

    A block, not a rewrite: install.sh and codex itself both own keys in this file, and a
    round trip through a TOML writer would lose their comments and their ordering.  A
    `[mcp_servers.browser]` somebody wrote by hand outside the block is an error rather than a
    second one appended, because two tables of the same name do not parse at all.  A marker
    counts only as a line of its own, so a comment quoting one is no block; and the new file
    must parse to the old one with only these servers and the old block's changed, or nothing
    is written.
    """
    path = config_entries()["file"]
    raw = ""
    before = {}
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise config.Error(f"cannot read {path}: {exc}") from None
        try:
            before = tomllib.loads(raw)
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            raise config.Error(f"{path} is not valid TOML, so nothing was changed: {exc}")
    block, ours = mcp_block(servers), set(servers)
    lines = raw.splitlines(keepends=True)
    begins, ends = ([i for i, line in enumerate(lines) if line.strip() == marker]
                    for marker in (BEGIN, END))
    if begins or ends:
        if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0]:
            raise config.Error(f"{path} has half of the agentkit block or more than one; repair "
                               f"or delete the lines from {BEGIN!r} to {END!r} and run this again")
        start, stop = begins[0], ends[0] + 1
        try:        # the servers the old block held are ours to replace, renamed ones too
            held = tomllib.loads("".join(lines[start:stop])).get("mcp_servers")
        except tomllib.TOMLDecodeError:
            held = None
        ours |= set(held) if isinstance(held, dict) else set()
        head, tail = "".join(lines[:start]), "".join(lines[stop:]).lstrip("\n")
        text = head + block + ("\n" + tail if tail else "")
    else:
        clash = sorted(set(before.get("mcp_servers", {})) & set(servers))
        if clash:
            raise config.Error(f"{path} already defines mcp_servers."
                               f"{', mcp_servers.'.join(clash)} outside the agentkit block; "
                               "remove those tables and run this again")
        text = (raw.rstrip("\n") + "\n\n" if raw.strip() else "") + block
    try:
        result = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:      # a bug here, caught before it lands on disk
        raise config.Error(f"the block this would write does not parse: {exc}")
    if set(result.get("mcp_servers", {})) < set(servers):
        raise config.Error(f"{path}: the block did not take effect")
    if _outside(result, ours) != _outside(before, ours):
        raise config.Error(f"{path}: registering would change settings outside the agentkit "
                           f"block, so nothing was changed; move them out from between "
                           f"{BEGIN!r} and {END!r} and run this again")
    if text == raw:
        return f"already registered in {path}"
    _replace(path, text)
    return f"registered in {path}"


def _outside(data, names):
    """A parsed config less the MCP servers in `names`: what registering them leaves alone."""
    servers = data.get("mcp_servers")
    if not isinstance(servers, dict):
        return data
    kept = {name: entry for name, entry in servers.items() if name not in names}
    rest = {key: value for key, value in data.items() if key != "mcp_servers"}
    return {**rest, "mcp_servers": kept} if kept else rest


def _replace(path, text, mode=0o600):
    """Replace a config file without ever leaving a half-written one behind."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        mode = path.stat().st_mode & 0o777
    temp = path.with_name(path.name + ".ak-tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        temp.chmod(mode)
        temp.replace(path)
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise config.Error(f"cannot write {path}: {exc}") from None


def trust_here():
    """Mark the launch's cwd trusted in ~/.codex/config.toml, which every account's home links
    to, so the seat opens on its prompt rather than on "do you trust this folder?".

    Appended, never rewritten: the file is the user's.  Read first, so a directory trusted in
    any spelling -- its own table, a key under `[projects]`, an inline table -- gets no second
    table, which would leave a file Codex cannot parse; one that does not parse is Codex's to
    report, and stays as it is.  The appended file must parse too: a `projects` kept as an
    inline table cannot take another table, so the file stays and Codex asks for itself.  So
    does a file this cannot read or write: the trust only spares the seat Codex's question.
    """
    path, here = config_entries()["file"], str(Path.cwd().resolve())
    entry = f"\n[projects.{json.dumps(here, ensure_ascii=False)}]\ntrust_level = \"trusted\"\n"
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        projects = tomllib.loads(text).get("projects", {})
        if not isinstance(projects, dict) or here in projects:
            return
        tomllib.loads(text + entry)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(entry)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return


def main(argv, launch=None):
    if argv == ["capture"]:
        try:
            path = os.environ.get(CAPTURE_ENV)
            if path:
                capture(path, json.load(sys.stdin))
        except ValueError:
            pass
        return 0
    rulebook = None
    if argv[:1] == ["--rulebook"] and len(argv) > 1:
        rulebook, argv = argv[1], argv[2:]
    if not argv or argv[0] != "--" or len(argv) < 2:
        raise config.Error("usage: codex-seat.py [--rulebook <file>] -- <codex command> | capture")
    cmd = argv[1:]
    trust_here()
    if os.environ.get(config.ACCOUNT_ENV):
        # A named CODEX_HOME must use its own file login, never the default Keychain
        # entry, and trust must apply in this invocation's config as well.
        cmd += ["-c", 'cli_auth_credentials_store="file"', "-c",
                f'projects.{json.dumps(str(Path.cwd().resolve()))}.trust_level="trusted"']
    if rulebook:
        # The rulebook this seat is launched with.  Codex takes per-launch instructions only as
        # a config value, so the file's text goes in as one more -c here, where this launch's
        # other overrides are added -- never as a file of the user's that every Codex reads.
        # Unreadable, and codex is not started at all: a seat that came up without the rules it
        # was launched with would look like every other seat and work to nobody's rules.
        try:
            cmd += ["-c", "developer_instructions=" + Path(rulebook).read_text()]
        except OSError as exc:
            raise config.Error(f"cannot read this seat's rulebook {rulebook}: {exc}")
    # Only this invocation installs a hook. A nested adapter launch clears the callback target
    # and needs its own receipt to install another, even when it inherits the parent's env.
    receipt = os.environ.pop(RECEIPT_ENV, None)
    os.environ.pop(CAPTURE_ENV, None)
    if receipt:
        try:
            help_text = subprocess.run([cmd[0], "--help"], capture_output=True,
                                       text=True, timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            help_text = ""
        if "--dangerously-bypass-hook-trust" in help_text:
            # CLI overrides form their own hook layer; existing configured hooks still run.
            # The help flag is a capability check only: never bypass trust for other hooks.
            hooks = {"SessionStart": [(shlex.join(
                [sys.executable, str(config.REPO / "tools/codex-seat.py"), "capture"]), 5)]}
            # The same launch carries the seat-state hooks: the events 0.153.x emits that say
            # what this seat is doing.  They go here rather than into ~/.codex/config.toml
            # because that file is the user's.  What each event means is
            # adapters/codex.toml's to say; that script only writes down what arrived.  The
            # end-of-turn rule rides the Stop layer beside it, and is the one that decides.
            # 3s, not the receipt hook's 5: Interrupt is capped there and 0.153.4 prints a
            # clamping warning into the seat on every launch that asks for more
            seat = (shlex.join(["bash", str(config.REPO / "hooks/seat-state.sh")]), 3)
            hooks.update((event, [seat]) for event in SEAT_EVENTS)
            hooks["Stop"].append((shlex.join(["bash", str(config.REPO / STOP_RULE)]), 3))
            os.environ[CAPTURE_ENV] = receipt
            for event, handlers in hooks.items():
                run = ",".join(f'{{type="command",command={json.dumps(command)},timeout={timeout}}}'
                               for command, timeout in handlers)
                cmd += ["-c", f'hooks.{event}=[{{hooks=[{run}]}}]']
            cmd += ["-c", trust(hooks)]
        else:
            print("orch: Codex cannot capture seat ownership on this version; "
                  "an unbound seat starts fresh next time", file=sys.stderr)
    if launch and receipt and os.environ.get(CAPTURE_ENV):
        return launch(cmd, receipt)
    os.execvp(cmd[0], cmd)
