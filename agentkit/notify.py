"""Discord webhook notification.  The orchestrator's, and the orphaned run's.

Two shapes, each one line naming its seat and nothing it said (the owner keeps what a seat
asked or did out of Discord): `ak notify needs "<question>"` when the orchestrator needs the
user, and Done when the seat's plan proves the job done.  A question records itself as the session's
last notification, which is what the menu shows as that session's state. `ak notify` records
the question; the session-state transition sends the card.

Workers are silent by construction. A needs episode is sent once after it has stood for a minute
and the owner has typed nothing into the seat for a minute. A question a seat asks during its own turn is
kept back in its record, apart from every notice, until a look finds that turn ended
(`watch.ask_kept_back`): only then is the seat waiting for the answer. A done episode is sent
once when the session state becomes done, and its work once whatever episodes, or versions,
it turns up in. A card once out is never edited: he has read it by the time he answers, and
a question over before Discord took its card is never sent late. Nothing is sent, or
retried, for a seat the owner closed himself, or an episode begun before this agentkit was
installed.

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
import itertools
import json
import math
import os
import secrets
import stat
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import command_help, config, history, retention, transitions
from . import harness

FILE_CAP = 8 * 1024 * 1024
UA = "agentkit/1 (+https://github.com)"
# Where a seat's question must have asked: a seat's bar and its menu row show a question from its
# start and cut the rest, so context written before the ask hides it.  One classic terminal line.
ASK_CAP = 80
TITLES = {"needs": "Needs you", "done": "Done"}
EMOJI = {"needs": "\U0001f64b", "done": "\u2705"}     # 🙋 a seat with its hand up, ✅ work done
CARD_WAIT = 60
SINK_ENV = "AK_NOTIFY_SINK"   # the suites' destination; it outranks the owner's webhook
SINK_LOG_ENV = "AK_NOTIFY_SINK_LOG"   # where a diversion is written, for the suite to fail on
WEBHOOK_ENV = "AGENTKIT_DISCORD_WEBHOOK"
USER_ID_ENV = "AGENTKIT_DISCORD_USER_ID"
ENV_NAMES = (SINK_ENV, SINK_LOG_ENV, WEBHOOK_ENV, USER_ID_ENV)
RETRY_BACKOFF = (60, 180, 600, 1800, 3600)
USAGE = command_help.NOTIFY_USAGE


def terminal_targets(session):
    """Visible panes on our server, once per window; never the seat being reported.

    A linked window shared with the source seat needs per-client output to suppress that
    seat's toast. Exited panes retain stale tty names, so their clients need direct output
    too. Otherwise pane output passes through tmux to every client viewing it. A control-mode
    client (`tmux -C`) has no terminal to show a toast.
    """
    from . import orch
    rc, output = orch.tmux_out("list-clients", "-F",
                               "#{client_tty}\t#{session_name}\t#{window_id}\t#{pane_tty}\t#{pane_dead}"
                               "\t#{client_control_mode}",
                               socket=orch.socket_name())
    if rc:
        return []
    clients = [parts + [""] * (6 - len(parts)) for line in output.splitlines()
               if 2 <= len(parts := line.split("\t")) <= 6]
    clients = [client for client in clients if client[5] != "1"]
    excluded = {window for _, attached, window, _, dead, _ in clients
                if attached == session or dead != "0"}
    targets, seen = [], set()
    for tty, attached, window, pane, *_ in clients:
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
        return _secret(WEBHOOK_ENV, "discord_webhook")
    target = marker if marker.startswith(("https://", "http://")) else "off"
    if report:
        try:
            configured = _secret(WEBHOOK_ENV, "discord_webhook")
        except config.Error:
            configured = None
        if configured and configured != target:
            diverted(f"{SINK_ENV} is set; this notification went to the test sink and not to "
                     "the configured webhook")
    return target


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


def title(kind, session):
    """All a card says: its emoji, two words and its seat, `🙋 Needs you · atlas-growth`, the
    seat carried whole as the menu shows it; `agentkit` outside a seat, never what was said."""
    return (f"{EMOJI[kind]} {TITLES[kind]} \u00b7 "
            f"{' '.join((session or '').split()) or 'agentkit'}")


def card_payload(kind, session):
    """What a page posts: its title, then the owner's mention, the only one it may ping.  No
    embed: what was asked or done stays in the seat.  Once out it is never edited: the owner
    has read it by the time it is answered (owner, 19 Oct 2026)."""
    user_id = _secret(USER_ID_ENV, "discord_user_id")
    return {"username": "agentkit", "content": title(kind, session) + (f" <@{user_id}>" if user_id else ""),
            "allowed_mentions": {"users": [user_id]} if user_id else {"parse": []}}


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
            if isinstance(data, dict) and isinstance(data.get("mentions"), list):
                _learn(data["mentions"])
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


def _learn(mentions):
    """Keep the name Discord gave the user a delivered card pinged, for the `c` screen's row.

    No bot may ask Discord who an id is, and a webhook's own GET names nobody; the message a
    card created does, in its `mentions`. Best effort: the card was delivered either way.
    """
    for user in mentions:
        if isinstance(user, dict) and user.get("id") and isinstance(user.get("username"), str):
            path = config.STATE / "discord-user.json"
            tmp = path.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps({"id": str(user["id"]), "name": user["username"]}) + "\n")
                tmp.replace(path)
            except OSError:
                pass


def pinged(user_id):
    """The Discord name a delivered card's receipt gave `user_id`, or None until one has."""
    try:
        data = json.loads((config.STATE / "discord-user.json").read_text())
    except (OSError, ValueError):
        return None
    return data.get("name") if isinstance(data, dict) and data.get("id") == user_id else None


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


class _Held(threading.local):
    def __init__(self):
        self.names = set()      # the seats whose lock this thread holds


_HELD = _Held()


