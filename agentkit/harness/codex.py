"""A Codex seat owns only the thread reported by its own launch's SessionStart hook.

Receipts are separate from session records so a late hook cannot undo a rename, overwrite
the menu's state, or recreate a stopped seat. No directory or timestamp search is involved.

This is also where the harness hooks the core asks for live -- `conversation`, `resumable`,
`reconcile`, `restart_word`, `launched`, `forget` -- because every one of them is that
receipt: a Codex thread is this seat's only where its own launch reported it.
"""

import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
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


def seat_auth(account):
    """Named seats use file-only logins; the worker adapter still uses the usual login."""
    if account in (None, config.DEFAULT_ACCOUNT):
        from .. import worker
        return worker.auth_ok("codex", seat=True, account=account)
    path = Path.home() / f".codex-{account}" / "auth.json"
    why = f"codex: no valid seat login in {path}"
    try:
        data = json.loads(path.read_text())
        tokens = data.get("tokens") or {}
        token = tokens.get("access_token") or data.get("access_token")
        expires = tokens.get("expires_at", data.get("expires_at"))
        if not isinstance(token, str) or not token:
            return False, why
        if expires is not None:
            if not str(expires).isdigit():
                return False, why
            until = int(expires) // (1000 if len(str(expires)) > 11 else 1)
            if until <= time.time():
                return False, why
    except (OSError, ValueError, AttributeError):
        return False, why
    return True, f"codex: seat login in {path}"


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
        homes.append(config.STATE / f"codex-remote-{remote}")
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
            hook = shlex.join([sys.executable, str(config.REPO / "tools/codex-seat.py"),
                               "capture"])
            # CLI overrides form their own hook layer; existing configured hooks still run.
            # Keep the definition stable across launches so normal hook trust can be reused.
            # The help flag is a capability check only: never bypass trust for other hooks.
            inline = ('hooks.SessionStart=[{hooks=[{'
                      'type="command",command=' + json.dumps(hook) + ',timeout=5}]}]')
            os.environ[CAPTURE_ENV] = receipt
            cmd += ["-c", inline]
            # The same launch carries the seat-state hooks: the events 0.153.x emits that say
            # what this seat is doing.  They go here rather than into ~/.codex/config.toml
            # because that file is the user's, and a hook layer added on the command line is
            # trusted once with the receipt hook instead of twice.  What each event means is
            # adapters/codex.toml's to say; that script only writes down what arrived.  The
            # end-of-turn rule rides the Stop layer beside it, and is the one that decides.
            seat = shlex.join(["bash", str(config.REPO / "hooks/seat-state.sh")])
            for event in SEAT_EVENTS:
                scripts = [seat]
                if event == "Stop":
                    scripts.append(shlex.join(["bash", str(config.REPO / STOP_RULE)]))
                # 3s, not the receipt hook's 5: Interrupt is capped there and 0.153.4 prints a
                # clamping warning into the seat on every launch that asks for more
                run = ",".join(f'{{type="command",command={json.dumps(script)},timeout=3}}'
                               for script in scripts)
                cmd += ["-c", f'hooks.{event}=[{{hooks=[{run}]}}]']
        else:
            print("orch: Codex cannot capture seat ownership on this version; "
                  "an unbound seat starts fresh next time", file=sys.stderr)
    if launch and receipt and os.environ.get(CAPTURE_ENV):
        return launch(cmd, receipt)
    os.execvp(cmd[0], cmd)
