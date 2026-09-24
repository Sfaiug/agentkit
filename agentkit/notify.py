"""Discord webhook notification.  The orchestrator's, and the orphaned run's.

Two shapes, both embeds: `ak notify needs "<question>"` when the orchestrator needs the user,
and `ak notify done "<summary>"` when the job is done.  Each records itself as the session's
last notification, which is what the menu shows as that session's state. `ak notify` records
the reason or declaration; the session-state transition sends the card.

Workers are silent by construction. A needs episode is sent once after it has stood for a minute
with no client attached. A done episode is sent once when the session state becomes done, and a
declaration once whatever episodes, or versions, it turns up in. Opening its seat or finishing
edits outstanding questions without pinging. Nothing is sent, or retried, for a seat the owner
closed himself, or for an episode that began before the agentkit running now was installed.

A run stays quiet while the orchestrator that launched it is alive to report it -- a job that
fans out into a dozen runs must not fan out into a dozen pings -- and speaks for itself only
when that seat is gone; a run nobody launched from a seat never speaks at all. Required events
are persisted before delivery and retried by `ak watch`. No webhook means exit 0 and a stderr
note; an unusable configured webhook or an event that cannot be persisted returns failure.
`--check` proves the webhook is live without posting anything.

A test never reaches the owner: $AK_NOTIFY_SINK, which the suites set around everything they
start, outranks the configured webhook -- a sink of the suite's own, or `dry-run`, which posts
nowhere -- and a post that was diverted says so on stderr.
"""

import fcntl
import hashlib
import json
import math
import mimetypes
import os
import secrets
import stat
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import command_help, config, retention

FILE_CAP = 8 * 1024 * 1024
UA = "agentkit/1 (+https://github.com)"
COLORS = {"needs": 0xF5A623, "done": 0x2ECC71, "fail": 0xE74C3C}   # amber, green, red
SUBJECT_CAP = 60   # a title the phone shows whole, when the task has to stand in for a session
TITLES = {"needs": "Needs you", "done": "Done"}
CARD_WAIT = 60
SINK_ENV = "AK_NOTIFY_SINK"   # the suites' destination; it outranks the owner's webhook
SINK_LOG_ENV = "AK_NOTIFY_SINK_LOG"   # where a diversion is written, for the suite to fail on
RETRY_BACKOFF = (60, 180, 600, 1800, 3600)
USAGE = command_help.NOTIFY_USAGE


def terminal_targets(session):
    """Visible panes on our server, once per window; never the seat being reported.

    A linked window shared with the source seat needs per-client output to suppress that
    seat's toast. Exited panes retain stale tty names, so their clients need direct output
    too. Otherwise pane output passes through tmux to every client viewing it.
    """
    from . import orch
    rc, output = orch.tmux_out("list-clients", "-F",
                               "#{client_tty}\t#{session_name}\t#{window_id}\t#{pane_tty}\t#{pane_dead}",
                               socket=orch.socket_name())
    if rc:
        return []
    clients = [parts + [""] * (5 - len(parts)) for line in output.splitlines()
               if 2 <= len(parts := line.split("\t")) <= 5]
    excluded = {window for _, attached, window, _, dead in clients
                if attached == session or dead != "0"}
    targets, seen = [], set()
    for tty, attached, window, pane, _ in clients:
        if not attached or attached == session:
            continue
        passthrough = bool(pane and window and window not in excluded)
        target = pane if passthrough else tty
        key = window if passthrough else tty
        if key not in seen and target.startswith("/dev/"):
            targets.append((target, passthrough))
            seen.add(key)
    return targets


def terminal_notice(session, text, dry_run=False, targets=None):
    """Best-effort OSC 9; never queue, retry or record terminal delivery.

    Write output to a pane tty, not input into its harness. For a client tty outside tmux's
    parser send the OSC itself; only pane output needs the DCS passthrough wrapper.
    """
    from . import orch
    if os.environ.get("AK_RUN_ROLE") == "worker":
        return False
    text = " ".join("".join(c if c.isprintable() else " " for c in text).split())[:1000]
    if dry_run:
        print(f"terminal notice: {text}", file=sys.stderr)
        return False
    sent = False
    osc = f"\033]9;{text}\007"
    targets = terminal_targets(session) if targets is None else targets
    if any(passthrough for _, passthrough in targets):
        # Also upgrade an already-running server that has not started a new seat yet.
        orch.tmux_out("set-option", "-g", "allow-passthrough", "on", socket=orch.socket_name())
    for tty, passthrough in targets:
        sequence = "\033Ptmux;" + osc.replace("\033", "\033\033") + "\033\\" if passthrough else osc
        try:
            fd = os.open(tty, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK | os.O_NOFOLLOW)
            try:
                if stat.S_ISCHR(os.fstat(fd).st_mode) and os.isatty(fd):
                    data = sequence.encode()
                    if os.write(fd, data) == len(data):
                        sent = True
            finally:
                os.close(fd)
        except OSError:
            pass
    return sent


def _secret(env_var, filename):
    """$env_var, else the one-line secrets file, else None."""
    value = os.environ.get(env_var)
    if value:
        return value.strip()
    path = config.SECRETS / filename
    if not path.exists():
        return None
    try:
        return path.read_text().strip() or None
    except OSError as exc:
        if filename == "discord_webhook":
            raise config.Error("notify: cannot read the configured webhook") from None
        print(f"notify: cannot read {path} ({exc})", file=sys.stderr)
        return None


def sink():
    """The suites' destination, or None outside a test.

    A test must never post to the owner's Discord, whatever webhook the environment it
    inherited happens to name: `AK_NOTIFY_SINK=<url>` posts there instead, and anything else
    -- `dry-run`, `off` -- posts nowhere at all.
    """
    return (os.environ.get(SINK_ENV) or "").strip() or None