@contextmanager
def session_lock(session, wait=True):
    """Serialize repeat checks, posts, acknowledgement and project votes across concurrent ak processes.

    `wait=False` is for a caller that must never wait on it -- a harness hook, which a delivery
    holding this lock may be typing the prompt for: it gets None at once while another has it.
    A thread waiting for one it holds already holds it on, as a switch lifts a seat's text and
    respawns it in one hold.
    """
    config.ensure_dirs()
    if wait and config.resolve_session(session) in _HELD.names:
        yield config.resolve_session(session)
        return
    while True:
        session = config.resolve_session(session)
        with config.notify_path(session).with_suffix(".lock").open("a") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield None
                return
            try:
                if config.resolve_session(session) != session:
                    continue       # a rename won while this writer waited for the lock
                _HELD.names.add(session)
                try:
                    yield session
                finally:
                    _HELD.names.discard(session)
                return
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)


@contextmanager
def name_lock(name):
    """The lock file of that very name, never followed to the seat it leads to: a rename back to
    an earlier name holds it, so a writer reaching that name once its record moves there waits
    for the files to follow."""
    config.ensure_dirs()
    with config.notify_path(name).with_suffix(".lock").open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
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
    if (not isinstance(data, dict) or data.get("kind") != "needs"
            or not isinstance(data.get("text"), str) or (resolved(data) and not include_seen)):
        return None
    return data


def resolved(data):
    """An owner's later prompt, or fresh output after an open, answers a question.

    These facts travel with the notice, so rendering never acknowledges it or depends on
    whether tmux reports a client attached. `seen` also covers explicit retirement and
    guarded retraction of the watcher's own recovery alerts.
    """
    if data.get("seen"):
        return True
    stamps = [data.get(key) for key in ("time", "answered_at")]
    if (all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n)
            for n in stamps) and stamps[0] < stamps[1]):
        return True
    stamps = [data.get(key) for key in ("time", "opened_at", "last_progress_at")]
    return (all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n)
                for n in stamps) and stamps[0] <= stamps[1] < stamps[2])


def answered(session, at, typed=None, replies=None):
    """The owner submitted a prompt; only the seat's question already standing is answered.

    The hook owns this fact. Keep it on the notice so a later line of ak's own or a rename
    cannot reopen it. The background look checks the pane and waits for this lock; card
    delivery stays with the tick. Watcher alerts end through their own recovery rules.
    With no question notice standing, the needs you only the screen said -- a dialog, a
    waiting prompt -- is what was answered, and its card keeps the answer.  An answered
    question lets go of the stall latch it held (`watch.forget`): opening the seat kept it.
    A question the seat kept back for its turn's end, that end on record, is the one he read
    at its stop and answers: it is asked here first, whoever held this lock when it ended.
    `typed` dates a message of the owner's read from the seat's conversation (`answer_written`):
    it answers only what was asked before it (`asked_at`), judged here, where the seat cannot
    ask another meanwhile.  `replies` name what a native card's answer answered (`replied`):
    only those questions, the rest standing.  True once a question was answered.
    """
    from . import watch    # here, not at the top: watch imports this module
    with session_lock(session) as session:
        # a standing question asked again, kept back under a newer card, is that card's now,
        # as its turn's end will record it (`_said`)
        renewed = {question_key(q["text"]): q.get("id")
                   for q in watch.questions_kept(watch.seat_read(session).get("unasked"))}
        partial = (watch.answered_kept(session, replies, typed or at)
                   if replies is not None else False)
        ask_kept(session, ended=True)
        previous = last(session)
        if replies is None and typed is not None and not typed > (asked_at(session) or math.inf):
            return
        if previous and previous.get("watcher") is True:
            return
        if replies is not None and previous:
            ids = {**(previous.get("question_ids") or {}), **renewed}
            dates = previous.get("question_times") or previous.get("asked_at") or {}
            matched = [q for q in questions(previous)
                       if replied(replies, q, ids.get(question_key(q)))
                       and dates.get(question_key(q), previous["time"]) < (typed or at)]
            if not matched:
                return partial
            remaining = [q for q in questions(previous) if q not in matched]
            if remaining:
                matched_keys = {question_key(q) for q in matched}
                waited({"asked_at": {k: v for k, v in (previous.get("asked_at") or {}).items()
                                    if k in matched_keys}}, at)
                previous.update(text=ALSO.join(remaining), questions=remaining)
                for field in ("asked_at", "question_times", "question_ids"):
                    previous[field] = {k: v for k, v in (previous.get(field) or {}).items()
                                       if k not in matched_keys}
                record(session, previous["kind"], previous["text"],
                       **{k: v for k, v in previous.items() if k not in ("session", "kind", "text")})
                return True
        if replies is not None and typed is not None and not previous:
            return partial      # a reply read again from the conversation: its question is gone
        # the needs you he answered has its card retired now, before a retry can take this lock
        card = _card_read(session)
        if not previous:
            if card.get("word") == "needs you":
                if at > card["since"]:
                    _retire(card)
                _card_write(session, {**card, "answered_at": at})
            return partial
        previous["answered_at"] = at
        if not resolved(previous):
            return
        if at > card.get("since", math.inf):
            _retire(card)
        waited(previous, at)
        record(session, previous["kind"], previous["text"],
               **{k: v for k, v in previous.items() if k not in ("session", "kind", "text")})
    watch.forget(session, acknowledge=False)    # after the notice lock: forget takes the state lock
    return True


def replied(replies, question, card):
    """Does a native card's reply name that question: by its card's id (`question_ids`), or,
    asked on none, by its words, as a card's answer may name what it asked."""
    return card in replies if card else question_key(question) in map(question_key, replies)


def spoken_at(notice):
    """The latest moment any question that notice asks was said: when the seat said one it kept
    back for its turn's end, else when it was asked."""
    return notice.get("said_at", notice["time"])


