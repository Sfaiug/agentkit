"""A Codex seat owns only the thread reported by its own launch's SessionStart hook.

Receipts are separate from session records so a late hook cannot undo a rename, overwrite
the menu's state, or recreate a stopped seat. No directory or timestamp search is involved.

This is also where the harness hooks the core asks for live -- `conversation`, `resumable`,
`reconcile`, `restart_word`, `launched`, `forget` -- because every one of them is that
receipt: a Codex thread is this seat's only where its own launch reported it.
"""

import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import socket
import struct
import subprocess
import sys
import time
import tomllib
import uuid

from .. import config

RECEIPT_ENV = "AGENTKIT_CODEX_RECEIPT"
CAPTURE_ENV = "AGENTKIT_CODEX_CAPTURE"
SOURCE = "codex-session-start"
# The lifecycle hooks Codex 0.153.4 defines that name a state; adapters/codex.toml maps them,
# and the script they run writes down what arrived.
SEAT_EVENTS = ("UserPromptSubmit", "Stop", "Interrupt", "PermissionRequest")
SEAT_STATE = "hooks/seat-state.sh"
# ... and what rides the end of a turn beside them.  Codex documents a blocking Stop hook
# (learn.chatgpt.com/docs/hooks#stop), and 0.153.4's own `stop.command.output` schema is
# Claude's -- a `decision` of `block` with the `reason` beside it -- so the end-of-turn rule is
# the one script on both harnesses.
STOP_RULE = "hooks/orchestrator-stop.sh"
# Codex's default command deadline; only Interrupt has its separate three-second cap.
# Callbacks stay ordered: a late tool completion must not clear a newer question.
HOOK_TIMEOUT = 600
# Native async cards can disappear at a turn boundary. Record the questions before allowing
# the cards through, and resolve only the reply items the owner actually submits.
QUESTION_TOOL = "request_user_input_async"
# A Plan-mode turn asks with `request_user_input`, which waits in a dialog of the seat's own: its
# PreToolUse is the seat asking.  One group takes both tools, as Codex reads a matcher as a regex.
QUESTIONS = "request_user_input(_async)?"
FRESH = "Codex ownership unverified; starts fresh"
BEGIN = "# --- agentkit browser bridge: managed by `ak browser mcp-register` ---"
END = "# --- end agentkit browser bridge ---"


def token_counts(run_dir):
    """Kept Codex turns as (events file, thread total, turn spend), in reporting order."""
    from .. import history

    previous = {}
    for path in history.event_paths(run_dir):
        thread = None
        try:
            with path.open(errors="replace") as source:
                for line in source:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict) and event.get("type") == "thread.started":
                        thread = event.get("thread_id")
                        break
        except OSError:
            continue
        if not isinstance(thread, str) or not thread:
            continue
        total = history.event_tokens(path)
        if total is not None:
            spent = max(0, total - previous.get(thread, 0))
            previous[thread] = total
            yield path, total, spent


def tokens(out):
    """Codex reports the thread's running total; only its increase belongs to this turn."""
    from .. import history
    events = Path(out) / "events.jsonl"
    for path, _, spent in token_counts(events.parent.parent.parent):
        if path == events:
            return spent
    return history.event_tokens(events)


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


def seat_token_sources(record):
    from . import token_family
    receipt = read(record)
    path = (receipt.get("event") or {}).get("transcript_path")
    paths = [Path(path)] if path and Path(path).is_file() else []
    # A remote seat's private store holds its threads and their subagents, on every login.
    if receipt.get("remote"):
        paths.extend(seat_conversations(receipt["remote"]).rglob("rollout-*.jsonl"))
    elif record.get("conversation"):
        def metadata(entry):
            meta = entry["payload"]
            source = meta.get("source")
            subagent = source.get("subagent") if isinstance(source, dict) else None
            parent = (subagent or {}).get("thread_spawn") or {}
            return meta["id"], parent.get("parent_thread_id")
        root = Path.home() / ".codex"
        candidates = [path for folder in ("sessions", "archived_sessions")
                      for path in (root / folder).rglob("rollout-*.jsonl")]
        paths.extend(token_family(candidates, [record.get("conversation")], metadata))
    return paths