def diverted(line):
    """Say it on stderr, and leave it where the suite's own accounting fails the gate on it.

    A test aiming at the owner's webhook is the failure rule 6 is about, so it may not be a
    warning nobody reads: `$AK_NOTIFY_SINK_LOG` is the file `tests/acceptance.sh` checks.
    """
    print(f"notify: {line}", file=sys.stderr)
    path = os.environ.get(SINK_LOG_ENV)
    if not path:
        return
    try:
        with open(path, "a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def webhook(report=False):
    """Where a post goes: the sink outranks the configured webhook, always.

    `report` names a diversion on the way out, so a suite whose run tried to reach the owner
    fails on that line instead of the owner hearing about it.
    """
    marker = sink()
    if marker is None:
        return _secret("AGENTKIT_DISCORD_WEBHOOK", "discord_webhook")
    target = marker if marker.startswith(("https://", "http://")) else "off"
    if report:
        try:
            configured = _secret("AGENTKIT_DISCORD_WEBHOOK", "discord_webhook")
        except config.Error:
            configured = None
        if configured and configured != target:
            diverted(f"{SINK_ENV} is set; this notification went to the test sink and not to "
                     "the configured webhook")
    return target


def speaker(session):
    """Who is speaking: the seat, by the name the owner opens it with.

    Never the hostname: a provider's `v1234567890123456789` names nothing the owner can press a number for.
    """
    name = " ".join((session or "").split())
    return f"agentkit \u00b7 {name}" if name else "agentkit"


def _scrub(exc, url):
    """The URL is the secret; scrub it in case the exception quotes it back."""
    return str(exc).replace(url, "<webhook>")


def _read(paths):
    """[(name, bytes)] for the attachments, or an Error naming the file that cannot be sent.

    A refused attachment is an error, not a truncated message: a deliverable the user was told
    to expect and never got is worse than a command that says why.
    """
    files = []
    for raw in paths:
        path = Path(raw).expanduser()
        if not path.is_file():
            raise config.Error(f"--file {path}: no such file")
        size = path.stat().st_size
        if size > FILE_CAP:
            raise config.Error(f"--file {path}: {size} bytes is over Discord's "
                               f"{FILE_CAP // (1024 * 1024)} MB limit per file")
        try:
            files.append((path.name, path.read_bytes()))
        except OSError as exc:
            raise config.Error(f"--file {path}: {exc}")
    return files


def _multipart(payload, files):
    """(body, content-type) for a webhook POST that carries files as well as text."""
    boundary = f"----agentkit{secrets.token_hex(16)}"
    sep = f"--{boundary}\r\n".encode()
    body = bytearray()
    body += sep
    body += b'Content-Disposition: form-data; name="payload_json"\r\n'
    body += b"Content-Type: application/json\r\n\r\n"
    body += json.dumps(payload).encode() + b"\r\n"
    for n, (name, blob) in enumerate(files):
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        body += sep
        body += (f'Content-Disposition: form-data; name="files[{n}]"; '
                 f'filename="{name}"\r\n').encode()
        body += f"Content-Type: {ctype}\r\n\r\n".encode()
        body += blob + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def mention():
    """The `<@id>` that makes Discord push-notify the user, or "" when no id is configured."""
    user_id = _secret("AGENTKIT_DISCORD_USER_ID", "discord_user_id")
    return f"<@{user_id}>" if user_id else ""


def webhook_url(url, message_id=None):
    """Keep webhook query options (e.g. thread_id), replacing wait for POST receipts."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "wait"]
    path = parts.path.rstrip("/")
    if message_id:
        path += f"/messages/{message_id}"
    else:
        query.append(("wait", "true"))
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query), ""))


def post(payload, files, message, receipt=None):
    """POST; optionally collect a message id without putting the webhook secret in state."""
    result = receipt if receipt is not None else {}
    url = webhook(report=True)
    if not url or url.lower() == "off":
        result["status"] = "disabled"
        print(f"notify: no webhook configured; message: {message}", file=sys.stderr)
        return 0
    if not url.startswith(("https://", "http://")):
        result.update(status="blocked", error="webhook is not an http(s) URL")
        print("notify: the configured webhook is not an http(s) URL", file=sys.stderr)
        return 1
    body, ctype = json.dumps(payload).encode(), "application/json"
    target = url
    try:
        parts = urlsplit(url)
        if not parts.hostname:
            raise ValueError("webhook has no host")
        parts.port   # reject malformed port numbers before treating them as an outage
        target = webhook_url(url) if receipt is not None else url
        req = urllib.request.Request(target, data=body,
                                     headers={"Content-Type": ctype, "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            reply = resp.read()
        result["status"] = "delivered"
        if receipt is not None:
            try:
                data = json.loads(reply)
            except ValueError:
                data = None
            if isinstance(data, dict) and str(data.get("id", "")).isdigit():
                receipt.update(message_id=str(data["id"]),
                               webhook=hashlib.sha256(url.encode()).hexdigest())
    except urllib.error.HTTPError as exc:
        result.update(status="pending" if exc.code in (408, 429) or exc.code >= 500 else "blocked",
                      error=f"HTTP {exc.code}")
        if exc.code == 429:
            result["retry_after"] = retry_after(exc)
        print(f"notify: webhook POST failed (HTTP {exc.code})", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError, ValueError, HTTPException) as exc:
        # Exception text can contain tokens or query parameters even without the full URL.
        result.update(status="blocked" if isinstance(exc, ValueError) else "pending",
                      error=type(exc).__name__)
        print(f"notify: webhook POST failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    return 0


def retry_after(exc):
    """Discord's seconds, or HTTP's seconds/date header, bounded like our own backoff."""
    delay = 0
    value = exc.headers.get("Retry-After", "") if exc.headers else ""
    try:
        delay = float(value)
    except ValueError:
        try:
            delay = parsedate_to_datetime(value).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            pass
    try:
        body = json.loads(exc.read())
        if isinstance(body, dict):
            delay = max(delay, float(body.get("retry_after", 0)))
    except (OSError, ValueError, TypeError, HTTPException):
        pass
    return min(RETRY_BACKOFF[-1], max(RETRY_BACKOFF[0], delay)) if math.isfinite(delay) else RETRY_BACKOFF[-1]


def worker_blocked(kind, dry_run=False):
    """A worker's descendants inherit the guard and the run log, even outside its cwd."""
    if os.environ.get("AK_RUN_ROLE") != "worker":
        return False
    line = f"notify: {kind} suppressed: AK_RUN_ROLE=worker; only an orchestrator may notify"
    print(line)
    log = os.environ.get("AK_RUN_LOG")
    if log and not dry_run:
        try:
            with Path(log).open("a") as fh:
                fh.write(f"[{datetime.now():%H:%M:%S}] {line}\n")
        except OSError:
            pass
    return True



# --- the two shapes ---------------------------------------------------------


@contextmanager
def session_lock(session):
    """Serialize repeat checks, posts, acknowledgement and project votes across concurrent ak processes."""
    config.ensure_dirs()
    while True:
        session = config.resolve_session(session)
        with config.notify_path(session).with_suffix(".lock").open("a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                if config.resolve_session(session) != session:
                    continue       # a rename won while this writer waited for the lock
                yield session
                return
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)


def record(session, kind, text, **extra):
    """Remember the last thing a session said, so the menu can show it as the session's state."""
    config.ensure_dirs()
    path = config.notify_path(session)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"session": session, "kind": kind, "text": text,
                               "time": time.time(), **extra}) + "\n")
    tmp.replace(path)