def asked_at(session):
    """When what the owner would answer in that seat was said: its own question standing, else
    a needs you only the screen said, unanswered; None where neither stands."""
    from . import watch
    notice = last(session)
    if notice:
        return (spoken_at(notice) if watch.owner_question(notice)
                and isinstance(notice.get("time"), (int, float)) else None)
    card = _card_read(session)
    return (card["since"] if card.get("word") == "needs you"
            and (card.get("answered_at") or 0) <= card["since"] else None)


PROMPT_WRITTEN = 2     # seconds a prompt's own message is given to reach the seat's conversation


def answer_written(name, at=None, wait=0):
    """A message of the owner's in that seat's conversation, written after what it asked them,
    answers it now, by the path their prompt takes (`answered`), whoever asked it.  Their prompt
    hook cannot say so: a harness hands it the turns it begins itself -- a scheduled check-in,
    another session's message, a notice that one was refused -- as it hands the owner's, and
    only its conversation marks them nobody's words (`owner_said`, which also leaves ak's own
    lines out).  `wait` gives a prompt's own message that long to arrive: a harness may write it
    only after its prompt hook returns.  Read only while something asked stands; a question kept
    back whose turn's end is on record is asked first, as `answered` asks it, and one whose turn
    still runs waits for the look that asks it, which dates it.  None where the seat's harness
    cannot say whose its messages are, and only its hook can."""
    from . import watch
    seat = None
    native_answered = False
    if last(name) or watch.seat_read(name).get("unasked"):
        seat = conversation_of(name)
        if seat and seat[3] and seat[0].reads_messages:
            for message in owner_messages(name, seat):
                if "replies" in message:
                    native_answered = bool(answered(name, at or time.time(), typed=message["at"],
                                                   replies=message["replies"])) or native_answered
    if watch.seat_read(name).get("unasked"):
        with session_lock(name) as locked:
            ask_kept(locked, ended=True)
    since, kept = asked_at(name), watch.seat_read(name).get("unasked")
    if since is None:
        return native_answered
    seat = seat or conversation_of(name)
    if seat is None or not seat[3] or not seat[0].reads_messages:
        return None
    deadline = time.monotonic() + wait
    while since is not None and not kept:
        typed = max((m["at"] for m in owner_messages(name, seat)
                     if "replies" not in m), default=0)
        if typed > since:
            return answered(name, at or time.time(), typed=typed)
        if time.monotonic() >= deadline:
            break
        time.sleep(0.2)
        since, kept = asked_at(name), watch.seat_read(name).get("unasked")
    return native_answered


def answer_typed(log=print):
    """A message the owner typed while a seat's turn ran went into that turn, and no prompt hook
    heard it: it answers by the conversation (`answer_written`)."""
    for name in config.session_records():
        if answer_written(name):
            log(f"{name}: its question was answered in the turn it was asked in")


def waited(notice, at):
    """Each question that notice asks the owner is answered at `at`: one wait apiece, from when
    it was last asked (`_said` dates them)."""
    for asked in (notice.get("asked_at") or {}).values():
        history.owner_time("answered", at, at - asked)


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


ALSO = " Also: "      # between the questions a notice asks


def question_key(question):
    """A question's identity and date share a key; its stored words stay untouched."""
    return " ".join(question.split()).casefold()


def questions(notice):
    """The questions a needs notice asks, in the order asked: its own, or the several a seat
    asked before its owner answered (`_said`)."""
    listed = notice.get("questions")
    if isinstance(listed, list) and listed and all(isinstance(q, str) for q in listed):
        return listed
    return [notice["text"]]


def typed_since(session, since):
    """The lines ak typed into that seat at `since` or after, by its typing receipts
    (`watch._send_line` writes one before each line): ak's own, never the owner's words it
    relays (`source` owner).  A question's answer is never one of them."""
    return [sent for sent in harness.entries(config.seat_file("input", session))
            if sent.get("source") != "owner" and isinstance(sent.get("at"), (int, float))
            and not isinstance(sent.get("at"), bool) and sent["at"] >= since]


def ak_prompt(session, said, notice):
    """The prompt is a line ak typed, rather than the owner's answer to that notice: one typed
    since its question -- a hand-back, a wait notice -- or the one that put the question to the
    seat, which carries its words and is typed before the question is recorded
    (`watch.ask_inbox`); heard before the record, it predates the question and answers nothing
    anyway (`resolved`).

    The window starts at the question on purpose: ak types only at a quiet prompt, so its line
    is heard before the seat can ask, and every other way of matching typing receipts to prompts
    met a new order of hooks or clocks in review.
    """
    since = (notice or {}).get("time")
    if not isinstance(since, (int, float)) or not said:
        return False
    # by its key: asked again in other spelling, a question keeps its first words (`_said`)
    asking = any(question_key(question) in question_key(said) for question in questions(notice))
    return any(sent.get("text") == said and (asking or sent["at"] >= since)
               for sent in typed_since(session, 0))