def seat_token_usage(entry, cursor):
    from . import moment
    payload = entry.get("payload") or {}
    if entry.get("type") != "event_msg" or payload.get("type") != "token_count":
        return None
    total = ((payload.get("info") or {}).get("total_token_usage") or {}).get("total_tokens")
    if type(total) is int and total >= 0 and moment(entry.get("timestamp")) is not None:
        previous = cursor.get("total", 0)
        cursor["total"] = max(previous, total)
        return entry["timestamp"], f"{Path(cursor['source']).name}:{total}", max(0, total - previous)


def prompt(entry):
    """The owner's words one rollout line holds, or None for anything else."""
    # Response items also contain rules and environment text with the user role.
    # The completed UserMessage item keeps the original prompt exactly once.
    return completed(entry, "UserMessage")


def answer(entry):
    """The model's visible words one rollout line holds, commentary or final, or None."""
    return completed(entry, "AgentMessage")


def completed(entry, kind):
    """The text of the completed item of that kind one rollout line holds, or None."""
    payload = entry.get("payload")
    if (entry.get("type") != "event_msg" or not isinstance(payload, dict)
            or payload.get("type") != "item_completed"):
        return None
    item = payload.get("item")
    if not isinstance(item, dict) or item.get("type") != kind:
        return None
    content = item.get("content")
    if not isinstance(content, list):
        return None
    # A UserMessage's parts are `text`, an AgentMessage's `Text` (Codex 0.163).
    return "\n".join(part["text"] for part in content if isinstance(part, dict)
                     and part.get("type") in ("text", "Text")
                     and isinstance(part.get("text"), str)) or None


def said(record, cwd, conversation):
    from . import turns
    return turns(transcript(record, cwd, conversation), prompt, answer)


def user_messages(record, cwd, conversation):
    from . import entries, user_message
    calls = {}
    for entry in entries(transcript(record, cwd, conversation)):
        payload = entry.get("payload")
        if (entry.get("type") == "response_item" and isinstance(payload, dict)
                and payload.get("type") == "function_call"
                and str(payload.get("name", "")).split(".")[-1] == QUESTION_TOOL):
            try:
                asked = json.loads(payload["arguments"])["questions"]
                if isinstance(asked, list) and all(isinstance(q, dict) for q in asked):
                    calls[payload["call_id"]] = asked
            except (KeyError, TypeError, ValueError):
                pass
        kept = user_message(entry.get("timestamp"), prompt(entry))
        if kept:
            if kept["text"].startswith("<send_user_message_question_reply>"):
                # Codex 0.163's submitted card reply names its call and question index.
                # A skipped/expired card emits no such owner message. Bad ids answer none.
                kept["replies"] = []
                try:
                    body, closing, rest = kept["text"].rpartition("</send_user_message_question_reply>")
                    replies = json.loads(body.split(">", 1)[1]) if closing and not rest.strip() else []
                except (IndexError, ValueError):
                    replies = []
                for reply in replies if isinstance(replies, list) else ():
                    try:
                        tool, call, index = json.loads(reply["questionItemId"])
                        if (tool == QUESTION_TOOL and type(index) is int and index >= 0
                                and index < len(calls[call])
                                and isinstance(reply.get("answer"), str) and reply["answer"].strip()):
                            kept["replies"].append(question_id(call, index))
                    except (KeyError, IndexError, TypeError, ValueError):
                        continue
            yield kept