def last(session, include_seen=False):
    """The last notification; resolved history stays on disk but off the menu."""
    try:
        data = json.loads(config.notify_path(session).read_text(encoding="utf-8"))
    except (OSError, ValueError, config.Error):
        return None
    if (not isinstance(data, dict) or data.get("kind") not in TITLES
            or not isinstance(data.get("text"), str) or (resolved(data) and not include_seen)):
        return None
    return data


def resolved(data):
    """An orchestrator notice resolves after its seat was opened and produced fresh output.

    These facts travel with the notice, so rendering never acknowledges it or depends on
    whether tmux reports a client attached. `seen` also covers explicit retirement and
    guarded retraction of the watcher's own recovery alerts.
    """
    if data.get("seen"):
        return True
    stamps = [data.get(key) for key in ("time", "opened_at", "last_progress_at")]
    return (all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n)
                for n in stamps) and stamps[0] <= stamps[1] < stamps[2])


def opened(session, capture):
    """Record the first interactive open of this notice, including its output baseline."""
    with session_lock(session) as session:
        previous = last(session)
        if not previous or previous.get("opened_at") is not None:
            return                 # two quick opens must not erase progress between them
        pane = capture()
        stamp = previous.get("time")
        if (not isinstance(stamp, (int, float)) or isinstance(stamp, bool)
                or not math.isfinite(stamp)):
            # Old notices had no timestamp. Migrate at the open, keeping the question
            # pending until output after this baseline proves the seat has moved on.
            previous["time"] = time.time()
        record(session, previous["kind"], previous["text"],
               **{k: v for k, v in previous.items() if k not in ("session", "kind", "text")},
               opened_at=max(time.time(), previous["time"]), opened_pane=pane)


def progress(session, capture):
    """Persist new output after an open; Discord and the row use the same resolved fact.

    Capture under the notice lock: output sampled before an open or a newer notify cannot
    resolve it. Empty captures and viewport resizing are not evidence of resumed work.
    """
    with session_lock(session) as session:
        previous = last(session)
        if not previous or previous.get("opened_at") is None:
            return
        pane = capture()
        baseline = previous.get("opened_pane", "")
        if not pane or (baseline and (pane in baseline or pane.endswith(baseline))):
            return
        extra = {k: v for k, v in previous.items() if k not in ("session", "kind", "text")}
        if not baseline:
            extra["opened_pane"] = pane  # failed initial capture: establish a baseline first
        else:
            extra["last_progress_at"] = max(time.time(), math.nextafter(previous["opened_at"],
                                                                        math.inf))
            extra["open_needs"] = []
        record(session, previous["kind"], previous["text"], **extra)
        if resolved(extra):
            close_needs(previous, "Answered")
            _end_done_episode(session, previous)
            return True