def answer_context(session, said):
    """The open questions this prompt may answer, read before its background look answers them.

    Read without the notice lock: a sender holds it while typing a prompt and waiting for
    this hook. Each question keeps its own last-asked date, or an older notice's timestamp.
    """
    from . import watch
    notice = last(session)
    if not watch.owner_question(notice) or ak_prompt(session, said, notice):
        return ""
    dated = notice.get("asked_at") or {}
    context = []
    for question in questions(notice):
        asked = dated.get(question_key(question), notice["time"])
        stamp = datetime.fromtimestamp(asked, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        context.append(f"Asked {stamp}:\n{question}")
    return "Questions you asked the owner that this prompt may answer:\n\n" + "\n\n".join(context)


def progress(session, capture, seat_harness):
    """Persist new output after an open; Discord and the row use the same resolved fact.

    Capture under the notice lock: output sampled before an open or a newer notify cannot
    resolve it. Empty captures and viewport resizing are not evidence of resumed work, and
    neither is output once ak has typed a line of its own into the seat since the open -- a
    hand-back, a wait's end: the seat's turn, not the owner's answer, which its harness's prompt
    hook then reports.  A line typed before the open is history, and so is one typed where no
    prompt hook reports anything: there this output is the only answer.
    Nor is any output the answer to the seat's own question where `seat_harness`, its harness
    (None for a seat ak has no record of), reports the owner's prompts or reads their messages:
    a seat asks with `ak notify needs` and works on, so its screen moves whether they answered,
    only looked or ak told it something, and their prompt (`answered`) or message
    (`answer_written`) is what answers it.
    """
    with session_lock(session) as session:
        previous = last(session)
        if not previous or previous.get("opened_at") is None:
            return
        plugin = harness.load(seat_harness) if seat_harness else None
        if (plugin and previous.get("watcher") is not True
                and (plugin.prompt_hook is not None or plugin.reads_messages)):
            return
        if any(isinstance(sent.get("harness"), str)
               and harness.load(sent["harness"]).prompt_hook is not None
               for sent in typed_since(session, previous["opened_at"])):
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
        record(session, previous["kind"], previous["text"], **extra)
        if resolved(extra):
            waited(extra, extra["last_progress_at"])
            return True


def clear(session, *, notice=None):
    """Retire a conversation's notice and the question it kept back for its turn's end, or
    retract only the watcher's matching alert."""
    with session_lock(session) as session:
        if notice is None:
            from . import watch    # here, not at the top: watch imports this module
            watch.seat_write(session, unasked=None)
        previous = last(session, include_seen=True)
        if not previous or previous.get("seen"):
            return
        if notice is not None and previous["text"] != notice:
            return
        # its episode ends here, as an answer's does, so a question asked before the next
        # tick gets a card of its own (`needs_transition`)
        card = _card_read(session)
        _retire(card)
        if card.get("word") == "needs you":
            _card_write(session, {**card, "answered_at": time.time()})
        record(session, previous["kind"], previous["text"],
               **{k: v for k, v in previous.items() if k not in ("session", "kind", "text", "seen")},
               seen=True)


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
    if event["status"] == "delivered":
        history.owner_time("paged", time.time())
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


def _remember(event):
    """A late-delivered event's notice, which the outbound event alone carried."""
    session = event["session"]
    if not session:
        return
    record(session, event["kind"], event["text"], **event.get("receipt", {}),
           time=event["created_at"],
           watcher=str(event.get("source") or "").startswith(("auth:", "stuck:", "stall:")))


def _remember_retry(event, session):
    """A late receipt never reopens an acknowledged menu row, and a card's never changes the
    session's notice: a card is the word's, and once out it is never edited."""
    if not session or str(event.get("source") or "").startswith("card:"):
        return
    previous = last(session, include_seen=True)
    if not previous or previous.get("time", 0) < event["created_at"]:
        _remember({**event, "session": session})


def _unsendable(event, session):
    """Why a queued event may no longer go out, or "".

    A retry is a card sent late, and the rules for sending hold for it too: nothing queued
    before the agentkit running now was installed, and nothing about a seat the owner has
    closed himself since.  A question that is over had its card retired then (`_retire`).
    """
    if event.get("created_at", 0) < installed_at():
        return "queued before the agentkit running now was installed"
    if session:
        from . import watch
        if watch.seat_closed_by_owner(session):
            return "its seat was closed by the owner"
    return ""


def _dropped(event, session, log=print):
    """Whether a queued event about to go out late is dropped unsent instead (`_unsendable`)."""
    why = _unsendable(event, session)
    if why:
        event.update(status="disabled", error=why, next_attempt=None)
        _write_event(event)
        log(f"notification {event['id']} dropped unsent: {why}")
    return bool(why)


def retry_pending(dry_run=False, log=print):
    """The existing watcher drains the outbox even when GitHub or the original seat is gone."""
    from . import watch
    for path in sorted(outbox().glob("*.json")):
        try:
            event = _read_event(path.stem)
            if not event or event["status"] in ("delivered", "disabled", "held"):
                continue    # a hold is released by a run ending, never by a retry
            if not event["session"]:
                continue    # a page is retried by asking for it again (`page`)
            if dry_run:
                log(f"would retry notification {event['id']} ({event['status']})")
                continue
            session = config.resolve_session(event["session"]) if event["session"] else None
            with session_lock(session) if session else nullcontext(session) as session, outbox_lock():
                event = _read_event(path.stem)
                if (session and event.get("episode") and event["kind"] == "needs"
                        and watch.session_state(session)["word"] == "working"):
                    continue    # its question stands through independent work: the stop sends it
                if _dropped(event, session, log):
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

    install.sh stamps `installed-at` on a server; a move of the checkout it installed
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


def _last_input(session, seat):
    """When he last typed into the seat or opened it, or 0 where its server cannot say.

    Ask the seat's own server for the session's activity: every key a client sends it and every
    attach move it, and it stays when he leaves, as a client's own activity does not.  Neither
    the seat's output nor a line ak types (`send-keys`) moves it.
    """
    from . import orch
    rc, output = orch.tmux_out("display-message", "-p", "-t", f"={session}:",
                               "#{session_activity}", socket=orch.seat_socket(seat))
    try:
        return int(output.strip()) if not rc else 0
    except ValueError:
        return 0


def _card_key(episode):
    """The outbox id of an episode's one card."""
    return hashlib.sha256(json.dumps(["card", episode, sink() is not None]).encode()).hexdigest()


def _retire(card):
    """A question's episode ends: its card, if Discord has not taken it yet, never goes out, and
    one it took stays as it went.  Called under the seat's lock, which a retry takes too, so a
    late card goes out only while its question stands.  An unsent card is looked up too:
    `_send_card` queues its event before it marks the card sent."""
    if card.get("word") != "needs you":
        return
    with outbox_lock():
        event = _read_event(_card_key(card["episode"]))
        if event and event["status"] not in ("delivered", "disabled"):
            event.update(status="disabled", error="the question it asked is over", next_attempt=None)
            _write_event(event)


def _send_card(session, kind, card, answer, completion=None):
    """Queue once under the session lock; the outbox owns any further attempts.  A done
    covers `completion`."""
    previous = last(session, include_seen=True)
    text = answer["reason"]
    # the seat's word shows its notice on one line; the card carries the notice as written
    if previous and " ".join(str(previous["text"]).split()) == text:
        text = previous["text"]
    payload = card_payload(kind, session)
    key = _card_key(card["episode"])
    with outbox_lock():
        event = _read_event(key)
        fresh = event is None
        if fresh:
            event = {"id": key, "source": "card:" + card["episode"], "episode": card["episode"],
                     "session": session, "kind": kind, "text": text, "files": [],
                     "payload": payload, "message": f"{TITLES[kind]} · {session}: {text}",
                     "created_at": time.time(), "sink": sink() is not None,
                     "status": "pending", "attempts": 0, "next_attempt": 0}
            if kind == "done" and completion:
                event["completion"] = completion
            _write_event(event)
        card["sent"] = True
        if kind == "done" and event.get("completion"):
            card["completed"] = event["completion"]
        _card_write(session, card)
        if fresh:
            terminal_notice(session, f"{TITLES[kind]} · {session}: {text}")
        return _attempt(event)


def page(key, about, text):
    """Page the owner about no seat, once per `key` however often it is asked: the outbox
    keeps the event, so no later tick or restart queues it again. One the webhook did not
    take is tried again on a card's schedule and rules only when asked again, so a caller
    asking while the page is still due never has it sent once it is not: 0 once it is out
    or never will be, 1 while it waits to be asked again.
    It reads as a seat's question does, `about` standing where the seat's name would."""
    payload = card_payload("needs", about)
    key = hashlib.sha256(json.dumps(["page", key, sink() is not None]).encode()).hexdigest()
    with outbox_lock():
        event = _read_event(key)
        if event is None:
            event = {"id": key, "session": None, "kind": "needs", "text": text,
                     "payload": payload, "message": text, "created_at": time.time(),
                     "sink": sink() is not None, "status": "pending", "attempts": 0,
                     "next_attempt": 0}
            _write_event(event)
        elif event["status"] not in ("delivered", "disabled") and _dropped(event, None):
            return 0
        _attempt(event)
        return 0 if event["status"] in ("delivered", "disabled") else 1


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


def _done_events(session):
    """Recorded completions of this seat, including its earlier names."""
    for path in outbox().glob("*.json"):
        try:
            event = json.loads(path.read_text())
            if (event.get("kind") == "done" and event.get("session")
                    and config.resolve_session(event["session"]) == session):
                yield event
        except (OSError, ValueError, AttributeError, TypeError, config.Error):
            continue


def _carded(session, completion):
    """The existing done receipt covering this work, if any.

    Recorded identities compare the checked work through later handbacks and renames.
    """
    return next((event for event in _done_events(session)
                 if event.get("completion") == completion), None)


def needs_transition(session, card, answer, now, seat=None, wait=CARD_WAIT):
    """One amber card once needs you has stood `wait`, the owner has typed nothing into the seat
    for as long and, for a question, been out of it a minute, which stays `Needs you` for as
    long as the seat does.

    Never for an episode that is history, nor for a seat the owner closed himself -- `x`,
    `ak orch stop` or a pause script: its row says so and its number reopens it, and nobody
    in it is asking him anything.
    """
    declared = last(session, include_seen=True) or {}
    # A newer notice carries the answer to the one it replaced (`shaped`).
    answered_at = max(card.get("answered_at") or 0, declared.get("earlier_answer_at") or 0,
                      (declared.get("answered_at") or 0) if resolved(declared) else 0)
    answered_here = answered_at > card["since"]
    asked = (declared.get("kind") == "needs" and declared.get("watcher") is not True
             and not resolved(declared))
    # A card that is out stays as it went: input there is him looking, at a dialog as at a
    # question the seat asked, and his answer or the word changing (`transition`) ends its
    # episode.
    if answered_here:
        _retire(card)
        # The answer ends the needs you it answered, its card left as it went out: one still
        # read now came after it -- a dialog, or the seat waiting again -- and is an episode
        # of its own, though no tick saw the seat work in between.  Its minute counts from
        # now, no earlier than its current question: an older callback can still be
        # publishing. It began after the answer, which an upgrade since makes history, and
        # after a newer `ak notify` asking again, which is never history; a watcher's notice
        # is dated by the word.
        card = {"word": "needs you", "since": max(
                    now, declared.get("time", 0) if asked else 0), "began": max(
                    answered_at, 0 if declared.get("source") else declared.get("time", 0)),
                "episode": secrets.token_hex(16), "sent": False,
                **({"completed": card["completed"]} if card.get("completed") else {})}
        _card_write(session, card)
        return 0
    if card.get("sent"):
        return 0
    # His keys hold back a card that is not out yet, and a client in the seat holds back a
    # question's for as long as he is there: a seat works on with its question standing, so a
    # glance at it must not answer it.  The minute counts from his last key, though he left
    # between two ticks, and from the first look that found him gone, as tmux keeps no time
    # he left.  A login or a failure is no question: he may be in the seat without seeing it.
    if seat is None:
        from . import orch
        seat = orch.find(session) or {}
    present = bool(answer.get("question") and seat.get("attached"))
    if bool(card.get("present")) != present:
        card.update(present=present, left=now)
        _card_write(session, card)
    if present or now - card.get("left", 0) < CARD_WAIT or now - max(
            card["since"], _last_input(session, seat)) < wait:
        return 0
    from . import watch
    if _history(card) or watch.seat_closed_by_owner(session):
        return 0
    return _send_card(session, "needs", card, answer)


def done_transition(session, card, answer, now, completion):
    """One completion when the state function says done.

    Never for an episode that is history, a seat the owner closed himself, or work already
    carded -- which latches this episode as sent, so the outbox is read once.  A done that
    covers none of the seat's verified work (`completion`: its plan holds only
    what runs delivered, or the seat has no creation stamp) cards nothing: its first pass ends
    the owner's intent.
    """
    from . import watch
    if card.get("sent") or _history(card) or watch.seat_closed_by_owner(session):
        return 0
    if not completion and card.get("closed") == "Done":
        return 0        # read already: its first pass is on record
    card["closed"] = "Done"
    if not completion:
        _intent(session, now)
        _card_write(session, card)
        return 0
    receipt = _carded(session, completion)
    if card.get("completed") == completion or receipt:
        card["sent"] = True
        card["completed"] = completion
        _card_write(session, card)
        return 0
    _intent(session, now)     # work the plan proved
    return _send_card(session, "done", card, answer, completion)


def transition(session, answer=None, now=None, dry_run=False, log=print, seat=None,
               began=None, wait=CARD_WAIT):
    """The command and tick share a session lock, the decision and the episode file.

    `began` is an explicit command's own moment: the episode it lands in, unless its card
    already went out, begins there, so `ak notify` is never history.  `wait` is how long the
    word and the owner's last key hold its card: a notice is asked on purpose and waits for
    neither.
    """
    if os.environ.get("AK_RUN_ROLE") == "worker" or dry_run:
        return 0
    # A legacy seat is another program's session: the tick never cards it, while an
    # explicit `ak notify --session` still may -- it names its subject on purpose.
    if seat is not None and seat.get("legacy"):
        return 0
    from . import watch, menu, orch
    try:
        with session_lock(session) as name:
            at = time.time() if now is None else now
            card = _card_read(name)
            records = menu.run_records()
            declared = last(name, include_seen=True)
            previous = watch.seat_read(name)
            # A screen may have observed an intervening episode since our last tick.
            if card and (previous.get("word_since") or 0) <= card.get("since", 0):
                previous = {"word": card["word"], "word_since": card["since"]}
            current = watch.session_state(name, now=time.time() if answer is not None else at,
                                          session=seat, records=records,
                                          previous=previous, card=True)
            # A newer notice or run can outrank the answer shaped read before this
            # lock. An unchanged word keeps its observed beginning, including the explicit
            # question's clock before shaped advances the hold.
            if answer is not None and answer["word"] == current["word"]:
                current["since"] = answer.get("since")
            elif answer is not None:
                began = None
            answer = current
            since = answer.get("since")
            since = since if isinstance(since, (int, float)) and math.isfinite(since) else at
            word = answer["word"]
            # An older command's clock cannot make input before the current question its
            # answer, or make that question history across an install.
            asked = (declared.get("time") if watch.owner_question(declared)
                     and not resolved(declared) else None)
            if word == "needs you" and isinstance(asked, (int, float)) and math.isfinite(asked):
                since = max(since, asked)
                if began is not None:
                    began = max(began, asked)
            # a done covers the seat's verified work now
            completion = _completion(name) if word == "done" else None
            # A needs you whose question still stands keeps its episode through a turn a run's
            # result opens: the same question, asked again at that turn's stop, is no news.
            kept = card.get("word") == "needs you" and word == "working" and asked is not None
            if card.get("word") != word and not kept or (
                    word == "done" and completion and card.get("completed") and card.get("sent")
                    and card.get("completed") != completion):
                _retire(card)
                card = {"word": word, "since": since, "began": since,
                        "episode": secrets.token_hex(16), "sent": False,
                        **({"completed": card["completed"]} if card.get("completed") else {})}
                if seat is not None and any(seat.get(key) for key in orch.CLOSED):
                    # a seat nobody is in began its word when it went, whichever tick reads it
                    card["began"] = min(since, _went_at(name))
                _card_write(name, card)
            if began is not None and not card.get("sent") and card.get("began") != began:
                card["began"] = began
                _card_write(name, card)
            if word == "needs you":
                return needs_transition(name, card, answer, at, seat, wait)
            if word == "done":
                return done_transition(name, card, answer, at, completion)
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
        for name, _ in config.seat_files("card"):
            if name not in known and orch.seatless(name):
                forget_card(name, log)


def forget_card(name, log=lambda _: None):
    """Drop a gone session's card, retiring it where Discord has not taken it yet; what went
    out stays as it went.

    The notify lock stays: a writer may hold it or wait on it, and one that opened a new file in
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
            _retire(_card_read(name))
            config.card_path(name).unlink(missing_ok=True)
        log(f"closed the card of {name}: no seat holds it any more")
    except (OSError, ValueError, config.Error) as exc:
        log(f"WARN the card of {name} was not closed ({type(exc).__name__}); retry required")


def _completion(session):
    """Verified plan work, beside the work earlier Done cards covered: a receipt remembers its
    distinct outcomes after plan cleanup."""
    from . import plan
    created = (config.session_records().get(session) or {}).get("created")
    if created is None:
        return None

    def outcomes(value):
        if not isinstance(value, dict) or value.get("created") != created:
            return set()
        return {tuple(outcome) for outcome in value["outcomes"]}

    covered = outcomes(_card_read(session).get("completed"))
    for event in _done_events(session):
        covered.update(outcomes(event.get("completion")))
    work = set(plan.outcomes(session))
    if not work:
        return None
    return {"created": created, "outcomes": [list(outcome) for outcome in sorted(work | covered)]}


def asks_first(text):
    """Refuse a question whose "?" is not within its first ASK_CAP characters."""
    asked, mark, _ = " ".join(text.split()).partition("?")
    if not mark or len(asked) >= ASK_CAP:
        raise config.Error(f'put the question first, its "?" within {ASK_CAP} characters: '
                           "the status bar and the menu show a question's start; context "
                           "goes after it")


def keep_back(name, text, question_id=None):
    """Keep the seat's question back for its turn's end, after any it kept already, in the
    seat's record, which `ask_kept` asks once that turn has ended.  The seat's newer word ends its `ak wait` here as `shaped`
    does.  No notice lock is taken, so the stop hook keeps one without waiting on it."""
    from . import watch
    asks_first(text)
    watch.keep(name, text, question_id=question_id)


def shaped(kind, text, paths=(), session=None, dry_run=False, event_id=None, question_id=None):
    """Record the question, then evaluate the transition latch.

    A question the seat itself asks waits for its turn's end where `watch.keeps_back` says so:
    nothing is recorded here but the question, in the seat's record, which `ask_kept` turns
    into this notice when that turn has ended."""
    if worker_blocked(kind, dry_run):
        return 0
    if paths:
        raise config.Error("--file was removed: notification cards carry no attachments")
    name = config.resolve_session(session) if session else config.current_session()
    if dry_run:
        print(json.dumps(card_payload(kind, name), indent=2))
        terminal_notice(name, f"{TITLES[kind]} · {name or 'agentkit'}: {text}", dry_run=True)
        return 0
    if not name:
        raise config.Error("notify needs a session: use --session NAME")
    from . import watch
    try:
        own = name == config.current_session()      # the seat's own word
        if kind == "needs" and own and event_id is None and watch.keeps_back(name):
            keep_back(name, text, question_id=question_id)
            return 0
        with session_lock(name) as name:
            previous = _said(name, kind, text, event_id,
                             question_ids={question_key(text): question_id})
            if event_id is None:
                # the seat's newer word ends its `ak wait`; a question it kept back waits for
                # its own turn's end, and is asked beside this one then (`ask_kept`)
                watch.seat_write(name, wait=None)
        # A command is the visible start of the episode. Decide from now's facts, waiting for
        # no earlier key, so the recorder's own question is not left waiting for the
        # three-minute watcher tick; the owner in the seat, or there within the minute, still
        # holds it. A repeated watcher event re-records nothing, but the latch is still
        # evaluated: the first attempt may have recorded without ever queueing the card.
        stamp = time.time()
        answer = watch.session_state(name, now=stamp)
        if answer["word"] == "needs you":
            since = answer.get("since")
            if not (isinstance(since, (int, float)) and math.isfinite(since)
                    and since <= stamp):
                answer["since"] = stamp
        # `ak notify` itself begins its episode at the command, however long the word it
        # lands on has stood; a watcher's own notice is dated by the word.
        return transition(name, answer=answer, now=stamp, wait=0,
                          began=stamp if event_id is None else None)
    except (OSError, ValueError, config.Error) as exc:
        print(f"notify: record could not be persisted ({type(exc).__name__}); retry required", file=sys.stderr)
        return 1


def _said(name, kind, text, event_id=None, at=None, said_at=None, question_times=None,
          question_ids=None):
    """Record what that session said, under its notice lock, which the caller holds; the
    notice it replaced, or None.  A watcher's repeated event re-records nothing, nor does its
    alert while the seat's own question stands unanswered.  A question -- `text` one, or the
    several a turn kept back -- is asked beside every one still standing unanswered, each once
    (asked again, it is dated anew), and the owner's one prompt after it answers them all
    (`answered`).  `at` dates it where it was said before now, never before those it is asked
    beside.  `said_at` is when the seat said what it kept back for its turn's end: the notice
    keeps the latest moment any question it asks was said (`answer_typed`)."""
    from . import watch
    previous = last(name, include_seen=True)
    if event_id and previous and previous.get("source") == event_id:
        return previous
    extra = {"source": event_id,
             "watcher": str(event_id or "").startswith(("auth:", "stuck:", "stall:"))}
    if extra["watcher"] and watch.owner_question(previous) and not resolved(previous):
        # The seat's own question outranks a watcher's alert: its owner is asked already, and
        # the seat's screen says what the alert would.  Taken in its place, the question was
        # lost once the alert was retracted, though nobody had answered it.
        return previous
    fresh = 0     # the questions this notice asks the owner for the first time
    if kind == "needs":
        standing = (questions(previous) if watch.owner_question(previous)
                    and not resolved(previous) else [])
        if standing and at is not None:
            at = max(at, previous["time"])
        asked, seen = list(standing), {question_key(q) for q in standing}
        dated = dict(previous.get("asked_at") or {}) if standing else {}
        said_dates = dict(previous.get("question_times") or dated) if standing else {}
        ids = dict(previous.get("question_ids") or {}) if standing else {}
        for question in [text] if isinstance(text, str) else text:
            words = question_key(question)
            if words not in seen:
                seen.add(words)
                asked.append(question)
            dated[words] = time.time() if at is None else at
            original = (question_times or {}).get(words, dated[words])
            # A delayed Stop can bring an older copy of a question already repeated.
            if question_times is None or original > said_dates.get(words, -math.inf):
                said_dates[words] = original
                ids[words] = (question_ids or {}).get(words)
        text = ALSO.join(asked)
        if len(asked) > 1:
            extra["questions"] = asked
        if not extra["watcher"]:
            fresh = len(asked) - len(standing)
            extra["asked_at"] = dated
            extra["question_times"] = said_dates
            extra["question_ids"] = ids
        if said_at is not None:
            extra["said_at"] = max([said_at, *([spoken_at(previous)] if standing else [])])
    earlier = previous and previous.get("answered_at", previous.get("earlier_answer_at"))
    if earlier:
        # The answer ends its card's episode at the next tick; the newer notice carries it
        # there, in a field of its own: it answered only the one replaced.
        extra["earlier_answer_at"] = earlier
    if at is not None:
        extra["time"] = at
    record(name, kind, text, **extra)
    for _ in range(fresh):
        history.owner_time("asked", time.time() if at is None else at)
    return previous


def conversation_of(name):
    """That seat's (harness plugin, record, checkout, conversation), or None where it has no
    record or its harness cannot say which conversation is its."""
    from . import orch
    record = config.session_records().get(name)
    if not record:
        return None
    plugin, cwd = orch.seat_plugin(record), record.get("cwd")
    try:
        return plugin, record, cwd, plugin.conversation(record, cwd)
    except (OSError, ValueError):
        return None


def owner_said(name, seat=None):
    """When the owner wrote each of their messages in that seat's conversation, oldest first:
    `user_messages` leaves ak's own lines out; none where it cannot be read."""
    return [message["at"] for message in owner_messages(name, seat)]


def owner_messages(name, seat=None):
    """The owner's messages, including which questions a native reply answers."""
    seat = seat or conversation_of(name)
    if seat is None or not seat[3]:
        return []
    plugin, record, cwd, conversation = seat
    try:
        return plugin.user_messages(record, cwd, conversation, seat=name)
    except (OSError, ValueError):
        return []


def _intent(name, done_at):
    """Record that seat's done with where the owner's intent it ends began: their first message
    in its conversation since that conversation's previous done (`user_messages` leaves ak's own
    lines out).  Read here, from facts already decided, never stamped by a prompt's hook: hook
    order, renames and reused names moved such stamps after they were written.  The start is
    unknown, and the done still the next one's boundary, with no message of theirs since, where
    the harness reads no messages or cannot read them now, for the first done of a
    conversation begun before dones were kept: its earlier dones were never recorded, and a
    notice keeps only a seat's latest, and where the seat's finished work, its plan's done lines
    and the runs it launched that merged, is what that conversation's previous done recorded:
    an answer about finished work finished nothing.  A known start keeps the runs the seat
    started from it to the done."""
    from . import menu, plan
    seat = conversation_of(name)
    if seat is None:
        return
    plugin, conversation = seat[0], seat[3]
    known = history.last_done(f"{plugin.name}:{conversation}") if conversation else None
    if known is None:
        return
    records = menu.run_records()
    merged = sorted(directory.name for directory, state in records
                    if state.get("merged") and transitions.launched_session(state) == name)
    # every line ticked, a run's too: asking which run has one (`taken`) takes the seat lock
    # this caller holds
    ticked = plan.outcomes(name, runs=False)
    work = hashlib.sha256(json.dumps([ticked, merged]).encode()).hexdigest()
    asked = [at for at in owner_said(name, seat) if at <= done_at]
    last, since, then = known
    fresh = [at for at in asked if last is None or at > last]
    if not fresh or (last is None and min(asked) < since) or work == then:
        history.done(f"{plugin.name}:{conversation}", done_at, None, work=work)
        return
    began = min(fresh)
    # the runs the seat started for it, whose going live is the intent's
    history.done(f"{plugin.name}:{conversation}", done_at, began,
                 [directory.name for directory, state in records
                  if transitions.launched_session(state) == name
                  and began <= (state.get("started_at") or 0) <= done_at], work=work)


def ask_kept(name, ended=False):
    """The turn that seat asked in has ended: the questions it kept back become its notice,
    as the command would have recorded them, dated at that end (`watch.turn_ended`).

    The caller holds `session_lock(name)`.  With `ended` it asks only those whose turn's end
    is already on record, which are the first kept: the caller has not looked at the seat
    itself, and one kept since, in a turn still going, waits for its own.  The tick's card
    pass sends the card, like any other's.
    """
    from . import watch
    kept = watch.questions_kept(watch.seat_read(name).get("unasked"))
    if ended:
        kept = list(itertools.takewhile(lambda question: "ended" in question, kept))
    if not kept:
        return False
    stamps = [question.get("ended") for question in kept]
    spoken = [question.get("at") for question in kept]
    _said(name, "needs", [question["text"] for question in kept],
          at=None if None in stamps else max(stamps),
          said_at=None if None in spoken else max(spoken),
          question_times={question_key(q["text"]): q["at"] for q in kept if "at" in q},
          question_ids={question_key(q["text"]): q.get("id") for q in kept})
    watch.kept_asked(name, kept)
    return True


def check():
    """Prove the webhook is live without posting: Discord answers a GET with the hook object.

    0 on 200, 1 on anything else, and 2 -- via config.Error -- only when none is configured.
    """
    url = _secret(WEBHOOK_ENV, "discord_webhook")
    if not url:
        raise config.Error("--check: no webhook configured; put one in "
                           f"{config.SECRETS / 'discord_webhook'} or ${WEBHOOK_ENV}")
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
    kind = argv[0] if argv[:1] == ["needs"] else None
    rest, session, dry_run, i = [], None, False, 1 if kind else 0
    while i < len(argv):
        arg = argv[i]
        if kind and arg == "--session":
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
    if not kind or len(rest) != 1 or rest[0].startswith("-") or not rest[0].strip():
        raise config.Error(USAGE)
    if worker_blocked(kind, dry_run):
        return 0                          # before the question's shape: a worker asks nothing
    asks_first(rest[0])
    own = config.current_session()
    if own and (session is None or config.resolve_session(session) == own):
        from .stop import question_refused
        refused = question_refused(own)     # as its question prompt is
        if refused:
            raise config.Error(refused)
    return shaped(kind, rest[0].strip(), session=session, dry_run=dry_run)