def error(record, cwd, conversation):
    """The error Codex recorded as the end of that thread's last turn, "" where none ends it,
    or None where it has no rollout.

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
    if not path:
        return None
    entry = last_entry(path, turn)
    payload = entry.get("payload") if entry and entry.get("type") == "event_msg" else None
    failed = payload.get("error") if payload and payload.get("type") == "task_complete" else None
    message = failed.get("message") if isinstance(failed, dict) else None
    return message.strip() if isinstance(message, str) else ""


def running(record, cwd, conversation):
    """The model and effort of the turn that holds that thread's latest answer, with that
    answer's time: Codex records them as a turn starts (`turn_context`), so `/model` typed in
    the seat shows at its next answer, and a turn that never answered shows nothing."""
    from . import last_entry, moment
    answered = None

    def pick(entry):
        # read back from the end: the latest answer first, then the start of its turn
        nonlocal answered
        if answered is None and answer(entry):
            answered = entry
        return (answered is not None and entry.get("type") == "turn_context"
                and isinstance(entry.get("payload"), dict)
                and isinstance(entry["payload"].get("model"), str))
    path = transcript(record, cwd, conversation)
    entry = path and last_entry(path, pick)
    return ((entry["payload"]["model"], entry["payload"].get("effort"),
             moment(answered.get("timestamp"))) if entry else None)


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
    retire(record)


def retire(record):
    """Drop that launch's receipt alone: the remote home is the seat's, and outlives a launch."""
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
                same_path = old.get("transcript_path") == event.get("transcript_path")
                if not same_path:
                    # Codex resolves the launch's transcript symlink when it resumes.
                    try:
                        same_path = os.path.samefile(old.get("transcript_path"),
                                                    event.get("transcript_path"))
                    except (OSError, TypeError, ValueError):
                        pass
                if not same_path or any(old.get(k) != event.get(k)
                                        for k in ("session_id", "cwd")):
                    receipt["ambiguous"] = True
            # Compaction also emits SessionStart, but cannot replace ownership evidence.
            if not receipt.get("ambiguous") and event.get("source") in ("startup", "resume"):
                receipt["event"] = event
            # The callback runs under the TUI's actual login, including CODEX_HOME.
            receipt["home"] = str(Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve())
            fh.seek(0)
            json.dump(receipt, fh)
            fh.truncate()
    except (OSError, ValueError, TypeError, AttributeError):
        return


class Client:
    """The Unix transport is WebSocket, including its HTTP upgrade and masking."""
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(15)
        self.buffer = b""
        self.serial = 0
        try:
            self.socket.connect(path)
            key = base64.b64encode(os.urandom(16)).decode()
            self.socket.sendall((f"GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                                 f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                                 "Sec-WebSocket-Version: 13\r\n\r\n").encode())
            while b"\r\n\r\n" not in self.buffer:
                self.more()
                if len(self.buffer) > 65536:
                    raise config.Error("Invalid Codex socket handshake")
            head, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
            accept = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
            if not head.startswith(b"HTTP/1.1 101 ") or accept not in head:
                raise config.Error("Codex socket did not accept WebSocket upgrade")
            self.call("initialize", {"clientInfo": {"name": "agentkit", "version": "1"},
                                     "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized"})
        except BaseException:
            self.close()
            raise

    def more(self):
        chunk = self.socket.recv(65536)
        if not chunk:
            raise config.Error("Codex app server closed its socket")
        self.buffer += chunk

    def read(self, size):
        while len(self.buffer) < size:
            self.more()
        data, self.buffer = self.buffer[:size], self.buffer[size:]
        return data

    def send(self, value, opcode=1):
        data = json.dumps(value).encode() if opcode == 1 else value
        size, mask = len(data), os.urandom(4)
        header = bytes([128 | opcode, 128 | size]) if size < 126 else (
            bytes([128 | opcode, 254]) + struct.pack("!H", size))
        self.socket.sendall(header + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def receive(self):
        fragments = bytearray()
        while True:
            first, second = self.read(2)
            size = second & 127
            if size == 126:
                size = struct.unpack("!H", self.read(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.read(8))[0]
            if second & 128 or size + len(fragments) > 16 * 1024 * 1024:
                raise config.Error("Invalid Codex WebSocket frame")
            data = self.read(size)
            opcode = first & 15
            if opcode == 8:
                raise config.Error("Codex app server closed its connection")
            if opcode == 9:
                self.send(data, 10)
            elif opcode in (0, 1):
                fragments.extend(data)
                if first & 128:
                    return json.loads(fragments)

    def call(self, method, params=None):
        self.serial += 1
        self.send({"id": self.serial, "method": method, "params": params})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            self.socket.settimeout(max(.01, deadline - time.monotonic()))
            message = self.receive()
            if message.get("id") == self.serial:
                if "error" in message:
                    raise config.Error(message["error"]["message"])
                return message["result"]
        raise config.Error(f"Codex app server did not answer {method}")

    def close(self):
        self.socket.close()


def in_flight(client, thread):
    """The background work the seat's thread still runs, in the shape Claude Code hands its Stop
    hook, read through `client` on the seat's app server, the one place 0.163 lists it: its
    background terminals (`unified_exec`) and the sub-agents it spawned, at any depth, still
    working (`multi_agent`).  0.163 wakes the seat for neither once it ends -- a terminal's exit
    is an event and no turn (core/src/unified_exec/async_watcher.rs), a sub-agent's result waits
    for the seat's next turn (core/src/agent/control.rs, `trigger_turn` false) -- so each is a
    `terminal` or an `agent`, held and never waited on (hooks/orchestrator-stop.sh)."""
    def pages(method, params):
        found, cursor = [], None
        while True:
            page = client.call(method, {**params, "cursor": cursor})
            found += page["data"]
            cursor = page.get("nextCursor")
            if not cursor:
                return found
    terminals = pages("thread/backgroundTerminals/list", {"threadId": thread})
    agents = pages("thread/list", {"ancestorThreadId": thread,
                                   "sourceKinds": ["subAgentThreadSpawn"]})
    return ([{"id": t["processId"], "type": "terminal", "status": "running",
              "description": t["command"]} for t in terminals]
            + [{"id": a["id"], "type": "agent", "status": "running",
                "description": a.get("agentNickname") or a["preview"]}
               for a in agents if a["status"]["type"] == "active"])



def holds(record):
    """The type of each piece of background work that seat's thread runs now (`in_flight`),
    asked of its own app server, through the connection its launch writes in the seat's home
    (tools/codex-seat.py `connected`), or None where that server cannot be asked: no work's end
    starts a turn whose Stop would list it afresh."""
    thread = conversation(record)
    try:
        with (remote_home(read(record)["remote"]) / "connection.json").open() as fh:
            client = Client(json.load(fh)["socket"])
        try:
            return [task["type"] for task in in_flight(client, thread)] if thread else None
        finally:
            client.close()
    except (OSError, ValueError, KeyError, TypeError, AttributeError, config.Error):
        return None

def trust(hooks, matchers=None):
    """The `-c` that trusts exactly these command-line hooks, and nobody else's.

    Codex 0.160 runs a hook only once its hash is trusted and otherwise stops a new seat on
    "Hooks need review" for nobody.  It reads that trust from the command line as well as
    from the user's config.toml, keyed by layer, event, group and position, and hashes the
    hook's sorted JSON (`hook_hash` in codex-rs/hooks/src/engine/discovery.rs), which holds
    its group's matcher where it has one (`matchers`, by event).
    """
    state = {}
    for event, handlers in hooks.items():
        label = re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()
        for position, (command, timeout) in enumerate(handlers):
            identity = {"event_name": label, "hooks": [
                {"async": False, "command": command, "timeout": timeout,
                 "type": "command"}]}
            if (matchers or {}).get(event):
                identity["matcher"] = matchers[event]
            digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"),
                                               ensure_ascii=False).encode()).hexdigest()
            state[f"/<session-flags>/config.toml:{label}:0:{position}"] = "sha256:" + digest
    return "hooks.state={" + ",".join(f"{json.dumps(key)}={{trusted_hash={json.dumps(value)}}}"
                                      for key, value in state.items()) + "}"


def ask(event):
    """Keep each async question before letting Codex draw its native cards. A completed
    plan still refuses unnecessary questions; recording failure asks the model to retry."""
    if not isinstance(event, dict) or not re.fullmatch(QUESTIONS, str(event.get("tool_name"))):
        return None
    if os.environ.get("AK_RUN_ROLE") == "worker" or not config.current_session():
        return None
    from .. import notify, stop
    try:
        refused = stop.question_refused(config.resolve_session(config.current_session()))
    except config.Error:
        refused = None
    if refused:
        return {"decision": "block", "reason": refused.rstrip(".")}     # Codex adds its own
    if event["tool_name"] != QUESTION_TOOL:
        return None
    questions = (event.get("tool_input") or {}).get("questions")
    texts = [(index, question_line(item)) for index, item in enumerate(questions)
             if isinstance(item, dict)] if isinstance(questions, list) else []
    try:
        for _, text in texts or [(None, "")]:
            notify.asks_first(text)
        with contextlib.redirect_stdout(sys.stderr):
            failed = any(notify.shaped("needs", text.strip(), question_id=question_id(
                event.get("tool_use_id"), index)) for index, text in texts)
    except config.Error as exc:
        # Codex adds its own period after the reason
        return {"decision": "block",
                "reason": f"ak did not ask the owner this: {str(exc).rstrip('.')}. Ask again"}
    if failed:
        return {"decision": "block", "reason": "ak could not record this question. Ask again"}
    return None


def answered(event):
    """Does that PostToolUse end a call while the seat's record holds a question -- one the
    owner's answer or approval let run, after which the turn runs on?  Only then is it news: any
    other call ends in a turn already running, or in one that ended -- a shell the owner's Esc
    left running, a sub-agent's call after the seat's Stop -- which it would bring back."""
    if (not isinstance(event, dict) or event.get("hook_event_name") != "PostToolUse"
            or os.environ.get("AK_RUN_ROLE") == "worker"):
        return False
    name = config.current_session()
    if not name:
        return False
    from .. import lifecycle
    return lifecycle.state("codex", lifecycle.facts(name))[0] == "asking"


def question_id(call, index):
    """The card's identity survives repeated wording and the turn's end."""
    return json.dumps([QUESTION_TOOL, call, index])


def question_line(item):
    """One question the tool was called with, as the owner reads it: its title, its options
    numbered after it, so a number answers it."""
    title = " ".join(str(item.get("title") or "").split())
    options = item.get("options")
    options = [" ".join(str(option).split()) for option in options
               if str(option).strip()] if isinstance(options, list) else []
    if not options:
        return title
    return f"{title} Options: " + " · ".join(f"{n}. {option}"
                                               for n, option in enumerate(options, 1))


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


ROLLOUT = re.compile(r"rollout-.+-([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.jsonl")


def conversation_stores():
    """~/.codex/sessions/YYYY/MM/DD, where Codex keeps every thread's rollout and never removes
    one, and each seat's sessions and archived_sessions, kept apart (`seat_conversations`).  An
    account's home links its own to the first."""
    seats = sorted(seat_conversations("*").parent.glob("*/"))
    return [{"root": root, "pattern": "*/*/*/rollout-*.jsonl"}
            for root in (Path.home() / ".codex" / "sessions",
                         *(seat / name for seat in seats
                           for name in ("sessions", "archived_sessions")))]