def close_needs(previous, status):
    """Edit every outstanding question without mentions; missing messages/hooks are harmless.

    The ones Discord did not take, for a reason `post` would retry, are handed back: a caller
    about to drop its receipts keeps those instead.
    """
    if not previous:
        return []
    try:
        url = webhook()
    except config.Error:
        return list(previous.get("open_needs", []))
    if not url or not url.startswith(("https://", "http://")):
        return []
    fingerprint = hashlib.sha256(url.encode()).hexdigest()
    left = []
    for pending in previous.get("open_needs", []):
        message_id = pending.get("message_id")
        if (not isinstance(message_id, str) or not message_id.isdigit()
                or pending.get("webhook") != fingerprint):
            continue
        body = dict(pending["embed"])
        body["title"] = body["title"].replace(TITLES["needs"], status, 1)[:256]
        body.pop("fields", None)   # the instruction to open this seat no longer applies
        payload = {"content": "", "embeds": [body], "allowed_mentions": {"parse": []}}
        try:
            req = urllib.request.Request(webhook_url(url, message_id), method="PATCH",
                                         data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json", "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (408, 429) or exc.code >= 500:
                left.append(pending)
        except (urllib.error.URLError, OSError, HTTPException):
            left.append(pending)
        except ValueError:
            pass
    return left


def clear(session, *, notice=None):
    """Retire a conversation's notice, or retract only the watcher's matching alert."""
    with session_lock(session) as session:
        previous = last(session, include_seen=True)
        if not previous or previous.get("seen"):
            return
        if notice is not None and (previous["kind"] != "needs" or previous["text"] != notice):
            return
        close_needs(previous, "Answered")
        record(session, previous["kind"], previous["text"],
               **{k: v for k, v in previous.items() if k not in ("session", "kind", "text",
                                                               "seen", "open_needs")},
               seen=True, open_needs=[])
        _end_done_episode(session, previous)


def outbox():
    return config.STATE / "notification-outbox"


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def outbox_lock():
    """Session lock first, then this lock, for enqueue, retry and receipt updates alike."""
    config.ensure_dirs()
    outbox().mkdir(mode=0o700, exist_ok=True)
    _sync_dir(config.STATE)
    _sync_dir(config.HOME)
    _sync_dir(config.HOME.parent)
    with (outbox() / ".lock").open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def _write_event(event):
    """One atomic, fsynced card record never includes the webhook URL."""
    path = outbox() / f"{event['id']}.json"
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(event, fh)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)
        _sync_dir(outbox())
    finally:
        tmp.unlink(missing_ok=True)


def _read_event(event_id):
    try:
        return json.loads((outbox() / f"{event_id}.json").read_text())
    except FileNotFoundError:
        return None


def _attempt(event):
    """Return success only for a delivered, disabled, or durably retryable event."""
    if event["status"] in ("delivered", "disabled"):
        return 0
    testing = sink() is not None
    if bool(event.get("sink")) != testing:
        # A queued event outlives the environment that made it, so the destination it was
        # queued for is the only one it may ever reach: a test's event is dropped rather than
        # delivered to the owner once the marker is gone, and the owner's own -- including
        # every event queued before there was a marker at all, which is nobody's test -- waits
        # instead of being drained into a suite's sink or disabled by it.
        if event.get("sink"):
            diverted(f"event {event['id']} was queued under {SINK_ENV}; it is dropped, never "
                     "delivered to the configured webhook")
            event.update(status="disabled", error=f"queued under {SINK_ENV}", next_attempt=None)
            _write_event(event)
        else:
            print(f"notify: event {event['id']} was queued for the configured webhook; "
                  f"{SINK_ENV} is set, so it waits", file=sys.stderr)
        return 0
    try:
        url = webhook() or ""
    except config.Error:
        event.update(status="blocked", error="cannot read the configured webhook", next_attempt=None)
        event.pop("webhook", None)
        _write_event(event)
        print("notify: cannot read the configured webhook; event retained", file=sys.stderr)
        return 1
    fingerprint = hashlib.sha256(url.encode()).hexdigest()
    if not url and event.get("webhook") and event["webhook"] != fingerprint:
        # A cron process may lack a caller's environment override. Missing configuration
        # there must not discard an event that was queued with a configured destination.
        event.update(status="blocked", webhook=fingerprint,
                     error="no webhook configured for queued event", next_attempt=None)
        _write_event(event)
    if event.get("webhook") == fingerprint:
        if event["status"] == "blocked":
            print(f"notify: event {event['id']} blocked ({event['error']}); fix the webhook configuration",
                  file=sys.stderr)
            return 1
        if time.time() < event["next_attempt"]:
            return 0
    now = time.time()
    event["attempts"] += 1
    delay = RETRY_BACKOFF[min(event["attempts"] - 1, len(RETRY_BACKOFF) - 1)]
    event.update(status="pending", webhook=fingerprint, next_attempt=now + delay)
    # A killed sender leaves a scheduled event, even if it dies inside urlopen.
    _write_event(event)
    receipt = {}
    post(event["payload"], [], event["message"], receipt)
    event["status"] = receipt["status"]
    event["receipt"] = {k: receipt[k] for k in ("message_id", "webhook") if k in receipt}
    if receipt.get("error"):
        event["error"] = receipt["error"]
    else:
        event.pop("error", None)
    if event["status"] == "pending":
        event["next_attempt"] = time.time() + max(delay, receipt.get("retry_after", 0))
    else:
        event["next_attempt"] = None
    _write_event(event)
    if event["status"] == "pending":
        print(f"notify: event {event['id']} queued; retry after {event['next_attempt']:.0f}",
              file=sys.stderr)
    return 1 if event["status"] == "blocked" else 0


def _remember(event, previous):
    """The local notice and its edit receipts are independent of the outbound event."""
    session = event["session"]
    if not session:
        return
    receipt = event.get("receipt", {})
    pending = list(previous.get("open_needs", [])) if previous else []
    if event["kind"] == "done":
        pending = []
    elif receipt.get("message_id") and not any(
            all(p.get(k) == receipt[k] for k in ("message_id", "webhook")) for p in pending):
        pending.append({**receipt, "embed": event["payload"]["embeds"][0]})
    record(session, event["kind"], event["text"], **receipt, open_needs=pending,
           event_id=event["id"], time=event["created_at"],
           watcher=str(event.get("source") or "").startswith(("auth:", "stuck:", "stall:")))


def _remember_retry(event, session):
    """Late receipts can close a question, but must never reopen an acknowledged menu row."""
    if not session:
        return
    previous = last(session, include_seen=True)
    if str(event.get("source") or "").startswith("card:"):
        _remember_card(event, previous)
        return
    if not previous or previous.get("time", 0) < event["created_at"]:
        _remember({**event, "session": session}, previous)
        return
    receipt = event.get("receipt", {})
    if not receipt.get("message_id") or event["kind"] != "needs":
        return
    pending = {**receipt, "embed": event["payload"]["embeds"][0]}
    if resolved(previous) or previous["kind"] == "done":
        close_needs({"open_needs": [pending]}, "Done" if previous["kind"] == "done"
                    else "Answered")
        return
    opened = previous.get("open_needs", [])
    if pending not in opened:
        extra = {k: v for k, v in previous.items() if k not in ("session", "kind", "text", "open_needs")}
        if previous.get("event_id") == event["id"]:
            extra.update(receipt)
        record(session, previous["kind"], previous["text"], **extra, open_needs=[*opened, pending])


def _unsendable(event, session):
    """Why a queued event may no longer go out, or "".

    A retry is a card sent late, and the rules for sending hold for it too: nothing queued
    before the agentkit running now was installed, and nothing about a seat the owner has
    closed himself since.
    """
    if event.get("created_at", 0) < installed_at():
        return "queued before the agentkit running now was installed"
    if session:
        from . import watch
        if watch.seat_closed_by_owner(session):
            return "its seat was closed by the owner"
    return ""


def retry_pending(dry_run=False, log=print):
    """The existing watcher drains the outbox even when GitHub or the original seat is gone."""
    for path in sorted(outbox().glob("*.json")):
        try:
            event = _read_event(path.stem)
            if not event or event["status"] in ("delivered", "disabled", "held"):
                continue    # a hold is released by a run ending, never by a retry
            if dry_run:
                log(f"would retry notification {event['id']} ({event['status']})")
                continue
            session = config.resolve_session(event["session"]) if event["session"] else None
            with session_lock(session) if session else nullcontext(session) as session, outbox_lock():
                event = _read_event(path.stem)
                why = _unsendable(event, session)
                if why:
                    event.update(status="disabled", error=why, next_attempt=None)
                    _write_event(event)
                    log(f"notification {event['id']} dropped unsent: {why}")
                    continue
                _attempt(event)
                _remember_retry(event, session)
        except (OSError, ValueError, config.Error) as exc:
            log(f"WARN notification {path.stem} could not be retried ({type(exc).__name__})")


def _card_read(session):
    # One episode lives in card-<session>.json, shared by notify and the watch tick.
    try:
        data = json.loads(config.card_path(session).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def _card_write(session, data):
    path = config.card_path(session)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as fh:
        json.dump(data, fh)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)
    _sync_dir(config.STATE)


def installed_at():
    """When the agentkit running now was put in place, or 0 where no install says so.

    install.sh stamps `installed-at` on a server; a fast-forward of the checkout it installed
    stamps nothing, so there the newest write among these modules counts too.  A home no
    install stamped -- a test's sandbox -- has no install to be older than.
    """
    try:
        stamps = [float((config.STATE / "installed-at").read_text())]
    except (OSError, ValueError):
        return 0
    for path in Path(__file__).resolve().parent.glob("*.py"):
        try:
            stamps.append(path.stat().st_mtime)
        except OSError:
            pass
    return max(stamps)


def _end_done_episode(session, previous):
    """A resolved done declaration ends its episode: hiding the record moves the word
    off done, so the next declaration opens a new episode even before any tick runs."""
    if previous.get("kind") != "done":
        return
    card = _card_read(session)
    if card.get("word") == "done":
        card["word"] = ""
        _card_write(session, card)


def _attached(session, seat=None):
    """Ask the session's own server, never the caller's inherited tmux client."""
    from . import orch
    if seat is None:
        seat = orch.find(session)
    rc, output = orch.tmux_out("list-clients", "-t", session,
                               socket=orch.seat_socket(seat))
    if rc:
        return False
    lines = [line for line in output.splitlines() if line.strip()]
    return any(line.split("\t")[1:2] == [session] for line in lines) or \
        any("\t" not in line for line in lines)


def failed_declaration(notice, mine):
    """A run the declaration waited on failed; earlier jobs do not invalidate a new done."""
    stamp = notice.get("time", 0)
    return [directory.name for directory, state in mine
            if state.get("state") in ("fail", "error", "blocked")
            and (directory.name in notice.get("runs", []) or
                 (isinstance(state.get("finished_at"), (int, float))
                  and state["finished_at"] >= stamp))]


def _close_card(session, card, status):
    """Close receipts, including cards inferred from state with no notify record at all.

    What Discord did not take stays on the card, and the next close tries it again.
    """
    left = close_needs(card, status)
    card.update(open_needs=left, closed=status)
    previous = last(session, include_seen=True)
    if previous and previous.get("open_needs"):
        extra = {k: v for k, v in previous.items() if k not in ("session", "kind", "text", "open_needs")}
        record(session, previous["kind"], previous["text"], **extra, open_needs=[])
    return left


def _remember_card(event, previous=None):
    """A late receipt may close a card; it never changes the session's reason or declaration."""
    session = config.resolve_session(event["session"])
    card = _card_read(session)
    receipt = event.get("receipt", {})
    current = last(session, include_seen=True)
    if event["kind"] == "needs" and receipt.get("message_id"):
        pending = {**receipt, "embed": event["payload"]["embeds"][0]}
        answered = current is not None and (resolved(current) or current["kind"] == "done")
        if (card.get("episode") != event.get("episode") or card.get("closed")
                or card.get("word") != "needs you" or answered):
            finished = card.get("word") == "done" or (current is not None
                                                      and current["kind"] == "done")
            close_needs({"open_needs": [pending]}, "Done" if finished else "Answered")
        elif pending not in card.get("open_needs", []):
            card.setdefault("open_needs", []).append(pending)
        _card_write(session, card)
    if current is None or resolved(current) or current["kind"] == "done":
        return
    extra = {k: v for k, v in current.items() if k not in ("session", "kind", "text", "open_needs", "event_id")}
    if card.get("episode") == event.get("episode"):
        extra.update(receipt, event_id=event["id"])
    record(session, current["kind"], current["text"], **extra,
           open_needs=card.get("open_needs", []))