def end_conversation(path, ends):
    """`codex delete`, which takes a thread's rollout and what Codex indexed of it at once, run
    as Codex runs on the home that indexes it, whatever home and database the caller selected:
    ~/.codex, or an open seat's own (tools/codex-seat.py `connected`), never one reached through
    a link.  Nothing indexes a closed seat's thread, so its rollout goes alone."""
    from .. import retention
    path = Path(path)
    match = ROLLOUT.fullmatch(path.name)
    if not match:
        return
    folder = path.parents[4]
    remote = folder.name if seat_conversations(folder.name) == folder else None
    home = remote and remote_home(remote)
    if not ends():
        return
    if remote is None or retention.safe(home):
        env = {key: value for key, value in os.environ.items() if key != "CODEX_SQLITE_HOME"}
        env["CODEX_HOME"] = str(home or folder)
        database = ["-c", "sqlite_home=" + json.dumps(str(home))] if home else []
        subprocess.run([config.harness_binary("codex") or "codex", *database, "delete", "--force",
                        match[1]], stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
                       env=env, check=True)
    elif not os.path.lexists(home):
        path.unlink()
        drop_closed_seat(home)


def drop_closed_seat(home):
    """Every empty folder of the seat whose home (`remote_home`) is gone, bottom up, so its own
    goes once it holds no rollout: nothing indexes or reads it any more.  Asked as the home goes
    and as each of its rollouts does.  Never one reached through a link, whose folders are
    somebody else's."""
    from .. import retention
    folder = seat_conversations(home.name.removeprefix(remote_home("").name))
    if os.path.lexists(home) or not retention.safe(folder):
        return
    for directory, _, _ in os.walk(folder, topdown=False):
        with contextlib.suppress(OSError):
            os.rmdir(directory)


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