def _send_card(session, kind, card, answer):
    """Queue once under the session lock; the outbox owns any further attempts."""
    previous = last(session, include_seen=True)
    text = previous["text"] if kind == "done" and previous else answer["reason"]
    payload = {"username": "agentkit", "embeds": [embed(kind, session, text)]}
    who = mention()
    if who:
        payload["content"] = who
    key = hashlib.sha256(json.dumps(["card", card["episode"], sink() is not None]).encode()).hexdigest()
    with outbox_lock():
        event = _read_event(key)
        fresh = event is None
        if fresh:
            event = {"id": key, "source": "card:" + card["episode"], "episode": card["episode"],
                     "session": session, "kind": kind, "text": text,
                     "pr": previous.get("pr") if previous else None, "files": [],
                     "payload": payload, "message": f"{TITLES[kind]} · {session}: {text}",
                     "created_at": time.time(), "sink": sink() is not None,
                     "status": "pending", "attempts": 0, "next_attempt": 0}
            _write_event(event)
        card["sent"] = True
        _card_write(session, card)
        if fresh:
            terminal_notice(session, f"{TITLES[kind]} · {session}: {text}")
        result = _attempt(event)
        _remember_card(event)
    return result


def _history(card):
    """Did that episode begin before the agentkit running now was installed?

    Then it is history: an upgrade finds every word already standing, and none of them is
    news, whether the tick that reads it is the first to or had opened it and not sent yet.
    """
    return card.get("began", card.get("since", 0)) < installed_at()


def _went_at(name):
    """When a seat nobody is in went, at the latest, or inf where nothing says.

    Its record's `exited_since` is when the first tick saw its pane dead, and it stays when
    tmux loses the pane as well.  Without one there is only the last time it was seen alive,
    which a live seat's record renews every SEEN_EVERY at the next tick after: it went
    within two of those.
    """
    from . import orch
    record = config.session_records().get(name) or {}
    for key, late in (("exited_since", 0), ("seen", 2 * orch.SEEN_EVERY)):
        stamp = record.get(key)
        if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
            return stamp + late
    return math.inf


def _carded(session, declared):
    """Was a done card already made for that declaration, by this version or one before it?

    The outbox keeps every card it was handed, keyed however the version that queued it
    keyed them, and each carries its seat, the declaration's text and when it was made: one
    for this seat -- or the name it had -- with the same text, made no earlier than the
    declaration, is this ending's.  So a word coming back to done is not a second ending,
    whichever episodes it went through and whichever version saw them.
    """
    stamp = declared.get("time")
    if not isinstance(stamp, (int, float)) or isinstance(stamp, bool):
        return False
    for path in outbox().glob("*.json"):
        try:
            event = json.loads(path.read_text())
            if (event.get("kind") == "done" and event.get("text") == declared["text"]
                    and event.get("created_at", 0) >= stamp and event.get("session")
                    and config.resolve_session(event["session"]) == session):
                return True
        except (OSError, ValueError, AttributeError, TypeError, config.Error):
            continue
    return False


def needs_transition(session, card, answer, now, seat=None):
    """One amber card after a minute of needs you, while nobody is attached to the seat.

    Never for an episode that is history, nor for a seat the owner closed himself -- `x`,
    `ak orch stop` or a pause script: its row says so and its number reopens it, and nobody
    in it is asking him anything.
    """
    if _attached(session, seat):
        if not card.get("closed"):
            if card.get("sent"):
                _close_card(session, card, "Answered")
            else:
                # Seen live and left unasked: this episode ends without a card.
                card["closed"] = "Answered"
            _card_write(session, card)
        return 0
    if card.get("sent") or card.get("closed") or now - card["since"] < CARD_WAIT:
        return 0
    from . import watch
    if _history(card) or watch.seat_closed_by_owner(session):
        return 0
    return _send_card(session, "needs", card, answer)


def done_transition(session, card, answer, now):
    """One completion when the state function says done, after editing open questions.

    Never for an episode that is history, a seat the owner closed himself, or a declaration
    already carded -- which latches this episode as sent, so the outbox is read once.
    """
    from . import watch
    if card.get("sent") or _history(card) or watch.seat_closed_by_owner(session):
        return 0
    declared = last(session, include_seen=True)
    if declared and declared["kind"] == "done" and _carded(session, declared):
        card["sent"] = True
        _card_write(session, card)
        return 0
    _close_card(session, card, "Done")
    return _send_card(session, "done", card, answer)


def transition(session, answer=None, now=None, dry_run=False, log=print, seat=None,
               began=None):
    """The command and tick share a session lock, the decision and the episode file.

    `began` is an explicit command's own moment: the episode it lands in, unless its card
    already went out, begins there, so `ak notify` is never history.
    """
    if os.environ.get("AK_RUN_ROLE") == "worker" or dry_run:
        return 0
    # A legacy seat is another program's session: the tick never cards it, while an
    # explicit `ak notify --session` still may -- it names its subject on purpose.
    if seat is not None and seat.get("legacy"):
        return 0
    from . import watch, menu, orch, run
    at = time.time() if now is None else now
    try:
        with session_lock(session) as name:
            card = _card_read(name)
            records = menu.run_records()
            mine = [(directory, state) for directory, state in records
                    if run.launched_session(state) == name]
            declared = last(name, include_seen=True)
            if declared and declared.get("seen") and declared.get("kind") == "done":
                # Already dropped: no second log line, but later words still card.
                declared = None
            if declared and declared["kind"] == "done":
                failed = failed_declaration(declared, mine)
                if failed:
                    extra = {k: v for k, v in declared.items() if k not in ("session", "kind", "text")}
                    record(name, "done", declared["text"], **extra, seen=True)
                    log(f"dropping done declaration for {name}: {', '.join(failed)} failed; not sent")
                    answer = None
            if answer is None:
                previous = watch.seat_read(name)
                # A screen may have observed an intervening episode since our last tick.
                if card and (previous.get("word_since") or 0) <= card.get("since", 0):
                    previous = {"word": card["word"], "word_since": card["since"]}
                answer = watch.session_state(name, now=at, session=seat, records=records,
                                             previous=previous)
            since = answer.get("since")
            since = since if isinstance(since, (int, float)) and math.isfinite(since) else at
            word = answer["word"]
            if card.get("word") != word:
                pending = card.get("open_needs", (last(name, include_seen=True) or {}).get("open_needs", []))
                card = {"word": word, "since": since, "began": since,
                        "episode": secrets.token_hex(16), "sent": False, "open_needs": pending}
                if word != "done" and pending:
                    # The old episode left questions standing; a new episode with nothing
                    # to close closes nothing, not even an empty edit.
                    _close_card(name, card, "Answered")
                    card.pop("closed", None)
                if seat is not None and any(seat.get(key) for key in orch.CLOSED):
                    # a seat nobody is in began its word when it went, whichever tick reads it
                    card["began"] = min(since, _went_at(name))
                _card_write(name, card)
            if began is not None and not card.get("sent") and card.get("began") != began:
                card["began"] = began
                _card_write(name, card)
            if word == "needs you":
                return needs_transition(name, card, answer, at, seat)
            if word == "done":
                return done_transition(name, card, answer, at)
        return 0
    except (OSError, ValueError, config.Error) as exc:
        log(f"WARN card transition for {session} failed ({type(exc).__name__}); retry required")
        return 1


def tick_cards(dry_run=False, log=print):
    """Every session, including saved seats without a tmux pane, on every watch tick.

    A card whose session is neither a seat nor a saved record any more has nobody left to
    answer it: its open needs are closed the way an answered one is, and it goes.  One
    reading of the process table answers the whole pass.
    """
    from . import orch
    with orch.one_reading():
        seats = orch.listing(reconcile=False)
        for seat in seats:
            transition(seat["name"], seat=seat, dry_run=dry_run, log=log)
        if os.environ.get("AK_RUN_ROLE") == "worker" or dry_run:
            return
        known = {seat["name"] for seat in seats} | set(config.session_records())
        for path in sorted(config.STATE.glob("card-*.json")):
            name = path.name[len("card-"):-len(".json")]
            if name not in known and orch.seatless(name):
                forget_card(name, log)


def forget_card(name, log=lambda _: None):
    """Close a gone session's open needs as `Answered`, then drop its card.

    An edit Discord did not take stays on the card for the next tick to try again, with the
    card's word gone so a seat given the name meanwhile starts an episode of its own.  The
    notify lock stays: a writer may hold it or wait on it, and one that opened a new file in
    its place would wait for neither.  A card that is a link, a hard link or not this user's is
    not this seat's to read or remove, the way retention leaves it too.
    """
    path = config.card_path(name)
    if not retention.safe(path.parent.resolve() / path.name):
        return
    try:
        with session_lock(name) as session:
            if session != name:
                return        # an old name that leads to a renamed seat: its card is not this
            card = _card_read(name)
            if _close_card(name, card, "Answered"):
                _card_write(name, {**card, "word": ""})
                log(f"WARN the card of {name} was not closed: Discord did not take the edit; "
                    "retry required")
                return
            config.card_path(name).unlink(missing_ok=True)
        log(f"closed the card of {name}: no seat holds it any more")
    except (OSError, ValueError, config.Error) as exc:
        log(f"WARN the card of {name} was not closed ({type(exc).__name__}); retry required")


def session_number(name):
    """This session's number in the menu, or None when the menu has no row for it.

    The menu's own listing, and not just the seats tmux is holding: a seat that is resumable
    still has a row, and the number the message names has to be the number that opens it.
    """
    from . import orch   # here, not at the top: orch imports nothing of ours that imports notify
    # Use the menu's eligibility rules without listing()'s session-record reconciliation;
    # rendering a notification preview must not write resumability changes to those records.
    names = {s["name"] for s in orch.sessions()}
    names.update(name for name, record in config.session_records().items()
                 if orch.resumable(record) or orch.seat_plugin(record).always_offered)
    names = sorted(names)
    return names.index(name) + 1 if name in names else None


def subject(session, text):
    """Who the notification is about: the session it speaks for, else what it is about.

    A dash names nothing, and a phone shows the title before it shows anything else.  Outside
    a seat -- a run whose orchestrator is gone, an `ak notify` run by hand -- the subject is
    the task itself, cut to a title's worth of it.  The cut is the fallback's alone: a session
    name is what the user has to find in the menu, so it is carried whole.
    """
    name = " ".join((session or "").split())
    if name:
        return name
    return " ".join((text or "").split())[:SUBJECT_CAP] or "agentkit"