def first_prompt(cmd):
    """(options, prompt): a codex line split at the `--` before the seat's first message
    (adapters/codex.sh), so every option added to the line goes ahead of it."""
    at = cmd.index("--") if "--" in cmd else len(cmd)
    return cmd[:at], cmd[at:]


def main(argv, launch=None):
    if argv == ["capture"]:
        try:
            path = os.environ.get(CAPTURE_ENV)
            if path:
                capture(path, json.load(sys.stdin))
        except ValueError:
            pass
        return 0
    if argv == ["ask"]:
        payload = sys.stdin.read()
        try:
            answer = ask(json.loads(payload))
        except ValueError:
            answer = None
        if answer:
            print(json.dumps(answer))
        else:
            # the call goes up, so the seat asks: written down only now, as a refused one asks
            # nothing; stdout is Codex's to read the decision from, and nothing else
            try:
                subprocess.run(["bash", str(config.REPO / SEAT_STATE)], input=payload, text=True,
                               stdout=subprocess.DEVNULL)
            except OSError:
                pass
        return 0
    if argv == ["answered"]:
        payload = sys.stdin.read()
        try:
            if answered(json.loads(payload)):
                subprocess.run(["bash", str(config.REPO / SEAT_STATE)], input=payload, text=True)
        except (OSError, ValueError, config.Error):
            pass
        return 0
    rulebook = None
    if argv[:1] == ["--rulebook"] and len(argv) > 1:
        rulebook, argv = argv[1], argv[2:]
    if not argv or argv[0] != "--" or len(argv) < 2:
        raise config.Error("usage: codex-seat.py [--rulebook <file>] -- <codex command> | capture")
    cmd, prompt = first_prompt(argv[1:])
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
                [sys.executable, str(config.REPO / "tools/codex-seat.py"), "capture"]), HOOK_TIMEOUT)]}
            # The same launch carries the seat-state hooks: the events 0.153.x emits that say
            # what this seat is doing.  They go here rather than into ~/.codex/config.toml
            # because that file is the user's.  What each event means is
            # adapters/codex.toml's to say; that script only writes down what arrived.  A Stop
            # reaches it and the end-of-turn rule, the one that decides, with the background
            # work the seat holds added (tools/codex-seat.py `stop_hook`).
            # The script also rides SessionStart, where a compaction (0.160's `compact` source)
            # leaves the seat holding its launch's rulebook again (`orch.rulebook_compacted`).
            seat = (shlex.join(["bash", str(config.REPO / SEAT_STATE)]), HOOK_TIMEOUT)
            hooks.update((event, [seat]) for event in SEAT_EVENTS)
            hooks["Interrupt"] = [(seat[0], 3)]
            hooks["SessionStart"].append(seat)
            hooks["Stop"] = [(shlex.join(
                [sys.executable, str(config.REPO / "tools/codex-seat.py"), "stop"]), HOOK_TIMEOUT)]
            # The seat's question goes to its owner through ak (`ask`). A Plan-mode question
            # going up is written down by it, once it lets the call through, and a call's end
            # only while the seat's record holds a question (`answered`).
            hooks["PreToolUse"] = [(shlex.join(
                [sys.executable, str(config.REPO / "tools/codex-seat.py"), "ask"]), HOOK_TIMEOUT)]
            hooks["PostToolUse"] = [(shlex.join(
                [sys.executable, str(config.REPO / "tools/codex-seat.py"), "answered"]), HOOK_TIMEOUT)]
            matchers = {"PreToolUse": QUESTIONS}
            os.environ[CAPTURE_ENV] = receipt
            for event, handlers in hooks.items():
                run = ",".join(f'{{type="command",command={json.dumps(command)},timeout={timeout}}}'
                               for command, timeout in handlers)
                matcher = f"matcher={json.dumps(matchers[event])}," if event in matchers else ""
                cmd += ["-c", f'hooks.{event}=[{{{matcher}hooks=[{run}]}}]']
            cmd += ["-c", trust(hooks, matchers)]
        else:
            print("orch: Codex cannot capture seat ownership on this version; "
                  "an unbound seat starts fresh next time", file=sys.stderr)
    cmd += prompt
    if launch and receipt and os.environ.get(CAPTURE_ENV):
        return launch(cmd, receipt)
    os.execvp(cmd[0], cmd)