def embed(kind, session, text):
    """The card Discord hears: two words and the seat, nothing else.

    The title names the seat; the colour says which of the two it is.  No
    description, no fields, no footer, no PR link, no run id, no key hint: the
    text `ak notify` was given lives on in the outbox record, the log line, the
    terminal notice and `--dry-run`, never on Discord.
    """
    color = COLORS["fail" if kind == "done" and text.lstrip().upper().startswith("FAIL")
                   else kind]
    return {"title": f"{TITLES[kind]} \u00b7 {subject(session, text)}"[:256], "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def shaped(kind, text, pr=None, paths=(), session=None, dry_run=False, event_id=None):
    """Record the question or declaration, then evaluate the same transition latch."""
    if worker_blocked(kind, dry_run):
        return 0
    if paths:
        raise config.Error("--file was removed: notification cards carry no attachments")
    name = config.resolve_session(session) if session else config.current_session()
    if dry_run:
        payload = {"username": "agentkit", "embeds": [embed(kind, name, text)]}
        who = mention()
        if who:
            payload["content"] = who
        print(json.dumps(payload, indent=2))
        terminal_notice(name, f"{TITLES[kind]} · {subject(name, text)}: {text}", dry_run=True)
        return 0
    if not name:
        raise config.Error("notify needs a session: use --session NAME")
    from . import menu, run, watch
    try:
        with session_lock(name) as name:
            previous = last(name, include_seen=True)
            if not (event_id and previous and previous.get("source") == event_id):
                extra = {"source": event_id, "pr": pr,
                         "watcher": str(event_id or "").startswith(("auth:", "stuck:", "stall:")),
                         "open_needs": previous.get("open_needs", []) if previous else []}
                if kind == "done":
                    extra["runs"] = [directory.name for directory, state in menu.run_records()
                                     if run.launched_session(state) == name and
                                     (run.going(state) or run.unfinished(state))]
                record(name, kind, text, **extra)
        # A command is the visible start of the episode. Decide from now's facts, and
        # evaluate a hold later, so the recorder's own question is not left waiting
        # for the three-minute watcher tick; deciding at the later clock would date
        # the word from then and the hold would never elapse. A repeated watcher
        # event re-records nothing, but the latch is still evaluated: the first
        # attempt may have recorded without ever queueing the card.
        stamp = time.time()
        answer = watch.session_state(name, now=stamp)
        if answer["word"] == "needs you":
            since = answer.get("since")
            if not (isinstance(since, (int, float)) and math.isfinite(since)
                    and since <= stamp):
                answer["since"] = stamp
        # `ak notify` itself begins its episode at the command, however long the word it
        # lands on has stood; a watcher's own notice is dated by the word.
        return transition(name, answer=answer, now=stamp + (CARD_WAIT if kind == "needs" else 0),
                          began=stamp if event_id is None else None)
    except (OSError, ValueError, config.Error) as exc:
        print(f"notify: record could not be persisted ({type(exc).__name__}); retry required", file=sys.stderr)
        return 1


def log_line(line, dry_run=False):
    """The line on stdout and in the run log, the way a suppression already says it."""
    print(line)
    log = os.environ.get("AK_RUN_LOG")
    if log and not dry_run:
        try:
            with Path(log).open("a") as fh:
                fh.write(f"[{datetime.now():%H:%M:%S}] {line}\n")
        except OSError:
            pass


def check():
    """Prove the webhook is live without posting: Discord answers a GET with the hook object.

    0 on 200, 1 on anything else, and 2 -- via config.Error -- only when none is configured.
    """
    url = _secret("AGENTKIT_DISCORD_WEBHOOK", "discord_webhook")
    if not url:
        raise config.Error("--check: no webhook configured; put one in "
                           f"{config.SECRETS / 'discord_webhook'} or $AGENTKIT_DISCORD_WEBHOOK")
    if not url.startswith(("https://", "http://")):
        # exit 2 means "nothing configured"; a webhook that is configured but unusable is a
        # failed check like any other, and the caller has to tell those two apart
        print("notify: fail (the configured webhook is not an http(s) URL)", file=sys.stderr)
        return 1
    try:
        # inside the try: Request() itself rejects a URL urlopen would never reach, and that is
        # a failed check like any other, not a traceback
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            code = resp.status
            resp.read()
    except urllib.error.HTTPError as exc:
        code = exc.code           # a 401/404 is the webhook answering: report the code, not a crash
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"notify: fail (no response: {_scrub(exc, url)})", file=sys.stderr)
        return 1
    print(f"notify: {'ok' if code == 200 else 'fail'} ({code})")
    return 0 if code == 200 else 1


def main(argv):
    if command_help.show("notify", argv):
        return 0
    if argv == ["--check"]:
        return check()
    kind = argv[0] if argv[:1] in (["needs"], ["done"]) else None
    rest, pr, session, dry_run, i = [], None, None, False, 1 if kind else 0
    while i < len(argv):
        arg = argv[i]
        if kind == "done" and arg == "--pr":
            if i + 1 >= len(argv) or not argv[i + 1].startswith(("https://", "http://")):
                raise config.Error("--pr needs the PR's URL")
            pr, i = argv[i + 1], i + 2
        elif kind and arg == "--session":
            # for a caller that speaks for a seat it is not in: `ak watch` speaks for `inbox`
            if i + 1 >= len(argv):
                raise config.Error("--session needs a session name")
            session, i = argv[i + 1], i + 2
        elif kind and arg == "--dry-run":
            dry_run, i = True, i + 1
        elif kind and arg == "--file":
            raise config.Error("--file was removed: notification cards carry no attachments")
        else:
            rest.append(arg)
            i += 1
    if len(rest) != 1 or rest[0].startswith("-") or not rest[0].strip():
        raise config.Error(USAGE)
    if kind:
        return shaped(kind, rest[0].strip(), pr, session=session, dry_run=dry_run)
    raise config.Error(USAGE)
