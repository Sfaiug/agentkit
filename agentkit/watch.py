"""`ak watch`: other people's PRs and this machine's stalled seats, every three minutes from cron.

For every checkout under ~/code whose GitHub repo this account owns, each open PR by somebody
else that agentkit has not reviewed at its current head gets a review-only run (`ak run
--review-pr <url> --bg`).  That run posts its verdict as a GitHub review and, on PASS with green
checks, hands the question to the `inbox` seat -- started here if it is not running -- and pings
the user with `ak notify needs`.  The orchestrator in that seat merges on yes.

The other direction too: this account's open PRs on repos it does not own -- the ones a run
without push rights opened from a fork and left `waiting for the maintainer`, and the ones the
user opened by hand -- are followed here.  What the maintainer decided is left on the run,
where `ak run status` and the menu show it, and typed into the seat that opened it while
that seat is live.  Never Discord: the user's own PR moving is neither an orchestrator
needing them nor a job finishing, and those two are all Discord ever hears.

Every tick also looks at the seats themselves: a pane showing its harness's own words for a
stall is typed back into motion, which is what makes a night's work survive an API error nobody
was there to answer.  See the babysitter's own block below.  And merged agentkit goes live here,
working sessions or not: see `update.go_live`; so does a harness's newer release, upgraded in
the background through `ak update`'s gates: see `update.keep_current`.

What was reviewed, what was said and which seat is stuck is kept in ~/.agentkit/state/watch.json,
so a tick never launches the same review twice and never says the same thing twice.  A launched
review counts only once its run has posted; one that died is retried with recoverable backoff.
`--dry-run` lists what a tick would do and does none of it, under a line saying whether a real
tick is running right now and how big the log it writes has grown.
"""

from contextlib import contextmanager, nullcontext, redirect_stdout
import base64
import fcntl
import io
import json
import math
import os
import re
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import (aside_editor, browser, command_help, config, gc, gitcall, handback, host, notify,
               orch, seat_tokens, staffing, statusbar, transitions, turns, update, usage, worker)
from . import record as run_record
from . import terminal as terminal_mod
from .harness import LIMITED, SPENT, entries, says
from .lifecycle import LIVE, facts as hook_facts, held_work, state as hook_state

INBOX_WARMUP = 10       # seconds a seat that was just started gets before it is typed into
# what a seat reopened after its process died mid-turn is told, in a run's mid-turn words
MIDTURN_LINE = ("Your process was ended by the host, not by you, in the middle of a turn. "
                "Continue that turn and finish it; do not start over.")
# ... and one reopened while it asked the owner: its harness marks the open question interrupted
ASKED_LINE = ("The host restarted while your question to the owner was still open. "
              "Ask it again.")
# ... and one whose turn its usage cut off, on an account with usage again, this or another
ACCOUNT_LINE = ("Your turn was cut off when its usage ran out, and there is usage again. "
                "Continue that turn and finish it; do not start over.")
# ... and, after any of these or alone, one whose background work went with its process
HELD_LINE = ("Your process was ended, not by you, while it held background work: {}. Resume "
             "what can be resumed and start the rest again.")
# ... and one moved mid-turn to a model of another harness: its rulebook hands the turn on
MOVED_LINE = ("This seat moved to you in the middle of a turn. Continue that turn from where "
              "the conversation your instructions point you to leaves it; do not start over.")
CONTINUE_LINE = "continue"
MIDTURN_TRIES = 3       # passes that may type it before a seat is left at its prompt
MARKER = "agentkit review of"
RETRY_BACKOFF = (600, 1800, 3600)  # after that, hourly; a head is never abandoned
KEY_GAP = 0.5           # text and Enter go separately: a return in the same read as the text
                        # is absorbed by the TUI, leaving the line unsent; measured on Codex
                        # 0.153.4 and Muse 1.2.1, 0.10 s still lost it and 0.15 s did not
SENT_WAIT = 5.0         # how long a typed line gets to show whole in its composer, and to leave it
SENT_POLL = 0.5         # ... polling the pane this often for its absence
RESUME_EVERY = 600      # seconds between resume attempts for one exhausted run: a start that
                        # failed -- and a launch already on its way -- is retried at most this often
DEAD_BACKOFF = 600      # a loop that dies again this soon after its resume waits this long
DEAD_WINDOW = 3600      # a third death inside this parks the run and tells the seat once
# What gh says when the credentials are the problem rather than the network: gh's own advice
# when there is no login at all, and the API's own words when the token is rejected.  A
# timeout, an unreachable api.github.com or a reply that was not JSON says none of these, and
# none of those is a login for the user to go and fix.  Neither is a 403, which is what a
# rate limit answers with credentials that are perfectly good; only 401 is about the login.
LOGGED_OUT = re.compile(r"gh auth login|not logged in|bad credentials|HTTP 401", re.I)
# the ticks a wait may stand on a fact nobody can read before it ends, said
UNREAD_TICKS = 3


def ask_inbox(cfg, question, url, sha, log, asked=False, typed=lambda: None):
    """Put the question to the inbox seat, and then to the user.  0 once both have it.

    The merge the seat is told to run is pinned to the commit that was reviewed: gh refuses
    `--match-head-commit` when the author has pushed since, so a yes can never merge code the
    reviewer never saw.  The user is pinged only after the seat took the question: their yes
    goes to a seat that knows what it is for.  `typed` is told when it did, and `asked` says
    an earlier try's did, so a retry of a failed ping never types the question twice.
    """
    # the seat by the name it goes by now: renamed once, `inbox` is a pointer at it, and the
    # question, the keys and the ping all have to land on the seat and not on the old name
    name = config.resolve_session(config.inbox())
    if asked:
        return notify.shaped("needs", question, session=name, event_id=f"inbox:{url}:{sha}")
    if orch.ensure(cfg, name, log):
        time.sleep(INBOX_WARMUP)     # the TUI has to be listening before it is typed into
    line = (f"{question} -- {url} at {sha[:12]}, reviewed by agentkit. The user was pinged with "
            "`ak notify needs`; wait for their yes or no here. On yes run `gh pr merge " + url
            + f" --squash --delete-branch --match-head-commit {sha}` -- it refuses if the author "
            "has pushed since the review, and then the PR needs a new review, not a merge; on no "
            "leave the PR as it is and say so.")
    # `=name:` -- the session, exactly, and its current pane: send-keys wants a pane target,
    # on whichever server holds the seat, which for a legacy one is not agentkit's own
    session = orch.find(name) or {"name": name}
    try:
        harness, _ = seat_model(cfg, name)
    except (config.Error, OSError):
        harness = None

    composed = []
    # an earlier try's Enter failed and left this very question in the composer: only its
    # Enter is owed, and that draft is ours, not one the question would be typed onto
    ours = re.sub(r"\s+", "", line)
    stuck = composer_draft(harness, pane_text(session)) == ours

    def veto(held):
        # Under the seat lock the other senders type under, held back by an owner question as
        # recovery nudges are -- except for an earlier PR's merge question, which is ours.  The
        # screen is read once, before typing: text already in the composer, or a dialog, would
        # go out with the question as one garbled prompt, and after typing the composer holds
        # the question.
        notice = notify.last(held)
        if owner_question(notice) and not str(notice.get("source") or "").startswith("inbox:"):
            return True
        if composed:
            return False
        composed.append(True)
        pane = pane_text(session)
        state, draft = _decided_state(held, harness, pane), composer_draft(harness, pane)
        if stuck:
            return state == "asking" or draft != ours
        return state in ("draft", "asking") or bool(draft)

    if not type_checked(session, line, log, harness, pending=stuck,
                        guard=lambda: seat_held(name), veto=veto):
        log(f"WARN could not type the question into the {name} seat")
        return 1
    log(f"asked the {name} seat: {question}")
    typed()
    return ask_inbox(cfg, question, url, sha, log, asked=True)


# --- the tick ---------------------------------------------------------------
# The tick is a three-minute cron line, so it has to look after itself: one at a time, its own
# log kept small, and no single thing it cannot do -- a logged-out `gh` above all -- allowed to
# take the rest of it down with a traceback.


TICK_HUNG = 1800        # seconds a tick may hold the lock before the log calls it hung
LOG_NAME = "watch.log"  # the tick's own log; cron only redirects into it
LOG_MAX = 5 * 1024 * 1024   # ... and it is rolled over to <name>.1 once it passes this
LOG_KEPT = f"{LOG_NAME}.1"  # one generation; there is nothing older to keep
LOG_OWNED = set()       # ... and the streams of ours found to be it, kept because a roll can
                        # unlink the file under them and an unlinked descriptor has no name


def state_path():
    return config.STATE / "watch.json"


def tick_lock_path():
    return config.STATE / "watch.tick.lock"


def log_path():
    return config.TMP / LOG_NAME


def tick_lock():
    """The held one-tick-at-a-time lock, or None because another tick already holds it.

    Cron starts a tick every three minutes whatever the last one is doing, and a tick that
    runs long is not rare: it reads every pane, waits on typed lines and talks to GitHub.  The
    state lock only serialises the writes around all of that, so two ticks could still be
    reading the same panes and typing into the same seats.  This one is taken first and held
    for the whole tick; the caller closes it, and a killed tick's kernel closes it for free.
    """
    handle = tick_lock_path().open("a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")    # the write is also the stamp: mtime is when we began
    handle.flush()
    return handle


def tick_holder():
    """(pid, seconds it has been holding) of whoever has the lock, off the file it wrote."""
    path = tick_lock_path()
    try:
        pid = int(path.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        pid = 0
    try:
        holding = max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        holding = 0.0
    return pid, holding


def tick_running():
    """(pid, seconds held) when a tick is in flight, else None: the question `--dry-run` asks.

    Asking is taking and letting go again, so this never creates the lock file: no lock file
    means no tick has ever run here, which is the same answer as a free one.
    """
    try:
        handle = tick_lock_path().open("r+")
    except OSError:
        return None
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return tick_holder()
        fcntl.flock(handle, fcntl.LOCK_UN)
    return None


def same_file(stream, found):
    """Is that stream's descriptor the file `found` was stat'ed from."""
    try:
        ours = os.fstat(stream.fileno())
    except (OSError, ValueError, AttributeError):
        return False
    return (ours.st_dev, ours.st_ino) == (found.st_dev, found.st_ino)


def log_files():
    """The two files that count as the tick's log: the live one and the generation behind it.

    A writer can be one roll behind and no more, because every line it writes rejoins the live
    log first.  So a descriptor on either of these is one the log owns -- whether this tick
    rolled it or an overlapping tick did, and whether or not this tick had written a line yet
    when that happened.
    """
    found = []
    for name in (LOG_NAME, LOG_KEPT):
        try:
            found.append(log_path().with_name(name).stat())
        except OSError:
            pass
    return found


def log_streams():
    """Which of our streams the log owns: cron's line is `>>watch.log 2>&1`, so both are it.

    Found by name the first time -- either name, so a tick that had not written a line when
    somebody else rolled is recognised too -- and remembered from then on, because the roll
    after that unlinks the file and a descriptor on an unlinked file answers to no name at
    all.  `ak watch` run by hand prints to a terminal and a test prints into a buffer, and a
    `2>` somewhere else is somebody else's file; none of those is ever claimed here.
    """
    files = log_files()
    for name in ("stdout", "stderr"):
        if any(same_file(getattr(sys, name), found) for found in files):
            LOG_OWNED.add(name)
    return [getattr(sys, name) for name in sorted(LOG_OWNED)]


def follow_log():
    """Put the streams the log owns back on whatever its name points at now.

    A roll is a rename, and cron opened the file rather than the name.  Our own roll leaves our
    descriptors on the generation just closed; an overlapping tick's roll leaves them there
    while we were not even looking -- and a writer left behind goes on filling a file the next
    roll unlinks, and never bounds anything again.  Reopening the name is how a writer rejoins
    the live log, whoever rolled it.
    """
    path = log_path()
    try:
        live = path.stat()
    except OSError:
        live = None
    behind = [stream for stream in log_streams()
              if live is None or not same_file(stream, live)]
    if not behind:
        return
    try:
        with path.open("a") as fresh:
            for stream in behind:
                stream.flush()      # what it wrote before the roll belongs in the roll
                os.dup2(fresh.fileno(), stream.fileno())
    except (OSError, ValueError):
        pass        # a log we cannot reopen is no reason to lose the tick


def log_lock_path():
    return config.STATE / f"{LOG_NAME}.lock"


def rotate_log():
    """Roll the log this tick is writing into over to one kept generation past LOG_MAX.

    Nothing else ever trims it: the cron line only redirects, with `>>`, and would append for
    years.  The roll is under a lock and the size is read again inside it, because two ticks
    that both saw the file oversized would otherwise both rename: the second rename would put
    the first one's brand-new log where the kept generation goes and unlink the generation
    itself -- five megabytes of history gone, and whoever still held it writing into nothing.
    Whether we rolled or somebody else did, we rejoin the live log before returning.  True
    when this call was the one that rolled.
    """
    if not log_streams():
        return False
    path, rolled = log_path(), False
    try:
        if path.stat().st_size > LOG_MAX:
            with log_lock_path().open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if path.stat().st_size > LOG_MAX:
                    path.replace(path.with_name(LOG_KEPT))
                    rolled = True
    except OSError:
        pass            # a log that cannot be rolled is no reason to skip the tick
    follow_log()
    return rolled


def tick_log(text):
    """Print one of the tick's lines, keeping the file it prints into bounded on the way in.

    The bound belongs on the write path and nowhere else: the cron line only redirects, so
    nothing will ever trim that file for us, and every tick has lines of its own to write --
    including the one that never gets the lock, which is the only thing still writing while
    another tick hangs on to it.  Flushed as it goes, so a log read while a tick is still
    running shows how far that tick has got.
    """
    rotate_log()
    print(text, flush=True)


def tick_health():
    """The line `--dry-run` prints beside its preview: who holds the lock, how big the log is."""
    running = tick_running()
    lock = (f"lock held by pid {running[0]} for {int(running[1] // 60)} min" if running
            else "lock free")
    try:
        size = log_path().stat().st_size
    except OSError:
        size = 0
    return f"{lock} · {LOG_NAME} {size / 1048576:.1f} MB of {LOG_MAX / 1048576:.0f} MB"


def generation(value):
    """An on-disk generation must be numeric, nonnegative and safely incrementable."""
    try:
        if (isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
                and math.isfinite(math.nextafter(value, math.inf))):
            return value
    except OverflowError:
        pass
    return 0


def load_state():
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    for key in ("reviewed", "own", "stalls", "seen_at", "after_merge"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    data["seen_at"] = {name: generation(stamp) for name, stamp in data["seen_at"].items()}
    return data


def tell_audit(cfg, log, now=None):
    """The tick's pass for the `audit` seat: the week's line (`audit.weekly`), else a stall's
    (`stuck.scan`), goes into the seat at its quiet prompt.  The seat is opened with the
    setting's models while there is neither a seat nor a record of one, resumed while its
    record is there and its process gone (`orch.ensure`), and left alone while the owner closed
    it on purpose: what the owner stopped stays stopped, and the line waits for them to open
    it.  Delivered at least once: the mark is kept in the line's record from tick to tick until
    the composer reads empty, and a tick that dies mid-line is finished by the next.  The one
    exception to "only a person opens a seat" (AGENTS.md, Owner rules, 14 Oct, 17 Oct)."""
    from . import audit, stuck
    now = time.time() if now is None else now
    pending = stuck.read()
    # a stall's line in the composer is sent before a new week's is written to go after it
    found, write = (None if pending.get("typed") and not pending.get("delivered")
                    else audit.weekly(cfg, log, now)), audit.write
    if not found:
        found, write = stuck.scan(cfg, log, now), stuck.write
    if not found:
        return
    setting, state = found
    about = f"week {state['week']}" if state.get("week") else state["about"]
    name = config.resolve_session(audit.NAME)     # the name the owner may have given it since
    if seat_closed_by_owner(name):
        if not state.get("held"):
            state["held"] = True
            write(state)
            log(f"audit: the {name} seat was closed by the owner; its line about {about} "
                "waits for them to open it")
        return
    seat = orch.find(name)
    if not seat or seat.get("exited"):
        # the next tick types, once the harness sits at its prompt
        orch.ensure(cfg, name, log=log, saved=bool(seat) or name in orch.records(),
                    roles=setting, repo=config.REPO)
        return
    if any(seat.get(key) for key in ("resumable", "restart")):
        return

    def kept(mark):
        state["typed"] = mark
        write(state)

    if type_at_prompt(seat, state["line"], log, cfg=cfg, typed=state.get("typed"), receipt=kept):
        state["delivered"] = now
        write(state)
        log(f"audit: told the {name} seat about {about}")


@contextmanager
def state_lock():
    """Serialize lifecycle changes and watcher writes, including the read before each write."""
    config.ensure_dirs()
    with state_path().with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def sync_seen(data, current):
    """A newer lifecycle generation wins over any stall record a tick kept in memory."""
    seen = data["seen_at"] = {name: generation(stamp)
                              for name, stamp in data.get("seen_at", {}).items()}
    changed = set()
    for name, stamp in current.get("seen_at", {}).items():
        stamp = generation(stamp)
        if stamp > seen.get(name, 0):
            changed.add(name)
            data["stalls"].pop(name, None)
            if name in current["stalls"]:
                data["stalls"][name] = dict(current["stalls"][name])
            seen[name] = stamp
    for name, entry in current["stalls"].items():
        if entry.get("told"):
            data["stalls"][name] = dict(entry)
    return changed


def _write_state(data):
    tmp = state_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(state_path())


def save_state(data):
    with state_lock():
        current = load_state()
        sync_seen(data, current)
        # A menu may have completed boot recovery while this watcher was checking GitHub.
        for key in ("boot_id", "boot_resume"):
            if key in current:
                data[key] = current[key]
        _write_state(data)


def boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return None


def reboot_line(cfg, name, moved=None):
    """What that seat is told once it is back, by what it was doing when its process went.

    Its last look, unless its hook has spoken since, which is then the newest word.  Asking
    the owner, in a turn or not: its question on the screen, or its own unanswered `ak notify
    needs`.  Else in the middle of a turn: the ladder's own test -- a hook's prompt with no
    `Stop` after it, or a screen positively `working`, as it is once a question the turn asked
    was answered.  A move to another account knows what it cut instead: `moved` says whether
    that was a turn, which goes on with ACCOUNT_LINE.  Background work its process held goes
    after that line or alone, named, to be resumed or started again.  None for a seat that was
    idle or done and held nothing.
    """
    fact = hook_facts(name)
    line = _cut_line(cfg, name, fact) if moved is None else ACCOUNT_LINE if moved else None
    work = held_work(fact)
    return " ".join(filter(None, (line, work and HELD_LINE.format(", ".join(work))))) or None


def _cut_line(cfg, name, fact):
    harness = seat_model(cfg, name)[0]
    if not harness:
        return None
    looked = seat_read(name)
    try:
        hooked, _event, _text, when = hook_state(harness, fact)
    except config.Error:
        return None
    if when is not None and when != looked.get("hooked_at"):
        looked = {"state": hooked, "hooked": hooked, "hooked_at": when}
    if looked.get("state") == "asking" or owner_question(notify.last(name)):
        return ASKED_LINE
    if _turn_in_flight(harness, looked)[0]:
        return MIDTURN_LINE
    return None


def resume_after_boot(cfg, dry_run=False, log=print):
    """Claim each owned, absent seat that still owes work before restarting it, once per
    kernel boot.

    The watch lock is shared with the menu. Claims survive a killed recovery pass; the boot
    is complete only after all candidates were considered. No run is launched or retried.
    A seat the owner closed stays closed, and so does one that owes nothing (`owes_work`) and
    was neither mid-turn nor asking the owner when the host went down: it reopens with its
    number, like any closed seat. A seat that died mid-turn or asking the owner and came back
    on its own conversation is marked for `continue_turns`: otherwise it sits silent at its
    prompt, its turn or its question lost.
    """
    from . import menu as menu_mod    # here, not at the top: the menu imports this module
    boot = boot_id()
    if not boot:
        return
    with nullcontext() if dry_run else state_lock():
        state = load_state()
        if state.get("boot_id") == boot:
            return
        if not state.get("boot_id"):
            # Installation is not evidence of a reboot. Establish the first tick's baseline.
            if not dry_run:
                state["boot_id"] = boot
                _write_state(state)
            return
        recovery = state.get("boot_resume", {})
        if not isinstance(recovery, dict):
            recovery = {}
        attempted = recovery.get("attempted", []) if recovery.get("id") == boot else []
        present = {seat["name"] for seat in orch.sessions()}
        try:
            records = menu_mod.run_records(cache=not dry_run)
        except (config.Error, OSError, ValueError):
            records = []
        index, now = transitions.supersession_index(records), time.time()
        for name, record in sorted(config.session_records().items()):
            if (name in present or name in attempted or not orch.resumable(record)
                    or seat_closed_by_owner(name)):
                continue
            # background work alone owes nothing: its words go only to a seat that comes back
            if (not _cut_line(cfg, name, hook_facts(name))
                    and not owes_work(name, own_runs(name, records), index, now)):
                continue
            line = reboot_line(cfg, name)   # read before the relaunch writes anything
            if dry_run:
                log(f"would resume {name} after reboot in {record.get('cwd')}")
                continue
            attempted = [*attempted, name]
            state["boot_resume"] = {"id": boot, "attempted": attempted}
            _write_state(state)       # a failed or interrupted launch is never repeated this boot
            try:
                at = time.time()
                back = orch.resume(cfg, name, log=lambda _: None, detached=True,
                                   hand_over=False, line=line)
                log(f"resumed {name} after reboot")
                if line and back == "resumed":
                    relaunched(name, seat_model(cfg, name)[0], line, at, boot)
            except (config.Error, OSError) as exc:
                log(f"WARN could not resume {name} after reboot: {exc}")
        if not dry_run:
            state["boot_id"] = boot
            _write_state(state)


def relaunched(name, harness, line, at, boot=None, account=False):
    """Mark the line a seat relaunched at `at` goes on with, for `continue_turns`; `account`
    marks a move to another account, whose line the same tick types.

    Where its harness took the line as its first prompt (`orch.takes_line`) the mark only
    waits for that prompt; elsewhere the tick types it once the TUI is listening.
    """
    seat_write(name, midturn={"boot": boot or boot_id(), "at": at, "name": name, "line": line,
                              **({"launched": True} if orch.takes_line(harness) else {}),
                              **({"account": True} if account else {})})


def prompted_since(name, at):
    """Has a prompt gone into that seat since `at` -- the line, or his own?

    hooks/seat-state.sh stamps each prompt's moment into the seat's stop file, whichever
    harness it came from, and a turn that has since finished keeps that stamp.
    """
    try:
        turn = json.loads(config.stop_path(name).read_text(encoding="utf-8")).get("turn")
    except (OSError, ValueError, AttributeError, config.Error):
        return False
    return isinstance(turn, (int, float)) and not isinstance(turn, bool) and turn > at


def continue_turns(cfg, log, accounts=False):
    """Continue rebooted seats or have them ask again, or (`accounts`) continue seats reopened
    on another subscription.

    The mark goes on once the relaunch is back and comes off once the line has landed, so a
    send that failed -- or a tick killed in the warmup -- is tried again by the next tick,
    MIDTURN_TRIES times in all; unread-input deferrals spend none of those tries.
    Only the tick types it, and ticks never overlap, so no two
    passes send the same line.  A mark from another boot, a seat gone again, and a seat that
    has been prompted since it came back -- by the line, or by him, finished or not -- need
    no line at all, and that is read under the send's own lock, just before each keystroke.
    A question the seat put to the owner holds no line back: that turn went on after asking.
    The re-ask is a new prompt and waits, sparing its tries, for a quiet one, read under that
    lock too: nothing running, asked or typed there.
    A seat renamed since loses its mark: its harness stamps prompts under the name it was
    started with.
    A line the relaunch gave its harness as its first prompt is never typed: a harness without
    prompt hooks stamps none, and typing it again would start a second turn.  Its mark holds
    till the prompt is stamped, or for MIDTURN_TRIES passes.
    """
    boot = boot_id()
    for name in config.session_records():
        mark = seat_read(name).get("midturn")
        if not isinstance(mark, dict) or bool(mark.get("account")) != accounts:
            continue
        at = mark.get("at") if isinstance(mark.get("at"), (int, float)) else 0
        line = mark.get("line") or MIDTURN_LINE
        session = orch.find(name) if mark.get("boot") == boot else None
        if mark.get("launched"):
            waited = (mark.get("tries") or 0) + 1
            if (session and not session.get("exited") and not prompted_since(name, at)
                    and waited < MIDTURN_TRIES):
                replace_midturn(name, mark, {**mark, "tries": waited})
                continue
        elif session and not session.get("exited"):
            wait = at + INBOX_WARMUP - time.time()
            if wait > 0:
                time.sleep(min(wait, INBOX_WARMUP))   # the TUI has to be listening first
            harness, found = look_at(session, cfg=cfg)
            if accounts and found.get("state") in ("draft", "asking"):
                continue
            flight, began = _turn_in_flight(harness, found) if harness else (False, None)
            if not (flight and isinstance(began, (int, float)) and began > at):
                tries = (mark.get("tries") or 0) + 1
                quiet = []     # the re-ask's screen, read before its text goes in

                def taken(held):
                    return held != mark.get("name") or prompted_since(held, at)

                def stale(held):
                    if line.startswith(ASKED_LINE) and not quiet:
                        quiet.append(quiet_prompt(session, held, cfg))
                    return quiet == [False] or taken(held)
                sent = type_into(session, line, log, stale, asked=True)
                if sent:
                    log(f"told {name}: {line}")
                elif taken(config.resolve_session(name)):
                    log(f"{name} was prompted or renamed since it came back: no line")
                elif sent is None or quiet == [False]:
                    continue
                elif tries < MIDTURN_TRIES:
                    replace_midturn(name, mark, {**mark, "tries": tries})
                    log(f"WARN {name}: its line did not land; the next tick tries again")
                    continue
                else:
                    log(f"WARN {name}: its line did not land in {tries} tries")
        replace_midturn(config.resolve_session(name), mark)


def finish_own_lines(cfg, log):
    """Finish a fixed ak line left in its composer, even after its retries were spent.

    The screen decides, without a mark: only that line alone gets its locked Enter.  A seat's
    `continue_turns` mark is the one exception: its line, a handover's too, was typed past an
    open question, so its Enter is too, and once it lands the mark comes off, as that pass's
    own send takes it; its composer holding that line defers `continue_turns` until then.
    Delivery remains at least once, as it does for every line ak types.
    """
    for session in orch.sessions():
        if session.get("legacy") or any(session.get(key) for key in orch.CLOSED):
            continue
        name = session["name"]
        harness, _ = seat_model(cfg, name)
        if not harness:
            continue
        resume = config.manifest(harness).get("resume")
        key = resume.get("key") if isinstance(resume, dict) else None
        mark = seat_read(name).get("midturn")
        marked = (mark.get("line") or MIDTURN_LINE) if isinstance(mark, dict) else None
        for line in (marked, ACCOUNT_LINE, MIDTURN_LINE, MOVED_LINE, ASKED_LINE, CONTINUE_LINE,
                     key):
            def alone(held):
                return composer_holds(held, session, line, cfg, exact=True) == "line"

            if not line or not alone(name):
                continue
            if (type_checked(session, line, log, harness, pending=True,
                             guard=lambda: seat_held(name),
                             veto=lambda held: line != marked
                             and owner_question(notify.last(held)),
                             ready=alone) and line == marked):
                replace_midturn(name, mark)
            break


# --- the session babysitter -------------------------------------------------
# A seat stopped on its harness's own error is not a seat that needs the user: it needs a
# keystroke.  Every tick reads the tail of every toolkit seat's pane, and where the harness's
# own words for `I have given up` are in it, types the one thing that starts it again -- never
# before the line has stood for three minutes, never twice within three minutes, and never into
# a pane that is not showing one. Auth expiry asks for login immediately without typing.
# An unchanged terminal failure with no known signature asks for inspection after an hour.
# Ordinary output and idle prompts are not evidence of a blocked session.
# A quota waits for its provider, a usage-limit reset held or not -- only the owner spends
# one -- and known windows are waited out even past an hour. Otherwise an hour of the same is
# the end of it: the user is asked once, by menu number, and nothing is typed into that seat
# again until they open it and it makes progress.

# Everything a harness shows on its screen is its adapter's, in adapters/<harness>.toml beside
# adapters/<harness>.sh: the words it uses for a stall, a quota and an expired login, what its
# composer and footer look like, and the rules that say whether it is working, asking or back
# at its prompt.  Nothing here names a harness, so a new one plugs in with those two files.
RULE = r"[─━═\-╭╮╰╯┌┐└┘]+"
FOOTER = re.compile(rf"(?:{RULE}|[>›❯])$", re.I)
_SCREEN = {}


def _pattern(source, path, flags=0):
    try:
        return re.compile(source, flags) if source else None
    except re.error as exc:
        raise config.Error(f"{path}: {exc}")


def _rule(entry, path):
    """One [[rule]] table, with its marks folded and its patterns compiled."""
    if not isinstance(entry, dict) or entry.get("state") not in LIVE:
        raise config.Error(f"{path}: every [[rule]] needs state = one of {', '.join(LIVE)}")

    def marks(key):
        return tuple(str(m).lower() for m in entry.get(key) or ())
    return {"id": str(entry.get("id") or entry["state"]), "state": entry["state"],
            "lines": max(1, int(entry.get("lines", 8))), "all": marks("all"),
            "any": marks("any"), "none": marks("none"), "row": _pattern(entry.get("row"), path),
            "newest": _pattern(entry.get("newest"), path), "chrome": bool(entry.get("at_composer")),
            "picker": bool(entry.get("picker"))}


def screen(harness):
    """The compiled `[screen]` chrome and `[[rule]]` list of that harness's adapter manifest."""
    data = config.manifest(harness)
    cached = _SCREEN.get(harness)
    if cached is not None and cached[0] is data:
        return cached[1]
    path = f"adapters/{harness}.toml"
    block = data.get("screen") if isinstance(data.get("screen"), dict) else {}
    footer = "|".join(f"(?:{part})" for part in block.get("footer") or ())
    built = {"composer": _pattern(block.get("composer"), path),
             "footer": _pattern(f"(?:{footer})$" if footer else None, path, re.I),
             "ruled": bool(block.get("ruled")),
             "boxed": bool(block.get("boxed")),
             "folds_over": block.get("folds_over") if isinstance(block.get("folds_over"), int)
             else None,
             "folded": _pattern(block.get("folded"), path),
             "scrolled": _pattern(block.get("scrolled"), path),
             "away": _pattern(block.get("away"), path),
             "draft": _pattern(block.get("draft"), path, re.M),
             "faint": tuple(colour for colour in block.get("faint") or ()
                            if isinstance(colour, str)),
             "tray": _pattern(block.get("tray"), path),
             # it keeps the terminal cursor in its composer's box while keys go there
             # (`off_composer`)
             "cursor": block.get("cursor") is True,
             # the keys that hand its composer to $VISUAL, ak's editor (`seat_editor`)
             "editor": tuple(key for key in block.get("editor") or ()
                             if isinstance(key, str) and key),
             # a paste it hands that editor as its placeholder alone (`_may_paste`)
             "pasted": _pattern(block.get("pasted"), path),
             "rules": [_rule(entry, path) for entry in data.get("rule") or ()]}
    _SCREEN[harness] = (data, built)
    return built


def _words(harness, table, key):
    """A list of the harness's own words from its manifest, or () where it declares none."""
    block = config.manifest(harness).get(table)
    values = block.get(key) if isinstance(block, dict) else None
    return tuple(word for word in values if isinstance(word, str)) if isinstance(values, list) else ()


def stalls(harness):
    """That harness's own terminal words for `I have given up`."""
    return _words(harness, "stall", "signatures")


def quotas(harness):
    """The subset of them that is a spent provider window rather than a fault."""
    return _words(harness, "stall", "quotas")


def refusals(harness):
    """The provider declined the turn; older manifests may name only spent windows."""
    return _words(harness, "stall", "refusals") + quotas(harness)


def terminal(harness):
    """The kind of its event log's terminal record: the run's own last word, failure or not."""
    block = config.manifest(harness).get("stall")
    value = block.get("terminal") if isinstance(block, dict) else None
    return value if isinstance(value, str) and value else None


def auth_expiry(harness):
    """(title, remedy, signatures): its words for an expired login, and how to fix it.

    These are auth errors, never capacity errors: even an old stop latch must not hide them.
    Sources and installed versions are recorded in tests/fixtures/README.md.
    """
    block = config.manifest(harness).get("auth")
    if not isinstance(block, dict):
        return (None, None, ())
    return (block.get("title"), block.get("remedy"), _words(harness, "auth", "signatures"))


def _stamp(value):
    """A moment, or None where nothing is one: a bool is an int, and `True` is not a time."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def stop_marks(harness, pane, found, previous, at):
    """What this look adds to the two marks the end-of-turn rule reads, or nothing at all.

    `turn_began` is when the turn behind what is on the screen began, as near as anything
    watching can say it.  A seat caught working says it exactly.  A seat at its prompt saying
    something it was not saying at the last look says a turn ended between the two, and that
    turn began no earlier than that look -- a bound, never later than the truth, so a question
    recorded during the turn always falls inside it.  Mid-turn output moves nothing: only a
    seat at its prompt has ended anything.  The tighter of the two bounds is the one kept.

    Every screen that draws a row comes through live_state, so a turn no tick was awake for
    is still marked by the menu draw that saw it, and a turn shorter than the gap between two
    looks is still marked by the words it left behind.

    A seat that has said the same thing since it was first seen, and was never once caught
    working, has ended no turn anything here watched: its screen is the harness's own banner
    and not an answer.  That seat has no mark, and stop_nudge leaves it alone, as the hook
    leaves alone a stop it has no turn for.
    Only a harness the rule is typed at pays for any of this.
    """
    if not stop_enforced(harness):
        return {}
    if found["state"] == "working":
        return {} if previous.get("state") == "working" else {"turn_began": found["began"]}
    if found["state"] != "at_prompt":
        return {}       # a dialog or a half-typed line ends no turn and begins none
    said = progress_output(harness, pane_tail(pane))
    spoke = previous.get("stop_said") != said       # it has said something it was not saying
    came = previous.get("state") != "at_prompt"     # ... or it has only just got back here
    if not spoke and not came:
        return {}
    # Words go on standing only while the seat stays at its prompt showing them.  Away and
    # back, they start again: a turn that ended on the very same words it began with is
    # still a turn, and the completion look judges that new episode.
    marks = {"stop_said": said, "stop_said_at": at}
    # A turn ended between the last look and this one if the words changed, or if the seat
    # was caught working and is stopped now.  A composer typed into and cleared again is
    # neither, and moves nothing.
    if spoke or previous.get("state") == "working":
        seen, began = _stamp(previous.get("stop_said_at")), _stamp(previous.get("turn_began"))
        if seen is not None and (began is None or seen > began):
            marks["turn_began"] = seen
    return marks


def stop_enforced(harness):
    """Does the end-of-turn rule have to be typed at this harness, for want of a hook?

    A harness with no blocking end-of-turn hook says `[stop] enforce = "nudge"`
    and its completion look applies the same test to its screen.
    """
    block = config.manifest(harness).get("stop")
    return bool(isinstance(block, dict) and block.get("enforce") == "nudge")


def login_reason(harness):
    """The one sentence a seat blocked on an expired login says, on every screen.

    The remedy is that harness's own, out of `[auth] remedy` in its manifest, so nothing
    here names a harness or knows what logging into one looks like.
    """
    remedy = auth_expiry(harness)[1]
    return (f"{harness} login expired: open it and "
            f"{remedy if isinstance(remedy, str) and remedy else 'log in again'}")


def logged_out(harness, auth_out):
    """The tick's record of that harness being unable to authenticate, or None.

    `auth_out` is to a login what `gh_out` is to `gh`: the tick asks the `auth` verb and
    writes down what it found, and every screen reads the record instead of forking a
    subprocess per draw.  Only a recorded `no` blocks a seat -- a harness nobody has asked
    about yet, and one whose adapter declares no `auth` verb, block nothing.
    """
    found = (auth_out or {}).get(harness)
    return found if isinstance(found, dict) and found.get("ok") is False else None


def logged_in(harness, auth_out):
    """Whether the record says that harness positively authenticated.

    Not the opposite of `logged_out`: a verb that could not answer is neither, and an
    episode ends on a `yes` and on nothing else.  An adapter that is briefly unrunnable is
    not somebody logging back in, and treating it as one would retract a card the owner
    still has to act on and restart work nothing has authenticated.
    """
    found = (auth_out or {}).get(harness)
    return bool(isinstance(found, dict) and found.get("ok") is True)


def record_auth(state, harness, *, fresh=False, now=None, answers=None):
    """Ask that harness's `auth` verb, once per pass, and keep the answer in `auth_out`.

    The seat's login, not a worker's: `auth seat` is the interactive one, and where a harness
    has a worker credential of its own the two expire apart -- answering a seat with the
    token its workers use would hide a screen saying `Please run /login`.  A run parked on
    the worker login needs no record: being parked is its own evidence.

    `since` is when this episode of being logged out began: it stands until the verb passes
    again, so the seat's word and its card keep one beginning however many passes it lasts
    and whatever the pane shows in between.  `fresh` asks again inside the same pass, which
    is what a pane showing that harness's own logout words is for.

    A verb that did not answer writes nothing at all: the last real answer stands, so an
    adapter that is briefly unrunnable neither raises a login nor lifts one.
    """
    now = time.time() if now is None else now
    if answers is None or harness not in answers or fresh:
        ok, why = worker.auth_ok(harness, seat=True)
        if answers is not None:
            answers[harness] = (ok, why)
    else:
        ok, why = answers[harness]
    record = state.setdefault("auth_out", {})
    previous = record.get(harness)
    if ok is None:
        return previous if isinstance(previous, dict) else {"ok": None, "why": why, "at": now}
    since = previous.get("at") if isinstance(previous, dict) and previous.get("ok") is ok else now
    record[harness] = {"ok": ok, "why": why, "at": since}
    return record[harness]


TOKEN_LIFE_DAYS = 365    # a worker token lives exactly one year from its file's date
TOKEN_WARN_DAYS = 14     # ... and from this many days out the ak screen says it
TOKEN_POLL_EVERY = 86400  # the verb is asked at most once a day; a new file date asks at once


def token_ends(mtime):
    """When the worker token in a file dated `mtime` dies, as the `auth` verb dates it."""
    return mtime + TOKEN_LIFE_DAYS * 86400


def token_files():
    """{harness: its `[worker_token]` table} for every harness declaring a token of its own.

    The scan is the manifests', read the way `config.seat_env_names` reads them: the
    adapter directory first, this checkout's own beside it.  A harness that declares no
    table has no worker token, and nothing here names one or asks about one.
    """
    override = os.environ.get(config.ADAPTER_DIR_ENV)
    roots = ([Path(override).expanduser(), config.REPO / "adapters"] if override
             else [config.REPO / "adapters"])
    found = {}
    for root in roots:
        try:
            paths = sorted(root.glob("*.toml"))
        except OSError:
            continue
        for path in paths:
            block = config.manifest(path.stem).get("worker_token")
            file = block.get("file") if isinstance(block, dict) else None
            remedy = block.get("remedy") if isinstance(block, dict) else None
            if (isinstance(file, str) and file and file not in (".", "..")
                    and Path(file).name == file and isinstance(remedy, str) and remedy):
                found.setdefault(path.stem, block)
    return found


def token_warning(record):
    """The reason every session reads while that worker token dies, or None.

    The tick keeps the record; this only reads it.  A file nobody wrote is no token and
    warns of nothing -- without it the workers use the seat's own login, which has its
    own expiry and its own rung.
    """
    if not isinstance(record, dict):
        return None
    harness, remedy = record.get("harness"), record.get("remedy")
    if not harness or not remedy:
        return None
    if record.get("expired"):
        return f"{harness} worker token expired: {remedy}"
    days = record.get("days")
    if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= TOKEN_WARN_DAYS:
        return None
    return f"{harness} worker token expires in {days} days: {remedy}"


def token_alert(token_out):
    """(reason, since) of the first warning worker token, sorted by harness, or (None, None)."""
    if not isinstance(token_out, dict):
        return None, None
    for harness in sorted(token_out):
        reason = token_warning(token_out[harness])
        if reason:
            return reason, token_out[harness].get("at")
    return None, None


def token_dead(token_out):
    """The records of `token_out` whose worker token has expired: what pages the owner (rung 1c).
    One that only nears its day stands on the ak screen instead (`token_standing`)."""
    if not isinstance(token_out, dict):
        return {}
    return {harness: record for harness, record in token_out.items()
            if isinstance(record, dict) and record.get("expired")}


def token_standing(now=None):
    """The worker token's note (`worker_token_note`) while the ak and `c` screens show it --
    from TOKEN_WARN_DAYS out, and once it has expired -- else None."""
    note = worker_token_note(now)
    days = re.search(r"\(in (\d+) days\)", note or "")
    return note if note and ("expired" in note or days and int(days.group(1))
                             <= TOKEN_WARN_DAYS) else None


def remind_worker_tokens(token_out, now=None):
    """Page the owner once a local day while a worker token ends within a login's window
    (`logins.REMIND_WITHIN`), as a login's end does: nearer than the ak screen's line alone
    says, and before it is every seat's word (`token_dead`)."""
    from . import logins   # here, as the tick takes it: logins reads through the menu
    now = time.time() if now is None else now
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    for harness, record in sorted(token_out.items() if isinstance(token_out, dict) else ()):
        reason = token_warning(record)
        if (reason and not record.get("expired")
                and token_ends(record["mtime"]) - now <= logins.REMIND_WITHIN):
            notify.page(f"token:{harness}:{day}", f"{harness} worker token", reason)


def token_episode_restarted(answer, token_out, word_since):
    """The warning's new beginning where a replaced file restarted it, else None.

    The classifier ages an unchanged word from when it began, so a warning that arrives
    -- or a file that is replaced -- while the seat already reads `needs you` would
    otherwise keep the older age, and the new episode would never be seen to begin.
    """
    reason, begun = token_alert(token_dead(token_out))
    if reason is None or answer.get("reason") != reason:
        return None
    if (isinstance(begun, (int, float)) and not isinstance(begun, bool)
            and isinstance(word_since, (int, float)) and not isinstance(word_since, bool)
            and begun > word_since):
        return begun
    return None


def poll_worker_token(state, now=None):
    """Ask each declared worker token's `auth` verb, once a day, and keep the answers.

    The file's own date plus a year is the day it dies; the verb says `expires in N days`
    until then and `worker token expired` after it, and that line is what is kept here,
    per harness under `worker_tokens`.  A replaced file has a new date, which asks again
    at once rather than waiting out the day -- replacing the file is what ends the
    episode -- and so does the file's date passing, which is what begins it.  A verb that did not answer moves nothing at all, not even the throttle:
    the last real answer stands, as `auth_out` does.
    """
    now = time.time() if now is None else now
    kept, previous = {}, state.get("worker_tokens")
    previous = previous if isinstance(previous, dict) else {}
    for harness, block in sorted(token_files().items()):
        record = previous.get(harness)
        record = record if isinstance(record, dict) else {}
        try:
            mtime = (config.SECRETS / block["file"]).stat().st_mtime
            blank = not (config.SECRETS / block["file"]).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):   # a byte that is no text is no token either
            continue
        if blank:
            continue
        checked = record.get("checked_at")
        if (isinstance(checked, (int, float)) and not isinstance(checked, bool)
                and 0 <= now - checked < TOKEN_POLL_EVERY and record.get("mtime") == mtime
                and not checked < token_ends(mtime) <= now):
            kept[harness] = record
            continue
        ok, why = worker.auth_ok(harness)
        if ok is None:
            if record:
                kept[harness] = record
            continue
        found = re.search(r"expires in (\d+) days", why or "")
        expired = "worker token expired" in (why or "")
        days = int(found.group(1)) if found else None
        # `at` stands while the token is dead, so the word and its card keep one beginning
        # however many passes it lasts -- but any new file date ends the episode, even one
        # still dead: a replacement is a new episode, never the old one continued.
        continued = expired and record.get("expired") and record.get("mtime") == mtime
        since = record.get("at") if continued else (now if expired else None)
        kept[harness] = {"harness": harness, "remedy": block["remedy"], "at": since,
                         "checked_at": now, "mtime": mtime, "days": days,
                         "expired": expired, "why": why}
    if kept:
        state["worker_tokens"] = kept
    else:
        state.pop("worker_tokens", None)
    return kept


def worker_token_note(now=None):
    """The first declared token's `expires 2027-09-22 (in 142 days)` line for the `i` screen,
    or None where no declared token file exists to date."""
    for harness, block in sorted(token_files().items()):
        try:
            mtime = (config.SECRETS / block["file"]).stat().st_mtime
            if not (config.SECRETS / block["file"]).read_text(encoding="utf-8").strip():
                continue
        except (OSError, UnicodeDecodeError):
            continue
        at = time.time() if now is None else now
        exp = token_ends(mtime)
        when = time.strftime("%Y-%m-%d", time.localtime(exp))
        if at >= exp:
            return f"{harness} worker token expired {when}"
        return f"{harness} worker token expires {when} (in {int((exp - at) // 86400)} days)"
    return None


TURN_SECS = 3 * 3600   # age of a seat fact worth checking; never a worker turn cap
# Screen captures for the seat rules are taken with attributes (`capture-pane -p -e`),
# so dim text can be told from typed text. A faint (SGR 2) span is a suggestion or
# placeholder, never a draft.
SGR_SEQ = re.compile(r"\x1b\[([0-9;]*)m")
SGR_ALL = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]")
PANE_LINES = 15         # how much of a pane's tail says what it is doing
STALL_WAIT = 180        # how long a stall line has to stand before anything is typed at all
NUDGE_EVERY = 180       # and at most one keystroke per seat in that many seconds
GIVE_UP = 3600          # an hour of it: the user is asked, once, and the nudging stops
PARKED_NUDGES = 2       # the stop hook's LIMIT: nudges for the same parked run, then a stop stands
# Unknown logout wording is still a reason to ask, never a reason to type `continue`.
LOGIN_HINT = re.compile(r"/login\b|\b(?:log[ -]?in|sign[ -]in|logged out|expired|revoked|"
                        r"unauthori[sz]ed|401|403)\b|"
                        r"\b(?:authentication|authorization) (?:failed|required)\b", re.I)
# `Error:` and `Tests failed:` alone can be final answers. Require a blocked operation.
TERMINAL_FAILURE = re.compile(r"\b(?:cannot|can't|unable to) (?:proceed|continue)\b|"
                              r"\b(?:session|connection|stream|transport)\b.*\b(?:closed|lost|terminated)\b|"
                              r"\bunexpected status [45]\d\d\b", re.I)


def owner_question(notice):
    """Only orchestrator decisions block recovery; watcher alerts have their own latches."""
    return bool(notice and notice["kind"] == "needs" and notice.get("watcher") is not True)


def forget(session, *, resolve=True, acknowledge=True, opening=False, notice=None):
    """Advance the generation, retracting only our alert when `notice` identifies it."""
    try:
        with state_lock():
            name = config.resolve_session(session) if resolve else session
            state = load_state()
            previous = state["seen_at"].get(name, 0)
            state["seen_at"][name] = max(time.time(), math.nextafter(previous, math.inf))
            last = notify.last(name)
            if opening and last and last.get("watcher") is True:
                notice = last["text"]    # the user is taking over the watcher's recovery
            if not opening or not last or last.get("watcher") is True:
                state["stalls"].pop(name, None)
                # ... and seat_account's give-up on a bare 429, kept in the seat's record
                if (seat_read(name).get("usage_refusal") or {}).get("told"):
                    seat_write(name, usage_refusal=None)
            if notice is not None:
                notify.clear(name, notice=notice)
            elif acknowledge:
                notify.clear(name)
            _write_state(state)
    except (config.Error, OSError) as exc:
        print(f"WARN could not clear the stall record of {session}: {exc}", file=sys.stderr)


def seat_model(cfg, name):
    """(harness, provider) of the model in that seat, or (None, None) for a seat that is nobody's.

    A seat somebody made by hand with `tmux new` has no record saying what is in it, and
    nothing here types into a pane whose harness it cannot name.
    """
    try:
        selection = config.load_session(cfg, name, required=False)
        entry = config.model(cfg, selection["orchestrator"]) if selection else None
    except config.Error:
        return None, None
    return (entry["harness"], entry["provider"]) if entry else (None, None)


def _pane(session):
    """The tmux target a seat is read at and typed into: the pane a pass or step on it is bound
    to (`pinned`, `drafts_back`), or `=name:` -- that session exactly, and its current pane."""
    return session.get("pane") or f"={session['name']}:"


def pinned(session):
    """That seat held to the pane it shows now, by id: what is read and typed for one line goes
    to that pane, whichever pane the owner selects meanwhile; as it was where tmux cannot say."""
    rc, pane = orch.tmux_out("display-message", "-p", "-t", f"={session['name']}:", "#{pane_id}",
                             socket=orch.seat_socket(session))
    return dict(session, pane=pane) if rc == 0 and re.fullmatch(r"%[0-9]+", pane) else session


def pane_text(session):
    """The whole pane: output above the tail must reset the quiet clock too."""
    rc, out = orch.tmux_out("capture-pane", "-p", "-e", "-J", "-t", _pane(session),
                            socket=orch.seat_socket(session))
    return out if rc == 0 else ""


def strip_sgr(text):
    """Plain text without attributes; dim and colour never change what was said."""
    return SGR_ALL.sub("", text)


def _sgr_codes(params):
    """The attribute codes of one SGR sequence's parameters; a bare `m` is a reset.

    Extended colours ride along as parameter runs -- `38;5;n`, `38;2;r;g;b` and
    their background `48` twins -- and come out whole, as that run's text: the `2`
    inside one names a colour, never faint.
    """
    params = params.split(";") if params else ["0"]
    i = 0
    while i < len(params):
        if params[i] in ("38", "48") and i + 1 < len(params) and params[i + 1] in ("5", "2"):
            size = 3 if params[i + 1] == "5" else 5
            yield ";".join(params[i:i + size])
            i += size
            continue
        if params[i].isdigit():
            yield int(params[i])
        i += 1


def _faint_runs(raw, state=(False, False), colours=()):
    """(that raw `-e` row's runs of text between its codes, each as (text, whether faint,
    whether reversed), the (faint, muted) state at its end), from that state at its start.
    Faint is SGR 2; muted is a foreground colour its harness draws only placeholders in
    (`[screen] faint`), which reads the same."""
    faint, muted, reverse = *state, False
    runs, at = [], 0
    for found in SGR_SEQ.finditer(raw):
        runs.append((raw[at:found.start()], faint or muted, reverse))
        for code in _sgr_codes(found.group(1)):
            faint = True if code == 2 else False if code in (0, 22) else faint
            reverse = True if code == 7 else False if code in (0, 27) else reverse
            if isinstance(code, str):
                muted = code in colours if code.startswith("38;") else muted
            elif code in (0, 39) or 30 <= code <= 37 or 90 <= code <= 97:
                muted = False
        at = found.end()
    return [*runs, (raw[at:], faint or muted, reverse)], (faint, muted)


def _faint_drawn(raw, state=(False, False), colours=()):
    """(whether faint text is drawn in that raw `-e` row, the (faint, muted) state at its end),
    from that state at its start (`_faint_runs`): a code that turns either on and another that
    ends it before any visible text draws nothing faint."""
    runs, state = _faint_runs(raw, state, colours)
    return any(dim and text.strip() for text, dim, _ in runs), state


def _bright_rows(raws, colours=()):
    """Each raw `-e` row as plain text, its faint text blanked, the state carried as `dim_rows`
    carries it: what is left is what was typed, a suggestion drawn on after it none of it, nor
    the cursor's cell, drawn reversed, on its first letter."""
    state, rows = (False, False), []
    for raw in raws:
        runs, state = _faint_runs(raw, state, colours)
        shown = [at for at, (text, _, _) in enumerate(runs) if strip_sgr(text).strip()]
        under = {at for at, after in zip(shown, shown[1:]) if runs[at][2] and runs[after][1]}
        rows.append(strip_sgr("".join(" " * len(text) if dim or at in under else text
                                      for at, (text, dim, _) in enumerate(runs))).strip())
    return rows


def has_dim(line, colours=()):
    """Does that raw `-e` line draw faint text: a suggestion, never a draft.  `colours` are the
    ones its harness draws placeholders in (`[screen] faint`)."""
    return _faint_drawn(line, colours=colours)[0]


def dim_rows(raws, colours=()):
    """For each raw `-e` row, whether faint text is drawn in it.

    tmux writes an attribute once, where it starts, and carries it on to the rows under it
    until something ends it: a faint suggestion wrapped onto more rows has its SGR 2 on the
    first alone.  So faint is carried from row to row, as `in_colour` carries a colour.
    """
    state, dims = (False, False), []
    for raw in raws:
        drawn, state = _faint_drawn(raw, state, colours)
        dims.append(drawn)
    return dims


def _boxed(pane):
    """That `-e` capture with each row cut where a box drawn on it ends: where, after cells on
    another background, the background of its first cell comes back.  A composer drawn as a
    box on its own background (`[screen] boxed`) ends there, and what is drawn beside it, a
    sidebar, is none of it -- whatever columns its characters take."""
    back, rows = None, []
    for raw in pane.splitlines():
        first, away, cut, at = True, False, None, 0
        for found in [*SGR_ALL.finditer(raw), None]:
            if cut is None and raw[at:found.start() if found else len(raw)]:
                if first:
                    start, first = back, False
                elif back != start:
                    away = True
                elif away:
                    cut = at
            if found is None:
                break
            at = found.end()
            sgr = SGR_SEQ.fullmatch(found.group())
            for code in _sgr_codes(sgr.group(1)) if sgr else ():
                if isinstance(code, str):
                    back = code if code.startswith("48;") else back
                elif code in (0, 49):
                    back = None
                elif 40 <= code <= 47 or 100 <= code <= 107:
                    back = code
        rows.append(raw[:cut])
    return "\n".join(rows)


def in_colour(text):
    """Each line of that raw `-e` text with only what it draws in a colour of its own: tmux
    draws a colour once and carries it on to the lines under it until something ends it."""
    lines, colour = [], False
    for line in text.splitlines():
        shown = []
        for i, part in enumerate(SGR_SEQ.split(line)):
            if i % 2 == 0:
                part = strip_sgr(part)
                shown.append(part if colour else " " * len(part))
                continue
            params = [int(p) if p else 0 for p in part.split(";")]
            at = 0
            while at < len(params):
                if params[at] in (0, 39):
                    colour = False
                elif 30 <= params[at] <= 38 or 90 <= params[at] <= 97:
                    colour = True
                # `38;5;n`, `38;2;r;g;b` and their background `48` twins name a colour in their run
                at += {5: 3, 2: 5}.get(params[at + 1] if at + 1 < len(params) else None, 1) \
                    if params[at] in (38, 48) else 1
        lines.append(" ".join("".join(shown).split()))
    return lines


def _draft_text(plain, composer):
    """Typed, unsent text after the prompt mark, or "": a row read with its faint text blanked
    (`_bright_rows`), as a suggestion or placeholder is no draft."""
    # A quoted transcript (`● it said '❯ ...'`) is not a composer: only a line that
    # starts at the prompt holds a draft. The harness's own composer pattern names
    # its empty box and placeholders, so no list of them lives here: a line the
    # pattern fullmatches holds nothing the owner typed.
    found = re.match(r"(?:│\s*)?([❯›⟩])\s*(.*)$", plain)
    if found and found.group(2).strip():
        if composer is not None and composer.fullmatch(plain):
            return ""
        return " ".join(found.group(2).split())
    return ""


def _suggestion_line(raw, plain, colours=()):
    """Dim-only composer content: a suggestion or placeholder, treated as empty."""
    if not has_dim(raw, colours):
        return ""
    found = re.match(r"(?:│\s*)?([❯›⟩])\s*(.*)$", plain)
    if found and found.group(2).strip():
        return " ".join(found.group(2).split())[:160]
    return ""


def _content_rows(text):
    """The non-blank rows of a capture, raw and right-stripped.  A blank row can still change
    an attribute -- a faint suggestion's reset on the empty line of a draft -- and tmux carries
    one on until something ends it, so a blank row's codes go on at the head of the next row."""
    rows, carried = [], ""
    for line in text.splitlines():
        if strip_sgr(line).strip():
            rows.append(carried + line.rstrip())
            carried = ""
        else:
            carried += "".join(found.group(0) for found in SGR_SEQ.finditer(line))
    return rows


def pane_tail(text):
    """The last PANE_LINES of content; a TUI can leave blank space above its composer."""
    lines = _content_rows(text)
    return "\n".join(lines[-PANE_LINES:])


def _plain_lines(tail):
    """Stripped plain lines; `-e` attributes never make a blank line non-empty."""
    return [strip_sgr(line).strip() for line in tail.splitlines() if strip_sgr(line).strip()]


def content_lines(harness, tail):
    """Trim known bottom chrome, preserving newer output after an old error."""
    lines = _plain_lines(tail)
    # The composer box and key hints are chrome, not progress. Strip only known harness
    # chrome at the bottom; arbitrary output below an old error still means it has moved on.
    chrome = screen(harness)
    lines = lines[:chrome_below(chrome, [line for line in tail.splitlines()
                                         if strip_sgr(line).strip()])]
    while lines and chrome_line(chrome, lines[-1]):
        lines.pop()
    return lines


def prompt_rows(rows):
    """The rows a composer's prompt mark can open, bottom-most first: of those that open on a
    mark, only the ones whose mark sits furthest left.  A draft's wrapped or later rows are
    indented past its prompt mark, so a mark at the head of one is text, never the composer.
    Rows keep their leading spaces (raw or plain); plain stripped rows all sit at the left.
    """
    marks = {}
    for at, row in enumerate(rows):
        found = re.match(r"\s*(?:│\s*)?([❯›⟩])", strip_sgr(row).rstrip())
        if found:
            marks[at] = found.start(1)
    left = min(marks.values(), default=None)
    return [at for at in sorted(marks, reverse=True) if marks[at] == left]


def ruled_composer(chrome, rows):
    """(prompt row, closing rule row) of the composer a ruled harness draws, else (None, None).

    It is the bottom-most prompt row whose first chrome row under it is a bare rule, so a
    user's status line under that rule is never the composer, even where it starts with a
    prompt mark.  The box's prompt row and rules start at the pane's left edge, with at most
    one space after `│`, and a draft's rows are indented farther.  Only that edge and inset
    are removed: `rows` keep their remaining leading spaces (raw or plain),
    and only rows at the left edge are its prompt row and its chrome: nothing typed -- a run
    of rule glyphs, `---`, a prompt mark -- is ever the box, and every row between is the
    composer's.
    """
    if not chrome["ruled"]:
        return None, None
    cells = [re.sub(r"^│\s?", "", strip_sgr(row)).rstrip() for row in rows]
    for at in range(len(cells) - 1, -1, -1):
        if re.match(r"[❯›⟩]", cells[at]):
            end = next((row for row in range(at + 1, len(cells))
                        if not cells[row].startswith(" ") and chrome_line(chrome, cells[row])),
                       len(cells))
            if end < len(cells) and re.fullmatch(RULE, cells[end]):
                return at, end
    return None, None


def chrome_below(chrome, rows):
    """Where a ruled harness's composer begins in `rows`, its prompt row, else len(rows).

    From the composer's prompt row down to a footer on the bottom row nothing is output: the
    owner's unsent text, the closing rule and the chrome under it, a user's status line among
    it.  A bottom row that is no footer is newer output, as anywhere else, and leaves the rows
    as they are.
    """
    at, end = ruled_composer(chrome, rows)
    last = next((row for row in reversed(rows) if row.strip()), "")
    return at if end is not None and chrome_line(chrome, last) else len(rows)


def chrome_line(chrome, line):
    """Is that line the harness's composer or footer, rather than anything it said?"""
    plain = strip_sgr(line).strip()
    return bool(FOOTER.fullmatch(plain) or
                (chrome["footer"] and chrome["footer"].fullmatch(plain)) or
                (chrome["composer"] and chrome["composer"].fullmatch(plain)))


def output_line(lines):
    """The latest logical output line (-J joins wraps), excluding prompt text and quotes."""
    if not lines or re.match(r"(?:│\s*)?[>›❯⟩]", lines[-1]):
        return ""
    return re.sub(r'''`[^`]*`|"[^"]*"|“[^”]*”|(?<!\w)'[^']*'(?!\w)''', "", lines[-1])


def progress_output(harness, pane):
    """Comparable output, without composer input, footer repainting or terminal wrapping."""
    lines = content_lines(harness, pane)
    return " ".join(" ".join(line for line in lines
                            if not re.match(r"(?:│\s*)?[>›❯⟩]", line)).split())


def recorded_error(harness, name):
    """The error that seat's harness recorded as its conversation's last event, "" where it
    recorded none there, or None where it keeps no record to read, and only then is its screen.

    A screen's last rows cannot tell a model's answer quoting an error from the harness's own
    notice, nor a wrapped error from two rows; the record the harness writes down can, since a
    model's answer is never one of its error entries.
    """
    record = config.session_records().get(name) if name else None
    plugin = orch.harness_plugin(harness)
    if not record or not plugin.keeps_errors:
        return None
    cwd = record.get("cwd")
    try:
        conversation = plugin.conversation(record, cwd)
        if not plugin.transcript(record, cwd, conversation):
            return None
        return plugin.error(record, cwd, conversation) or ""
    except OSError:
        return None


def limit_ended(harness, name):
    """When that seat's harness ended its latest turn for a spent subscription -- told the model
    to wrap up, so it stopped without a refusal -- on a job its plan does not prove done; None
    where it did not."""
    from . import plan as plan_mod
    record = config.session_records().get(name) if name else None
    if not record:
        return False
    plugin = orch.harness_plugin(harness)
    cwd = record.get("cwd")
    try:
        at = plugin.wrapped_up(record, cwd, plugin.conversation(record, cwd))
    except OSError:
        return None
    return at if at is not None and not plan_mod.finished(name) else None


def interrupted_at(harness, name):
    """When the owner interrupted that seat's turn, as its harness recorded it -- a turn's end it
    reports by no hook -- or None where it recorded none or keeps no record to read."""
    record = config.session_records().get(name) if name else None
    if not record:
        return None
    plugin = orch.harness_plugin(harness)
    cwd = record.get("cwd")
    try:
        return plugin.interrupted(record, cwd, plugin.conversation(record, cwd))
    except OSError:
        return None


def follow_model(cfg, name):
    """Make the model that seat's harness says its latest answer ran on its orchestrator:
    `/model` typed inside a seat moves its row, its bar and `c`'s mark as a move on `c` would,
    nothing restarted (the owner's word of 20 Oct 2026).  Only an answer made since the harness
    in the seat was launched counts (`launched` in its record, written once it is up), so a
    move on `c` is not undone by the old model's last answer; a seat launched before launches
    were written down counts every answer.  The model is the configured entry running it on
    that harness, the seat's own first, at the effort the answer recorded where one does; a
    model no entry runs, a seat on its harness's own model, or an answer that cannot be read
    leaves the record as it is."""
    try:
        record = config.load_session(cfg, name, required=False)
        entry = record and config.model(cfg, record["orchestrator"])
    except config.Error:
        return
    if not entry or entry["model"] in ("", config.DEFAULT_MODEL):
        return
    plugin, cwd = orch.harness_plugin(entry["harness"]), record.get("cwd")
    try:
        ran = plugin.running(record, cwd, plugin.conversation(record, cwd))
    except OSError:
        return
    launched = _stamp(record.get("launched"))
    if not ran or launched is not None and not (ran[2] or 0) > launched:
        return
    kept, models = record["orchestrator"], cfg["models"]
    runs = [each for each in (kept, *config.offered(cfg))
            if (models[each]["harness"], models[each]["model"]) == (entry["harness"], ran[0])]
    chosen = next((each for each in runs if models[each].get("effort") == ran[1]),
                  runs[0] if runs else kept)
    if chosen != kept:
        config.update_session(name, orchestrator=chosen)


def cancelled(harness, name, pane):
    """Did the owner cancel that seat's turn before any answer?  Its harness records nothing
    then and sends no hook, so its record is that of a turn not yet answered; but it puts the
    prompt back in the composer, word for word, where a turn that runs leaves none."""
    record = config.session_records().get(name) if name else None
    if not record or not pane:
        return False
    plugin = orch.harness_plugin(harness)
    cwd = record.get("cwd")
    try:
        asked = plugin.unanswered(record, cwd, plugin.conversation(record, cwd))
    except OSError:
        return False
    return bool(asked) and composer_draft(harness, pane) == re.sub(r"\s+", "", asked["text"])


def auth_expired_on(harness, tail, name=None):
    """Match a harness's terminal auth message, including wrapped lines, never quoted prose.

    Where that seat's harness keeps a record, the error it recorded last is read instead, in
    the same words, anywhere in it: a record holds no prose to quote.
    """
    wrapper = (config.manifest(harness).get("auth") or {}).get("wrapper")
    said = recorded_error(harness, name)
    if said is not None:
        found = re.search(wrapper, said, re.I) if wrapper else None
        return next((mark for mark in auth_expiry(harness)[2] if says(said, mark)),
                    found.group(0) if found else None)
    lines = content_lines(harness, tail)
    # A capacity error can accompany a logout; auth still wins over resuming that error.
    while lines and any(mark.lower() in lines[-1].lower() for mark in stalls(harness)):
        if any(mark.lower() in lines[-1].lower() for mark in auth_expiry(harness)[2]):
            break
        lines = content_lines(harness, "\n".join(lines[:-1]))
    for mark in auth_expiry(harness)[2]:
        for start in range(len(lines)):
            text = " ".join(" ".join(lines[start:]).split())
            if re.fullmatch(r"(?:[●■⎿✕!]\s*)?(?:Error:\s*)?" + re.escape(mark) +
                            r"(?:, url: https?://\S+)?", text, re.I):
                return mark
    # A harness whose own auth wrapper precedes arbitrary 401/403 server text declares that
    # wrapper as `[auth] wrapper` in its manifest: matching a particular server message misses
    # real expired/revoked tokens and even new wording.
    if wrapper:
        found = re.search(wrapper, output_line(lines), re.I)
        if found:
            return found.group(0)
    return None


def error_said(harness, lines):
    """A seat's error, as its harness drew it.

    The last line is the error line.  One that names no failure of its own -- `Goal stalled`,
    `Error ID: ...` -- is read with the line above it only where the harness drew that line as
    its own error (`[stall] error_marks`); nothing else above is read, so a word in the model's
    answer is never the provider's.  Nor is a last line drawn behind another mark, as Codex
    draws its answer behind `•`: it says none, and a stall there is only typed at.
    """
    marks = _words(harness, "stall", "error_marks")
    if lines and marks and re.match(r"[^\w\s]\s", lines[-1]) and not lines[-1].startswith(marks):
        return ""
    if (len(lines) > 1 and orch.harness_plugin(harness).failure(lines[-1])[0] is None
            and lines[-2].startswith(marks)):
        return "\n".join(lines[-2:])
    return lines[-1] if lines else ""


def failed_on(harness, lines, name=None):
    """What a seat's error says, read as a worker turn's failure is: (outcome, word).

    The error its harness recorded where it keeps a record, else the error line `lines` end on.
    """
    said = recorded_error(harness, name)
    said = (error_said(harness, lines) if lines else "") if said is None else said
    return orch.harness_plugin(harness).failure(said)


def stalled_on(harness, pane, session, log):
    """The stall signature that pane is showing, or None: it is working, or it is not ours.

    A harness that draws its own notices in colour and the model's answer in the terminal's
    own (`[stall] coloured`) says a stall word only on a line wholly in colour, where the pane
    has attributes -- the whole pane, as a colour drawn above its tail can still be on its last
    line -- since the answer styles a span of its own in colour too.  Where the pane has none,
    its own line begins with the stall word, behind whatever mark it is drawn with: the
    model's sentence about one names it further on.

    None of that is guessed where the seat's harness keeps a record: the error it recorded
    last, in the word `failure` reads it by, is the stall, and no error there is none.
    """
    said = recorded_error(harness, session)
    if said is not None:
        return orch.harness_plugin(harness).failure(said)[1]
    lines = content_lines(harness, pane_tail(pane))
    last = lines[-1] if lines else ""
    block = config.manifest(harness).get("stall")
    coloured = isinstance(block, dict) and block.get("coloured") is True
    if lines and coloured and SGR_SEQ.search(pane):
        drawn = [shown for raw, shown in zip(pane.splitlines(), in_colour(pane))
                 if strip_sgr(raw).strip()]      # the rows pane_tail keeps, in its order
        if drawn[-PANE_LINES:][len(lines) - 1] != " ".join(last.split()):
            last = ""
    elif coloured:
        said = re.sub(r"^[^\w\s]+\s*", "", last).lower()
        if not any(said.startswith(mark.lower()) for mark in stalls(harness)):
            last = ""
    if not any(says(last, mark) for mark in stalls(harness)):
        mark = next((mark for line in reversed(lines[:-1]) for mark in stalls(harness)
                     if says(line, mark)), None)
        if mark:
            log(f"{session}: ignored {mark!r}; newer line {lines[-1]!r} is not known chrome")
        return None
    # Quota and goal text can coexist. The quota policy must run before goal resume.
    outcome, word = failed_on(harness, lines)
    return (word if outcome in (SPENT, LIMITED)
            else next(mark for mark in stalls(harness) if says(last, mark)))


def stall_mark(harness, pane, name, log):
    """The stall the tick types that seat back past (`health`), or None.  An error that may be
    a login is none: it takes the quiet path, and nothing types past it."""
    said = recorded_error(harness, name)
    said = output_line(content_lines(harness, pane_tail(pane))) if said is None else said
    return None if LOGIN_HINT.search(said) else stalled_on(harness, pane, name, log)


def stuck_on(harness, tail, name=None):
    """Login trouble or a blocked operation, not a test summary or an error above progress.

    In the error that seat's harness recorded last, where it keeps a record.
    """
    said = recorded_error(harness, name)
    line = output_line(content_lines(harness, tail)) if said is None else said
    return bool(LOGIN_HINT.search(line) or TERMINAL_FAILURE.search(line))


# --- what a live seat is doing ----------------------------------------------
# A seat that is alive and has said nothing with `ak notify` is still saying something.  Where a
# harness has lifecycle hooks -- `adapters/<h>.sh hooks` installs them -- they say when a turn
# began, when it ended and when a question went up, and the hook writes that one fact for the
# seat named in its own $AGENTKIT_SESSION.  Where it has none, its manifest's screen rules read
# the bottom of the pane instead.  Both go through classify(), which is a function of persisted
# facts alone, so the menu, the overlay, `ak orch list`, the status bar and a watch tick all say
# the same word with the same `since`.  Observation is never acknowledgement: nothing here opens
# a seat, answers a notice or types into one.


def _screen_rows(tail):
    """(raw, plain) non-blank rows of that tail."""
    raw_lines = _content_rows(tail)
    return raw_lines, [strip_sgr(line).strip() for line in raw_lines]


def screen_state(harness, tail):
    """(state, rule id, evidence line) of the first adapter rule that matches, else (None, "", "").

    A fix here adds no fallback for a shape it did not set out to read and reads only the rows
    the code it replaces read: every such fallback, and every reach further up the pane, misread
    another real screen.  It is proven on a pane captured from a real, renamed seat, not only a
    hand-drawn fixture.

    Rules are read in file order and the first match wins, which is why every manifest puts its
    dialog rules before its working rules, its draft rule before its prompt rule, and its
    at-the-prompt rule last: a TUI still draws the composer it drew when the turn ended while
    the next turn is running.  Only the bottom of the pane is read, never the scrolled viewport,
    and a dialog rule has to name the pair of controls a real dialog shows, so transcript text
    quoting a prompt cannot fake one.  A composer whose only content is dim -- a suggestion or
    placeholder -- is empty; one holding bright text is a draft.  The draft and suggestion
    rules are read out of the manifest like every other rule: their `lines` bound the window,
    their `none` marks skip them (a turn in flight owns the composer), and `at_composer`
    keeps them at the composer -- only the bottom-most prompt-marked line counts where the
    line right under it and the pane's last line are chrome, one with its own rule right
    under it first, so a transcript echoing a past turn above newer output can never read as
    one, while whatever the harness draws between its composer and its footer, a user's
    status line, never hides it or reads as it, even where it starts with a prompt mark.
    """
    raw_lines, lines = _screen_rows(tail)
    if not lines:
        return None, "", ""
    chrome = screen(harness)

    def drawn_rule(row):
        # a bare rule, or a rule the harness's own chrome names, as one carrying a session's name
        return bool(re.fullmatch(RULE, row) or (row[:1] in "─━═" and chrome_line(chrome, row)))

    # A view the harness has scrolled up from its live bottom shows none of what a rule reads
    # there -- a dialog's controls, the composer, a turn's spinner -- however much of it the rows
    # left look like one: it reads nothing, and what the hooks said stands (`[screen] away`).
    # The mark sits on the row right above the bottom rule, over a transcript row a tray could
    # take for its own, so it is read before any tray is left out; that row is never the
    # composer's, so a draft quoting the mark stays a draft.
    if (chrome["away"] and len(lines) > 1 and drawn_rule(lines[-1])
            and chrome["away"].search(lines[-2])
            and ruled_composer(chrome, raw_lines)[1] != len(lines) - 1):
        return None, "", ""
    # A tray the harness draws under its footer, or between its composer and its footer, is
    # neither: left out, every rule reads the rows it reads where none is drawn, and never
    # further up the transcript.
    if chrome["tray"]:
        at = len(lines)
        while at > 1 and chrome["tray"].fullmatch(lines[at - 1]):
            at -= 1
        if at < len(lines) and chrome_line(chrome, lines[at - 1]):
            raw_lines, lines = raw_lines[:at], lines[:at]
    if chrome["tray"] and chrome_line(chrome, lines[-1]):
        at = len(lines) - 1
        while at and chrome["tray"].fullmatch(lines[at - 1]):
            at -= 1
        raw_lines, lines = raw_lines[:at] + raw_lines[-1:], lines[:at] + lines[-1:]
    # A rule right under a row drawn at the left edge is that row's frame, not a newer line:
    # Claude Code 2.1.291 closes AskUserQuestion's footer with one, and read as the newest line
    # it hid every question, which then read as answered.  In a renamed session -- every seat --
    # that rule carries the session's name, which the adapter's composer pattern knows.  A draft never sits there: its
    # first row is prompt-marked and the rest are indented or inside a box's edge, so what is
    # typed stays a draft.
    newest = lines[-1]
    if chrome["ruled"] and len(lines) > 1 and drawn_rule(newest):
        above = strip_sgr(raw_lines[-2]).rstrip()
        if (above and not above[0].isspace() and above[0] not in "│┃║"
                and not re.match(r"[❯›⟩>]", above) and not drawn_rule(above.strip())):
            newest = lines[-2]
    for rule in chrome["rules"]:
        region = lines[-rule["lines"]:]
        raws = raw_lines[-rule["lines"]:]
        # marks read their rows as drawn, indented or from the left edge, so a dialog's
        # indented controls are not a reply's rows quoting them
        low = "\n".join(strip_sgr(raw).rstrip() for raw in raws).lower()
        if rule["id"] in ("prompt.draft", "prompt.suggestion"):
            if rule["none"] and any(mark in low for mark in rule["none"]):
                continue
            prompt = r"(?:│\s*)?[❯›⟩]"
            marked = prompt_rows(raws)
            end = None
            if rule["chrome"] and chrome["ruled"]:
                # Its composer is the box `ruled_composer` finds in the rule's own rows, every
                # row of it down to its closing rule, under the footer at the pane's bottom --
                # or, with none drawn, a prompt row right on that bottom.
                at, end = ruled_composer(chrome, raws)
                if at is not None and not chrome_line(chrome, region[-1]):
                    at = None
                elif at is None and re.match(prompt, region[-1]):
                    at, end = len(region) - 1, len(region)
                marked = [] if at is None else [at]
            elif rule["chrome"]:
                # The composer's own rule sits right under it and the footer at the bottom;
                # what the harness draws between them, a user's status line, is not the draft
                # even where it starts with a prompt mark, over a line that reads like chrome:
                # a line without a rule under it, a composer drawn right on the footer, counts
                # only under no composer with its own rule, and never where the manifest says
                # its composer always has one.
                # A draft a wrap or a newline took past its prompt row goes on in rows indented
                # under it, a mark at the head of one its text, down to that chrome, as
                # `_composer_rows` reads it.
                def under(index):
                    for row in range(index + 1, len(region)):
                        if chrome_line(chrome, region[row]):
                            return row
                        if not strip_sgr(raws[row])[:1].isspace():
                            return None
                    return None
                marked = [index for index in marked if index + 1 == len(region)
                          or (under(index) is not None and chrome_line(chrome, region[-1]))]
                marked = [index for index in marked if index + 1 < len(region)
                          and re.fullmatch(RULE, region[index + 1])] or [
                              index for index in marked
                              if index + 1 == len(region) or not chrome["ruled"]]
                end = None if not marked or marked[0] + 1 == len(region) else under(marked[0])
            at = next(iter(marked), None)
            if at is None:
                continue
            end = at + 1 if end is None else end
            if rule["id"] == "prompt.draft":
                draft = " ".join(_composer_parts(chrome, raws, region, at, end))
                if draft:
                    return rule["state"], rule["id"], draft[:160]
            elif _suggestion_line(raws[at], region[at], chrome["faint"]):
                return rule["state"], rule["id"], region[at][:160]
            continue
        # a row pattern reads its rows as drawn, indented or from the left edge
        drawn = [line for raw, line in zip(raws, region)
                 if rule["row"] and rule["row"].search(strip_sgr(raw).rstrip())]
        if ((rule["all"] and not all(mark in low for mark in rule["all"]))
                or (rule["any"] and not any(mark in low for mark in rule["any"]))
                or (rule["none"] and any(mark in low for mark in rule["none"]))
                or (rule["row"] and not drawn)
                or (rule["newest"] and not rule["newest"].search(newest))
                or (rule["chrome"] and not chrome_line(chrome, lines[-1]))):
            continue
        marks = rule["all"] + rule["any"]
        evidence = next((line for line in reversed(region)
                         if any(mark in line.lower() for mark in marks)), (drawn or [newest])[-1])
        if rule["state"] == "draft" and (chrome["draft"] or rule["chrome"]):
            # the chrome or a row told the draft apart, but the owner reads its words: what the
            # composer the rule reads at or the manifest finds holds, read as a typed line's
            # delivery reads it
            parts = _composer_rows(harness, tail)
            # The rule found a draft, but a full tail can leave its prompt above the read.
            if (parts is None and rule["chrome"] and rule["row"]
                    and len(raw_lines) >= PANE_LINES):
                parts = _cropped_composer_rows(harness, tail)
            evidence = " ".join(parts or ()) or evidence
        return rule["state"], rule["id"], evidence[:160]
    return None, "", ""


def classify(harness, tail, fact, opened_at, previous, now, interrupted=None):
    """What that live seat is doing, since when, and what decided it.  A pure function.

    The hook decides the states its manifest reserves for it, except where a rule positively
    names a different one.  A harness reports a question going up and nothing when it comes
    down, and a question is asked inside a turn that only its Stop ends: a record still holding
    the question has had no Stop since.  So where its hooks own `working`, a rule reading
    anything but a question -- the composer, a draft, a turn running -- means the question was
    answered and the turn that asked it runs on, however the screen draws it.  With neither a
    hook fact nor a rule the answer is `at_prompt`: `working` needs a `UserPromptSubmit` hook
    fact, an answered question or a rule that names it.  These are the facts, not the word a
    screen says: what the user reads is one of `session_state`'s three, and this is one of the
    things it reads.  `interrupted` is when the harness recorded the owner interrupting the
    turn, which then ended with no Stop: it ends a turn its hook began before it.
    """
    authority = config.manifest(harness).get("authority") or {}
    opened = (opened_at if isinstance(opened_at, (int, float))
              and not isinstance(opened_at, bool) else None)
    hooked, event, spoken, when = hook_state(harness, fact)
    seen, rule, line = screen_state(harness, tail)
    if hooked == "asking" and seen not in (None, "asking") and authority.get("working") == "hooks":
        hooked, spoken = "working", "its question was answered; the turn that asked it runs on"
    # Esc ends a turn with no Stop, a question's turn too: the dialog goes with it.
    stopped = hooked in ("working", "asking") and interrupted is not None and interrupted >= when
    if stopped:
        hooked, spoken = "at_prompt", "the owner interrupted its turn"
    if hooked and authority.get(hooked) == "hooks" and seen in (None, hooked):
        state, source, why, evidence, began = hooked, "hook", event, spoken, when
    elif seen:
        state, source, why, evidence, began = seen, "screen", rule, line, None
    else:
        # nothing said anything: never `working` without evidence. `began` stays
        # unknown, so the row ages from the seat's start and an unchanged seat is
        # not rewritten on every draw.
        state, source, why, evidence, began = "at_prompt", "", "none", \
            "no hook fact and no screen rule matched", None
    if source and began is None:
        kept = previous.get("began") if previous.get("state") == state else None
        if isinstance(kept, (int, float)) and not isinstance(kept, bool):
            began = kept
        elif previous.get("state") is None and opened is not None and opened <= now:
            # first sight of this seat: it has been in this state at least since it was last
            # opened, because nothing here watched what came before, and a seat the user has
            # opened and not been told anything about is not one that is waiting for them
            began = opened
        else:
            began = now
    return {"state": state, "since": began, "began": began,   # None where nothing knows when
            "authority": source, "rule": why, "evidence": evidence,
            # what the hook alone said, kept even where a rule positively overrode it:
            # `session_state` reads it for the one thing the manifest reserves to hooks,
            # and which event said it, so a Stop on background work is not a turn in flight
            # for his own unsent text
            "hooked": hooked, "hooked_at": when, "hooked_event": event if hooked else None,
            # the owner stopped its last turn, as recorded or by a hook event its manifest marks
            # `interrupt`: until their next prompt the seat rests
            "interrupted": stopped or event in marked_events(harness, "interrupt")}


def seat_read(name):
    """The seat's persisted live state, or {} where it has none yet."""
    try:
        data = json.loads(config.seat_state_path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError, config.Error):
        return {}
    return data if isinstance(data, dict) else {}


@contextmanager
def seat_lock(name):
    """Serialize the classifier's write against the one an interactive open makes."""
    config.ensure_dirs()
    with config.seat_state_path(name).with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


@contextmanager
def announcing(name):
    """One look, decision and publication of that seat at a time, whoever makes it.

    A menu, the tick, `ak orch` and the seat's own hook each finish before the next begins, so
    the last to publish is the last to have looked, and an older answer can never land on the
    bar after a newer one has been written to the record.
    """
    config.ensure_dirs()
    with config.seat_state_path(name).with_suffix(".announce").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def seat_write(name, **fields):
    """Merge fields into that seat's live-state record; a renamed seat is written under its name."""
    try:
        with seat_lock(name):
            return _seat_put(name, seat_read(name), fields)
    except (OSError, config.Error) as exc:
        print(f"WARN could not record what {name} is doing: {exc}", file=sys.stderr)
        return {}


def _seat_put(name, data, fields):
    """The write under `seat_lock`: merge fields into the record as it was just read."""
    if all(data.get(key) == value for key, value in fields.items()):
        return data
    data.update(fields, session=name)
    path = config.seat_state_path(name)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data) + "\n")
    tmp.replace(path)
    return data


def wait_mark(name, wait, **marks):
    """Put marks on that seat's wait, only while it is still that wait; True where it was.

    The tick's one write about a wait: `typed` while the line is in the composer, `told` once
    the confirmed send took it.  A wait the seat replaced meanwhile -- a newer `ak wait` is a
    new wait, and `ak notify` ends one -- is left as the seat wrote it, so the compare and the
    write are one stretch under the seat's lock.
    """
    try:
        with seat_lock(name):
            data = seat_read(name)
            current = data.get("wait")
            if not isinstance(current, dict) or any(
                    current.get(key) != wait.get(key) for key in ("on", "at")):
                return False
            _seat_put(name, data, {"wait": dict(current, **marks)})
            return True
    except (OSError, config.Error) as exc:
        print(f"WARN could not record what {name} is doing: {exc}", file=sys.stderr)
        return False


def replace_midturn(name, mark, new=None):
    """Replace that `continue_turns` mark -- take it off, or count a try -- only while it is
    still that mark: one saved while the Enter was confirmed -- a model switch's handover -- is
    a newer line's, so the compare and the write are one stretch under the seat's lock."""
    try:
        with seat_lock(name):
            data = seat_read(name)
            if data.get("midturn") == mark:
                _seat_put(name, data, {"midturn": new})
    except (OSError, config.Error) as exc:
        print(f"WARN could not record what {name} is doing: {exc}", file=sys.stderr)


def live_state(session, harness=None, pane=None, cfg=None, now=None):
    """Classify one live seat, persist what it is doing, and say what decided it.

    One capture per live seat, which is what a tick already does, on every menu draw, overlay
    draw, `ak orch list` and watch tick -- never on a seat whose process is gone, which has no
    screen to read.  These are the facts `session_state` reads, not a word any screen says.
    Nothing is typed and nothing is acknowledged.
    """
    name = session["name"]
    previous = seat_read(name)
    if harness is None:
        harness = seat_model(cfg if cfg is not None else config.load(), name)[0]
    if pane is None:
        pane = pane_text(session)
    at = time.time() if now is None else now
    try:
        found = observed(name, harness, pane, previous, at)
    except config.Error as exc:
        # a manifest somebody is in the middle of writing is not a reason for a blank menu
        print(f"WARN cannot read what {name} is doing: {exc}", file=sys.stderr)
        return {"state": "at_prompt", "since": None, "began": None, "hooked": None,
                "hooked_at": None, "hooked_event": None, "authority": "", "rule": "none",
                "evidence": str(exc)[:160]}
    fields = dict(found, **stop_marks(harness, pane, found, previous, at))
    if any(previous.get(key) != value for key, value in fields.items()):
        seat_write(name, **fields)
    return found


def observed(name, harness, pane, previous, at):
    """`classify` of that pane with the seat's hook facts and an interruption its harness
    recorded, and the stall the tick would type it back past (`stall`), writing nothing."""
    fact = hook_facts(name)
    # only a turn its hooks say runs, or asked in, can have ended unreported; and a prompt
    # whose hook lands while the record is read is a newer turn, which the record may not
    # show yet
    ended = None
    if hook_state(harness, fact)[0] in ("working", "asking"):
        ended = interrupted_at(harness, name)
        if ended is None and cancelled(harness, name, pane):
            # seen now, and never before the turn it ends
            ended = max(at, _stamp(fact.get("at")) or at)
    if ended is not None and hook_facts(name) != fact:
        ended = None
    found = classify(harness, pane_tail(pane), fact, previous.get("opened_at"), previous, at,
                     interrupted=ended)
    # read off this same capture, so a turn since answers it as soon as the screen does; a
    # capture that failed says nothing of it
    found["stall"] = (previous.get("stall") if not pane.strip() else
                      stall_mark(harness, pane, name, lambda _: None)
                      if found["state"] == "at_prompt" else None)
    return found


def word_from(found):
    """What of an observation a seat's word is decided from and kept beside it: its state and
    rule, and the words the owner reads in its reason, a question's, a draft's or the error a
    retry is typed past -- never a spinner's own line, which a harness redraws with its timer."""
    said = (found.get("evidence") if found.get("state") in ("asking", "draft")
            else found.get("stall")) or ""
    return [found.get("state"), found.get("rule"), said]


def _turn_in_flight(harness, found):
    """Is a harness turn running now, and since when.

    A harness whose manifest reserves `working` to its hooks is the authority on its own
    turns: a `UserPromptSubmit` fact with no later `Stop` is a turn in flight even while the
    TUI still draws the composer it drew when the last one ended, which is why the row can
    no longer be talked out of it by a prompt rule.  A harness that keeps `working` on the
    screen instead says so by its at-prompt rule not matching -- a rule that named `working`,
    or no rule at all, since a screen nothing here can read is not a seat at its prompt.
    """
    try:
        authority = config.manifest(harness).get("authority") or {}
    except config.Error:
        authority = {}
    if authority.get("working") == "hooks" and found.get("hooked") == "working":
        return True, found.get("hooked_at")
    if found.get("state") == "working":
        return True, found.get("began")
    if (authority.get("working") == "screen" and found.get("state") == "at_prompt"
            and found.get("rule") == "none"):
        return True, found.get("began")
    return False, None


def _composer_open(harness, found):
    """Is that seat's turn over with its composer open: no turn in flight, or a Stop on
    background work, which its manifest marks and whose composer takes a line at once."""
    return (not _turn_in_flight(harness, found)[0]
            or found.get("hooked_event") in marked_events(harness, "background"))


def keeps_back(name):
    """Does a question that seat asks itself wait for the end of the turn it asks in?

    It asks during its own turn, and may work on: until that turn ends its screen shows no
    question and it waits for nobody.  So it does on every harness ak knows the seat to run,
    the same way: where hooks report the turn's end a look follows at once, and where only
    the screen shows it ak's next look finds it (`ask_kept_back`).  One asked while an older
    question stands -- in a turn a run's result opened -- waits too, and is asked beside it
    then (`notify._said`).
    """
    try:
        harness = seat_model(config.load(), name)[0]
    except config.Error:
        return False
    return bool(harness)


def questions_kept(unasked):
    """The questions a seat's record keeps back for their turn's end, in the order kept, each
    with when the seat said it (`at`) and that end (`ended`) once each is on record.  One the
    older install kept is one."""
    if not isinstance(unasked, dict):
        return []
    listed = unasked.get("questions")
    if not isinstance(listed, list):
        listed = [unasked]
    return [{"text": q["text"], "id": q.get("id"),
             **{key: q[key] for key in ("at", "ended") if _stamp(q.get(key)) is not None}}
            for q in listed if isinstance(q, dict) and isinstance(q.get("text"), str)]


def _kept(questions):
    """What a seat's record keeps back: those questions, and the line reading them all."""
    return {"text": notify.ALSO.join(q["text"] for q in questions),
            "questions": questions} if questions else None


def keep(name, text, question_id=None):
    """Keep that question back for its turn's end, after those the seat kept already: a turn
    that asks twice asks both once it ends.  The seat's newer word ends its `ak wait` here."""
    try:
        with seat_lock(name):
            data = seat_read(name)
            kept = [*questions_kept(data.get("unasked")),
                    {"text": text, "at": time.time(), "id": question_id}]
            _seat_put(name, data, {"unasked": _kept(kept), "wait": None})
    except (OSError, config.Error) as exc:
        print(f"WARN could not record what {name} is doing: {exc}", file=sys.stderr)


def turn_ended(name):
    """Write down that the turn that seat asked in has ended, on each question it kept back in
    that turn: by its stop hook as the stop stands, or by a look that finds it over.  The
    record's own lock is all it takes, so it is on record whoever holds the notice then."""
    if not isinstance(seat_read(name).get("unasked"), dict):
        return      # nothing kept: a stop writes nothing
    try:
        with seat_lock(name):
            data = seat_read(name)
            now = time.time()
            kept = [{"ended": now, **q} for q in questions_kept(data.get("unasked"))]
            if kept:
                _seat_put(name, data, {"unasked": _kept(kept)})
    except (OSError, config.Error):
        pass


def kept_asked(name, kept):
    """Those kept questions, the first the record keeps, are a notice now: drop them, and keep
    any kept since.  Only this drops one while its notice lock is held, so they are still the
    first, unless the record was replaced meanwhile: then nothing is dropped, and what was
    asked already is asked once (`notify._said`)."""
    try:
        with seat_lock(name):
            data = seat_read(name)
            current = questions_kept(data.get("unasked"))
            if [q["text"] for q in current[:len(kept)]] == [q["text"] for q in kept]:
                _seat_put(name, data, {"unasked": _kept(current[len(kept):])})
    except (OSError, config.Error):
        pass


def answered_kept(name, replies, at):
    """A native card reply answers only its questions, including before the turn ends: its own
    card's copy, and every copy of a question whose latest card it is."""
    with seat_lock(name):
        data = seat_read(name)
        kept = questions_kept(data.get("unasked"))
        keys = set(replies)
        latest = {notify.question_key(q["text"]): q.get("id") for q in kept}
        remaining = [q for q in kept if not (q.get("at", at) < at and (
                     q.get("id") in keys or latest[notify.question_key(q["text"])] in keys))]
        if remaining != kept:
            _seat_put(name, data, {"unasked": _kept(remaining)})
            return True
    return False


def ask_kept_back(name, harness, found, held=False):
    """A fresh look found that seat's turn ended: the question it kept back is asked now.

    Ended is a prompt, a draft there, or a Stop on background work -- never a dialog, which is
    a turn waiting.  Its callers have just looked: `look_at`, the health pass after its own
    look, and every typer under the seat's typing lock (`type_checked`, `held`), so no line
    ak types opens a turn on a seat that stopped on a question before that question is asked.
    `live_state` is itself read under that lock, which is the notice's own, so it asks
    nothing.  The end goes on record first (`turn_ended`): a look that finds the notice lock
    taken leaves the asking to whoever next holds it -- a typer, the owner's prompt
    (`notify.answered`) or the next look.
    """
    kept = seat_read(name).get("unasked") if harness and found else None
    if (not isinstance(kept, dict) or found.get("state") == "asking"
            or not _composer_open(harness, found)):
        return
    turn_ended(name)
    try:
        if held:
            notify.ask_kept(name)
            return
        with notify.session_lock(name, wait=False) as current:
            if current:
                notify.ask_kept(current)
    except (config.Error, OSError):
        pass


def marked_events(harness, mark):
    """Hook events the manifest marks with `mark` (a background wait, an interrupt), as
    `hook_state` names them, or ().  No names live here."""
    try:
        events = (config.manifest(harness).get("hooks") or {}).get("event") or ()
    except config.Error:
        return ()
    marked = []
    for entry in events:
        if not isinstance(entry, dict) or not entry.get(mark):
            continue
        name = entry.get("name")
        if not isinstance(name, str):
            continue
        kinds = entry.get("kinds")
        if isinstance(kinds, list):
            marked.extend(f"{name}/{kind}" for kind in kinds if isinstance(kind, str))
        else:
            marked.append(name)
    return tuple(marked)


def look_at(session, cfg=None, pane=None, now=None):
    """(harness, what its screen and hooks say) for one seat, recorded as it always was.

    The observation `session_state` decides on, kept apart from it: this captures a pane and
    writes the classifier's own record, and the decision itself does neither.  A seat nobody
    is in has no screen to read, and answers (None, {}).  A look that finds the seat's turn
    ended asks the question it kept back during it (`ask_kept_back`).
    """
    if any(session.get(key) for key in orch.CLOSED):
        return None, {}
    try:
        harness = seat_model(cfg if cfg is not None else config.load(), session["name"])[0]
    except config.Error:
        return None, {}
    if not harness:
        return None, {}
    try:
        found = live_state(session, harness, pane=pane, cfg=cfg, now=now)
    except (config.Error, OSError):
        return harness, {}
    ask_kept_back(session["name"], harness, found)
    return harness, found


def plan_text(name):
    """The session's latest plan, or an empty string without one.

    An orchestrator renamed with `ak orch rename` still
    writes under the name it was launched with, so a plan under any name whose rename
    pointers lead here is this session's, and of several the one written last wins.
    """
    from . import plan
    try:
        return plan.path(name).read_text(encoding="utf-8", errors="replace")
    except (OSError, config.Error):
        return ""


def plan_progress(name):
    """(done, total) from the session's latest plan, or (0, 0) without one: done as the stop
    hook reads it (`plan.is_open`), so the bar and the seat's word never disagree."""
    from . import plan
    lines = [line for line in plan_text(name).splitlines() if plan.BOX.match(line)]
    return (sum(not plan.is_open(line) for line in lines), len(lines))


def unsent(name, harness, found, session, cfg=None):
    """Typed text nobody sent at a quiet prompt once nobody is in the seat to see it, else "".
    Text in the composer never changes the word (owner, 14 Oct 2026): the seat the owner left
    reads what its runs and its turn say, and its row still marks what they never sent.  Three
    seats once read `working` over their own unsent text for nineteen hours while they believed
    each had their message.  While a client is attached it is their typing; a Stop on
    background work is a quiet prompt, its composer open, and so is a turn refused for usage,
    whose hooks never saw it end (`usage_wait`)."""
    if (not harness or any(session.get(key) for key in orch.CLOSED) or session.get("attached")
            or found.get("state") != "draft"
            or not (seat_read(name).get("usage_wait") or _composer_open(harness, found))):
        return ""
    # what ak typed there, whole, is its own to send (`composer_holds`), not the owner's
    last = next(reversed([*entries(config.seat_file("input", name))]), None)
    if last and composer_holds(name, session, str(last.get("text")), cfg, exact=True) == "line":
        return ""
    return " ".join(str(found.get("evidence") or "").split())


def session_state(name, now=None, session=None, cfg=None, records=None, number=None,
                  run_numbers=None, index=None, silent=None, live=None, harness=None,
                  previous=None, auth_out=None, gh_out=None, token_out=None, card=False,
                  stalls=None):
    """`working`, `needs you`, `done`, `idle` or `out of usage` -- why, and since when.  The one
    decision.

    Every screen reads this and says one of those five words: the menu row, the project
    heading, the top line, `ak orch list`, `ak orch why`, the seat's own status bar and its
    window title.  It works until it is done or it is blocked on him, or he closed it and
    it sits idle, or its usage ran out; nothing else exists.  It decides from recorded notices, runs and the
    screen, never from when the seat's turn began, and a new fact gets a field of its own
    (`stopped_at` means closed).

    Top wins, and the ladder is the whole of it:

    * a login this harness needs is expired -- only he can fix it;
    * the `gh` login a run of its own needs is expired, which is the same news about the one
      login no harness owns, and is said only on the seats whose runs cannot push without it;
    * a worker token dies within a fortnight or is dead -- every session says so, on any
      harness, because any seat's next turn on it can be the one that fails;
    * a question on its screen is him even during a turn, and so is one it asked with `ak
      notify needs` that nothing has answered, from the end of the turn it asked in
      (`keeps_back`) whenever no later turn runs; so is a move to another account that
      failed, whatever its runs do;
    * a run it launched is unfinished and resumes itself, so the seat is working;
    * a harness turn is in flight, so the seat is working (a turn past three hours says so
      in its reason and keeps the word) -- parked run or not;
    * an error it launched is parked with no scheduled resume and still needs his
      attention -- recent, unacknowledged, not handed back or superseded -- or a run
      is stalled, or a merge wait only its age turned away;
    * its subscription ran out and ak resumes it when the usage comes back, so the seat is
      out of usage until then (`resumes_at`), or working while a move to another account
      that failed is retried;
    * its turn stopped on an error the tick types it back past, as its look saw it (`stall`),
      so the seat is working, `retrying: <error>`, until the tick gives up (`stalls`);
    * a run of its own merged and its project has yet to prove itself live (`awaiting_live`),
      so the seat is working, unless a run below or a watcher's alert is his;
    * nobody is in the seat any more and its number is the way back in: one the owner closed
      rests, `idle`, and one gone on its own needs them while it owes work, else is `done`
      where its plan is finished;
    * otherwise it is at its prompt with nothing running: the owner's again where a watcher's
      alert or a question on its screen says so, or where something of its own is still theirs
      (`still_owed`: work its plan owes, a question kept back); with nothing asked or owed it
      is `done` where its plan is finished and no run of its own sits undecided, else `idle`.

    An ended run is its orchestrator's business: the run hands its ending back to the seat
    that launched it, so no reason ever names a run or sends him to one -- unless the
    run is parked with no scheduled resume and still needs his attention.

    Every argument is a fact, and every one of them is read where it is left out: `session`,
    `cfg`, `records` and `index` (a `transitions.supersession_index` over the same records) are one
    draw's, handed down so a screen full of seats reads each of them once; `number` is this
    seat's number on the menu, which a gone seat's reason names; `silent` is one draw's map
    of run directory name to how long that run has been quiet; `live`/`harness` are what
    `look_at` read off the seat's own screen and hooks, `auth_out` what the last tick's `auth`
    verbs answered per harness, `gh_out` what it found about `gh`, `token_out` what its daily
    worker-token ask found, and `previous` the record of
    the last word. `run_numbers` is kept for callers that still hand it down and is read no more.

    Typed text nobody sent is never a word nor a reason: once no client is attached, the answer
    carries it as `unsent`, which a row marks (`menu.last_column`) and opens under it
    (`menu.detail`).  Never a `card`'s: what the owner never sent is not Discord's.

    Deciding is the whole of it: nothing here captures a pane, writes a record, sets an
    option or tells anybody -- not even through a lookup, which is why the seat and its
    number are read from `orch.listing(reconcile=False)` and never from the reconciling one.
    `look_at` does the looking and `announce_state` the remembering and the publishing.
    """
    from . import menu as menu_mod    # here, not at the top: the menu imports this module
    from . import run as run_mod
    at = time.time() if now is None else now
    if session is None:
        session = next((s for s in orch.listing(reconcile=False) if s["name"] == name),
                       None) or {"name": name}
    if live is None:
        live = seat_read(name)
    if auth_out is None or gh_out is None or token_out is None or stalls is None:
        saved = load_state()
        auth_out = (saved.get("auth_out") or {}) if auth_out is None else auth_out
        gh_out = (saved.get("gh_out") or {}) if gh_out is None else gh_out
        token_out = saved.get("worker_tokens") if token_out is None else token_out
        stalls = (saved.get("stalls") or {}) if stalls is None else stalls
    if harness is None and not any(session.get(key) for key in orch.CLOSED):
        try:
            harness = seat_model(cfg if cfg is not None else config.load(), name)[0]
        except config.Error:
            harness = None
    answer = _session_state(name, at, session, cfg, records, number, run_numbers, index,
                            silent, live, harness, auth_out, gh_out, token_out,
                            menu_mod, run_mod, terminal_mod, stalls)
    # `since` is the beginning of this run of this word, the way the classifier carries
    # `began`: unchanged, it keeps counting from where it started; changed, it starts now,
    # because a fact older than the change is not when the word began.  Only the first
    # sight of a seat takes the rung's own evidence, having nothing better to go on.
    if previous is None:
        previous = seat_read(name)
    if previous.get("word") == answer["word"]:
        restarted = token_episode_restarted(answer, token_out, previous.get("word_since"))
        answer["since"] = (restarted if restarted is not None
                           else previous.get("word_since", answer["since"]))
    elif previous.get("word") is not None:
        answer["since"] = at
    draft = "" if card else unsent(name, harness, live, session, cfg)
    if draft:
        answer["unsent"] = draft
    return answer


def announce_state(session, cfg=None, look=False, **facts):
    """Decide what that seat is, write down when that word began, and publish it.

    Every screen that draws a row does this, and the watch tick does it too, so a word that
    turns over between ticks still has one beginning and not one per draw.  Only a change is
    written; the bar itself is set every time, because publishing is the whole of it -- a set
    that failed, a seat that was closed and a seat given the same name again all come right on
    the next screen rather than waiting for the word to change.  The bar is the row's own
    values, written through the one writer, and a changed word reaches every other seat's bar
    at once, since each counts this one; the desktop notice is the card's own, sent where the
    card is queued, never here.

    All of it happens under `announcing`, and `look` has the seat's screen and hooks read
    there too (`look_at`), so the record and the bar always carry the same word, and it is
    the one the newest facts say.
    """
    name = session["name"]
    with announcing(name):
        if look:
            facts["harness"], facts["live"] = look_at(session, cfg=cfg)
            follow_model(config.load() if cfg is None else cfg, name)
        previous = seat_read(name)
        if facts.get("live") is None:
            facts["live"] = previous
        answer = session_state(name, session=session, cfg=cfg, previous=previous, **facts)
        # what it was decided from goes beside it: a classifier-only write since (a typing
        # preflight's) is a reading nobody has published yet (`unseen`)
        decided = word_from(facts["live"])
        if (previous.get("word") != answer["word"] or previous.get("reason") != answer["reason"]
                or (previous.get("unsent") or "") != answer.get("unsent", "")
                or previous.get("word_since") != answer["since"]
                or previous.get("word_from") != decided):
            seat_write(name, word=answer["word"], reason=answer["reason"],
                       unsent=answer.get("unsent", ""), word_since=answer["since"],
                       word_from=decided)
        statusbar.redress(session, answer, cfg=cfg, records=facts.get("records"))
        if previous.get("word") != answer["word"]:
            statusbar.retell(session)
    return answer


def hook_look(launched, answered_at=None, said="", prompt=False):
    """Look at that one seat again and publish what it is: its own hook's word, at once.

    hooks/seat-state.sh starts this in the background on every event it hears -- a turn
    begun, a turn ended, a question going up -- so the seat's record and its bar move then, and
    not at the next menu draw or tick, while the harness waits on nothing.  `launched` is the
    name the harness carries.  A Stop that hands over its background work is the one
    hooks/orchestrator-stop.sh writes down once it has judged it, and that one starts this look
    then, however long the judging took.  Both hooks write that fact under the name the seat
    goes by now, which is where it is read.

    Only a hook in the seat's own pane, on the seat's own server, moves its bar: a harness under
    some other tmux, or a test's sandbox with a seat's name in its environment, never paints a
    real seat's bar with facts that are not that seat's. The owner's prompt timestamp travels
    through the same check before answering a question; waiting for its notice lock happens
    here, off the harness's path.  A prompt `said` that is a line ak typed into the seat is the
    seat's own news, never the owner's answer (`notify.ak_prompt`): the harness's hook reports
    it as it reports the owner's words.  A `prompt`, unlike an answer through the harness's
    question tool, is the owner's only where the seat's conversation says so
    (`notify.answer_written`), which every other look also asks: the owner's message reaches it
    after their prompt hook ran.
    """
    name = config.resolve_session(launched)
    number, session = next(((number, session) for number, session
                            in enumerate(orch.listing(reconcile=False), 1)
                            if session["name"] == name), (None, None))
    here, pane = os.environ.get("TMUX", "").partition(",")[0], os.environ.get("TMUX_PANE", "")
    if session is None or not here or not pane or orch.tmux_out(
            "display-message", "-p", "-t", pane, "#{socket_path}\t#{session_name}",
            socket=orch.seat_socket(session)) != (0, f"{here}\t{name}"):
        return None
    if answered_at is not None and not notify.ak_prompt(name, said, notify.last(name)):
        if not prompt or notify.answer_written(name, answered_at, notify.PROMPT_WRITTEN) is None:
            notify.answered(name, answered_at)
    else:
        notify.answer_written(name)
    cfg = config.load()
    harness, provider = seat_model(cfg, name)
    # A turn its harness says failed settles its account before its word is told, as the tick
    # does: a spent subscription moves now, not at the next tick, and never reads `working`.
    # It is looked at first, as the tick looks: an older reading may still say it is asking.
    if hook_state(harness, hook_facts(name))[1] in marked_events(harness, "failed"):
        with announcing(name):
            pane = pane_text(session)
            look_at(session, cfg=cfg, pane=pane)
        seat_account(cfg, session, harness, provider, pane, False, lambda _: None)
    answer = announce_state(session, cfg=cfg, look=True, number=number)
    if stop_enforced(harness):
        from . import menu as menu_mod
        # A completion is already an event, not a suspected stall. The wrapper supplies
        # this look even where the harness has no native Stop callback.
        if stop_nudge(session, harness, pane_text(session), notify.last(name),
                      menu_mod.run_records(), False, lambda _: None):
            answer = announce_state(session, cfg=cfg, look=True, number=number)
    return answer


def start_look(launched):
    """`hook_look` for that seat in a process of its own session, as hooks/seat-state.sh starts
    it: whoever starts it -- the stop hook, the seat's wrapper -- ends none of it by ending.  The
    process, or None outside a tmux pane, which is where every seat's harness runs, or where
    none could start."""
    if not (os.environ.get("TMUX") and os.environ.get("TMUX_PANE")):
        return None
    try:
        return subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
             "from agentkit import watch; watch.hook_look(sys.argv[2])",
             str(Path(__file__).resolve().parents[1]), launched],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
    except OSError:
        return None


def still_owed(name, stopped):
    """Why a seat with nothing running and nothing asked on its screen or in its notices is
    still the owner's, or None where it rests.  Work its plan owes is a turn the stop hook let
    stand on its third stop, or one a harness it cannot send back left: the stop hook's own test
    says which (`stop.owed_line`), so this word and the turn's end never disagree -- except after
    a turn the owner `stopped`: they are in the seat and know (owner, 14 Oct 2026).  So does a
    question it kept back for its turn's end.  Any ending of its runs is typed into the seat at
    its next quiet prompt, so it is the seat's to act on, not theirs."""
    from . import stop as stop_mod    # stop imports this module
    line = None if stopped else stop_mod.owed_line(name)
    if line is not None or seat_read(name).get("unasked"):
        return f"stopped with work open: {line}" if line else "stopped with work open"
    return None


def news_owed(name, mine):
    """What ak still has to type into that seat, as its reason, or None: the end of its `ak
    wait` not yet told (`wait_over`), or an ending of its own runs nobody has heard that is the
    seat's to decide (`handback.owes_ending`, less a routine one, which is never typed)."""
    wait = seat_read(name).get("wait")
    if isinstance(wait, dict) and wait.get("over") and not wait.get("told"):
        return f"telling it its wait on {wait.get('on')} is over"
    for run_dir, state in mine:
        if handback.owes_ending(state) and not handback.routine_ending(state):
            return f"telling it how run {run_dir.name} ended"
    return None


def own_runs(name, records):
    """That seat's own (run_dir, state) pairs among `records`: the runs launched from it."""
    return transitions.runs_by_seat(records).get(name, [])


def resumes_itself(state, at):
    """Whether that run is unfinished and resumes itself.  `stalled` is the exception, as in
    the stop hook's `parked`: `going` counts it, but only `ak run resume` moves one."""
    return transitions.going(state, now=at) and state.get("state") != "stalled"


def parked_runs(mine, index, at):
    """Those of `mine` parked with no scheduled resume, which nothing but the owner moves: an
    ending still in the owner's tally, a stalled run, a merge wait only its age turned away."""
    from . import menu as menu_mod    # the menu imports this module
    return [(run_dir, state) for run_dir, state in mine
            if (state.get("state") in ("error", "exhausted")
                and menu_mod.v5o_needs_look(state, index=index, now=at))
            or (state.get("state") == "stalled" and transitions.unfinished(state, index=index))
            or (state.get("state") == "waiting" and not transitions.going(state, now=at)
                and transitions.tick_admission({**state, "finished_at": at}, now=at)
                and not transitions.is_superseded(state, None, index, merged_only=True))]


def owes_work(name, mine, index, at):
    """Whether that seat still owes work: a question or a watcher's alert still standing, what
    keeps any resting seat the owner's (`still_owed`), or a run of its own going, parked, or
    ended with nobody yet deciding it (the tally's own `needs you`).  It keeps a seat nobody is
    in the owner's, and, beside a turn or a question the host cut off (`reboot_line`), brings
    one back after a reboot.  `mine` is the seat's own (run_dir, state) pairs, `index` their
    supersession index."""
    from . import menu as menu_mod    # the menu imports this module
    last = notify.last(name)
    return bool(parked_runs(mine, index, at) or last
                or still_owed(name, stopped=False) is not None
                or any(resumes_itself(state, at) or transitions.unfinished(state, index=index)
                       or menu_mod.v5o_needs_look(state, index=index, now=at)
                       for _, state in mine))


def _session_state(name, at, session, cfg, records, number, run_numbers, index, silent_map,
                   found, harness, auth_out, gh_out, token_out, menu_mod, run_mod,
                   terminal_mod, stalls):
    """The ladder itself, top rung first, from the facts its caller gathered.

    The seat's own runs are gathered before the first rung, because a login the top rung
    reports may be one a run of this seat's parked on rather than the seat's own.
    """
    from . import status as status_mod    # status imports run, which imports this module
    from . import plan as plan_mod
    if records is None:
        try:
            records = menu_mod.run_records()
        except (config.Error, OSError, ValueError):
            records = []
    mine = own_runs(name, records)
    # 1. a login expired: the seat cannot move and only he can move it.  What decides it for
    # this seat is its harness's own `auth seat` verb, as the last tick asked it -- never the
    # pane, which a queued input redraws between ticks, and which is how `needs login` and
    # `moving again` used to take turns all night.
    out = logged_out(harness, auth_out)
    if out:
        return {"word": "needs you", "reason": login_reason(harness), "since": out.get("at")}
    last = notify.last(name)
    # 1a. ... and a run of this seat's parked on one is the same news about a login he has to
    # go and fix.  The run being parked is the evidence: nothing here re-asks the verb for it,
    # because the tick that can answer is the one that unparks it, and until it does the work
    # is stopped whatever any record says.  A run the tick has already found the login back
    # for is not that news -- it is being resumed, and saying `login expired` at it would
    # send him to `/login` for something he has.
    parked = [(run_dir, state) for run_dir, state in mine
              if state.get("state") == "waiting_login" and not state.get("login_back_at")]
    if parked:
        run_dir, first = min(parked, key=lambda pair: pair[1].get("finished_at") or 0)
        return {"word": "needs you", "reason": login_reason(first.get("waiting_for") or "a"),
                "since": first.get("finished_at")}
    # 1b. ... and the one login no harness owns: a run of its own cannot push until he
    # runs `gh auth login`, so the seat is blocked on him just the same
    if name in (gh_out.get("seats") or []):
        return {"word": "needs you", "reason": "gh login expired: run `gh auth login`",
                "since": gh_out.get("at")}
    # 1c. a worker token is dead: every session reads it, on any harness, because any
    # seat's next turn on it fails.  The tick asks the `auth` verb once a day and keeps the
    # answer; a replaced file has a new date, which is what ends the episode.  One card per
    # episode falls out of the cards rule, which keys episodes on the word.  One that only
    # nears its day stands under the ak screen's usage instead (`token_standing`).
    reason, since = token_alert(token_dead(token_out))
    if reason:
        return {"word": "needs you", "reason": reason, "since": since}
    # 1d. a question on its screen, even during a turn: that needs the owner, whatever its runs
    # are doing, and its card is held back while they are in the seat by the card rule itself.
    # Typed text nobody sent is no word of its own: `unsent` carries it.  A seat
    # nobody is in has no screen, so its record is history.
    gone = any(session.get(key) for key in orch.CLOSED)
    # A seat waiting for its usage to come back was refused mid-turn: whatever its screen
    # shows, no turn is in flight until ak resumes it (3b).
    waiting = None if gone or seat_closed_by_owner(name) else seat_read(name).get("usage_wait")
    if harness and not gone and found.get("state") == "asking":
        asked = " ".join(str(found.get("evidence") or "").split())
        return {"word": "needs you", "reason": asked or "waiting for you",
                "since": found.get("began"), "question": True}
    # ... and so is a question it asked with `ak notify needs` that nothing has answered, once
    # the turn it stood through has stopped: its runs going say nothing of it, but a turn a
    # run's result opened works without him until it stops on the question again (2b).  A
    # seat nobody is in names its number below, and a watcher's own alert about the seat
    # waits for its prompt (rung 5).
    if not gone and owner_question(last) and (
            not harness or waiting or _composer_open(harness, found)):
        return {"word": "needs you", "reason": " ".join(str(last["text"]).split()),
                "since": last.get("time"), "question": True}
    # ... and so is a move to another account that failed: no wait ends it by itself, so
    # neither its runs nor its `ak wait` going says he was not needed.
    if waiting and not waiting.get("until"):
        return {"word": "needs you", "reason": waiting["reason"], "since": waiting["since"]}
    # ... and so is a seat ak could not reopen over a run of its own still going: it tries once
    # per death (`revive_seats`), so the run going says nothing moves the seat back but the owner.
    # One the owner closed since is no failure: rung 4 has it.
    if (gone and last and str(last.get("source") or "").startswith("revive:")
            and not notify.resolved(last) and not seat_closed_by_owner(name)):
        return {"word": "needs you", "reason": " ".join(str(last["text"]).split()),
                "since": last.get("time")}
    # 2. a run of its own is unfinished and resumes itself: the seat is working.
    going = [(run_dir, state) for run_dir, state in mine if resumes_itself(state, at)]
    if going:
        going.sort(key=lambda pair: (pair[1].get("started_at") or 0, pair[0].name))

        def quiet(run_dir, state):
            """How long this run has gone without a write, from one draw's map or from disk."""
            if silent_map is not None:
                return silent_map.get(run_dir.name)
            return menu_mod.silent_for_run(run_dir, state, now=at)

        silent = next((triple for triple in
                       sorted(((d, s, quiet(d, s)) for d, s in going),
                              key=lambda triple: triple[0].name) if triple[2]), None)
        newest = silent[:2] if silent else going[-1]
        parts = [f"{len(going)} running"]
        if silent:
            parts.append(f"silent {silent[2]}")
        title = " ".join(str(newest[1].get("title") or newest[0].name).split())
        if title:
            parts.append(title)
        starts = [s.get("started_at") for _, s in going
                  if isinstance(s.get("started_at"), (int, float))
                  and not isinstance(s.get("started_at"), bool)]
        reason = (status_mod.parked_line(newest[1]) if transitions.landing_line(newest[1])
                  else " · ".join(parts))
        return {"word": "working", "reason": reason,
                "since": min(starts) if starts else None}
    # 2a. ... or it ended its turn on `ak wait`, and what it named is not over yet
    wait = waiting_on(name)
    if wait:
        return {"word": "working", "reason": f"waiting on {wait['on']}", "since": wait["at"]}
    # 2b. a turn is in flight: the seat is working, parked run or not.  Only a seat
    # somebody is still in has a screen to read.  The parked run below keeps its
    # word for the quiet prompt, but a turn answering him outranks it: the other
    # way round the word swung with every turn and each swing sent a new card.
    if gone:
        found = {}
    elif harness and not waiting:
        flight, began = _turn_in_flight(harness, found)
        if flight:
            long = (isinstance(began, (int, float)) and not isinstance(began, bool)
                    and at - began > TURN_SECS)
            return {"word": "working", "since": began, "reason":
                    f"turn running {terminal_mod.format_age(at - began)}" if long else ""}
    # 3. ... or a run of its own is parked with no scheduled resume: then it is
    # him the run waits for, only while the same ending still counts in his tally.
    # An acknowledged, handed-back, superseded or aged-out error is nobody's new
    # question. An exhausted run the tick cannot resume is no ending: told or old, it
    # stays unfinished until he resumes or stops it, so it is his -- by the tally's own
    # test, which no hand-back or age ends, or rung 5 would call it recovering --
    # unless a later merged run replaced it, which ends the question outright.  So is
    # a stalled run, and a merge wait only its age turned away: nothing told him, and
    # nothing but him will move it.
    # A gone seat still names its own number below instead: the number
    # is the way back to the run, never the run itself.
    if index is None:
        index = transitions.supersession_index(records)
    parked = parked_runs(mine, index, at)
    if parked and not gone:
        run_dir, first = min(parked, key=lambda pair: pair[1].get("finished_at") or 0)
        name, reason = run_dir.name, handback.handback_reason(first)
        if first.get("state") == "stalled":
            # from its id, never its error: a long step cuts the command in that one short
            reason = f"run {name} stalled: resume it with `ak run resume {name}`"
        elif first.get("state") == "waiting":
            reason = f"run {name} waits to merge: {reason}"
        else:
            reason = (status_mod.parked_line(first, name, now=at)
                      or f"run {name} parked: {reason}")
        return {"word": "needs you", "since": first.get("finished_at"), "reason": reason}
    # 3b. ... or its subscription ran out and ak resumes it when the usage comes back, or on
    # another account sooner: nothing moves until then unless he moves it, so it is out of
    # usage until when it comes back (`resumes_at`) -- and nothing on him outranked it above.
    # A move to another account that failed is retried: working.
    if waiting:
        until = waiting.get("until")
        return {"word": "out of usage" if until else "working", "reason": waiting["reason"],
                "since": waiting["since"], "resumes_at": until}
    # 3c. ... or its turn stopped on an error the tick types it back past (`health`, or
    # `seat_account` for a bare 429): it moves on without the owner until the tick gives
    # up and tells them (`told`), so it is working.  A legacy seat the tick never types into.
    # The error is its own look's (`stall`), so a turn since -- the retry's or the owner's --
    # answers it as soon as the screen does.
    if (found.get("stall") and not gone and not session.get("legacy")
            and not seat_closed_by_owner(name) and not (stalls.get(name) or {}).get("told")
            and not (seat_read(name).get("usage_refusal") or {}).get("told")):
        return {"word": "working", "reason": f"retrying: {found['stall']}",
                "since": found.get("began")}
    # 3a. ... or a run of its own merged and its project has yet to prove itself live: ak's own
    # probe, read every tick (`awaiting_live`), so the stop hook, this word and the card it
    # decides agree that nothing here is his.  Only where nothing below is his either: a run
    # parked or undecided (the hook's `unfinished`, which it puts first) or a watcher's alert
    # keeps the word the rungs below give it.
    pending = [state for _, state in mine if awaiting_live(state, now=at)]
    if pending and not (
            parked or any(transitions.unfinished(state, index=index) for _, state in mine)
            or last):
        newest = max(pending, key=lambda state: state.get("finished_at") or 0)
        title = " ".join(str(newest.get("title") or newest.get("run_id") or "").split())
        return {"word": "working", "reason": f"waiting on the live check · {title}".rstrip(" ·"),
                "since": min(state["finished_at"] for state in pending)}
    # 4. nobody is in it: its number is the way back into the conversation.  A seat the
    # owner closed is `idle`: he ended it, so nothing in it is his to unblock, and a hand-back
    # waiting on it waits for him to want it back; one that went on its own is the owner's
    # only while it owes work (`owes_work`).
    # An ended run is its orchestrator's to act on -- the run handed its ending back to
    # the seat that launched it -- so no reason ever says `press r` or names a run.
    if gone:
        if number is None:
            number = next((n for n, s in enumerate(orch.listing(reconcile=False), 1)
                           if s["name"] == name), None)
        where = "its number" if number is None else number
        # a harness that cannot prove which conversation this seat owned says so itself,
        # and that sentence is the rest of the reason -- it is what the number will do
        restart = session.get("restart")
        told = " ".join(restart.split()) if isinstance(restart, str) else ""

        def closed(reason):
            return f"{reason} · {told}" if told else reason

        # One the owner closed rests: they closed it, and nothing in it is asking them anything.
        if seat_closed_by_owner(name):
            waiting = sum(1 for _, st in mine if st.get("handback_pending"))
            reason = f"{OWNER_CLOSED_REASON}: press {where} to reopen"
            if waiting:
                reason += f" · {waiting} hand-backs waiting"
            return {"word": "idle", "since": None, "reason": closed(reason)}
        # One that went on its own is the owner's while it owes work: no ending is typed into a
        # seat nobody is in, so nothing moves it until it is opened.  With nothing owed it says
        # done where its plan is finished, or rests.
        reason = closed(f"session closed: press {where} to reopen")
        if owes_work(name, mine, index, at):
            return {"word": "needs you", "since": None, "reason": reason}
        if not plan_mod.finished(name):
            return {"word": "idle", "since": None, "reason": reason}
    # 5. at its prompt with nothing running: a watcher's alert, a question on its screen, or
    # nothing at all
    if last:
        return {"word": "needs you", "reason": " ".join(str(last["text"]).split()),
                "since": last.get("time")}
    asked = " ".join(str(found.get("evidence") or "").split()) if found.get(
        "state") == "asking" else ""
    if asked:
        return {"word": "needs you", "reason": asked, "since": found.get("began")}
    # ... or ak still has a line to type into it, at its next quiet prompt: that line moves it,
    # not the owner, who was paged `stopped with work open` while the line waited behind
    # their own unsent text (19 Oct 2026).  Only at a prompt a rule or hook read: `classify`
    # offers `at_prompt` with no `authority` for a screen nobody can read, which takes no line.
    telling = (news_owed(name, mine) if found.get("authority")
               and found.get("state") in ("at_prompt", "draft") else None)
    if telling:
        return {"word": "working", "reason": telling, "since": found.get("began")}
    # Nothing running, asked or owed: a plan whose every line is proven is done, which ak reads
    # and nobody declares (owner, 19 Oct 2026); otherwise the seat rests and nothing on it is
    # the owner's to do -- a new seat, a conversation, a turn the owner stopped.
    owed = still_owed(name, found.get("interrupted"))
    if owed is not None:
        return {"word": "needs you", "since": found.get("began"), "reason": owed}
    finished = plan_mod.finished(name)
    if finished:
        # a run still undecided waits on him: the stop hook's third stop stands on it
        if index is None:
            index = transitions.supersession_index(records)
        undecided = next(((d, s) for d, s in mine if transitions.unfinished(s, index=index)), None)
        if undecided:
            return {"word": "needs you", "since": found.get("began"), "reason":
                    f"run {undecided[0].name} parked: {handback.handback_reason(undecided[1])}"}
        return {"word": "done", "reason": " ".join(finished.split()), "since": found.get("began")}
    return {"word": "idle", "reason": "", "since": found.get("began")}


MAX_BYTES = 8000        # tmux refuses one command past 16 KiB, and a typed line goes in whole
def longest(cfg):
    """The most characters a typed line may hold: one every harness a seat can run shows whole
    in its composer (`[screen] folds_over`), so the line read back there is the line typed."""
    harnesses = {model.get("harness") for model in (cfg.get("models") or {}).values()}
    folds = [screen(name)["folds_over"] for name in harnesses if name]
    return min([fold for fold in folds if fold] or [MAX_BYTES])


def too_long(line):
    """Why `line` is more than a typed line may hold, else None."""
    most = longest(config.load())
    if len(line) > most or len(line.encode("utf-8")) > MAX_BYTES:
        return (f"{len(line):,} characters is more than a composer shows whole ({most:,}); "
                "write the rest to a file and name its path")
    return None


def waiting_on(name):
    """That seat's own `ak wait`, while the pull request or run it names is not yet over; else
    None.

    The wait is the seat's word, kept in its record's `wait` by `ak wait` and dropped by its
    next `ak notify`.  Only the tick's wait pass (`wait_over`) asks GitHub or the run's record
    whether what it names is over, and writes that down on the wait as `over` the moment it
    sees it; this reads that mark and nothing else, so the ladder, the stop hook and the
    tick's `stop_nudge` cost no network and decide the same.  A wait marked over counts for
    nothing afterwards, and only a new `ak wait` is a new wait.
    """
    wait = seat_read(name).get("wait")
    if (not isinstance(wait, dict) or wait.get("over") or wait.get("kind") not in ("pr", "run")
            or not isinstance(wait.get("on"), str)):
        return None
    at = _stamp(wait.get("at"))
    return {"on": wait["on"], "kind": wait["kind"], "at": at, "since": at}


def wait_fact(wait):
    """(whether what that wait names is over, the one line saying how, the run whose ending
    that is or None): a run once it is no longer going, or the run its task was started again
    as, a pull request once it is merged (by the run landing it, if one did) or closed, or
    while open, once no run reviewing or landing it is going (the last to end since the wait
    began).  (None, why, None) where nothing can say yet: `wait_over` leaves the wait as it is
    while that is the owner's login to fix, and for UNREAD_TICKS ticks otherwise."""
    on = wait.get("on")
    if wait.get("kind") == "run":
        while True:
            directory = config.RUNS / on
            state = run_record.read_state(directory) if directory.is_dir() else None
            if not state:
                return True, f"run {on} is gone", None
            if not state.get("lease_restarted"):
                break
            # stopped to wait on an older run's change, and started again (`leases.restart`):
            # the wait goes on with the new run
            on = state["lease_restarted"]
        if state.get("state") == "stalled":
            # going to the ladder, but nothing moves it except the seat: the wait is over
            return True, f"run {on} stalled: resume it with ak run resume {on}", None
        if transitions.going(state):
            return False, "", None
        ended = state.get("verdict") or state.get("state") or "ended"
        return True, f"run {on} ended {ended}" + (", merged" if state.get("merged") else ""), on
    data, why = gh_json(config.RUNS, "pr", "view", on, "--json", "state,number,mergeCommit")
    if not isinstance(data, dict) or data.get("state") not in ("OPEN", "MERGED", "CLOSED"):
        return None, why or "GitHub did not answer", None
    number = data.get("number")
    if data["state"] == "OPEN":
        # a run that ends without merging leaves it open, its ending may reach no seat (one
        # launched outside a seat records none), and one never sent to a run has none at all:
        # open, it waits while a wait on any going run of any seat reviewing or landing it
        # would, and one such run that would not (a stalled one) ends it with its own line
        runs = list(transitions.runs_on(pr=on))
        facts = [wait_fact({"kind": "run", "on": state["run_id"]})
                 for state in runs if transitions.going(state)]
        if not all(over for over, _, _ in facts):
            return False, "", None
        if facts:
            return facts[0]
        ended = [state for state in runs if state.get("state") in run_record.ENDED
                 and (state.get("finished_at") or 0) >= (wait.get("at") or 0)]
        last = max(ended, key=lambda state: state.get("finished_at") or 0, default=None)
        return True, (f"PR #{number} is open with no ak run going on it: "
                      f"ak run --review-pr {on} --bg takes it"), last and last["run_id"]
    if data["state"] == "MERGED":
        sha = str((data.get("mergeCommit") or {}).get("oid") or "")[:12]
        # its lander may still be finishing: `merged` is written before the run's ending
        lander = next((state["run_id"] for state in transitions.runs_on(pr=on)
                       if state.get("merged")), None)
        return True, f"PR #{number} merged" + (f" as {sha}" if sha else ""), lander
    return True, f"PR #{number} closed without merging", None


def wait_over(cfg, log):
    """The tick's wait pass: a seat whose `ak wait` names a pull request or run that is now
    merged, closed or ended is told so, once, and the wait is over.

    The fact is asked once per tick here and nowhere else, and written on the wait as `over`
    the moment it is seen, so every reader of `waiting_on` agrees from then on.  The line goes
    in through the confirmed send, only at the seat's own quiet prompt, the way a run's ending
    is handed back; a seat mid-turn is tried again next tick.  It names the fact and nothing
    else: no other seat's words, no other seat's screen.  The send that took it is written on
    the wait as `told`, so it is typed once.  An ending its own run hands back to the seat
    (`handback.hand_back`) is that line already: none is typed for it, and the wait is told
    once the hand-back is in.
    """
    waiting = {}
    for name in config.session_records():
        wait = seat_read(name).get("wait")
        if isinstance(wait, dict) and isinstance(wait.get("on"), str) and not wait.get("told"):
            waiting[name] = wait
    if not waiting:
        return
    # every seat with a record: a closed seat's wait, or one tmux no longer lists, still ends
    # on its fact, which its ladder reads; only the line has nowhere to go
    live = {session["name"]: session for session in orch.sessions()}
    for name, wait in waiting.items():
        session = live.get(name)
        closed = session is None or any(session.get(key) for key in orch.CLOSED)
        if wait.get("kind") not in ("pr", "run"):
            # the record `ak wait <session>` wrote before waits named a pull request or run:
            # no fact can end it, so it is over, and there is nothing to type
            if wait_mark(name, wait, over="a wait on a session, from before ak wait named a "
                         "pull request or run", told=time.time()):
                log(f"{name}: its wait on {wait['on']} named a session; ended, as ak waits only "
                    "on a pull request or run")
            continue
        if not wait.get("over"):
            over, reason, run = wait_fact(wait)
            if over is None:
                log(f"WARN {name}: its wait on {wait['on']} cannot be read: {reason}")
                if LOGGED_OUT.search(reason or ""):
                    # the owner's login to fix: the seat is written down as held up by gh
                    # (`pushing_seats`), and the wait holds until he has
                    continue
                unread = int(wait.get("unread") or 0) + 1
                if unread < UNREAD_TICKS:
                    wait_mark(name, wait, unread=unread)
                    continue
                # a fact nobody could read for this many ticks running ends the wait, said:
                # no seat stands on it for good
                over, reason, run = (True, f"your wait on {wait['on']} cannot be read ({reason})",
                                     None)
            elif not over:
                if wait.get("unread"):
                    wait_mark(name, wait, unread=0)     # read again: the misses were blips
                continue
            if not wait_mark(name, wait, over=reason, run=run):
                continue
            wait = seat_read(name).get("wait")
            if not isinstance(wait, dict) or wait.get("told"):
                continue
        if closed:
            continue
        run = wait.get("run") and run_record.read_state(config.RUNS / wait["run"])
        if run and transitions.launched_session(run) == name:
            # its own run hands this ending back with the verdict, PR and result: that line is
            # the one the seat hears, and a second for the same ending would join it in the
            # composer (22 Oct).  A routine ending, or one said elsewhere, is not typed to it
            if not handback.routine_ending(run) and (
                    run.get("state") not in run_record.ENDED or handback.owes_ending(run)):
                continue        # the hand-back is on its way
            if handback.already_handed_back(run) and not run.get("handback_note"):
                if wait_mark(name, wait, told=time.time()):
                    log(f"{name}: its own run's hand-back told it that {wait['over']}; its "
                        "wait is over")
                continue
        # one line, whatever gh said over several: a newline typed is a key of its own
        line = f"{' '.join(str(wait['over']).split())}; your wait is over. Decide the next step."
        if type_at_prompt(session, line, log, cfg=cfg, typed=wait.get("typed"),
                          receipt=lambda mark, name=name, wait=wait:
                          wait_mark(name, wait, typed=mark)):
            if wait_mark(name, wait, told=time.time()):
                log(f"{name}: told that {wait['over']}; its wait is over")


def wait_main(argv):
    """`ak wait PR_URL|RUN_ID`: this seat ends its turn waiting on that pull request or run.

    The seat is the one `ak notify` speaks for, and the wait is written to its own record and
    nowhere else: no card, no notice.  Its next `ak wait` or `ak notify` replaces it.  A wait
    names a fact ak can read, never a session: the tick ends it when the pull request merges
    or closes, no run is going on it, or the run ends, and tells the seat so (`wait_over`).
    One already over is refused with its fact (`wait_fact`): the tick would end it at once and
    wake the seat for nothing.
    """
    if command_help.show("wait", argv):
        return 0
    if len(argv) != 1 or argv[0].startswith("-"):
        raise config.Error(command_help.COMMANDS["wait"][0])
    seat = config.current_session()
    if not seat:
        print("ak wait: no seat: run it inside an orchestrator session", file=sys.stderr)
        return 1
    on = argv[0].strip()
    pull = transitions.PR_PARTS.match(on)      # the one pattern of a GitHub pull request URL
    if pull:
        kind, shown = "pr", f"PR #{pull.group(3)}"
    elif on and on not in (".", "..") and "/" not in on and (config.RUNS / on).is_dir():
        kind, shown = "run", f"run {on}"
    else:
        print(f"ak wait: {on!r} is neither a pull request URL nor a run id; ak waits on a "
              "pull request or a run, never on a session (ak run status lists runs)",
              file=sys.stderr)
        return 1
    wait = {"on": on, "kind": kind, "at": time.time()}
    over, why, _ = wait_fact(wait)
    if over is None:
        print(f"ak wait: gh cannot view {on}: {why}", file=sys.stderr)
        return 1
    if over:
        print(f"ak wait: {why}; nothing is left to wait on", file=sys.stderr)
        return 1
    if not seat_write(seat, wait=wait):
        return 1
    print(f"{seat}: waiting on {shown}")
    return 0


def opened_now(name):
    """Record the interactive open the live states are measured against.  Never a harness's."""
    seat_write(name, opened_at=time.time())


def stuck_notice(name, harness):
    return (f"{name} ({harness}) is stuck with no progress for an hour; "
            "open the host, press this session's number, and check this session.")


def observe(entry, tail, harness, now):
    """Age the last error line and the last pane change separately."""
    if entry.get("pane") != tail:
        entry.update(pane=tail, changed_at=now, since=now)
    line = next((line for line in reversed(tail.splitlines())
                 if any(says(line, mark) for mark in stalls(harness))), "")
    if entry.get("stall_line") != line:
        entry.update(stall_line=line, stall_at=now, since=now)
        entry.pop("reset_nudged_at", None)


def keystroke(harness, tail):
    """What starts that seat again: a goal is resumed by its own command, a turn by a word."""
    block = config.manifest(harness).get("resume")
    if isinstance(block, dict) and block.get("key") and block.get("when"):
        if re.search(block["when"], tail, re.I):
            return block["key"]
    return CONTINUE_LINE


def asking(name, harness, pane):
    """Does that pane, with its seat's hook facts, put a question to the owner?  Read without
    writing anything, so it may be asked under the seat's typing lock."""
    return _decided_state(name, harness, pane) == "asking"


def unseen(launched, harness, pane):
    """Does that pane read otherwise than the seat's published word was decided from, whoever
    published it?  Read as a look reads it (`observed`), writing nothing."""
    try:
        name = config.resolve_session(launched)
        previous = seat_read(name)
        found = observed(name, harness, pane, previous, time.time())
    except (config.Error, OSError):
        return False
    return word_from(found) != previous.get("word_from")


def _decided_state(name, harness, pane):
    """The live state positively read off that pane, or None where nothing decides one."""
    if not pane.strip():
        return None
    try:
        previous = seat_read(name)
        found = classify(harness, pane_tail(pane), hook_facts(name),
                         previous.get("opened_at"), previous, time.time())
    except (config.Error, OSError):
        return None
    return found.get("state") if found.get("authority") else None


def _holds_text(pane, text):
    """Is the typed line still sitting unsent in the pane's composer?"""
    needle = re.sub(r"\s+", "", text)
    if not needle:
        return False
    # The last screen rules read this far down; wrapping may split the line across rows,
    # so whitespace comes out before the comparison. Attributes come out first: a `-e`
    # capture paints the composer line this is searched for.  Only from the bottom-most
    # prompt mark down: a line the harness took is echoed just above its composer.
    region = [strip_sgr(line).strip() for line in pane.splitlines()
              if strip_sgr(line).strip()][-8:]
    at = next((index for index in range(len(region) - 1, -1, -1)
               if re.match(r"(?:│\s*)?[❯›⟩]", region[index])), 0)
    return needle in re.sub(r"\s+", "", "\n".join(region[at:]))


def _pane_sent(session, harness, pane, text):
    """The typed line left the composer, or a dialog took over the screen."""
    state = (_decided_state(session["name"], harness, pane)
             if harness is not None else None)
    if state == "asking":
        # A dialog owns the screen: the line landed, and no Enter goes into it blind.
        return True
    # read whole where the composer can be read: a long line wraps past the bottom rows, and
    # a line the harness took may be echoed above its empty composer
    held = composer_draft(harness, pane) if harness is not None else None
    if held is not None:
        return re.sub(r"\s+", "", text) not in held
    return not _holds_text(pane, text)


def _wait_ready(ready, held):
    """Poll `ready` for SENT_WAIT: a long conversation draws a typed line slower than KEY_GAP,
    and its Enter waits for the whole of it rather than for the next tick."""
    for _ in range(int(SENT_WAIT / SENT_POLL)):
        if ready(held):
            return True
        time.sleep(SENT_POLL)
    return False


def _wait_sent(session, harness, text):
    """Poll the pane for SENT_WAIT; True where the typed line left its composer in time."""
    for _ in range(int(SENT_WAIT / SENT_POLL)):
        if _pane_sent(session, harness, pane_text(session), text):
            return True
        time.sleep(SENT_POLL)
    return False


@contextmanager
def seat_held(name):
    """The seat's lock for typing into it, the news its next prompt carries made ready first
    (`orch.rulebook_prepare`): that prompt's own hook never waits on this lock, and nothing
    runs between the last look at the screen and the Enter."""
    with notify.session_lock(name) as held:
        orch.rulebook_prepare(held)
        yield held


def pane_unread(session):
    """Unread input on either tty; a terminal that cannot be asked keeps the old behavior.

    A wrapper can drain the pane's tty while its harness reads nothing from the inner one.
    Ask the kernel without taking those bytes, on the same pane and server we type into.
    """
    try:
        rc, paths = orch.tmux_out("display-message", "-p", "-t", _pane(session),
                                  "#{pane_tty}\t#{" + orch.INPUT_TTY_OPTION + "}",
                                  socket=orch.seat_socket(session), timeout=5)
    except (OSError, ValueError, AttributeError):
        return False
    if rc != 0:
        return False
    for path in paths.split("\t"):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY)
            try:
                if os.isatty(fd):
                    count = fcntl.ioctl(fd, termios.FIONREAD, struct.pack("i", 0))
                    if struct.unpack("i", count)[0] > 0:
                        return True
            finally:
                os.close(fd)
        except (OSError, ValueError):
            pass
    return False


def off_composer(session):
    """Is that seat's terminal cursor outside its composer's box, of a harness keeping it there
    while keys go there (`[screen] cursor`): one opening a dialog moves it into the dialog, and
    a key sent then goes into the dialog's search, Enter picking one of its rows.  The box is
    the bottom run of rows its `composer` pattern names, read off the same pane as the cursor;
    a dialog drawn inside that box itself, in a pane too short for it to clear the box, is not
    told apart.  A cursor or pane that cannot be read is outside."""
    try:
        harness = seat_model(config.load(), session["name"])[0]
        chrome = screen(harness) if harness else {}
    except (config.Error, OSError):
        return False
    if not chrome.get("cursor") or not chrome["composer"]:
        return False
    server, pane = orch.seat_socket(session), _pane(session)
    rc, at = orch.tmux_out("display-message", "-p", "-t", pane, "#{cursor_y}", socket=server)
    code, shown = orch.tmux_out("capture-pane", "-p", "-t", pane, socket=server, rows=True)
    box = [chrome["composer"].fullmatch(row.strip()) is not None for row in shown.splitlines()]
    if rc != 0 or code != 0 or not at.isdigit() or True not in box:
        return True
    top = bottom = max(row for row, inside in enumerate(box) if inside)
    while top and box[top - 1]:
        top -= 1
    return not top <= int(at) <= bottom


def _send_enter(session, log):
    """One Enter completing a line already begun; False where the send failed or the seat's
    cursor is off its composer (`off_composer`)."""
    name = session["name"]
    if off_composer(session):
        return False
    rc, out = orch.tmux_out("send-keys", "-t", _pane(session), "Enter",
                            socket=orch.seat_socket(session))
    if rc != 0:
        log(f"WARN could not type into the {name} seat: {out[-200:]}")
        return False
    return True


def _send_line(session, text, log, typed=lambda: None, *, source="ak", put=None):
    """Type one literal line; the caller waits KEY_GAP before sending its Enter.

    `typed` is told the moment the text is in, before the Enter that can still fail.
    `source="owner"` marks an owner's reply relayed unchanged, including from Discord.
    None means unread input, or a cursor off the composer (`off_composer`), deferred this line
    before any receipt or key was written.
    `put`, where given, puts the text in in place of its keys, and says whether it did.
    """
    if pane_unread(session) or off_composer(session):
        return None
    name = session["name"]
    record = config.session_records().get(name, {})
    plugin = orch.seat_plugin(record)
    cwd = record.get("cwd")
    conversation = plugin.conversation(record, cwd)
    sent = {"at": time.time(), "text": text, "source": source, "harness": plugin.name,
            "conversation": conversation, "after": len(plugin.user_messages(record, cwd, conversation))}
    config.STATE.mkdir(parents=True, exist_ok=True)
    with config.seat_file("input", name).open("a+", encoding="utf-8") as fh:
        before = fh.tell()
        # A restart between text and Enter must still know whose line is in the composer.
        fh.write(json.dumps(sent, ensure_ascii=False) + "\n")
        fh.flush()
        rc, out = (orch.tmux_out("send-keys", "-t", _pane(session), "-l", text,
                                 socket=orch.seat_socket(session)) if put is None
                   else (0, "") if put() else (1, "its editor did not put the line in"))
        if rc != 0:
            fh.truncate(before)
            log(f"WARN could not type into the {name} seat: {out[-200:]}")
            return False
    typed()
    return True


def kept_asked_first(session, harness=None, held=True):
    """Before a key goes into that seat: a line or an Enter sent where its turn has ended
    opens a new one, so a question it kept back for that end is asked first, on a look of
    the typer's own, and what the typer reads next is the question as it always stood.
    `held` says the caller holds the seat's typing lock, which is the notice's own."""
    name = session["name"]
    if not seat_read(name).get("unasked"):
        return
    try:
        harness = harness or seat_model(config.load(), name)[0]
        if harness:
            ask_kept_back(name, harness, live_state(session, harness), held=held)
    except (config.Error, OSError):
        pass


def type_checked(session, text, log, harness=None, guard=nullcontext,
                 veto=lambda name: False, typed=lambda: None, pending=False, *, source="ak",
                 ready=lambda name: True):
    """Type one line with a gap before Enter, and confirm it left the composer's line.

    Delivery is at least once: no mark, receipt or transcript read closes every crash window
    between the Enter and the queue rewrite, so nothing that types through this promises
    exactly once.

    Text, a KEY_GAP pause, then Enter; within SENT_WAIT the typed text has to be gone
    from the bottom region and the whole composer. A working seat can still hold unsent
    text. A dialog counts as landed, never as a reason for another Enter.  Still held:
    one more Enter and one more wait.  Still held after that, log and return False,
    leaving the composer alone.  Where the seat paints no composer at all, a delivered
    send counts as sent.
    `guard` covers text, gap and first Enter, with `veto` read once before typing, so
    another sender cannot join the line and a later veto cannot strand it. Confirmation
    waits release the guard; a retry Enter checks the veto under it again. `typed` is
    told the moment the text is in the composer; `pending` sends only its locked Enter.
    `ready` is asked under the guard right before each Enter, after the gap, and the first
    Enter waits up to SENT_WAIT for it: the owner can type in it, and an Enter it refuses is
    never sent. None means the owner's input deferred the line before its text went in:
    keys its terminal has not read yet, or text in its composer, which a line typed after it
    would join and send. Those checks gate new text, never the Enter completing it:
    withholding that Enter would leave a draft the caller cannot recover, or let a retry
    append the same text to itself.
    """
    text = terminal_mod.keyed(text)    # a typed escape or newline is a key, not text
    try:
        seat = dict(session, name=config.resolve_session(session["name"]))
    except (config.Error, OSError):
        seat = dict(session)
    name = seat["name"]
    if harness is None:
        try:
            harness, _ = seat_model(config.load(), name)
        except (config.Error, OSError):
            harness = None
    # a line left pending was read in its composer, whatever chrome is drawn around it
    confirm = pending
    if harness is not None and not confirm:
        pane = pane_text(seat)
        if composer_draft(harness, pane):
            return None     # the owner's text: a line typed after it joins it, and sends both
        try:
            pattern = screen(harness).get("composer")
        except config.Error:
            pattern = None
        if pattern is not None:
            # Stripped first: a real capture ends in blank rows, unlike a byte stream,
            # and a `-e` capture carries attributes a plain composer pattern never
            # names.  A seat painting no composer at all is not a TUI waiting on one:
            # the smoke suite's inbox seat holds a `sleep`, and a delivered send is
            # all there is.
            confirm = any(pattern.search(strip_sgr(line))
                          for line in pane_tail(pane).splitlines())
    with guard() as held:
        kept_asked_first(seat, harness, held=held is not None)
        if veto(held if held is not None else name):
            return False
        if not pending:
            sent = _send_line(seat, text, log, typed, source=source)
            if not sent:
                return sent
            time.sleep(KEY_GAP)
        if not _wait_ready(ready, held if held is not None else name) or not _send_enter(seat, log):
            return False
    if not confirm or _wait_sent(seat, harness, text):
        return True
    with guard() as held:
        if (veto(held if held is not None else name)
                or not ready(held if held is not None else name)):
            return False
        if not _send_enter(seat, log):
            return False
    if _wait_sent(seat, harness, text):
        return True
    log(f"WARN {name}: typed text sits unsent in its composer: {text[:60]}")
    return False


def type_into(session, text, log, stale=lambda held: False, *, source="ak", asked=False):
    """One line and Enter into a seat, the way the inbox is asked its question.

    `stale` is asked beside the owner's question, under the same lock and with the name the
    seat goes by now, so what changed while the pane was read or the lock waited still counts.
    `asked` types it past an open question too: the line goes on with a turn it never stopped.
    """
    return type_checked(session, text, log, None,
                        guard=lambda: seat_held(session["name"]),
                        veto=lambda held: (not asked and owner_question(notify.last(held)))
                        or stale(held),
                        source=source)


def title_record(name):
    """Under the seat lock, retire title sends when its recorded conversation changes."""
    record = config.session_records().get(name, {})
    conversation = record.get("conversation")
    if record.get("title_conversation", conversation) != conversation:
        # Retiring sends does not invalidate the title already recorded by a launch or receipt.
        config.update_session(name, title_sync=None, title_superseded=None,
                              title_conversation=conversation)
        record = config.session_records().get(name, {})
    return record


def follow_title(session, log=lambda _: None):
    """An owner's custom title names the seat; our own last title is only an echo."""
    if any(session.get(key) for key in orch.CLOSED):
        return None
    with notify.session_lock(session["name"]) as name:
        record = title_record(name)
        title = orch.seat_plugin(record).session_title(record)
    if (not title or title in (name, record.get("session_title")) or
            title in record.get("title_superseded", [])):
        return None
    aliases = {old for old, target in config.session_aliases().items() if target == name}
    aliases -= orch.held_names()
    new = orch.unique_name(title, orch.taken_names() - {name} - aliases)
    if not new:
        return None
    if new == name:
        # The owner may have changed only case or punctuation. The seat is now named,
        # and the title still needs its normalized spelling even if we sent it before.
        if record.get("unnamed"):
            orch.rename(name, name, log=log)
        if record.get("session_title") == name:
            sync_title(dict(session, name=name), log, force=True)
        return None
    new = orch.rename(name, new, log=log)
    log(f"{name}: renamed from the conversation title to {new}")
    return new


def composer_draft(harness, pane):
    """The composer's whole text without whitespace, "" when empty, None where none is found."""
    rows = _composer_rows(harness, pane)
    return None if rows is None else re.sub(r"\s+", "", "".join(rows))


def _composer_rows(harness, pane, *, exact=False):
    """The rows of text in the composer, [] when empty, None where none is found.

    Read on any turn, from its prompt row down to the chrome under it: a wrap or a newline
    puts text on the rows below.  Found the way the draft rule finds it: where the harness
    rules its composer only a prompt row that rule closes is one -- a user's status line under
    the rule never is, whatever its mark.
    """
    chrome = screen(harness)
    pane = _boxed(pane) if chrome["boxed"] else pane
    raws, rows = _screen_rows(pane_tail(pane))
    if chrome["draft"]:
        # A composer no `❯›⟩` mark finds: its manifest finds the framed block it holds,
        # and finding none reads as empty -- where the composer itself is on the
        # screen, a row its pattern names; with none there, a blank capture above all, nothing
        # was read.  Its rows are read as drawn, the tail's blank rows among them: their inset
        # tells its prompt row from text, and a blank row ends a box, so an older one framed
        # above it is none of it while a bare row inside it can be a draft's own.
        drawn = [strip_sgr(row).rstrip() for row in pane.splitlines()]
        top = [at for at, row in enumerate(drawn) if row.strip()][-PANE_LINES:]
        source = "\n".join(drawn[top[0]:] if top else [])
        found = list(chrome["draft"].finditer(source))
        if exact and not found:
            return None
        if not found and not (chrome["composer"]
                              and any(chrome["composer"].fullmatch(row) for row in rows)):
            return None
        parts = []
        for match in found:
            edge = match.groupdict().get("edge") or ""
            before = source[:match.start()].splitlines()
            # A block read without its opening is the end of one cropped above the read, a
            # padding row inside a draft is not its opening edge, nor is an edge at the start
            # of a cropped read proof that none of the draft sits above it.
            if exact and (not match.groupdict().get("opening") or edge and (
                    before and before[-1].startswith(edge)
                    or not before and len(_content_rows(pane)) > PANE_LINES)):
                return None
            parts.extend(row[len(edge):].strip() for row in match["text"].splitlines())
        return _unscrolled(chrome, parts, exact=exact)

    def end(at):
        return next((row for row in range(at + 1, len(rows)) if chrome_line(chrome, rows[row])),
                    len(rows))

    marked = prompt_rows(raws)
    if exact:
        marked = [row for row in marked
                  if re.match(r"(?:\s*│\s?)?[❯›⟩]", strip_sgr(raws[row]))]
    at = next(iter(marked), None)
    stop = None if at is None else end(at)
    if exact and at is not None:
        # Key hints can also be owner text. Read through them to the last composer chrome
        # (its status or box edge), or an unindented closing rule before that chrome.
        stop = next((row for row in range(len(rows) - 1, at, -1)
                     if chrome["composer"] and chrome["composer"].fullmatch(rows[row])), None)
        if stop is not None:
            stop = next((row for row in range(at + 1, stop)
                         if re.fullmatch(RULE, strip_sgr(raws[row]).rstrip())), stop)
    if chrome["ruled"]:
        # Its box between its own rules; a pane's bottom row stands in where none is drawn.
        at, stop = ruled_composer(chrome, raws)
        if not exact and at is None and marked and marked[0] + 1 == len(rows):
            at, stop = marked[0], len(rows)
    if at is None or exact and (stop is None or any(dim_rows(raws, chrome["faint"])[at:stop])
                               or chrome["composer"] and chrome["composer"].fullmatch(rows[at])):
        return None
    return _unscrolled(chrome, _composer_parts(chrome, raws, rows, at, stop), exact=exact)


def _unscrolled(chrome, rows, *, exact=False):
    """Those composer rows without what the harness draws on a composer scrolled past its
    height (`[screen] scrolled`: a scrollbar, a count of the rows above), none left empty."""
    if chrome["scrolled"] is not None:
        if exact and any(chrome["scrolled"].search(row) for row in rows):
            return None
        rows = [chrome["scrolled"].sub("", row) for row in rows]
    return [row for row in rows if row.strip()]


def _cropped_composer_rows(harness, pane):
    """A composer's top is above the read: every row over its bottom chrome is its text,
    read inside a box's edges and without scroll marks, as rows under its prompt are."""
    chrome = screen(harness)
    tail = content_lines(harness, pane_tail(_boxed(pane) if chrome["boxed"] else pane))
    return _unscrolled(chrome, [_inside_box(row) for row in tail])


def composer_holds(name, session, line, cfg=None, *, exact=False):
    """What that seat's composer holds now, off one capture: "line", "empty", or "other" --
    anything else, nothing read, or a question to the owner on the screen, as a dialog that
    keeps the composer drawn is.

    "line" is that line and nothing else, as its composer shows it: all of it; its end, rows
    of it, where it is taller than the composer shows -- one composer scrolls to its last rows,
    and another's top goes above the read; or the harness's fold of a line longer than `[screen]
    folds_over`.  What the owner types goes in at its end, so none of these is a line with the
    owner's words beside it, and a one-row draft that only ends the way the line does is the
    owner's.  It is also a composer read whole holding that line joined in order with the
    others ak typed there last (`_joined`): a line drawn late joins the next.
    `exact` requires the whole composer to be read and hold the full line: a cropped or
    scrolled composer, suffix or paste fold is no proof without a delivery mark.
    """
    try:
        name = config.resolve_session(name)
        harness = seat_model(config.load() if cfg is None else cfg, name)[0]
    except (config.Error, OSError):
        return "other"
    pane = pane_text(session)
    if not harness or not pane.strip() or asking(name, harness, pane):
        return "other"
    rows = _composer_rows(harness, pane, exact=exact)
    if rows is not None and not re.sub(r"\s+", "", "".join(rows)):
        return "empty"
    chrome = screen(harness)
    if not exact and rows is None and len(_content_rows(pane)) > PANE_LINES:
        rows = _cropped_composer_rows(harness, pane)
    held, whole = re.sub(r"\s+", "", "".join(rows or ())), re.sub(r"\s+", "", line)
    folded = (chrome["folded"] is not None and chrome["folds_over"] is not None
              and len(line) > chrome["folds_over"])
    if held and (held == whole or not exact and (
            len(rows) > 1 and whole.endswith(held)
            or folded and chrome["folded"].fullmatch(held))):
        return "line"
    # lines drawn joined are ak's only off a composer read whole: owner text can sit above a crop
    read = re.sub(r"\s+", "", "".join(
        (rows if exact else _composer_rows(harness, pane, exact=True)) or ()))
    return "line" if read and whole in _joined(name, read) else "other"


def _joined(name, held):
    """The lines ak typed into that seat last, whitespace aside, that the composer text `held`
    is all of joined in order, else none: a harness that draws a line late joins it to the next
    one ak types there, and both are still ak's to send (22 Oct 2026)."""
    typed = [re.sub(r"\s+", "", str(sent.get("text"))) for sent in entries(
        config.seat_file("input", name))]
    lines = []
    while typed and len("".join(lines)) < len(held):
        lines.insert(0, typed.pop())
    return lines if "".join(lines) == held else []


def _composer_parts(chrome, raws, rows, at, stop):
    """What is typed in a composer from its prompt row `at` down to `stop`, a part a row, none
    empty: the draft rule and `composer_draft` both read it here.  Bright text only -- what is
    typed over the start of a suggestion is a draft, the rest of it drawn faint after it none --
    and a boxed composer's edges, chrome on every row of it, left out."""
    boxed = rows[at].startswith("│") and rows[at].endswith("│")
    bright = _bright_rows(raws, chrome["faint"])
    parts = [_draft_text(bright[at][:-1].rstrip() if boxed else bright[at], chrome["composer"])]
    for plain in bright[at + 1:stop]:
        parts.append(_inside_box(plain) if boxed else plain)
    return [part for part in parts if part]


def _inside_box(row):
    """A composer row inside its box's edges, where it is drawn in one."""
    return row[1:-1].strip() if row.startswith("│") and row.endswith("│") else row


def sync_title(session, log=lambda _: None, *, force=False):
    """Record a title only once the harness takes it; abandon a name after three tries."""
    if any(session.get(key) for key in orch.CLOSED):
        return False

    with notify.session_lock(session["name"]) as name:
        session = dict(session, name=name)
        record = title_record(name)
        plugin = orch.seat_plugin(record)
        synced = plugin.sync_title(name, record)
        if synced is not None:
            if synced:
                config.update_session(name, session_title=name, title_sync=None)
            return synced
        line = plugin.title_command(name)
        attempt = record.get("title_sync")
        tries = (attempt or {}).get("tries", 0) if (attempt or {}).get("name") == name else 0
        if not line:
            return False
        pending = (plugin.title_command(attempt["name"])
                   if attempt and attempt.get("tries") and attempt.get("pending", True) else None)
        composed = [True] if pending and composer_draft(
            plugin.name, pane_text(session)) == re.sub(r"\s+", "", pending) else []
        if composed:
            line = pending    # our line still needs Enter, even after its seat changes name
        title = plugin.session_title(record)
        # A harness whose own naming can replace an acknowledged name restores it: an
        # empty receipt means our name is absent again, so repair it with the same cap.
        restores = getattr(plugin.module, "title_restores", None)
        if (record.get("session_title") == name and not force and not tries and not composed
                and not (restores and restores(record, title))
                and title not in record.get("title_superseded", [])):
            return False
        if title == name and not composed:
            config.update_session(name, session_title=name, title_sync=None)
            return True
        if tries >= 3 and not composed:
            if not attempt.get("failed"):
                log(f"WARN {name}: title did not take after three tries; leaving it until its name changes")
                config.update_session(name, title_sync=dict(attempt, failed=True))
            return False

    def veto(held):
        # A rename or another sender may have won while we waited. The receipt and each
        # send share the seat's lock; only confirmation polls release it.
        current = config.session_records().get(held, {})
        if (held != name or current.get("title_sync") != attempt
                or current.get("conversation") != record.get("conversation")):
            return True
        pane = pane_text(session)
        state = _decided_state(name, plugin.name, pane)
        if owner_question(notify.last(name)) or state in (None, "asking"):
            return True
        if not plugin.title_ready(current, state):
            return True
        if composed:
            return composer_draft(plugin.name, pane) != re.sub(r"\s+", "", line)
        if state not in ("at_prompt", "working"):
            return True
        return composer_draft(plugin.name, pane) != ""

    def typed():
        nonlocal attempt
        composed.append(True)
        attempt = {"name": name, "tries": tries + 1, "pending": True}
        config.update_session(name, title_sync=attempt,
                              title_conversation=record.get("conversation"))

    sent = type_checked(session, line, log, plugin.name,
                        guard=lambda: seat_held(name), veto=veto,
                        typed=typed, pending=bool(composed))
    with notify.session_lock(name) as held:
        current = config.session_records().get(held, {})
        if (held != name or current.get("title_sync") != attempt
                or current.get("conversation") != record.get("conversation")):
            return False
        title = plugin.session_title(current)
        if (sent and line == plugin.title_command(name)
                and (title == name or title is None and plugin.title_facts["unreadable"])):
            config.update_session(name, session_title=name, title_sync=None)
            return True
        if sent:
            # Delivery ends ownership of the composer even while its title receipt waits.
            config.update_session(name, title_sync=(dict(attempt, pending=False)
                                  if attempt["name"] == name else None))
    return False


def at_prompt(session, cfg=None, pane=None):
    """Is that seat's harness sitting at its own prompt, waiting to be typed into?

    The tick's own test before it nudges a stalled seat, off one fresh capture: a line typed
    into a turn in flight lands in a composer nobody is reading, and the harness sends it
    whenever its turn happens to end -- or never.  A seat nobody is in has no prompt at all.

    Only positive evidence counts, and `classify` offers `at_prompt` as its answer when it has
    none: with no hook fact and no rule that matched it says so in `authority`, which is empty
    exactly then.  A blank capture, a screen no adapter can read, a harness between turns with
    its hooks not installed -- none of those is a seat waiting to be typed into, whichever
    harness owns the word, and the absence of a `working` signal is not the presence of a
    prompt.  `health` drops a blank capture before it gates anything and this drops it too.
    """
    if any(session.get(key) for key in orch.CLOSED):
        return False
    try:
        harness = seat_model(config.load() if cfg is None else cfg, session["name"])[0]
        if not harness:
            return False
        pane = pane_text(session) if pane is None else pane
        if not pane.strip():
            return False        # a failed or blank capture is no evidence that it is free
        found = live_state(session, harness, pane=pane, cfg=cfg)
    except (config.Error, OSError):
        return False
    return _free(harness, found)


def _free(harness, found):
    """Does that read put the seat at its prompt: a rule or hook saying so, no turn in flight."""
    if not found.get("authority"):
        return False            # nothing said anything: that is not a prompt, it is silence
    return found.get("state") == "at_prompt" and not _turn_in_flight(harness, found)[0]


def takes_line(session, cfg=None, pane=None):
    """May a line be typed into that seat now: at its own prompt, or stopped on background work,
    whose composer stays open and sends a typed line at once (`background` on that hook event)."""
    if at_prompt(session, cfg=cfg, pane=pane):
        return True
    if any(session.get(key) for key in orch.CLOSED):
        return False
    try:
        harness = seat_model(config.load() if cfg is None else cfg, session["name"])[0]
        if not harness:
            return False
        pane = pane_text(session) if pane is None else pane
        if not pane.strip():
            return False
        found = live_state(session, harness, pane=pane, cfg=cfg)
    except (config.Error, OSError):
        return False
    return found.get("hooked_event") in marked_events(harness, "background")


def quiet_prompt(session, held, cfg=None):
    """May a new line go into that seat, the one its send lock calls `held`?

    One capture under that lock, right before the first key, says all of it: the seat at its
    prompt, no question up, and its composer read empty -- never onto the owner's draft, short
    or wrapped, a dialog, or a screen whose composer cannot be read.
    """
    pane = pane_text(session)
    try:
        harness = seat_model(config.load() if cfg is None else cfg, held)[0]
    except (config.Error, OSError):
        return False
    return bool(harness and takes_line(session, cfg=cfg, pane=pane)
                and not asking(held, harness, pane) and composer_draft(harness, pane) == "")


DRAFT_STILL = 120       # a seat whose terminal took no keys this long is not one the owner types in:
                        # only then is their text set aside for a line (`_past_text`)


def seat_editor(session, cfg=None):
    """{"id", "tty", "keys", "harness"} of that seat's pane, whose editor `_edit` asks a step: a
    seat its launch gave ak's, of a harness naming the keys that open it (`[screen] editor`), or
    None."""
    try:
        harness = seat_model(config.load() if cfg is None else cfg, session["name"])[0]
        keys = screen(harness)["editor"] if harness else ()
    except (config.Error, OSError):
        return None
    rc, out = (orch.tmux_out("display-message", "-p", "-t", _pane(session),
                             "#{pane_id}\t#{pane_pid}\t#{pane_tty}",
                             socket=orch.seat_socket(session)) if keys else (1, ""))
    pane, pid, tty = (out.split("\t") + ["", ""])[:3] if rc == 0 else ("", "", "")
    return ({"id": pane, "tty": tty, "keys": keys, "harness": harness}
            if pane.startswith("%") and aside_editor.launched(pid, tty) else None)


def _edit(session, where, mode, line=""):
    """Ask ak's editor for `line` or `back` with that line (`aside_editor`) and press the keys
    that open it: its answer, or None where it gives none within SENT_WAIT, or where no key
    goes out as the pane's cursor is off its composer (`off_composer`) or its composer, read
    just before them, may hold a paste the editor would lose (`_may_paste`).  The editor reads
    the composer itself, which a screen can draw late or cropped.  The ask is taken back after,
    for the owner's own edit never to find -- one that keys went out for and that went
    unanswered turned to `none`, which an edit they open late leaves as it is."""
    bound = dict(session, pane=where["id"])
    if off_composer(bound) or _may_paste(where["harness"], bound):
        return None
    server, pane, ask = orch.seat_socket(session), where["id"], aside_editor.request(mode, line)
    after = ("set-option", "-pu", "-t", pane, aside_editor.ASK)
    try:
        if (orch.tmux_out("set-option", "-p", "-t", pane, aside_editor.ASK,
                          orch.tmux_literal(ask), socket=server)[0] == 0
                and orch.tmux_out("send-keys", "-t", pane, *where["keys"], socket=server)[0] == 0):
            for _ in range(int(SENT_WAIT / SENT_POLL)):
                rc, said = orch.tmux_out("show-options", "-pqv", "-t", pane, aside_editor.ASK,
                                         socket=server)
                if rc == 0 and (word := aside_editor.answer(ask, said)):
                    return word
                time.sleep(SENT_POLL)
            after = ("set-option", "-p", "-t", pane, aside_editor.ASK,
                     orch.tmux_literal(aside_editor.request("none")))
    finally:
        orch.tmux_out(*after, socket=server)
    return None


def _may_paste(harness, session):
    """Whether that seat's composer may hold a paste its harness hands its editor as a
    placeholder and sends alone once the editor returns (`[screen] pasted`): one it shows, or
    any draft not read whole, which may hold one above the rows it shows."""
    pasted = screen(harness)["pasted"]
    if pasted is None:
        return False
    pane = pane_text(session)
    if composer_draft(harness, pane) == "":
        return False
    rows = _composer_rows(harness, pane, exact=True)
    return rows is None or bool(pasted.search("\n".join(rows)))


def _editor_kept(session):
    """{pane: (state, line it put)} of each pane of that seat, and of the one `pinned` named
    wherever it has moved since, whose text ak's editor keeps (`aside_editor.pack`), or None
    where tmux cannot say.  The editor writes one only for a step asked under the seat's send
    lock, so one read under that lock holds whichever of them the owner selects meanwhile."""
    server = orch.seat_socket(session)
    rc, names = orch.tmux_out("list-buffers", "-F", "#{buffer_name}", socket=server)
    if rc != 0:
        return None
    if not any(name.startswith(aside_editor.kept("")) for name in names.split("\n")):
        return {}
    rc, panes = orch.tmux_out("list-panes", "-s", "-t", f"={session['name']}:", "-F",
                              "#{pane_id}", socket=server)
    if rc != 0:
        return None
    found = {}
    for pane in {*panes.split("\n"), session.get("pane")}:
        if pane and aside_editor.kept(pane) in names.split("\n"):
            rc, stored = orch.tmux_out("save-buffer", "-b", aside_editor.kept(pane), "-",
                                       socket=server)
            if rc != 0 or not stored:
                return None
            state, put, _ = aside_editor.unpack(stored.encode())
            found[pane] = (state, put.decode())
    return found


def _editor_read(session, where, cfg=None):
    """That seat's screen as (harness, pane, live state) where it may be asked an editor step
    now, or None: none of its pane's input unread (`where`, `seat_editor`), read with no
    question or picker up (`[[rule]] picker`) -- the step's keys open the editor from a composer
    alone, and a picker drawn on over what it puts there takes its Enter.  However recently its
    terminal took keys: text given back goes only into a composer empty or holding the line
    alone, and the terminal takes ak's own keys as it does the owner's."""
    name = session["name"]
    try:
        harness = seat_model(config.load() if cfg is None else cfg, name)[0]
        pane = pane_text(session) if harness else ""
        found = live_state(session, harness, pane=pane, cfg=cfg) if pane.strip() else {}
        picker = _picker_up(harness, found)
    except (config.Error, OSError):
        return None
    return ((harness, pane, found) if found.get("authority") and not asking(name, harness, pane)
            and not picker and not pane_unread(session) else None)


def _picker_up(harness, found):
    """Whether that seat's screen, read as `found` (`live_state`), shows a picker
    (`[[rule]] picker`), which may draw its composer empty above it."""
    return any(rule["picker"] and rule["id"] == found.get("rule")
               for rule in screen(harness)["rules"])


def drafts_back(cfg):
    """Each tick: text ak's editor set aside from a pane of a seat's (`aside_editor.ASIDE`) asked
    back, every read and key of the step on that pane, whichever the owner selects: the editor
    hands it back only into an empty composer, however the pass that put ak's line in its place
    ended.  A line still in the composer is the mark's pass to send first, and a line the seat
    is owed (a `midturn` mark) goes before any text back; text a switch carried (`carry_draft`)
    goes back at once after it."""
    seats = [session for session in orch.sessions() if not session.get("legacy")
             and not any(session.get(key) for key in orch.CLOSED)]
    for session in seats:
        if not _editor_kept(session):   # most ticks keep nothing: no seat's send lock waited on
            continue
        with seat_held(session["name"]):
            if seat_read(session["name"]).get("midturn"):
                continue    # its line goes first: text back in the composer would go with it
            for pane, (state, _) in sorted((_editor_kept(session) or {}).items()):
                bound = dict(session, pane=pane)
                where = state == aside_editor.ASIDE and seat_editor(bound, cfg)
                read = where and _editor_read(bound, where, cfg)
                if read and composer_draft(read[0], read[1]) == "":
                    _edit(bound, where, "back")


def _past_text(session, cfg=None):
    """That seat's pane whose editor ak's line goes in through (`seat_editor`), or None: its turn
    over, its composer read holding text, or read empty with text that editor keeps, which it can
    draw late -- on the read its editor may be asked a step on too (`_editor_read`).  The owner:
    text they leave standing in a seat never keeps ak's line out of it (19 Oct 2026).  A composer
    not read whole -- a picker drawn in its place, text too tall for its rows, or scrolled past
    them -- says nothing it holds."""
    def past(harness, pane, found):
        return found and _composer_open(harness, found) and (
            _composer_rows(harness, pane, exact=True)       # rows of text, none left empty
            or composer_draft(harness, pane) == "" and _editor_kept(session))
    try:
        harness = seat_model(config.load() if cfg is None else cfg, session["name"])[0]
        pane = pane_text(session) if harness else ""
        found = live_state(session, harness, pane=pane, cfg=cfg) if pane.strip() else {}
    except (config.Error, OSError):
        return None
    where = past(harness, pane, found) and seat_editor(session, cfg)   # most seats ask no editor
    try:
        alone = where and time.time() - os.stat(where["tty"]).st_atime >= DRAFT_STILL
    except OSError:
        return None
    read = alone and _editor_read(session, where, cfg)
    return where if read and past(*read) else None


def _line_through(session, where, held, mark, log, receipt, cfg=None, *, source="ak"):
    """Under the seat's send lock: the line in through ak's editor, which sets aside what else the
    composer holds (`aside_editor`), its Enter once the composer shows the line alone, and the
    text kept given back into the composer that Enter emptied, never into a question its turn
    put up there, whose own field the editor's keys open too.  `receipt` has the mark, with the
    pane, once the line is in; what is left undone is that mark's pass's (`_line_left`)."""
    text = mark["line"]
    if not (_send_line(session, text, log, lambda: receipt(dict(mark, pane=where["id"])),
                       source=source, put=lambda: _edit(session, where, "line", text) == "line")
            and _wait_ready(lambda name: composer_holds(name, session, text, cfg) == "line", held)):
        return False
    _send_enter(session, log)
    return (_wait_ready(lambda name: composer_holds(name, session, text, cfg) == "empty", held)
            and _editor_read(session, where, cfg)
            and _edit(session, where, "back", text) == "sent" and not pane_unread(session))


def _line_left(session, text, log, cfg, stale):
    """A mark's pass on a line ak's editor put in, on the pane it went into (`_line_through`):
    the line is that editor's to read, as the screen draws what it puts there late -- its Enter
    where it is still alone in the composer, and delivered once it has left, the text kept given
    back into the composer it left empty."""
    with seat_held(session["name"]) as held:
        where = not stale(held) and seat_editor(session, cfg)
        word = where and _editor_read(session, where, cfg) and _edit(session, where, "back", text)
        if word == "unsent":
            kept_asked_first(dict(session, name=held))
            _send_enter(session, log)
        return word == "sent" and not pane_unread(session)


def carry_draft(session, harness, pane, to, cfg=None):
    """Whether the owner's unsent text in that seat's composer is kept from a switch ending its
    harness, on any turn: lifted whole by ak's editor (its `line` step with no line) into its
    pane's kept buffer, which the respawn keeps with the pane and `drafts_back` hands the
    harness launched there next, or left there, set aside already for a line of ak's.  Not
    where the editor gives no answer, or finds text typed since that set aside, which no step
    merges.  Only through ak's editor, which reads a composer whole, and only to a harness
    (`to`) that opens it too: a screen draws a draft late, wrapped and cropped, and elsewhere
    the text would go with the old harness.  Not where the editor may not be asked a step now
    either (`_editor_read`): a picker drawn since, or input unread, would take its keys.
    Under the seat's lock its caller holds over the respawn too, so no tick hands the text back
    to the harness going; the pane is read again under it, as the caller's capture predates a
    paste or picker taken since."""
    pane = pane_text(session)
    # no keys to a question: they could answer it; nothing to keep in a composer read empty,
    # but a picker may draw it empty over the owner's text
    if not harness or asking(session["name"], harness, pane):
        return True
    if composer_draft(harness, pane) == "" and not (
            pane.strip() and _picker_up(harness, live_state(session, harness, pane=pane, cfg=cfg))):
        return True
    where = screen(to).get("editor") and seat_editor(session, cfg)
    return bool(where and _editor_read(session, where, cfg)
                and _edit(session, where, "line") in ("line", "unsent"))


def type_at_prompt(session, text, log, cfg=None, typed=None, receipt=lambda mark: None, *,
                   source="ak", stale=lambda held: False):
    """One line into a seat, and only while its harness sits at its own prompt.

    The prompt is tested twice: once here, and once more inside the send lock, because two
    runs ending together would both find the seat free and the second would then type into
    the turn the first had just started; and inside the lock, off that one capture, a composer
    that is not read empty -- holding any text, under a dialog, or unreadable -- gets no keys.  Only the first send is gated that way -- past it
    the line is already in the composer, and the seat working is what sending it did.

    A line goes into a composer once: a second copy is read twice, whether the first was taken
    or still waits for its Enter.  `receipt` is handed a mark the moment the text is in, for the
    ending's own record to keep until its delivery is recorded; given that mark back as `typed`,
    this only presses Enter, and only while the composer still holds the line alone -- read under
    the send lock, past any dialog -- and once that composer, read whole, is empty and the
    terminal reports no unread input, the seat has it.  A composer holding anything else, or
    one that cannot be read, says nothing yet: a line wrapped past the bottom rows still sits
    there.  A reopened seat is a new one, with an empty
    composer, and matches no mark.  `stale` is asked under the send lock
    too, with the name the seat goes by then, before each key: a line that has stopped being
    this seat's to have is typed no further.  Every Enter, the first, its retry and a mark's,
    goes only while the composer holds the line alone (`composer_holds`): what the owner typed
    in the gap before it is never sent.  The line is delivered only once its composer reads
    empty with no unread terminal input, the first pass's as a mark's: one the owner edited
    while its Enter was confirmed no longer reads whole there, and is still theirs to send.
    Text left standing in a seat launched with ak's editor holds none of it back: the line goes
    in through that editor, which sets the text aside and gives it back (`_past_text`), and a
    mark naming the pane it went into is that editor's to read (`_line_left`).
    No line goes in as keys while ak's editor keeps text of any pane of the seat's, which its
    composer can draw late, nor where tmux cannot say whether it does (`_editor_kept`).  Every
    read and key of a pass goes to the pane the seat showed as it began (`pinned`): a composer
    read empty is the one typed into, whichever pane the owner selects meanwhile.  A
    question the seat asked with
    `ak notify needs` holds none of this back: the seat works on what does not wait on the
    answer, which only the owner's own prompt gives (`notify.progress`).
    """
    session = pinned(session)
    text = terminal_mod.keyed(text)    # as `type_checked` types it: marks match
    mark = {"line": text, "seat": session.get("created")}
    if isinstance(typed, dict) and typed.get("pane") and typed == dict(mark, pane=typed["pane"]):
        return _line_left(dict(session, pane=typed["pane"]), text, log, cfg, stale)
    if typed == mark:
        with seat_held(session["name"]) as held:
            if stale(held):
                return False    # the screen is somebody else's: next pass
            holds = composer_holds(held, session, text, cfg)
            if holds == "empty":
                return not pane_unread(session)
            if holds == "line":
                kept_asked_first(dict(session, name=held))
                _send_enter(session, log)
        return False            # the next pass reads whether that Enter sent it
    where = _past_text(session, cfg)
    if where:
        with seat_held(session["name"]) as held:
            if stale(held) or _past_text(session, cfg) != where:
                return False
            kept_asked_first(dict(session, name=held))
            return _line_through(dict(session, name=held), where, held, mark, log, receipt, cfg,
                                 source=source)
    if not takes_line(session, cfg=cfg):
        return False
    composed = []

    def veto(held):
        if stale(held):
            return True
        if composed:
            return False        # the text is typed; what is left is the Enter that sends it
        composed.append(True)
        # text ak's editor keeps, or gave back, can be drawn late: only that editor reads it
        return not quiet_prompt(session, held, cfg) or _editor_kept(session) != {}

    return (type_checked(session, text, log, None,
                         guard=lambda: seat_held(session["name"]), veto=veto,
                         typed=lambda: receipt(mark), source=source,
                         ready=lambda held: composer_holds(held, session, text, cfg) == "line")
            and composer_holds(session["name"], session, text, cfg) == "empty"
            and not pane_unread(session))


def untyped(session, cfg=None):
    """What a look at that seat reads when no line went into it -- its state, what decided it, and
    its composer -- and whether it read at its prompt.  One read at its prompt that took no line
    contradicts itself, so its screen is kept (`refused-<seat>.txt`) for the cause to be read off
    it."""
    try:
        harness = seat_model(config.load() if cfg is None else cfg, session["name"])[0]
        pane = pane_text(session) if harness else ""
        found = live_state(session, harness, pane=pane, cfg=cfg) if pane.strip() else {}
    except (config.Error, OSError):
        found = {}
    if not found:
        return "its screen could not be read", False
    draft = composer_draft(harness, pane)
    # a turn its hook began goes on under a composer drawn empty, where the harness's spinner no
    # longer says what its working rule reads: that is no seat at its prompt
    turn = found.get("hooked") == "working" and found.get("state") != "working"
    said = (f"it reads {found.get('state')} by {found.get('rule') or 'nothing'}"
            + (f", its {found.get('hooked_event')} hook says its turn runs" if turn else "")
            + ", its composer "
            + ("empty" if draft == "" else "not found" if draft is None else "holding text"))
    if not _free(harness, found):
        return said, False
    try:
        path = config.seat_file("refused", session["name"])
        path.write_text(pane)
    except (OSError, config.Error):
        return said, True
    return f"{said}; its screen is kept in {path}", True


# --- a seat whose process died under its runs ------------------------------
# The seat comes back by itself, the way its number in the menu opens it, and is told what
# it missed: handback.announce does it for a run that finished under a gone seat, and the tick
# for a seat that dies while a run of its is still going.  The owner hears only when that
# fails, and never about a seat they ended themselves.

FRESH_NOTE = ("; this seat was started fresh because its earlier conversation could not be "
              "resumed")
HANDBACK_MAX_AGE = 3600   # an ending older than this when first seen is history, never replayed
ORPHAN_GRACE = 600        # a gone seat is reopened only when the run ended while it was alive
                          # or within ten minutes of its death
PREEXISTING_NOTE = "pre-existing ending; not replayed"
OWNER_CLOSED_REASON = "session closed by the owner"


def seat_stopped_at(name):
    """When the owner stopped that seat (`orch.cmd_stop`, `orch.mark_owner_closed`), or None:
    the mark in its state file, which a launch under the name clears again."""
    return seat_read(name).get("stopped_at") or None


def seat_closed(name):
    """Whether that seat stays gone: `ak orch stop` ended it, or nothing of it is left.

    The stop writes `stopped_at` into the seat's state file, and a launch under the name
    clears it again.  A seat with neither a pane nor a record was stopped, forgotten or never
    agentkit's to open: there is nothing to bring back, and the owner is asked as before.
    """
    if seat_stopped_at(name):
        return True
    return not orch.find(name) and not config.session_records().get(name)


def seat_closed_by_owner(name):
    """Whether the owner ended that seat on purpose: `x`, `ak orch stop` or a pause script.

    The mark lives beside `stopped_at` in the seat's state file, which the stop writes and a
    launch under the name clears again.  A hand-back for such a seat waits for the owner to
    reopen it; it never reopens the seat itself.
    """
    try:
        return bool(seat_read(name).get("closed_by_owner"))
    except (OSError, ValueError):
        return False


def ending_at(state):
    """When that run ended, or None where no ending date can be read."""
    for key in ("finished_at", "interrupted_at"):
        value = state.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def is_preexisting(state, now=None):
    """Whether that ending is history the tick must never replay.

    An ending that finished before the hand-back existed, or more than an hour before the tick
    first sees it without a mark, is not delivered: it is marked `handed_back` with the note,
    and nothing is typed or reopened for it.  A record with no date to age by is delivered: an
    interruption has no ending date by nature, and history always has one.
    """
    at = time.time() if now is None else now
    ended = ending_at(state)
    if ended is None:
        started = state.get("started_at")
        if isinstance(started, (int, float)) and not isinstance(started, bool):
            return at - float(started) > HANDBACK_MAX_AGE
        return False
    return at - ended > HANDBACK_MAX_AGE


def seat_died_at(name):
    """When that seat's process went, or None where nothing says.

    The retention stamp writes `exited_since` when it first sees the seat exited; where tmux
    holds no seat at all -- the orphan path's normal state, a reboot or a killed server -- the
    record's `seen` is the death proxy, as `orch.sweep` reads it.  Unknown means recent: only a
    known death older than the grace keeps a seat closed.
    """
    try:
        record = config.session_records().get(name) or {}
        died = record.get("exited_since")
        if isinstance(died, (int, float)) and not isinstance(died, bool):
            return float(died)
        if not orch.find(name):
            seen = record.get("seen")
            if isinstance(seen, (int, float)) and not isinstance(seen, bool):
                return float(seen)
    except (config.Error, OSError, ValueError):
        pass
    return None


def orphan_fresh(state, name, now=None):
    """Whether that run ended while the seat was alive or within ten minutes of its death.

    Only then is the orphan path a reopening: a run that ended long after its seat went is not
    brought back to life for it.  A death nothing recorded is no reason to keep it closed.
    """
    ended = ending_at(state)
    if ended is None:
        started = state.get("started_at")
        ended = float(started) if isinstance(started, (int, float)) and not isinstance(
            started, bool) else None
    if ended is None:
        return False
    died = seat_died_at(name)
    if died is None:
        return True
    return ended <= died + ORPHAN_GRACE


def sweep_preexisting(log, now=None):
    """Mark every unheard ending older than an hour as handed back, without replaying it.

    The first tick after the upgrade meets every historical ending unmarked, and a host whose
    tick was off for hours meets the endings it missed the same way: only endings younger than
    an hour are delivered when it comes back, and the older ones are marked here, in one log
    line with the count.  Nothing is typed and nothing is reopened.  An ending already seen --
    waiting for a closed or busy seat, or with a card still being retried -- is not history and
    is left alone.  Only a candidate takes the delivery lock, and re-verifies under it with the
    mark so nothing lands between them; every other directory costs one unlocked read.
    """
    at = time.time() if now is None else now
    try:
        dirs = run_record.run_dirs()
    except OSError:
        return 0
    marked = []
    for run_dir in dirs:
        try:
            state = run_record.read_state(run_dir)
        except (OSError, ValueError):
            continue
        if not state or not handback.owes_ending(state):
            continue
        if state.get("handback_pending") or state.get("notification_pending"):
            continue
        if not is_preexisting(state, at):
            continue
        try:
            with handback.delivery_lock(run_dir):
                current = run_record.read_state(run_dir) or state
                if not handback.owes_ending(current):
                    continue
                if current.get("handback_pending") or current.get("notification_pending"):
                    continue
                if not is_preexisting(current, at):
                    continue
                if handback.mark_delivery(run_dir, current, handed_back=at,
                                         handback_note=PREEXISTING_NOTE,
                                         handback_pending=None):
                    marked.append(run_dir.name)
        except (OSError, ValueError):
            continue
    if marked:
        names = ", ".join(sorted(marked))
        log(f"marked {len(marked)} pre-existing endings as handed back "
            f"without replaying ({PREEXISTING_NOTE}): {names}")
    return len(marked)


def revive(name, line, log, cfg=None, *, prepare):
    """Bring a gone seat back on its own conversation, and type one line into it.

    The way its number in the menu opens it: the saved conversation where the record holds
    one, and fresh where it does not -- then the line says so.  A seat just started gets
    INBOX_WARMUP before it is typed into, as the inbox does, and the line goes through the
    confirmed send, after `prepare` fits the final line to its composer. The answer is None
    when the seat was told, else why it was not, in a
    clause the owner's notice can end with.
    """
    try:
        back = orch.ensure(config.load() if cfg is None else cfg, name, log, saved=True)
    except (config.Error, OSError) as exc:
        return str(exc)
    if back == "fresh":
        line += FRESH_NOTE
    line = prepare(line)
    if back:
        time.sleep(INBOX_WARMUP)     # the TUI has to be listening before it is typed into
    if type_into(orch.find(name) or {"name": name}, line, log):
        return None
    return "the continue line was not confirmed sent"


def seat_subscription(cfg, provider, name):
    """The subscription of that provider the seat is on, or None where it lists none."""
    if not config.accounts(cfg, provider):
        return None
    return (config.session_records().get(name) or {}).get("account") or config.DEFAULT_ACCOUNT


def window_ends(cfg, provider, name):
    """When the spent window of the subscription that seat is on resets, or None when nothing
    says it is spent.  Its own: another subscription's room or deadline says nothing of it."""
    account = seat_subscription(cfg, provider, name)
    try:
        prov = usage.collect(cfg).get(provider) or {}
    except config.Error:
        return None
    if account is not None:
        prov = (prov.get("accounts") or {}).get(account) or {}
    ends = [meter.get("resets_at") for meter in prov.get("meters") or []
            if meter.get("exhausted") and isinstance(meter.get("resets_at"), (int, float))]
    return max(ends, default=None)


def stop_nudge(session, harness, pane, notice, records, dry_run, log):
    """The end-of-turn rule where no hook can hold it: a turn ends with a question asked through
    `ak notify needs`, a finished plan or a run or live job to wait on, and a seat that stopped on none
    of the three is told to get on with it.  A question mark on the screen asks nobody anything.
    An unnamed seat is told to name itself instead (`config.name_owed`).

    An unanswered question of this seat's own keeps it stopped. Otherwise the decision
    reads the plan and the runs and jobs.

    A run of its own parked and undecided holds the stop past a run going, an `ak wait` and a
    plan that owes nothing, as it holds the hook's.  A wait that is over is wait_over's to end, with
    the line saying what ended it: a bare keystroke typed first would take
    the prompt that line waits for, and leave the seat deciding without it.

    Every `continue` is a new turn, so the hook's two blocks a turn cannot be counted here: a
    seat is nudged at most PARKED_NUDGES times for the same parked run, and the next stop
    stands, as the hook's third does.  A run keeps its count when it is resumed and parks again,
    so runs taking turns buy no more; only a newer notice for the seat, answered or not, starts
    every count again.

    The episode is `turn_began` and the output that turn stopped on, both of them stop_marks'
    to say, so a footer that repainted is the same episode and the same words after another
    turn are a new one.  A seat with no turn marked at
    all has ended none where anything could see it -- it is sitting at the prompt its harness
    opened on, showing a banner and not an answer -- and the rule has nothing to hold it to,
    just as the hook has nothing to judge a stop by before the first prompt of a session.

    A composer typed into and cleared again begins no turn and ends none, so neither mark
    moves for it: the seat is at its prompt with the same words it finished on, and what the
    user did in the meantime is their business.

    Completion needs no stall timer. Nothing is typed on this pass's capture alone: the seat
    is read once more first, because a composer the user has begun typing into is theirs and
    a line appended to it would send what they are still writing. Errors remain with the
    health pass's recovery. One completion look at a time, including the tick's fallback.

    A turn the owner stopped (`interrupted`) is no stop at all: no hook runs on an Esc, and the
    seat rests until their next prompt (owner, 14 Oct 2026).
    """
    if not stop_enforced(harness):
        return
    with announcing(session["name"]):
        return _stop_nudge(session, harness, pane, notice, records, dry_run, log)


def _stop_nudge(session, harness, pane, notice, records, dry_run, log):
    from . import stop
    name = session["name"]
    live = seat_read(name)
    if (live.get("state") != "at_prompt" or live.get("interrupted") or records is None
            or live.get("closed_by_owner") or any(session.get(key) for key in orch.CLOSED)
            or session.get("legacy") or owner_question(notice)):
        return          # a failed pass over run.json is no evidence that nothing is running
    stood = _stamp(live.get("stop_said_at"))
    if stood is None:
        return
    tail = pane_tail(pane)
    if (auth_expired_on(harness, tail, name) or stuck_on(harness, tail, name)
            or stall_mark(harness, pane, name, lambda _: None)
            or (load_state()["stalls"].get(name) or {}).get("told")):
        return
    began = _stamp(live.get("turn_began"))
    if began is None:
        return          # nothing has watched this seat finish a turn; there is none to judge
    question = bool(notice and notice.get("kind") == "needs"
                    and (_stamp(notice.get("time")) or 0) >= began)
    said = progress_output(harness, pane_tail(pane))
    if not said or live.get("stop_nudged") == [began, said]:
        return
    wait = live.get("wait")
    if not question and isinstance(wait, dict) and wait.get("over") and not wait.get("told"):
        return      # its wait is over: wait_over says so, and why, before any continue
    ends, undecided = stop.recorded_ending(name, records, question=question)
    if ends:
        return
    parked = [directory.name for directory, _ in undecided]
    nudged = {}
    if parked:
        since = (notify.last(name, include_seen=True) or {}).get("time")
        kept = live.get("parked_nudged")
        if isinstance(kept, dict) and kept.get("notice") == since and isinstance(
                kept.get("runs"), dict):
            nudged = kept["runs"]
        if all(nudged.get(run, 0) >= PARKED_NUDGES for run in parked):
            return      # it has had its nudges for every run parked: this stop stands
        nudged = {"notice": since,
                  "runs": {**nudged, **{run: nudged.get(run, 0) + 1 for run in parked}}}
    tail = pane_tail(pane)
    keys = config.name_owed(name) or keystroke(harness, tail)
    if dry_run:
        log(f"would resume {name}, stopped with work open, no question and no run, with {keys!r}")
        return
    current = pane_text(session)
    # A prompt hook can precede the composer redraw: the turn must be over too.
    found = observed(name, harness, current, live, time.time()) if current.strip() else {}
    if (not _free(harness, found) or found.get("interrupted")
            or progress_output(harness, pane_tail(current)) != said):
        return          # it moved, or the seat is the user's again: neither is this rule's
    if type_into(session, keys, log):
        seat_write(name, stop_nudged=[began, said], **({"parked_nudged": nudged} if nudged else {}))
        log(f"{name}: stopped with work open, no question and no run; typed {keys!r}")
        return True


def _resume_on(cfg, name, log, account, continuing, still=None):
    """Resume that seat's conversation on `account`, told what the move cut (`reboot_line`)."""
    at, line = time.time(), reboot_line(cfg, name, bool(continuing))
    resumed = orch.resume(cfg, name, log=log, hand_over=False, account=account, still=still,
                          line=line)
    if line and resumed == "resumed":
        relaunched(name, seat_model(cfg, name)[0], line, at, account=True)


def between_turns(name, harness, record, opened_at, pane=None):
    """Is that seat, looked at afresh, the one `record` and `opened_at` were read for -- not
    closed, renamed, reopened or moved since -- with its harness's pane (`pane`, or the one a
    respawn would take) at its prompt with nothing in its composer, in no turn, asking nothing,
    and its terminal given no keys for DRAFT_STILL, none unread?  A capture that failed shows
    none of that, nor does a terminal that cannot be asked."""
    seat, now = orch.find(name), config.session_records().get(name) or {}
    if (not seat or any(seat.get(key) for key in orch.CLOSED) or seat_closed_by_owner(name)
            or any(now.get(key) != record.get(key)
                   for key in ("orchestrator", "conversation", "account"))
            or seat_read(name).get("opened_at") != opened_at):
        return False
    seat = dict(seat, pane=pane or orch.harness_pane(name, orch.seat_socket(seat)))
    rc, tty = orch.tmux_out("display-message", "-p", "-t", _pane(seat), "#{pane_tty}",
                            socket=orch.seat_socket(seat))
    try:
        # a key its harness took is drawn long before: the kernel dates a read to 8 seconds
        quiet = rc == 0 and time.time() - os.stat(tty).st_atime >= DRAFT_STILL
    except (OSError, ValueError):
        return False
    pane = pane_text(seat)
    fresh = observed(name, harness, pane, seat_read(name), time.time())
    return (quiet and bool(pane.strip()) and fresh["state"] == "at_prompt"
            and not _turn_in_flight(harness, fresh)[0] and not pane_unread(seat))


def seat_account(cfg, session, harness, provider, pane, dry_run, log):
    """Keep a seat on its model's usable subscriptions, preserving its live conversation.

    A seat's home is the account it opened on (the usual login for a record that names
    none), and an idle one comes home once it has room again. Without a proven conversation
    id the running pane is the only copy: wait for its own account, then continue in place.
    A closed pane is never a request to start a turn.
    """
    name = session["name"]
    record = config.session_records().get(name)
    if (not record or provider not in cfg.get("providers", {})
            or session.get("legacy") or any(session.get(key) for key in orch.CLOSED)
            or seat_closed_by_owner(name)):
        return False
    live = seat_read(name)
    if (live.get("midturn") or {}).get("account"):
        return True       # its resumed transcript may still show the previous account's refusal
    if live.get("state") == "asking":
        return True       # a respawn would lose it; an open question is ak's record and stays
    accounts = config.accounts(cfg, provider)
    current = record.get("account") or config.DEFAULT_ACCOUNT
    home = record.get("home_account") or config.DEFAULT_ACCOUNT
    model = record["orchestrator"]
    waiting = live.get("usage_wait")
    try:
        prov = (staffing._cached_providers() if dry_run else usage.collect(cfg)).get(provider) or {}
    except (config.Error, OSError) as exc:
        log(f"WARN {name}: could not read {provider} usage: {exc}")
        return True
    readings = (prov.get("accounts") or {}) if accounts else {current: prov}

    def spent(account):
        # Out of window and of credits: credits left still answer turns.
        return usage.model_exhausted(cfg, model, {provider: readings.get(account, {})})[0]

    def window(account):
        # Credits cost money, so a seat leaves them for a window that takes it.
        return not spent(account) and not usage.on_credits(
            cfg, model, {provider: readings.get(account, {})})

    def low(account):
        return usage.model_low(cfg, model, {provider: readings.get(account, {})})

    lines = content_lines(harness, pane_tail(pane))
    line = recorded_error(harness, name)
    if line is None:
        line = output_line(lines)
        # The pane and not the line: its colours say whose words they are.  What it ignores is
        # health()'s to log, as before.
        mark = stalled_on(harness, pane, name, lambda _: None) if line else None
        if mark:
            # A bare trailer (`Goal stalled`) is told apart, and dated, by the error line above it.
            line = error_said(harness, lines[:-1] + [line])
        outcome = failed_on(harness, [line])[0] if mark else None
        cue = line
    else:
        outcome = orch.harness_plugin(harness).failure(line)[0]
        # What starts it again is still the screen's to say: no record holds a goal's trailer.
        cue = error_said(harness, lines)
    refusal = outcome in (SPENT, LIMITED)
    if (not refusal and not waiting and live.get("state") in ("at_prompt", "draft")
            and not _turn_in_flight(harness, live)[0]):
        # A turn its harness wrapped up for the limit (`limit_ended`, its own note) refused
        # nothing, but its account is spent all the same, whatever the meters read yet.
        ended = limit_ended(harness, name)
        if ended:
            refusal, outcome, line = True, SPENT, f"wrap_up {ended}"
    now = time.time()
    observed = live.get("usage_refusal") or {}
    until = turns.try_again_at(line) if refusal else None
    handled = observed.get("line") == line and observed.get("handled")
    if handled and not waiting and not spent(current):
        return True       # a consumed refusal is still history when its transcript is redrawn
    if refusal and not waiting and not spent(current) and outcome == LIMITED:
        # A bare 429 has to stand before it counts; a spent window is acted on at once, so
        # the seat never sits at its prompt reading idle while it is out of usage.
        if observed.get("line") != line:
            if not dry_run:
                seat_write(name, usage_refusal={"line": line, "at": now})
            return True
        if now - observed["at"] < STALL_WAIT:
            return True
    elif not refusal and observed and not observed.get("handled") and not dry_run:
        seat_write(name, usage_refusal=None)
    if not waiting and not refusal and not spent(current):
        # An idle seat comes home once home has a window, and leaves credits for any window; a
        # turn the limit ended goes on there, though the meters may not show that limit yet.
        # One whose account runs low moves to one that does not, between turns, so no turn of
        # it is cut off when that account is spent; with every one low it spends its own, and
        # it comes home only to room it would not leave again at once.  None of it cuts off
        # background work: that waits until the account is spent (owner, 24 Oct 2026).
        moves = [a for a in orch.account_order(cfg, model, readings, home) if a != current
                 and window(a) and (not window(current) or not low(a)
                                    and (a == home or low(current)))]
        if (moves and live.get("state") == "at_prompt" and not held_work(hook_facts(name))
                and not _turn_in_flight(harness, live)[0]
                and orch.resumable(record)):
            if dry_run:
                log(f"would move {name} to {moves[0]}")
                return True
            target = next((a for a in moves
                           if orch.harness_plugin(harness).seat_auth(a)[0] is True), None)
            if target is None:
                return False
            def still(pane=None):
                # The last look, the old harness taking no keys from it on (the owner's choice
                # of 21 Oct 2026: a prompt from the phone in that instant may be lost), and
                # still holding no background work a turn ended on since the first.
                return (between_turns(name, harness, record, live.get("opened_at"), pane)
                        and not held_work(hook_facts(name)))
            with state_lock():
                if not still():
                    return True
                try:
                    _resume_on(cfg, name, log, target, limit_ended(harness, name), still)
                except (config.Error, OSError) as exc:
                    log(f"WARN {name}: {provider} account reopen failed: {exc}")
                    return True
                return True
        return False
    if dry_run:
        log(f"would recover {name} on a {provider} account with room, or wait for its reset")
        return True
    owned = orch.resumable(record)
    eligible = {a: readings[a] for a in (accounts or [current]) if a in readings
                and not spent(a) and (owned or a == current)
                and (a != current or waiting or not refusal)}
    # Keep the existing login when it has room again, or on its credits when no window takes
    # the seat. Probe only possible moves, in order, before the owner-action check: a slow
    # adapter must not undo a stop or typing.
    order = sorted(orch.account_order(cfg, model, eligible, home),
                   key=lambda a: (not window(a), a != current))
    target = next((a for a in order if a == current
                   or orch.harness_plugin(harness).seat_auth(a)[0] is True), None)
    with state_lock():
        # Slow meters must not undo a stop, rename, manual open or another launch.
        current_seat = orch.find(name)
        if (seat_closed_by_owner(name) or config.session_records().get(name) != record
                or seat_read(name).get("opened_at") != live.get("opened_at")
                or not current_seat or any(current_seat.get(key) for key in orch.CLOSED)
                or pane_text(current_seat) != pane):
            return True
        if refusal and not waiting and not spent(current):
            # The host may have slept through the deadline. Never replace that old
            # refusal with a new shared-cache park; retry it once in the existing pane.
            if until is not None and until <= now:
                if type_into(session, keystroke(harness, cue), log, asked=True):
                    seat_write(name, usage_refusal={"line": line, "at": now, "handled": True})
                return True
            # A bare 429/rate limit is not proof a subscription is empty. Retry the
            # stable error locally; only a spent window or deadline parks an account.
            if until is None and outcome == LIMITED:
                if observed.get("told") or owner_question(notify.last(name)):
                    return True     # a stall, and an open question is never a reason to type
                if now - observed["at"] >= GIVE_UP:
                    text = stuck_notice(name, harness)
                    if notify.shaped("needs", text, session=name,
                                     event_id=f"stall:{name}:{observed['at']}") == 0:
                        seat_write(name, usage_refusal={**observed, "told": now})
                elif now - observed.get("nudged_at", 0) >= NUDGE_EVERY:
                    if type_into(session, keystroke(harness, cue), log):
                        seat_write(name, usage_refusal={**observed, "nudged_at": now})
                return True
            until = usage.mark_exhausted(cfg, provider, until=until,
                                         account=current if accounts else None)
            readings[current] = {**readings.get(current, {}), "exhausted_until": until}
        if refusal:
            observed = {"line": line, "at": now, "handled": True}
            seat_write(name, usage_refusal=observed)
        # A turn begun since the wait and not refused is the owner's, answered by its account:
        # no limit cut it, so it is never continued, reopened under or typed into.
        flight, began = _turn_in_flight(harness, live)
        own_turn = (flight and not refusal and waiting is not None
                    and isinstance(began, (int, float)) and began > waiting["since"])
        continuing = bool((waiting or {}).get("continue") or refusal
                          or flight and not own_turn or limit_ended(harness, name))
        if target is not None:
            if own_turn:
                if target == current:
                    seat_write(name, usage_wait=None, usage_refusal=observed or None)
                return True       # a move to another account waits for that turn's end
            try:
                if owned:
                    # the owner's text lifted and the harness respawned in one hold, as a switch does;
                    # a move nobody asked for waits while no editor of ak's lifts it, or none could
                    with notify.session_lock(name):
                        if live.get("state") == "draft" and not (
                                seat_editor(session, cfg)
                                and carry_draft(session, harness, pane, harness, cfg)):
                            return True     # a respawn would lose the text
                        _resume_on(cfg, name, log, target, continuing)
                elif continuing and not type_into(session, keystroke(harness, cue), log,
                                                  asked=True):
                    return True
            except (config.Error, OSError) as exc:
                reason = f"{provider} account reopen failed: {exc}"
                if not waiting or waiting["reason"] != reason:
                    log(f"WARN {name}: {reason}")
                seat_write(name, usage_wait={"reason": reason,
                                            "since": waiting["since"] if waiting else now,
                                            "continue": continuing})
                return True
            seat_write(name, usage_wait=None, usage_refusal=observed or None)
            return True
        # Each account needs all of this model's spent windows back. Scoped meters
        # belonging to another model neither trigger a move nor postpone the reset.
        resets = []
        for account in (accounts or [current]) if owned else [current]:
            reading = readings.get(account, {})
            meters, _ = usage._gating_meters(cfg, model, {provider: reading})
            ends = [m.get("resets_at") for m in meters if m.get("used", 0) >= 100]
            ends.append(reading.get("exhausted_until"))
            ends = [end for end in ends if isinstance(end, (int, float)) and end > now]
            if ends:
                resets.append(max(ends))
        until = min(resets) if resets else (waiting or {}).get("until", 0)
        if until <= now:
            until = now + usage.DRY_FOR
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(until))
        reason = f"{provider} out of usage until {when}"
        if not waiting:
            log(f"{name}: {reason}")
        seat_write(name, usage_wait={"reason": reason, "until": until,
                                    "since": waiting["since"] if waiting else now,
                                    "continue": continuing})
        return True


def health(cfg, state, dry_run, log):
    """One pass over the toolkit's seats: nudge the stalled ones, leave the working ones be."""
    from . import menu as menu_mod   # here, not at the top: the menu draws without the tick
    poll_worker_token(state)   # each declared worker token, once a day: the ak screen says it
    stalls, seats = state["stalls"], orch.sessions()
    # one pass over run.json serves every live seat; a failed read is None, never a seat
    # with no runs
    try:
        records = menu_mod.run_records(cache=not dry_run)
    except (config.Error, OSError, ValueError):
        records = None
    # What each seat's runs are parked on, oldest first: the harness, when it parked and what
    # it said.  The seat that launched one has to read the login it waits for even when it
    # runs another harness itself, and the run being parked is the whole of the evidence --
    # `resume_waiting_login` is what asks the verb again, and what unparks it.
    parked_for = {}
    for _, record in records or ():
        if (record.get("state") != "waiting_login" or not record.get("waiting_for")
                or record.get("login_back_at")):
            continue        # back already: being resumed, and no login for anybody to fix
        try:
            owner = transitions.launched_session(record)
        except config.Error:
            owner = None
        if owner:
            parked_for.setdefault(owner, []).append(
                (record["waiting_for"], record.get("finished_at"), record.get("error") or ""))
    for held in parked_for.values():
        held.sort(key=lambda parked: parked[1] or 0)
    # Every harness an earlier pass recorded a `no` for, asked again every pass whether or not
    # a seat of theirs can be read this one: a login that came back has to clear itself off a
    # seat whose pane is blank, or that seat reports an expiry that ended hours ago for as
    # long as it exists.  A run parked on a login needs nobody to ask on its behalf -- being
    # parked is the whole evidence, and `resume_waiting_login` is what unparks it.
    answers = {}
    stale = {who for who, found in (state.get("auth_out") or {}).items()
             if isinstance(found, dict) and found.get("ok") is False}
    for who in sorted(stale):
        record_auth(state, who, answers=answers)
    # A failed capture or a resumable seat still owns its stop latch. A name with neither
    # a pane nor a session record is free again; tombstone it so stale saves cannot revive it.
    absent = set(stalls) - {seat["name"] for seat in seats}
    kept = (config.session_records() if dry_run else orch.records()) if absent else {}
    for gone in absent - set(kept):
        if dry_run:
            stalls.pop(gone)
        else:
            forget(gone, resolve=False, acknowledge=False)
            sync_seen(state, load_state())
    for session in seats:
        name = session["name"]
        harness, provider = seat_model(cfg, name)
        if not harness:
            continue        # a seat nothing here started
        # What this seat is, and its bar, are settled last -- after the login this pass
        # found or cleared and after the stall it recorded -- and on every path out of
        # the body below, including a capture that came back blank on a closed seat.
        live = {}
        try:
            if name in sync_seen(state, load_state()):
                continue
            if not dry_run:
                try:
                    orch.bind_pane(session)
                    renamed = follow_title(session, log)
                    if renamed:
                        session = dict(session, name=renamed)
                        continue    # rename moved the state this pass had read under the old name
                    sync_title(session, log)
                except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                    log(f"WARN {name}: title update did not finish: {exc}")
            # captured, read and written down under the lock every publisher takes, so a look
            # the seat's own hook makes meanwhile lands wholly before this one or after it
            with nullcontext() if dry_run else announcing(name):
                pane = pane_text(session)
                now = time.time()
                # A capture that came back blank is no screen to read: no stall to recover
                # from, no recovery from one, and nothing below the auth block runs on it.  The
                # auth block does, because a login is not the pane's to decide any more: a seat
                # whose harness is gone still has to stop saying a login expired once it has not.
                blank = not pane.strip()
                tail = pane_tail(pane)
                # the same capture answers both questions: what this seat is doing, on the one
                # classifier every render uses, and whether it has given up on its own error.
                # The gates below read this pass's answer and never the last one's.
                live = ({} if blank or dry_run or session.get("exited")
                        else live_state(session, harness, pane=pane, cfg=cfg))
                ask_kept_back(name, harness, live)
            at_prompt = (live or seat_read(name)).get("state") == "at_prompt"
            # Whether a login is expired is the `auth` verb's answer and never the pane's: a
            # pane showing that harness's own logout words is a trigger, and makes the verb
            # run again this pass rather than deciding anything itself.  That is the whole of
            # it -- the pane used to say `needs login` and `moving again` in turn all night,
            # once a minute, while the token stayed just as expired as it was.
            #
            # Two reasons to ask, then: a pane showing those words, and a seat already
            # carrying a login latch.  The second is what lets one an older watch.json wrote
            # -- back when the pane raised it, so there is no answer on record for it -- be
            # answered at all: without it the verb is never asked, the latch never clears,
            # and that seat keeps a card up and stays out of every recovery path for ever.
            signature = None if blank else auth_expired_on(harness, tail, name)
            if signature or stalls.get(name, {}).get("kind") == "auth":
                record_auth(state, harness, fresh=bool(signature), now=now, answers=answers)
            # And which login is out for this seat: its own harness, as the verb answered it,
            # else the one a run of its own parked on -- the same ladder `session_state`
            # climbs, so the card the tick sends and the word the row shows can never name
            # different harnesses.
            out = logged_out(harness, state.get("auth_out"))
            blocked, since, why = ((harness, out["at"], out["why"]) if out else
                                   (parked_for.get(name) or [(None, None, "")])[0])
            evidence = "verb" if out else "run"
            if not blank and not dry_run and not session.get("exited"):
                if notify.progress(name, lambda: progress_output(harness, pane_text(session)),
                                   harness):
                    forget(name, acknowledge=False)
                    sync_seen(state, load_state())
            entry = stalls.get(name, {})
            if blocked:
                with nullcontext() if dry_run else state_lock():
                    if name in sync_seen(state, load_state()):
                        continue
                    entry = stalls.get(name, {})
                    if entry.get("kind") != "auth" or entry.get("harness") != blocked:
                        entry = stalls[name] = {"kind": "auth", "harness": blocked,
                                                "since": since or now}
                    # what raised it, because what may retract it differs: see below
                    entry["evidence"] = evidence
                    entry["signature"] = signature or why
                    if not blank:
                        entry["pane"] = pane   # a blank capture replaces no screen it kept
                    if entry.get("told"):
                        continue
                    title, remedy, _ = auth_expiry(blocked)
                    text = (f"{name} ({title or blocked}) needs login: open the host, press this "
                            f"session's number, and {remedy or 'log in again'}.")
                    entry["notice"] = text
                    if dry_run:
                        log(f"would notify needs: {text}")
                    elif notify.shaped("needs", text, session=name,
                                       event_id=f"auth:{name}:{blocked}:{entry['since']}") == 0:
                        entry["told"] = now
                        log(f"{name}: {title or blocked} needs login; asked the user")
                    else:
                        log(f"WARN {name}: notification was not accepted; retry required")
                    if not dry_run:
                        _write_state(state)  # replace an older capacity stop latch before the next sync
                continue        # auth never reaches the capacity/resume path, even on delivery failure
            if entry.get("kind") == "auth":
                latched = entry.get("harness") or harness
                # A non-answer is not a yes: a latch a verb raised stands until that verb
                # says otherwise, so an adapter that is briefly unrunnable retracts nothing.
                # A latch a parked run raised has already had its answer -- nothing of this
                # seat's is parked on that login any more, which is the only thing that was
                # ever claimed.
                if (entry.get("evidence") != "run"
                        and not logged_in(latched, state.get("auth_out"))):
                    continue
                # every login this seat was blocked on passes again: the episode is over
                if dry_run:
                    stalls.pop(name)
                else:
                    forget(name, acknowledge=False, notice=entry.get("notice", ""))
                    sync_seen(state, load_state())
                log(f"{name}: {entry.get('harness') or harness} can authenticate again; "
                    "cleared needs login")
                entry = {}
            # Account recovery, like other capacity recovery, leaves closed seats alone.
            if seat_account(cfg, session, harness, provider, pane, dry_run, log):
                continue
            if blank:
                continue        # no screen: nothing below this can be decided on one
            if entry.get("kind") == "quiet" and (entry.get("pane") != pane or
                    session.get("legacy") or session.get("exited")
                    or not stuck_on(harness, tail, name)):
                if entry.get("told") and not dry_run:
                    forget(name, acknowledge=False, notice=entry.get("notice", stuck_notice(name, harness)))
                    sync_seen(state, load_state())  # a stale save must not restore the quiet latch
                else:
                    stalls.pop(name, None)
                entry = {}
            if session.get("legacy") or session.get("exited"):
                continue        # auth is read-only on these seats; no catch-all or capacity recovery
            notice = notify.last(name)
            if owner_question(notice):
                continue        # an unanswered owner decision is never a reason to type a resume
            if entry.get("told"):
                continue
            # Suspected auth takes the quiet escalation path even when `API Error` coexists.
            # Only verified auth messages get an immediate needs-login notice, but neither
            # known nor unknown logout wording can receive a capacity nudge.
            mark = stall_mark(harness, pane, name, log)
            if not mark:
                if entry.get("signature"):
                    log(f"{name}: moving again")
                if not stuck_on(harness, tail, name):
                    stalls.pop(name, None)
                    stop_nudge(session, harness, pane, notice, records, dry_run, log)
                    continue
                if entry.get("pane") != pane:
                    entry = stalls[name] = {"kind": "quiet", "pane": pane, "since": now}
                if now - entry["since"] >= GIVE_UP:
                    with nullcontext() if dry_run else state_lock():
                        if (name in sync_seen(state, load_state()) or
                                stalls.get(name, {}).get("told") or pane_text(session) != pane):
                            continue
                        text = stuck_notice(name, harness)
                        if at_prompt:
                            # nothing is running and the user has opened this seat since: it is
                            # sitting at its own prompt, which is not a seat stuck on anything
                            if not dry_run:
                                entry["told"] = now
                            log(f"{name}: no progress for an hour, but sitting at its own prompt; "
                                "the user is not asked")
                        elif dry_run:
                            log(f"would notify needs: {text}")
                        elif notify.shaped("needs", text, session=name,
                                           event_id=f"stuck:{name}:{entry['since']}") == 0:
                            entry["told"], entry["notice"] = now, text
                            log(f"{name}: no progress for an hour; asked the user")
                        else:
                            log(f"WARN {name}: notification was not accepted; retry required")
                continue
            if entry.get("kind") == "quiet":
                stalls.pop(name)
            entry = stalls.setdefault(name, {"since": now})
            observe(entry, pane, harness, now)
            entry["signature"] = mark
            stood = now - entry["since"]
            quiet = now - max(entry["stall_at"], entry["changed_at"])
            quota = failed_on(harness, content_lines(harness, tail), name)[0] in (SPENT, LIMITED)
            if not quota:
                for key in ("resets_at", "status", "reset_nudged_at"):
                    entry.pop(key, None)
            if quiet < STALL_WAIT:
                log(f"{name}: {mark} for {orch.span(quiet)}; nothing is typed until it has stood "
                    f"for {STALL_WAIT // 60} minutes")
                continue
            keys = keystroke(harness, tail)
            ends = entry.get("resets_at")
            throttled = (now - entry.get("nudged_at", 0) < NUDGE_EVERY or
                         bool(entry.get("reset_nudged_at")))
            # Read meters only for a possible nudge. A known window is already a decision:
            # wait on the persisted deadline, then resume once, without flushing usage every tick.
            if quota and not dry_run and ends is None and not throttled:
                ends = window_ends(cfg, provider, name)
                if ends and ends > now:
                    entry["resets_at"] = ends
            now = time.time()
            ends = entry.get("resets_at")
            if quota and ends and ends > now:
                entry["status"] = f"waiting until {time.strftime('%Y-%m-%d %H:%M', time.localtime(ends))}"
                log(f"{name}: {mark}; {entry['status']}")
                continue
            after_reset = quota and ends is not None and ends <= now
            # Re-read the lifecycle generation and pane after potentially slow meter I/O.
            # The same lock keeps a resolved stall from being recreated by a stale tick.
            with nullcontext() if dry_run else state_lock():
                if name in sync_seen(state, load_state()) or stalls.get(name, {}).get("told"):
                    continue
                notice = notify.last(name)
                if owner_question(notice):
                    continue    # a question may have arrived during slow meter I/O
                current = pane_text(session)
                if current != pane:
                    observe(entry, current, harness, time.time())
                    continue
                now = time.time()
                stood = now - entry["since"]
                if stood >= GIVE_UP and not after_reset:
                    # asked at its prompt too: an error that ends a turn leaves the harness at
                    # its composer, which says nothing of anyone having opened the seat
                    text = (f"{name} is stalled on {mark} for an hour and typing has not moved it; "
                            "open the host, press this session's number, and get it going again.")
                    if dry_run:
                        log(f"would notify needs: {text}")
                    else:
                        event_id = f"stall:{name}:{entry['since']}"
                        if notify.shaped("needs", text, session=name, event_id=event_id) != 0:
                            log(f"WARN {name}: notification was not accepted; retry required")
                            continue
                        entry["told"] = now
                    log(f"{name}: stalled on {mark} for {orch.span(stood)}; asked the user")
                    continue
                if ((entry.get("reset_nudged_at") and not after_reset) or
                        now - entry.get("nudged_at", 0) < NUDGE_EVERY):
                    continue
                if dry_run:
                    note = f" once the {provider} window has passed" if quota else ""
                    log(f"would resume {name}, stalled on {mark}, with {keys!r}{note}")
                elif type_into(session, keys, log):
                    entry["nudged_at"] = time.time()
                    if after_reset:
                        entry.update(since=now, reset_nudged_at=ends)
                        entry.pop("resets_at", None)
                        entry.pop("status", None)
                    log(f"{name}: stalled on {mark} for {orch.span(stood)}; typed {keys!r}")


        finally:
            if not dry_run:
                # decided on the seat's record as it stands under the lock, not on `live`: the
                # pass wrote its own look there, and a look the seat's own hook has published
                # since is newer -- and nothing captures the pane a second time
                announce_state(session, cfg=cfg,
                               harness=harness, auth_out=state.get("auth_out") or {},
                               gh_out=state.get("gh_out") or {},
                               token_out=state.get("worker_tokens"),
                               stalls=state["stalls"], records=records)


# --- silent runs: the tick recovers what the loop cannot --------------------
# A run that stood still for 18 hours is the shape this closes: its done-when gate deadlocked
# on its own background child, `run_done_when` has no limit, and `ak run` sat in round 1 until
# a person killed it. Limits inside the loop are the braces; this is the belt under them: the
# host's tick watches every run from outside and recovers a silent one whatever the loop is
# doing, so no single bug can halt the work again. Every rung is logged in the run's own
# log.txt and kept in its run.json `stalls` (time, round, step, action). The pass is bounded
# and never waits on a run: /proc reads have no subprocess to hang, TERM gives way to KILL
# after STALL_KILL_WAIT, resume is a detached Popen with no wait, typing and the one card
# carry their own timeouts -- and a pass that dies leaves the next one to act.
STALL_KILL_WAIT = 20      # TERM, then KILL after this many seconds; the next tick finishes


def stall_clock(run_dir, state):
    """When this run's silence began: its newest write, the thaw that restarted the clock, or
    the end of the transient wait its loop is sleeping out.

    A freeze stops every write a run could make, so the silence under one is the host's and
    not the run's; the clock starts again where the freeze was lifted, never where it began.
    A transient wait is the loop's own -- up to an hour at a time, on a provider that is down,
    writing nothing -- so the clock starts where that wait ends (`loop_wait`). A live loop
    waiting for another delivery's repository lock is silent for as long as that takes, so its
    clock starts now, every tick, until the wait is over.
    """
    until = loop_wait(state)
    if until == math.inf:
        return time.time()
    return max(run_last_write(run_dir), state.get("thawed_at") or 0, until)


def loop_wait(state):
    """Until when this run's own loop waits, else 0: the end of the transient wait it is
    sleeping out (`turns.transient_wait`), or `math.inf` while it waits for another delivery's
    repository lock.  Only the loop that recorded the wait is owed it: a resume after its death
    is a new loop, and its silence is its own."""
    delivery_wait = state.get("delivery_wait")
    if (delivery_wait and delivery_wait == state.get("pid") and state.get("state") == "running"
            and run_record.process_active(state)):
        return math.inf
    wait = state.get("transient_wait")
    return (wait.get("until") or 0) if (isinstance(wait, dict)
                                        and wait.get("pid") == state.get("pid")) else 0


def note_freeze(run_dir, frozen, now):
    """Pause this run's stall clock while the host holds it, and restart it at the thaw.

    Said once per run, in the run's own log, and to nobody else: a frozen host is the owner's
    own doing and a run waiting one out is neither stalled nor anything to be told about.
    Read again under the record's lock, so two ticks over one frozen run say it once between
    them, and neither writes over a run that has moved on.
    """
    with run_record.record(run_dir) as state:
        if state.get("state") != "running":
            return
        if frozen:
            if state.get("frozen_since"):
                return
            state["frozen_since"] = now
            stamp = time.strftime("%H:%M:%S", time.localtime(now))
            with (run_dir / "log.txt").open("a") as fh:
                fh.write(f"[{stamp}] host frozen since {stamp}; stall clock paused\n")
        else:
            state.pop("frozen_since", None)
            state["thawed_at"] = now


def run_last_write(run_dir, skip=(".lock", ".tmp")):
    """The newest write under the run directory: the run's last sign of life.  Locks and temp
    files are the tick's own bookkeeping, not the run's life; `skip` names what is not counted."""
    latest = 0.0
    try:
        for root, _, files in os.walk(run_dir):
            for name in files:
                if name.endswith(skip):
                    continue
                try:
                    stamp = Path(root, name).stat().st_mtime
                except OSError:
                    continue
                if stamp > latest:
                    latest = stamp
    except OSError:
        pass
    return latest


def _proc_table():
    """{pid: (ppid, state, cmdline)} from /proc; unavailable rows are skipped, never fatal."""
    table = {}
    try:
        pids = [entry for entry in os.listdir("/proc") if entry.isdigit()]
    except OSError:
        return table
    for entry in pids:
        pid = int(entry)
        stat = host.proc_stat(pid)
        if stat is None:
            continue
        try:
            raw = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
            args = [part for part in raw.split("\0") if part]
        except OSError:
            args = []
        table[pid] = (stat.ppid, stat.state, args)
    return table


def loop_children(pid):
    """The direct children of that pid as [(child pid, argv)]; [] where none can be read."""
    if not isinstance(pid, int) or pid <= 0:
        return []
    table = _proc_table()
    return [(child, args) for child, (ppid, _, args) in table.items() if ppid == pid]


def descendants(pid):
    """That pid and every process below it, children first; never the watcher's own tree."""
    if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
        return []
    table = _proc_table()
    if pid not in table:
        return []
    found, stack = [], [pid]
    while stack:
        current = stack.pop()
        if current in found or current == os.getpid():
            continue
        found.append(current)
        for child, (ppid, _, _) in table.items():
            if ppid == current and child not in found:
                stack.append(child)
    return found


def _gone(pid):
    """True where that pid no longer runs anything killable: gone, or a zombie reaped by init."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except OSError:
        return False
    stat = host.proc_stat(pid)
    return stat is not None and stat.exited


def kill_tree(pid, log=lambda _: None):
    """Stop that process tree: TERM to all of it, then KILL after STALL_KILL_WAIT.

    Bounded: polls at most STALL_KILL_WAIT for TERM, then briefly for KILL, and returns
    whether nothing killable is left -- a pass that dies leaves the next one to act.
    """
    tree = [p for p in descendants(pid) if p != os.getpid()]
    if not tree:
        return True
    for member in tree:
        try:
            os.kill(member, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + STALL_KILL_WAIT
    while time.monotonic() < deadline:
        if all(_gone(member) for member in tree):
            return True
        time.sleep(0.5)
    for member in tree:
        if not _gone(member):
            try:
                os.kill(member, signal.SIGKILL)
            except OSError:
                pass
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if all(_gone(member) for member in tree):
            return True
        time.sleep(0.2)
    left = [member for member in tree if not _gone(member)]
    if left:
        log(f"WARN {pid}: still alive after KILL: {left[:5]}; the next tick acts again")
    return not left


def stop_run_scope(state, log=lambda _: None):
    """Stop a run's scope, then whatever it missed by marker; old receipts keep tree cleanup."""
    scope = state.get("scope") if isinstance(state, dict) else None
    run_id = state.get("run_id") if isinstance(state, dict) else None
    stopped = bool(scope) and orch.stop_scope(scope, log)
    if run_id:
        worker.kill_marked(worker.run_marker(run_id), log=log)
    return stopped


def is_worker_cmd(args, cfg=None):
    """Is that direct child a worker turn (its harness's adapter) rather than the done-when gate?

    Only argv[0] -- the executable itself -- is read, never the command's text: a gate
    grepping its own logs or a test file named after a role must not read as a worker.
    The adapter script lives in an `adapters` directory and carries its harness's name,
    which config.toml supplies, so no harness is named here.
    """
    if not args:
        return False
    first = Path(str(args[0]))
    if first.parent.name.lower() == "adapters":
        return True
    name = first.name.lower()
    if not name or name in ("bash", "sh", "sleep", "flock", "env", "python3", "python"):
        return False
    if cfg is not None:
        try:
            harnesses = [entry.get("harness") for entry in cfg.get("models", {}).values()
                         if isinstance(entry, dict)]
        except AttributeError:
            harnesses = []
        return any(isinstance(harness, str) and harness and harness.lower() in name
                   for harness in harnesses)
    return False


def step_for_run(run_dir, state, pid, cfg=None):
    """(kind, step, child, argv) off the loop's own process tree.

    `worker` is an executor turn, `reviewer` a reviewer turn -- its out-dir argument carries
    `round-N/reviewer` -- and `done-when` the gate; `none` means the loop has no child.
    """
    children = loop_children(pid)
    if not children:
        return "none", "no child", None, []
    child, args = sorted(children, key=lambda pair: pair[0])[0]
    if is_worker_cmd(args, cfg):
        if any("/reviewer" in arg for arg in args):
            return "reviewer", f"reviewer: {state.get('reviewer') or 'reviewer'}", child, args
        return "worker", f"worker: {state.get('executor') or 'worker'}", child, args
    if len(args) >= 3 and Path(args[0]).name == "bash" and args[1] == "-c":
        cmd = args[2].strip()
    else:
        cmd = " ".join(args).strip() or "(unknown command)"
    return "done-when", f"done-when: {cmd[:200]}", child, args


def stall_allowance(state, kind, minutes):
    """Let the inner watchdog finish killing and recording before the tick intervenes.

    Its last observation can lag a write by one poll, and TERM cleanup takes
    KILL_GRACE. One more poll leaves room to record the stopped line. This margin
    applies even when the child just exited: a childless loop may still be logging.
    """
    cleanup = worker.KILL_GRACE + 2 * worker.ACTIVITY_POLL
    return state.get("silence_minutes", minutes) + cleanup / 60


def stall_line(minutes, rnd, step):
    return f"stall: no output for {minutes} min in round {rnd} ({step})"


def launch_resume(run_id, log=lambda _: None, verb="resume"):
    """`ak run resume <id>` in the background: detached, never waited on; its pid, or False.

    Into agentkit's slice, where every other agent process runs: a tick from cron would
    otherwise leave its resumes in the system's own cgroup, outside every limit the host has
    for the work.  `verb` starts `ak run merge <id>` the same way, for a job whose task's
    delivery is retried in the task's own scope rather than in the job's.  A record it cannot
    read starts nothing; one it cannot read once the child is started keeps that launch.
    """
    run_dir = config.RUNS / run_id
    from . import run as run_mod
    with run_record.recovery_lock(run_dir):
        receipt = run_record.read_state(run_dir)
        if receipt is None:
            log(f"WARN could not {verb} {run_id}: run.json cannot be read")
            return False
        if receipt.get("state") == "stopped":
            return False
        unit = f"agentkit-run-{run_id}"
        if (receipt.get("scope") and str(receipt["scope"]) != "none"
                and not str(receipt["scope"]).startswith("none (")):
            try:
                unit = orch.next_scope_unit(unit)
            except OSError as exc:
                log(f"WARN could not choose a scope for {run_id}: {exc}")
                return False
        placement = {}
        try:
            cap, properties = run_mod.run_scope_limits()
            # kept past a death: the reaper reads there whether the memory cap ended it, then stops it
            pid = orch.start_in_slice(
                [sys.executable, str(config.REPO / "bin" / "ak"), "run", verb, run_id],
                unit,
                {**config.child_env(), "AK_RUN_DEPTH": str(receipt.get("run_depth", 0))},
                run_dir / "log.txt", log, target_slice=orch.run_slice_name(),
                properties=properties,
                nice=True, placement=placement, ends=False)
        except OSError as exc:
            log(f"WARN could not {verb} {run_id}: {exc}")
            return False
        try:
            with run_record.record(run_dir) as state:
                state["scope"] = placement.get("scope")
                if placement.get("scope_reason"):
                    state["scope_reason"] = placement["scope_reason"]
                else:
                    state.pop("scope_reason", None)
                run_mod.remember_memory_cap(state, placement, cap)
        except run_record.Unreadable as exc:
            # the child owns the run now and its caller waits on it: only the scope goes unsaid
            log(f"WARN {run_id} was started, but its scope is not recorded: {exc}")
    return pid


def tell_parked(run_id, step, seat, log):
    """Tell the launching seat once, or send the one Discord card the rules allow; a run
    launched from no seat is one nothing else can move, so its owner is paged, the card's
    title naming how to resume it.

    True once the notice is delivered -- typed into a live seat, or accepted as a card.
    A refused card stays pending in `stalled_notified` and is retried on a later tick.
    """
    line = f"run {run_id} stalled three times at {step}; parked: ak run resume {run_id}"
    if seat:
        try:
            alive = handback.launcher_watched(seat)
        except (config.Error, OSError):
            alive = False
        if alive:
            found = orch.find(seat) or {"name": seat}
            try:
                run_dir = config.RUNS / run_id
                line = handback.seat_notice(
                    line, run_record.read_state(run_dir) or {}, run_dir,
                    f"run {run_id} stalled three times; parked.",
                    f"Resume: ak run resume {run_id}.")
                if type_into(found, line, log):
                    return True
            except (config.Error, OSError):
                pass
    event_id = f"stalled:{run_id}:{step}"[:200]
    if (notify.shaped("needs", line, session=seat, event_id=event_id) if seat
            else notify.page(event_id, f"ak run resume {run_id}", line)) == 0:
        return True
    log(f"WARN {run_id}: parking notice was not accepted; it stays pending for a later tick")
    return False


def note_stall(run_dir, state, entry, line):
    """Record one rung on the `record` the ladder holds: the entry first, then the log line, so
    the entry's time -- read back off the finished writes -- marks when the handling landed,
    not when it started."""
    state["stalls"] = [*(state.get("stalls") or []), entry]
    state.flush()
    with (run_dir / "log.txt").open("a") as fh:
        fh.write(f"[{time.strftime('%H:%M:%S')}] {line}\n")
    # the entry is the record's own, so the block's exit writes its time
    entry["time"] = run_last_write(run_dir) or entry["time"]


def _resume_ordered(state, now):
    """True while a resume this tick ordered is still the one to adopt the record."""
    at = state.get("stall_resume_at")
    return (isinstance(at, (int, float)) and not isinstance(at, bool)
            and 0 <= now - at < handback.STALL_RESUME_GRACE)


def _launch_grace(state, now):
    """A queued launch still inside the window where its pid may not be recorded yet."""
    if state.get("state") != "queued":
        return False
    if not (state.get("launch_pending") or not state.get("process_identity")):
        return False
    started = state.get("queued_at") or state.get("started_at") or 0
    if not isinstance(started, (int, float)) or isinstance(started, bool):
        return False
    return now - started < handback.QUEUED_GRACE


def _dead_parked(state):
    deaths = state.get("deaths") or []
    return bool(deaths) and isinstance(deaths[-1], dict) and deaths[-1].get("parked")


def _backoff_until(deaths):
    for death in reversed(deaths):
        if not isinstance(death, dict):
            continue
        at = death.get("resumed_at")
        if isinstance(at, (int, float)) and not isinstance(at, bool):
            return at + DEAD_BACKOFF
    return 0


def _dead_where(state, run_dir):
    """The role and round a dead loop was in, for the resume log line."""
    if state.get("state") == "queued" and state.get("slot_waiting"):
        role = "slot wait"
    else:
        role = state.get("step") or "executor"
    rnd = staffing.started_round(run_dir, state)
    return role, rnd if rnd else 1


def _dead_plan(state, run_dir, now):
    """What this tick does with a loop whose process is gone.

    `skip` is a resume already ordered. `wait` records a death and holds for the
    backoff. `park` is the third death inside an hour. `resume` continues now.
    """
    pid = state.get("pid")
    deaths = [death for death in (state.get("deaths") or []) if isinstance(death, dict)]
    last = deaths[-1] if deaths else None
    # A resume already ordered — by this pass or by the stall ladder — adopts the
    # record itself. Noticing the same dead pid again would launch a second loop.
    if _resume_ordered(state, now):
        return "skip", deaths, ""
    reaped = last and last.get("pid") == pid and not last.get("parked") and not last.get("resumed_at")
    # The hour runs to the death being judged, not to the tick judging it: a tick that gets
    # to a recorded death late must not age the first of three out of the window.
    upto = last.get("at") if reaped else now
    if not isinstance(upto, (int, float)) or isinstance(upto, bool):
        upto = now
    recent = [death for death in deaths
              if isinstance(death.get("at"), (int, float)) and not isinstance(death.get("at"), bool)
              and upto - death["at"] < DEAD_WINDOW]
    if reaped:
        # A reap noticed this death first and recorded it, so it is already among the recent:
        # the third inside the hour parks whoever noticed it.
        if len(recent) >= 3:
            return "park", [*deaths[:-1], {**last, "parked": True}], last.get("reason") or ""
        if now < _backoff_until(deaths):
            return "wait-quiet", deaths, last.get("reason") or ""
        return "resume-open", deaths, last.get("reason") or ""
    noticed = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    reason = f"loop process {pid} gone, noticed {noticed}"
    entry = {"at": now, "pid": pid, "reason": reason}
    if len(recent) >= 2:
        return "park", [*deaths, {**entry, "parked": True}], reason
    deaths = [*deaths, entry]
    previous = last.get("resumed_at") if last else None
    if (isinstance(previous, (int, float)) and not isinstance(previous, bool)
            and now - previous < DEAD_BACKOFF):
        return "wait", deaths, reason
    return "resume", deaths, reason


def _note_run(run_dir, line):
    try:
        with (run_dir / "log.txt").open("a") as fh:
            fh.write(f"[{time.strftime('%H:%M:%S')}] {line}\n")
    except OSError:
        pass


def _hold_live(state, deaths):
    """Record the death and keep the record live, exactly as this pass found it.

    A death the tick answers itself -- now, or after its backoff -- is not one a person
    revives: the reason is kept with the death, the seat goes on reading `working`, and no
    recovery card is sent for it. Any interruption stamp a reap left in between comes off
    with it, because a run about to go on is not interrupted work. A queued slot keeps its
    original `queued_at`.
    """
    state["state"] = "queued" if state.get("slot_waiting") else "running"
    for key in ("recovery_pending", "recovery_notified", "interrupted_at",
                "interruption_reason"):
        state.pop(key, None)
    state["deaths"] = deaths
    return state


def _arm_resume(state, deaths, now, role):
    """Hold the record live and stamp the order the resume this tick starts adopts it by.

    `stall_resume_at` is the order reap already understands, so the dead pid is not
    notified while its resume is on the way.
    """
    _hold_live(state, deaths)
    state.pop("resume_after", None)     # whatever backoff there was is over
    state["stall_resume_at"] = now
    state["resume_notice"] = {"at": now, "role": role, "restarted": False}
    return state


def resume_dead_loops(cfg=None, dry_run=False, log=print, now=None):
    """Resume a run whose loop is gone, in this tick, without a card.

    A `running` loop, or a queued launch past its grace, whose process is gone and
    that nobody stopped with `ak run stop`, continues where it stopped. The first
    death resumes at once. A death within ten minutes of that resume waits out the
    ten minutes. A third death inside an hour parks the run and the existing
    recovery notice speaks once. A launch still inside its grace, and a loop the
    stall ladder already ordered resumed, are left alone. A missing worktree is one
    WARN and an explicit resume.

    The seat stays `working`: the record is not left `interrupted` for the deaths
    this pass resumes, so no per-run card is sent for them.
    """
    now = time.time() if now is None else now
    for run_dir in run_record.run_dirs():
        try:
            state = run_record.read_state(run_dir)
            if not state:
                continue
            status = state.get("state")
            if status == "stopped" or status not in (*run_record.ACTIVE, "interrupted"):
                continue
            if status == "interrupted" and not (state.get("deaths") or []):
                # An interruption with no death recorded on it is not this pass's: a
                # failed launch, a worktree that went, an older record a person was told
                # about. Only a loop whose death was noticed -- here, or by the reap that
                # got to it first -- is one the tick carries on.
                continue
            if _dead_parked(state):
                continue
            if _launch_grace(state, now):
                continue
            if run_record.process_active(state):
                continue
            if handback.memory_cap_reason(state):
                # The kernel ended this scope on its own memory cap. That is a `fail` for
                # reap to conclude, with the cap in the reason: resuming a leak repeats it.
                continue
            wt = state.get("worktree")
            if not wt and not (status == "queued" and state.get("slot_waiting")):
                # Nothing to continue into: a launch that died before its workspace was
                # allocated is reap's to hand back. A slot wait has no workspace yet by
                # nature, and resuming one is resuming the wait itself.
                continue
            if wt and not Path(wt).is_dir():
                if state.get("dead_worktree_warned"):
                    continue
                if dry_run:
                    log(f"would leave {run_dir.name} alone: worktree {wt} is gone")
                    continue
                with run_record.record(run_dir) as state:
                    if not state.get("dead_worktree_warned"):
                        state["dead_worktree_warned"] = now
                log(f"WARN {run_dir.name}: worktree {wt} is gone; "
                    "leaving it for an explicit resume")
                continue
            role, rnd = _dead_where(state, run_dir)
            action, deaths, reason = _dead_plan(state, run_dir, now)
            if action == "skip":
                continue
            if dry_run:
                if action == "park":
                    log(f"would park {run_dir.name}: loop died ({reason})")
                elif action in ("resume", "resume-open"):
                    log(f"would resume {run_dir.name}: loop died ({reason}); "
                        f"continuing {role} of round {rnd}")
                elif action == "wait":
                    log(f"would wait to resume {run_dir.name}: loop died ({reason})")
                continue
            launch = False
            notice = False
            line = ""
            with run_record.record(run_dir) as state:
                if (state.get("state") == "stopped" or _dead_parked(state)
                        or _launch_grace(state, now) or run_record.process_active(state)):
                    continue
                action, deaths, reason = _dead_plan(state, run_dir, now)
                role, rnd = _dead_where(state, run_dir)
                if action == "skip" or action == "wait-quiet":
                    continue
                if action == "wait":
                    # The hold is on the record, not only in this pass's head: reap reads
                    # `resume_after` and leaves the dead pid alone until it passes, so the
                    # ten quiet minutes are quiet whoever looks during them.
                    _hold_live(state, deaths)
                    state["resume_after"] = _backoff_until(deaths)
                    line = (f"waiting to resume {run_dir.name}: loop died ({reason}); "
                            "next try after 10 min")
                elif action == "park":
                    transitions.interrupt(state, reason)
                    state["deaths"] = deaths
                    state.pop("resume_after", None)
                    notice = True
                    line = (f"parked {run_dir.name}: loop died ({reason}); "
                            "third death within an hour")
                elif action in ("resume", "resume-open"):
                    deaths[-1]["resumed_at"] = now
                    _arm_resume(state, deaths, now, role)
                    launch = True
                    line = (f"resumed {run_dir.name}: loop died ({reason}); "
                            f"continuing {role} of round {rnd}")
            if line:
                _note_run(run_dir, line)
                log(line)
            if notice:
                handback.notify_recovery(run_dir, run_record.read_state(run_dir) or state)
            if launch:
                launch_resume(run_dir.name, log)
        except run_record.StopRequested:
            continue
        except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            try:
                log(f"WARN cannot resume {run_dir.name}: {exc}")
            except (OSError, ValueError):
                pass


def resume_dead_jobs(dry_run=False, log=print, now=None):
    """Relaunch a job whose launcher is gone, where `job.job_admission` lets the tick.

    A job's launcher schedules its tasks, so without it the waiting ones never start: the
    dead-loop pass only carries the running one on, as a lone run.  The relaunch is the one
    `ak run resume <job>` makes -- finished tasks keep their result, a running one is
    adopted where it stands -- in the job's own scope and for its own seat.  After the
    dead-loop pass, so the run it adopts is already on its way.
    """
    from . import job as jobs
    now = time.time() if now is None else now
    for job_dir in jobs.job_dirs():
        try:
            job = jobs.read_job(job_dir)
            if (not job or not isinstance(job.get("tasks"), list)
                    or jobs.reap_job(job_dir, job)
                    or all(task.get("state") in jobs.JOB_TERMINAL for task in job["tasks"])):
                continue
            admission = jobs.job_admission(job_dir, job, now=now)
            if not admission:
                continue
            if dry_run:
                log(f"would relaunch job {job_dir.name}: launcher gone; {admission}")
                continue
            with redirect_stdout(io.StringIO()):
                jobs.spawn_job_bg(job_dir, relaunch=job)
            line = f"relaunched job {job_dir.name}: launcher gone; {admission}"
            _note_run(job_dir, line)
            log(line)
        except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            log(f"WARN cannot relaunch job {job_dir.name}: {exc}")


def recover_runs(cfg=None, dry_run=False, log=print, now=None):
    """One bounded pass over silent runs: detect from outside the loop, climb the ladder.

    Every `running` run silent past its recorded silence limit is handled by rung -- the step's
    tree, then the loop with a resume, then parking -- and every parked run whose notice
    was refused gets its one notice retried. Nothing else is touched.
    """
    from . import run as run_mod
    now = time.time() if now is None else now
    if cfg is None:
        try:
            cfg = config.load()
        except config.Error as exc:
            log(f"WARN the stall pass did not run: {exc}")
            return
    for run_dir in run_record.run_dirs():
        try:
            state = run_record.read_state(run_dir)
            if not state:
                continue
            if state.get("state") == "queued" and state.get("slot_waiting"):
                if run_record.process_active(state) or _resume_ordered(state, now):
                    continue
                if dry_run:
                    log(f"would restart the slot waiter for {run_dir.name}")
                else:
                    # spawn_bg checks the receipt again under the recovery lock. Two ticks,
                    # or a manual resume beside one, can never both adopt this waiter.
                    with redirect_stdout(io.StringIO()):
                        run_mod.spawn_bg(run_dir, ["resume", run_dir.name], expected=state)
                    log(f"restarted the slot waiter for {run_dir.name}")
                continue
            if state.get("state") == "stalled" and not state.get("stalled_notified"):
                if dry_run:
                    log(f"would notify the parking of {run_dir.name} again")
                    continue
                with run_record.record(run_dir) as state:
                    if state.get("state") != "stalled" or state.get("stalled_notified"):
                        continue
                    last = (state.get("stalls") or [{}])[-1]
                    try:
                        seat = transitions.launched_session(state)
                    except config.Error:
                        seat = None
                    if tell_parked(run_dir.name, last.get("step") or "the run",
                                   seat, log):
                        state["stalled_notified"] = True
                continue
            if state.get("state") != "running":
                continue
            # A dead loop whose resume is already ordered is the dead-loop pass's, or
            # the stall ladder's own order from earlier in this tick. Measuring its
            # silence would launch a second resume on top of the one still adopting.
            if _resume_ordered(state, now) and not run_record.process_active(state):
                continue
            # Read before the silence is measured, and every tick: a freeze that begins and
            # ends between two ticks is still the host's, and a clock that only stopped once a
            # run looked stalled would have counted it.  Only the run's own process is asked --
            # a pid the kernel has handed to somebody else says nothing about this run.
            frozen = (host.frozen_cgroup(state.get("pid")) if run_record.process_active(state)
                      else None)
            if frozen or state.get("frozen_since"):
                # The stall rules never act on a run the host is holding, and the silence a
                # freeze made is not counted against it: the clock starts again at the thaw,
                # which leaves this pass -- and the one after the thaw -- with nothing to do.
                if dry_run:
                    log(f"would pause the stall clock of {run_dir.name}: {frozen}" if frozen
                        else f"would restart the stall clock of {run_dir.name} at the thaw")
                    continue
                note_freeze(run_dir, frozen, now)
                continue
            minutes = turns.stall_minutes_for(run_dir, state)
            silent = now - stall_clock(run_dir, state)
            if silent < minutes * 60:
                continue
            resume_after_lock = False
            with run_record.record(run_dir) as state:
                if state.get("state") != "running":
                    continue
                pid = state.get("pid")
                alive = run_record.process_active(state)
                if not alive:
                    kind, step, target, argv = "none", "loop gone", None, []
                else:
                    kind, step, target, argv = step_for_run(run_dir, state, pid, cfg)
                    if kind == "none":
                        step = "no child"
                allowance = stall_allowance(state, kind, minutes)
                if now - stall_clock(run_dir, state) < allowance * 60:
                    continue
                rnd = len(state.get("round_summaries") or []) + 1
                stalls = list(state.get("stalls") or [])
                line = stall_line(turns.stall_minutes_for(run_dir, state), rnd, step)
                if dry_run:
                    rung = "park" if len(stalls) >= 2 else (
                        "resume" if len(stalls) >= 1 or kind == "none" else "kill the step")
                    log(f"would {rung} {run_dir.name}, silent for {orch.span(silent)}: {line}")
                    continue
                if len(stalls) >= 2:
                    if alive:
                        if not stop_run_scope(state, log):
                            kill_tree(pid, log)
                    entry = {"time": now, "round": rnd, "step": step, "action": "parked"}
                    handback.park_stalled(run_dir, state, entry)
                    with (run_dir / "log.txt").open("a") as fh:
                        fh.write(f"[{time.strftime('%H:%M:%S')}] {line}; parked as stalled\n")
                    entry["time"] = run_last_write(run_dir) or entry["time"]
                    state["stalls"] = [*(state.get("stalls") or [])[:-1], entry]
                    try:
                        seat = transitions.launched_session(state)
                    except config.Error:
                        seat = None
                    if tell_parked(run_dir.name, step, seat, log):
                        state["stalled_notified"] = True
                    log(f"{run_dir.name}: {line}; parked as stalled")
                elif len(stalls) >= 1 or kind == "none":
                    if alive:
                        if not stop_run_scope(state, log):
                            kill_tree(pid, log)
                    action = "resumed"
                    if kind == "worker":
                        # A stuck reviewer is the loop's own fallback to replace, not the
                        # executor: only a worker turn hands over.
                        try:
                            new = staffing.handover_executor(
                                state, cfg, "stalled", log=lambda line: _note_run(run_dir, line))
                        except (config.Error, OSError, ValueError, KeyError, TypeError,
                                AttributeError):
                            new = None
                        action = f"resumed with handover to {new}" if new else "resumed"
                    entry = {"time": now, "round": rnd, "step": step, "action": action}
                    # reap leaves this killed loop alone; the resume below adopts it
                    state["stall_resume_at"] = now
                    note_stall(run_dir, state, entry, f"{line}; {action}")
                    resume_after_lock = True
                    log(f"{run_dir.name}: {line}; {action}")
                else:
                    current = dict(loop_children(pid)) if alive else {}
                    if (target is not None and current.get(target) == argv
                            and target != os.getpid()):
                        kill_tree(target, log)
                        action = "killed step"
                    else:
                        action = "step already gone"
                    note_stall(run_dir, state, {"time": now, "round": rnd, "step": step,
                                                "action": action}, line)
                    log(f"{run_dir.name}: {line}")
            if resume_after_lock:
                launch_resume(run_dir.name, log)
        except run_record.StopRequested:
            continue  # a stop landed mid-pass; the deliberate end stands, nothing to check
        except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            try:
                log(f"WARN cannot check run {run_dir.name}: {exc}")
            except (OSError, ValueError):
                pass


def resume_waiting_login(dry_run=False, log=print, now=None):
    """Resume `waiting_login` runs whose harness can authenticate again, silently.

    The road an `exhausted` run takes when its window refills, for the other thing a run
    parks on: `ak run resume <id> --bg`, detached, never waited on, at most once per
    RESUME_EVERY per run, and never a word to anybody -- the run parked itself and picks
    itself up.  Nothing is handed over and nothing is re-picked: the work was never at
    fault, so it goes on in the same worktree, the same round and the same conversation.
    A run whose worktree is gone is left for an explicit resume, with one WARN.
    """
    from . import run as run_mod
    now = time.time() if now is None else now
    answers = {}
    for run_dir in run_record.run_dirs():
        try:
            state = run_record.read_state(run_dir)
            if not state or state.get("state") != "waiting_login":
                continue
            harness = state.get("waiting_for")
            if harness not in answers:
                # a `yes` and nothing else: an adapter that could not answer is not a login
                # coming back, and restarting work on one would spend a turn on a wall
                answers[harness] = worker.auth_ok(harness)[0] is True if harness else False
            if not answers[harness]:
                # Still logged out, and the row says which login it waits for.  Whatever an
                # earlier pass left on the record about a login being back, and about pacing
                # the launch it tried, belongs to an episode that is over: the mark comes off
                # or this run goes on reading `waiting to resume` while its seat reads
                # `working` and nobody is told the login went out again, and the pacing stamp
                # comes off with it or the next recovery would sit out a window that was
                # timed against the last one.  Written only where there is something to take
                # off, so an ordinary outage costs the same nothing it always did.
                if state.get("login_back_at") or state.get("login_resume_at"):
                    with run_record.record(run_dir) as state:
                        if state.get("state") == "waiting_login":
                            state.pop("login_resume_at", None)
                            if state.pop("login_back_at", None) is not None:
                                log(f"{run_dir.name}: the {harness} login went out again")
                continue
            with run_record.record(run_dir) as state:
                if state.get("state") != "waiting_login":
                    continue
                # The login is back, and that goes on the record before anything below can
                # skip this pass.  Only the launch is paced; what the run and its seat say is
                # not, and a run waiting out a window must never go on reporting a login that
                # is no longer expired.
                if not state.get("login_back_at") and not dry_run:
                    state["login_back_at"] = now
                last = state.get("login_resume_at")
                if (isinstance(last, (int, float)) and not isinstance(last, bool)
                        and 0 <= now - last < RESUME_EVERY):
                    continue    # a recent launch is still on its way, or a failure is throttled
                wt = state.get("worktree")
                if not wt or not Path(wt).is_dir():
                    if dry_run:
                        log(f"would interrupt {run_dir.name}: the {harness} login is back "
                            f"but its worktree {wt or '(none)'} is gone")
                        continue
                    # The login is back and the work is not.  This run waits for no login any
                    # more, and leaving it saying so would send the owner to `/login` for a
                    # worktree nothing there can restore: it is an interruption, which is the
                    # state that names its own reason and offers its own number.
                    reason = (f"The {harness} login is back, but this run's worktree "
                              f"{wt or '(none)'} is gone; it cannot be resumed where it "
                              "stopped.")
                    for key in ("waiting_for", "login_resume_at", "login_back_at"):
                        state.pop(key, None)   # it waits on no login, so it marks none
                    transitions.interrupt(state, reason)
                    log(f"WARN {run_dir.name}: {reason}")
                    continue
                if dry_run:
                    log(f"would resume {run_dir.name}: {harness} can authenticate again")
                    continue
                # the stamp lands before the child owns the run: spawn_bg only adopts a
                # record that still reads exactly like this one, and puts it back when the
                # launch never starts: retried on a later tick, never written after the fact.
                # `login_back_at` said the wait was over before the pacing above could skip
                # this pass, so nothing goes on telling the owner to log in to something he
                # already has, whatever happens to the launch now.
                state["login_resume_at"] = now
            decided = dict(state)
            try:
                with redirect_stdout(io.StringIO()):
                    run_mod.spawn_bg(run_dir, ["resume", run_dir.name], expected=decided,
                                     park_as=True)
            except (config.Error, OSError) as exc:
                log(f"WARN could not resume {run_dir.name}: {exc}")
                continue
            log(f"resumed {run_dir.name}: the {harness} login is back")
        except run_record.StopRequested:
            continue  # a stop landed mid-pass; the deliberate end stands, nothing to check
        except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            try:
                log(f"WARN cannot check run {run_dir.name}: {exc}")
            except (OSError, ValueError):
                pass


def resume_exhausted(cfg=None, providers=None, workers=None, dry_run=False, log=print,
                     now=None):
    """Resume `exhausted` runs whose window refilled or whose reviewer is back, silently.

    Every run in state `exhausted` is checked against the usage providers the tick
    already read: a run whose worktree is gone is left for an explicit resume, with a
    WARN, however dry every provider is; a run whose worktree still exists is resumed
    when an eligible worker can execute again -- in the pick order, budget above
    zero, not marked exhausted-until -- or, off a dead reviewer, when an eligible
    reviewer can review again.  The resume is the one the command runs
    (`ak run resume <id> --bg`, detached, never waited on), handing over to that
    worker when the saved executor is still dry.  One log line per resume:
    `resumed <id>: <provider> window refilled`.  Retry metadata goes on disk before
    the child owns the run, so a start that fails is retried on a later tick -- at
    most once per RESUME_EVERY per run, as a WARN -- and a run whose resume never
    started stays `exhausted`: still waiting, still silent, never a notification.
    A transport resume that fails again waits out the hour like an error before the
    next one, so a dead reviewer costs reviewer turns by the hour, not by the tick.
    A run a later merged run replaced is stood down, marked `replaced`, never
    resumed: its work is done, elsewhere, and no wait survives on it.
    """
    from . import menu as menu_mod, run as run_mod
    now = time.time() if now is None else now
    if cfg is None:
        try:
            cfg = config.load()
        except config.Error as exc:
            log(f"WARN the exhausted-resume pass did not run: {exc}")
            return
    if providers is None:
        try:
            providers = usage.collect(cfg)
        except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            log(f"WARN the exhausted-resume pass did not run: {exc}")
            return
    asked = False
    if workers is None:
        try:
            workers = config.workers(cfg)
        except (config.Error, KeyError, TypeError, AttributeError) as exc:
            log(f"WARN the exhausted-resume pass did not run: {exc}")
            return
    found = [(run_dir, run_record.read_state(run_dir)) for run_dir in run_record.run_dirs()]
    index = transitions.supersession_index(
        state for run_dir, state in found if state and not menu_mod.smoke_run(state))
    for run_dir, state in found:
        try:
            if not state or state.get("state") != "exhausted":
                continue
            # a quota run waits on a window; a run off a dead reviewer waits on a reviewer
            # being eligible again.  Anything else exhausted waits on nobody by itself, and
            # `transitions.going` reads the same test, so it keeps no seat working either.
            waits = transitions.exhausted_wait(state)
            if not waits:
                continue  # only a run waiting on a window or a reviewer is tick-resumable
            transport = waits == "reviewer"
            if not asked:
                # every pick below gives a role, so each harness is asked whether it can run:
                # once a pass, and only when a run waits on a pick, never on an empty tick
                providers, asked = usage.readiness(cfg, providers), True
            bound, review_bound = config.role_groups(
                cfg, staffing.run_workers(cfg, state), state.get("reviewers"))
            bound = bound if bound is not None else workers
            review_bound = review_bound if review_bound is not None else bound
            # one line per worker the pick leaves out, for the run's own log -- written only
            # when this pass resumes it, so a run waiting through tick after tick gets none
            skipped = []
            available = staffing.executable_models(cfg, providers, bound, now, skipped.append,
                                                 reviewers=review_bound)
            with run_record.record(run_dir) as state:
                if state.get("state") != "exhausted":
                    continue
                waits = transitions.exhausted_wait(state)
                if not waits:
                    continue
                if transitions.is_superseded(state, None, index, merged_only=True):
                    # a later merged run did the work: the tick stands down, marked
                    # `replaced`, so `going` stops reading a wait nothing will lift
                    if not dry_run and not state.get("replaced"):
                        state["replaced"] = True
                    continue
                transport = waits == "reviewer"
                last = state.get("exhausted_resume_at")
                if (isinstance(last, (int, float)) and not isinstance(last, bool)
                        and 0 <= now - last < RESUME_EVERY):
                    continue  # a recent launch is still on its way, or a failure still throttled
                retry = state.get("refusal_retry")
                retry_model = retry.get("model") if isinstance(retry, dict) else None
                retry_at = retry.get("at") if isinstance(retry, dict) else None
                retry_waiting = (isinstance(retry_model, str)
                                 and isinstance(retry_at, (int, float))
                                 and now < retry_at)
                wt = state.get("worktree")
                if not wt or not Path(wt).is_dir():
                    if dry_run:
                        log(f"would leave {run_dir.name} alone: worktree {wt or '(none)'} "
                            f"is gone")
                        continue
                    if last is None:
                        # one WARN for the life of the missing worktree, not one per
                        # pass: the stamp below stays put so later ticks stay silent.
                        state["exhausted_resume_at"] = now
                        log(f"WARN {run_dir.name} is exhausted but its worktree "
                            f"{wt or '(none)'} is gone; leaving it for an explicit resume")
                    continue
                saved = state.get("executor")
                # a PR review runs no executor, and a run whose review is pending has its
                # executor's work done: its reviewer is all either waits for
                if transport or state.get("review_pr") or state.get("review_pending"):
                    if (transport and isinstance(last, (int, float)) and not isinstance(last, bool)
                            and 0 <= now - last < transitions.ERROR_RETRY_CAP):
                        continue  # re-resumed within the hour: a dead reviewer gets an
                        # hour like an error, not a reviewer turn every ten minutes
                    reviewers = staffing.reviewable_models(cfg, providers, review_bound, now,
                                                          executor=saved)
                    if not reviewers:
                        continue  # no reviewer is eligible yet; the run keeps waiting, silently
                    # the executor, if any, never died, so it stays: the resume re-picks the
                    # reviewer, which is the one this run waited for.
                    chosen, why = saved, f"reviewer {reviewers[0][0]} eligible again"
                    reviewer = None
                else:
                    candidates = ([pair for pair in available if pair[0] != retry_model]
                                  if retry_waiting else available)
                    if not candidates:
                        continue  # every eligible provider is still dry or is the waiting refuser
                    kept = next(((n, p) for n, p in candidates if n == saved), None)
                    if kept is not None:
                        chosen, provider = kept
                        reviewer = None          # a kept executor keeps its pair as it is
                    else:
                        # A handover re-picks both roles as one pair (`staffing.best_pair`):
                        # keeping the reviewer would force a dearer executor on the run.
                        # Nothing resumes until a legal pair exists; a run with none left
                        # stays parked and waits for one.
                        review_order = staffing.ready_order(cfg, providers, review_bound,
                                                           role="reviewer", quiet=True)
                        pair = staffing.best_pair(cfg, [n for n, _ in candidates],
                                                 review_order)
                        if pair is None:
                            chosen, provider, reviewer = None, None, None
                        else:
                            chosen, reviewer = pair
                            provider = next(p for n, p in candidates if n == chosen)
                    if not chosen:
                        continue
                    why = f"{provider} window refilled"
                if dry_run:
                    log(f"would resume {run_dir.name}: {why}")
                    continue
                for line in skipped:
                    _note_run(run_dir, line)
                if chosen != saved:
                    state.setdefault("executor_history", []).append(
                        {"at": now, "from": saved, "to": chosen, "reason": "dry"})
                    state["executor"], state["exec_session"] = chosen, None
                if reviewer and reviewer != state.get("reviewer"):
                    state["reviewer"], state["review_session"] = reviewer, None
                # Consume the one-shot refusal deadline before the child owns the run.  The
                # stamp still travels into the queued receipt, so nothing is written after launch.
                state.pop("refusal_retry", None)
                state["exhausted_resume_at"] = now
            decided = dict(state)
            try:
                with redirect_stdout(io.StringIO()):
                    run_mod.spawn_bg(run_dir, ["resume", run_dir.name], expected=decided,
                                     park_as=True)
            except (config.Error, OSError) as exc:
                log(f"WARN could not resume {run_dir.name}: {exc}")
                continue
            log(f"resumed {run_dir.name}: {why}")
        except run_record.StopRequested:
            continue  # a stop landed mid-pass; the deliberate end stands, nothing to check
        except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            try:
                log(f"WARN cannot check run {run_dir.name}: {exc}")
            except (OSError, ValueError):
                pass


def resume_errored(dry_run=False, log=print, now=None):
    """Retry errors the seat still waits on, with the loop's transient ladder.

    Every resumable run in state `error` carries its next retry on its record --
    stamped when the run ended, on the rungs of a worker turn's own retries,
    then hourly.  A run the stamp says is due is resumed the way the
    command resumes it (`ak run resume <id> --bg`, detached, never waited on),
    and the rung climbs before the child owns the run, so a start that fails is
    retried on a later tick at the next rung up -- and a run whose resume never
    started stays `error`: still waiting, still silent, never a notification.

    Only a resumable error is scheduled at all: a worktree still there, the keys
    a resume replays, a task that still parses, and no job of its own to settle it.
    Anything else was never stamped, or loses its stamp here with one WARN, and
    reads parked for a person.
    A handed-back, carded or acknowledged ending, one at least a day old, or one
    with no launch session still on record loses its stamp and waits for a person.
    An error a later merged run replaced is retried never: its retry stamps go the
    way an inadmissible ending's do, and with them the wait they kept.
    """
    from . import menu as menu_mod, run as run_mod
    now = time.time() if now is None else now
    found = [(run_dir, run_record.read_state(run_dir)) for run_dir in run_record.run_dirs()]
    index = transitions.supersession_index(
        state for run_dir, state in found if state and not menu_mod.smoke_run(state))
    for run_dir, state in found:
        try:
            if not state or state.get("state") != "error":
                continue
            with run_record.record(run_dir) as state:
                if state.get("state") != "error":
                    continue
                if transitions.is_superseded(state, None, index, merged_only=True):
                    # a later merged run did the work: the stamps go, as an
                    # inadmissible ending's do, so `going` ends with them
                    if not dry_run and ("error_retry_at" in state
                                        or "error_retries" in state):
                        state.pop("error_retry_at", None)
                        state.pop("error_retries", None)
                    continue
                reason = ("cannot be resumed where it stopped"
                          if not transitions.error_resumable(state, run_dir) else
                          "ending is no longer admitted for automatic retry"
                          if not transitions.tick_admission(state, now=now) else None)
                if reason:
                    if "error_retry_at" in state or "error_retries" in state:
                        if dry_run:
                            log(f"would leave {run_dir.name} parked for a person: {reason}")
                        else:
                            state.pop("error_retry_at", None)
                            state.pop("error_retries", None)
                            log(f"WARN {run_dir.name}: {reason}; leaving it parked for a person")
                    continue
                at = state.get("error_retry_at")
                if dry_run:
                    if not (isinstance(at, (int, float)) and not isinstance(at, bool)):
                        log(f"would schedule {run_dir.name}: error retry")
                    elif now >= at:
                        log(f"would resume {run_dir.name}: error retry due")
                    continue
                if not (isinstance(at, (int, float)) and not isinstance(at, bool)):
                    # an old record, from before errors were scheduled: no rung
                    # survives without its hour, so the ladder starts at the bottom.
                    transitions.schedule_error_retry(state, now=now)
                    at = state["error_retry_at"]
                if now < at:
                    continue  # the ladder has not run out yet; a later tick fires it
                retries = state.get("error_retries")
                retries = retries if isinstance(retries, int) and not isinstance(
                    retries, bool) and retries >= 0 else 0
                state["error_retries"] = retries + 1
                transitions.schedule_error_retry(state, now=now)
            decided = dict(state)
            try:
                with redirect_stdout(io.StringIO()):
                    run_mod.spawn_bg(run_dir, ["resume", run_dir.name], expected=decided,
                                     park_as=True)
            except (config.Error, OSError) as exc:
                log(f"WARN could not resume {run_dir.name}: {exc}")
                continue
            log(f"resumed {run_dir.name}: error retry {decided.get('error_retries')}")
        except run_record.StopRequested:
            continue  # a stop landed mid-pass; the deliberate end stands, nothing to check
        except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            try:
                log(f"WARN cannot check run {run_dir.name}: {exc}")
            except (OSError, ValueError):
                pass


def resume_waiting(dry_run=False, log=print, now=None, run=None):
    """Park rebase-conflict FAILs as `waiting`, and resume them after main moves.

    A FAIL whose merge note is a rebase conflict, with rounds still to spend, is
    no verdict on the work: the branch tripped over main, and main keeps moving.
    The tick parks it `waiting` on its upstream at the sha a fetch reads now, and
    resumes it -- the command's own resume, detached, never waited on -- on the
    first pass that reads another sha there, or, for a run parked on a red target,
    that finds the run repairing it no longer holding that sha (`repair_open`).  A
    fetch that fails, or a ref that will not parse, is not a move: the waiter keeps
    waiting, silently.  A
    worktree that is gone cannot be resumed at all, so that run becomes an
    interruption naming what is really wrong, the way a login run's does.  A
    conflict FAIL at its budget stays a FAIL: more rounds are the owner's
    decision, never the tick's.  A run already parked by the merge step resumes
    regardless of its task budget: conflict rounds spend no task round.
    Every wait must still pass admission before a fetch or resume: waits left by
    an older tick do not keep permission after a telling, a lost seat or a day.
    A landing-line member belongs to the lander, so this pass leaves it alone.
    A dry run names what it would park and resume, and fetches nothing: a fetch
    moves the very refs it reports on.  A job's run is its job's: the tick's pass
    leaves it, and the job's own ladder passes it as `run` to resume its wait.
    """
    from . import land, run as run_mod
    now = time.time() if now is None else now
    lines = set()
    for run_dir in [run] if run else run_record.run_dirs():
        try:
            state = run_record.read_state(run_dir)
            if not state or state.get("state") not in ("fail", "waiting"):
                continue
            if name := transitions.landing_line(state):
                if name not in lines:
                    lines.add(name)
                    if dry_run:
                        log(f"would start lander for {name}")
                    else:
                        land.start_line(config.RUNS / name, log)
                continue    # saved verdicts also retry a wake that never started
            if state.get("job_id") and not run:
                continue
            if state.get("state") == "fail" and not transitions.parkable_conflict(
                    state, run_dir, now=now):
                continue
            if state.get("state") == "waiting":
                if not transitions.tick_admission(state, now=now):
                    continue
                wt = state.get("worktree")
                if not wt or not Path(wt).is_dir():
                    if dry_run:
                        log(f"would interrupt {run_dir.name}: waiting on a merge, but its "
                            f"worktree {wt or '(none)'} is gone")
                        continue
                    with run_record.record(run_dir) as state:
                        if (state.get("state") != "waiting"
                                or transitions.landing_line(state)
                                or not transitions.tick_admission(state, now=now)):
                            continue
                        wt = state.get("worktree")
                        if wt and Path(wt).is_dir():
                            continue  # back while the pass looked; the wait stands
                        reason = ("this run's worktree "
                                  f"{wt or '(none)'} is gone; it cannot be resumed where it "
                                  "stopped.")
                        transitions.interrupt(state, reason)
                    log(f"WARN {run_dir.name}: {reason}")
                    continue
                last = state.get("waiting_resume_at")
                if (not dry_run and isinstance(last, (int, float))
                        and not isinstance(last, bool) and 0 <= now - last < RESUME_EVERY):
                    continue  # a recent launch is still on its way, or a failure is throttled
                ref = (state.get("waiting_on") or {}).get("ref") or transitions.conflict_upstream(
                    state)
                if dry_run:
                    log(f"would resume {run_dir.name} after the next merge to {ref}")
                    continue
                sha = transitions.upstream_sha(wt, ref)
                if sha is None:
                    continue  # origin did not answer; the waiter keeps waiting, silently
                with run_record.record(run_dir) as state:
                    if (state.get("state") != "waiting"
                            or transitions.landing_line(state)
                            or not transitions.tick_admission(state, now=now)):
                        continue
                    waiting_on = state.get("waiting_on") or {}
                    if not waiting_on.get("sha"):
                        # no baseline to move from: this pass takes one, and the next
                        # merge after it, or the repair it names letting go, resumes the run.
                        waiting_on = {**waiting_on, "ref": ref, "sha": sha}
                        state["waiting_on"] = waiting_on
                        log(f"{run_dir.name} waits on {ref} at {sha[:12]}")
                        continue
                    repair = waiting_on.get("repair")
                    if sha != waiting_on.get("sha"):
                        why = f"{ref} moved ({(waiting_on.get('sha') or '')[:12]}..{sha[:12]})"
                    elif repair and not handback.repair_open(
                            run_record.read_state(config.RUNS / repair) or {}, sha):
                        why = f"its repair {repair} ended"
                    else:
                        continue  # main has not moved; the waiter keeps waiting, silently
                    state["waiting_resume_at"] = now
                decided = dict(state)
            else:
                ref = transitions.conflict_upstream(state)
                if dry_run:
                    log(f"would park {run_dir.name} waiting on {ref}")
                    continue
                wt = state.get("worktree")
                sha = transitions.upstream_sha(wt, ref)
                if sha is None:
                    continue  # origin did not answer; the FAIL keeps for the next pass
                with run_record.record(run_dir) as state:
                    if state.get("state") != "fail" or not transitions.parkable_conflict(
                            state, run_dir, now=now):
                        continue
                    state.update(state="waiting", error=state.get("merge_note"),
                                 waiting_on={"ref": ref, "sha": sha})
                    state.pop("recovery_pending", None)  # the wait is the tick's now
                    # a telling still pending is superseded with it: nothing delivers a
                    # hand-back for a waiting run, so the mark would only ever overcount
                    # the seat's hand-backs waiting
                    state.pop("handback_pending", None)
                    state.pop("handback_wait_reason", None)
                    state.pop("waiting_resume_at", None)  # a new wait paces its own launch
                log(f"parked {run_dir.name} waiting on {ref} at {sha[:12]}")
                continue
            try:
                # a job's threads share its stdout: swapping it would swallow their lines
                with nullcontext() if run else redirect_stdout(io.StringIO()):
                    run_mod.spawn_bg(run_dir, ["resume", run_dir.name], expected=decided,
                                     park_as=True)
            except (config.Error, OSError) as exc:
                log(f"WARN could not resume {run_dir.name}: {exc}")
                continue
            log(f"resumed {run_dir.name}: {why}")
        except run_record.StopRequested:
            continue  # a stop landed mid-pass; the deliberate end stands, nothing to check
        except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            try:
                log(f"WARN cannot check run {run_dir.name}: {exc}")
            except (OSError, ValueError):
                pass


def revive_seats(cfg, log):
    """Bring back a seat whose harness died while a run it launched is still going.

    A seat the listing shows exited, restarting or resumable -- its process gone, however it
    went -- with a run of its own still running or queued is reopened on its saved
    conversation and told the run is still going.  Once per death: `reopened_at` in the seat's
    state file, written before the launch so one that fails is not repeated every tick, and
    cleared when the seat is next seen live.  A seat the owner stopped stays stopped.  The
    owner hears only when the reopen fails.  tmux is asked only with something to do: a run
    going, or a marker to clear.  Every tick files a seat with no project from the run records
    read here (`orch.file_projectless`), a run going or not.
    """
    going, states = {}, []
    for run_dir in run_record.run_dirs():
        state = run_record.read_state(run_dir)
        if state:
            states.append(state)
        if not state or state.get("state") not in run_record.ACTIVE:
            continue
        try:
            seat = transitions.launched_session(state)
        except config.Error:
            continue
        if seat:
            going.setdefault(seat, (run_dir, state))
    kept = config.session_records()
    orch.file_projectless([{**record, "name": name} for name, record in kept.items()], states)
    if not going and not any(seat_read(name).get("reopened_at") for name in kept):
        return
    for session in orch.listing():
        name = session["name"]
        marks = seat_read(name)
        if not any(session.get(key) for key in ("exited", "restart", "resumable")):
            if marks.get("reopened_at"):
                seat_write(name, reopened_at=None)   # live again: the next death is a new one
            continue
        if (name not in going or marks.get("reopened_at") or seat_closed(name)
                or marks.get("closed_by_owner")):
            continue
        run_dir, state = going[name]
        run_id, title = run_dir.name, state.get("title") or run_dir.name
        died = time.time()
        seat_write(name, reopened_at=died)
        why = revive(name, f"continue: your run {run_id} ({title}) is still going; "
                           "pick up where you left off", log, cfg,
                     prepare=lambda line: handback.seat_notice(
                         line, state, run_dir, f"run {run_id} is still going.",
                         "Pick up where you left off."))
        if why is None:
            log(f"reopened {name} and asked it to continue {run_id}")
            continue
        text = (f"Its orchestrator session {name} is gone while run {run_id} ({title}) is "
                f"still going. agentkit tried to reopen the seat and could not: {why}. "
                f"Press its number in the menu, then say: continue {title}.")
        if notify.shaped("needs", text, session=name,
                         event_id=f"revive:{name}:{run_id}:{int(died)}") == 0:
            log(f"could not reopen {name}; asked the user to continue {run_id}")
        else:
            log(f"WARN {name}: notification was not accepted; retry required")


def wants_github(state):
    """Does that run still owe GitHub something a logged-out `gh` would refuse?

    Two shapes.  A run still going that has a delivery ahead of it: it ends at `git push` and
    `gh pr create`, unless it is a scratch workspace or `--no-merge`, which push nothing --
    except a `--review-pr` run, which pushes nothing either but cannot post its review.  A
    launch settles that in its preflight, before it waits for a slot, because only the process
    that launched it can resolve the repository a task inherits when it names none; a receipt
    written before preflight did -- or by an install that did not -- still has the options it
    was launched with, which is how `ak run resume` reads one, and one so old it saved no
    options at all keeps its work local.  And a run already finished whose
    delivery is the thing that failed, waiting on `ak run merge`: that is what
    `handback.retry_command` answers, so the menu and `ak run status` cannot disagree about which
    runs are still owed a push.
    """
    if state.get("state") in run_record.ACTIVE:
        if state.get("review_pr"):
            return True
        if "no_merge" in state:
            return not state["no_merge"]
        return not (state.get("launch_opts") or {"--no-merge": True}).get("--no-merge")
    return handback.retry_command(state) is not None


def pushing_seats():
    """The seats a logged-out `gh` is holding up, by the name each goes by now: one with a run
    that still owes GitHub a push, and one whose wait names a pull request only gh can read.

    No run.json can stop the tick from writing down the rest: a receipt half-written by a
    launch that is still starting, or one somebody edited by hand, counts for nobody.
    """
    seats = set()
    try:
        directories = run_record.run_dirs()
    except OSError:
        return []
    for run_dir in directories:
        try:
            state = run_record.read_state(run_dir)
            if state and wants_github(state):
                name = transitions.launched_session(state)
                if name:
                    seats.add(name)
        except (config.Error, OSError, TypeError, ValueError, AttributeError, KeyError):
            continue    # an unreadable run says nothing about whose seat it was
    for name in config.session_records():
        wait = waiting_on(name)
        if wait and wait["kind"] == "pr":
            seats.add(name)
    return sorted(seats)


def gh_json(cwd, *args, timeout=120):
    """The parsed JSON a gh command prints, or (None, why)."""
    try:
        proc = subprocess.run(["gh", *args], cwd=str(cwd if cwd.is_dir() else config.REPO), capture_output=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              stdin=subprocess.DEVNULL,
                              env={**config.child_env(), "GIT_TERMINAL_PROMPT": "0",
                                   "GH_PROMPT_DISABLED": "1"})
    except subprocess.TimeoutExpired:
        return None, "gh timed out"
    except OSError as exc:
        return None, f"gh: {exc}"
    if proc.returncode != 0:
        return None, (proc.stdout + proc.stderr).strip()[:300]
    try:
        data = config.json_pages(proc.stdout) if "--paginate" in args else json.loads(proc.stdout)
        return data, ""
    except ValueError as exc:
        return None, f"gh printed no JSON ({exc})"


def checkouts():
    if not config.CODE.is_dir():
        return []
    return sorted(d for d in config.CODE.iterdir() if (d / ".git").exists())


def pages(cwd, endpoint, key=None):
    """Flatten REST array pages or a search response's items arrays."""
    data, why = gh_json(cwd, "api", "--paginate", endpoint)
    if isinstance(data, list) and key:
        data = [page.get(key) if isinstance(page, dict) else None for page in data]
    if not isinstance(data, list) or any(not isinstance(page, list) for page in data):
        return None, why or "gh did not return arrays of pages"
    return [item for page in data for item in page], ""


def reviewed_on_github(url, sha, me):
    """Did this account already post an agentkit review of that head?  For a lost state file."""
    data, _ = gh_json(config.RUNS, "pr", "view", url, "--json", "reviews")
    for review in (data or {}).get("reviews") or []:
        if (isinstance(review, dict) and (review.get("author") or {}).get("login") == me
                and MARKER in (review.get("body") or "")
                and (review.get("commit") or {}).get("oid") == sha):
            return True
    return False


def settled(entry, dry_run=False):
    """What became of the review run an entry names: `done`, `pending` or `failed`.

    Recording a launch is not recording a review.  The run may have died on the provider, on
    the checkout, or on posting; only a run that ended with its review on GitHub settles the
    head.  An entry with no run came from a review found on GitHub, which is settled by nature.
    """
    if not entry.get("run"):
        return "failed" if entry.get("error") else "done"
    run_dir = config.RUNS / entry["run"]
    st = run_record.read_state(run_dir)
    if st is None:
        return "failed"
    if dry_run:
        if st.get("state") in run_record.ACTIVE and not run_record.process_active(st):
            return "pending"  # interruption requires an explicit recovery choice
    else:
        st = handback.reap(run_dir, st)
    if st.get("state") in run_record.ACTIVE or transitions.needs_recovery(st):
        return "pending"
    if st.get("state") == "stopped":
        return "done"  # deliberately ended: never relaunched, whatever the head does
    if (st.get("state") in ("pass", "fail") and st.get("review_posted")
            and not st.get("review_stale")
            and (not entry.get("sha") or st.get("head_sha") == entry["sha"])):
        return "done"
    return "failed"


def launch(url):
    """`ak run --review-pr <url> --bg`; the run id it printed."""
    proc = subprocess.run([sys.executable, str(config.REPO / "bin" / "ak"), "run",
                           "--review-pr", url, "--bg"], capture_output=True, encoding="utf-8",
                          errors="replace", env=config.child_env())
    if proc.returncode != 0:
        raise config.Error(f"ak run --review-pr {url} --bg exited {proc.returncode}: "
                           f"{(proc.stdout + proc.stderr).strip()[-300:]}")
    lines = proc.stdout.splitlines()
    for line in reversed(lines):
        if line.endswith("/result.md"):
            return line.rsplit("/", 2)[-2]
    raise config.Error(f"ak run --review-pr {url} --bg printed no result path")


def incoming(state, me, dry_run, log):
    """Other people's open PRs on this account's repos: review each head once."""
    for repo in checkouts():
        info, why = gh_json(repo, "repo", "view", "--json", "nameWithOwner,owner")
        if not isinstance(info, dict) or not info.get("nameWithOwner"):
            log(f"skip {repo.name}: {why or 'not a GitHub repo'}")
            continue
        if (info.get("owner") or {}).get("login") != me:
            continue
        prs, why = pages(repo, f"repos/{info['nameWithOwner']}/pulls?state=open&per_page=100")
        if not isinstance(prs, list):
            log(f"WARN {info['nameWithOwner']}: PR discovery failed: {why}")
            continue
        for pr in prs:
            author = (pr.get("user") or {}).get("login") or "?"
            url, sha = pr.get("html_url"), (pr.get("head") or {}).get("sha")
            if not url or not sha or author == me or pr.get("draft"):
                continue
            what = f"{url} (#{pr.get('number')} by {author}: {pr.get('title')}) at {sha[:12]}"
            seen = state["reviewed"].get(url)
            attempts = 0
            if seen and seen.get("sha") == sha:
                fate = settled(seen, dry_run)
                if fate != "failed":
                    continue
                attempts = seen.get("attempts") or 1
                if reviewed_on_github(url, sha, me):
                    state["reviewed"][url] = {"sha": sha, "run": None, "at": time.time()}
                    continue
                delay = RETRY_BACKOFF[min(attempts - 1, len(RETRY_BACKOFF) - 1)]
                retry_at = seen.setdefault("retry_at", time.time() + delay)
                seen.pop("gave_up", None)  # recover entries written by older installs too
                if time.time() < retry_at:
                    log(f"retry {what} after {time.strftime('%H:%M', time.localtime(retry_at))}")
                    continue
                log(f"WARN the review run {seen.get('run')} for {what} did not finish; launching again")
            elif reviewed_on_github(url, sha, me):
                state["reviewed"][url] = {"sha": sha, "run": None, "at": time.time()}
                continue
            if dry_run:
                log(f"would review {what}")
                continue
            try:
                run_id = launch(url)
            except config.Error as exc:
                log(f"WARN {exc}")
                state["reviewed"][url] = {"sha": sha, "run": None, "at": time.time(),
                                          "attempts": attempts + 1, "error": str(exc),
                                          "retry_at": time.time() + RETRY_BACKOFF[
                                              min(attempts, len(RETRY_BACKOFF) - 1)]}
                continue
            state["reviewed"][url] = {"sha": sha, "run": run_id, "at": time.time(),
                                      "attempts": attempts + 1}
            log(f"review {what} -> {run_id}")


def own_prs(state, me, log):
    """{url: session} for this account's open PRs on repos it does not own.

    Three sources: the runs that opened a PR from a fork (they know which seat to answer to),
    GitHub itself for the ones the user opened by hand, and what was being followed already --
    a PR that has since closed is no longer in the search, and its ending is exactly the news.
    """
    urls = {}
    for run_dir in run_record.run_dirs():
        st = run_record.read_state(run_dir)
        if st and st.get("foreign") and st.get("pr"):
            urls[st["pr"]] = transitions.launched_session(st)
    # /issues?filter=created omits repositories we do not belong to. Search includes PRs
    # opened by hand on those repositories, as well as ones opened by our own runs.
    found, why = pages(config.RUNS, "search/issues?q=is:pr+is:open+author:@me&per_page=100", "items")
    if isinstance(found, list):
        for pr in found:
            url = (pr.get("pull_request") or {}).get("html_url")
            owner = urlsplit(url or "").path.strip("/").split("/")[0]
            if url and owner and owner.lower() != me.lower():
                urls.setdefault(url, None)
    else:
        log(f"WARN authored PR discovery failed: {why}")
    for url, own in state["own"].items():
        if not own.get("done"):
            urls.setdefault(url, own.get("session"))
    return urls


def outgoing(state, me, dry_run, log):
    """This account's PRs on other people's repos: hand on what the maintainer decided, once."""
    for url, session in own_prs(state, me, log).items():
        own = state["own"].setdefault(url, {"decision": None, "done": False})
        if own.get("done"):
            continue
        if session:
            own["session"] = session
        view, why = gh_json(config.RUNS, "pr", "view", url, "--json",
                            "state,reviewDecision,title,number")
        if not isinstance(view, dict):
            log(f"WARN {url}: gh pr view failed: {why}")
            continue
        label = f"PR #{view.get('number')} {view.get('title')}"
        if view.get("state") == "MERGED":
            if say(dry_run, log, f"{label}: merged by the maintainer", url, session, merged=True):
                own["done"] = True
        elif view.get("state") == "CLOSED":
            if say(dry_run, log, f"{label}: closed by the maintainer without a merge", url,
                   session):
                own["done"] = True
        elif (view.get("reviewDecision") == "CHANGES_REQUESTED"
              and own.get("decision") != "CHANGES_REQUESTED"):
            if say(dry_run, log, f"{label}: the maintainer requested changes", url, session):
                own["decision"] = "CHANGES_REQUESTED"
        elif view.get("reviewDecision") and own.get("decision") != view.get("reviewDecision"):
            # the line an earlier decision left unsent in the seat's composer gets its Enter
            # first, or the next tick comes back here (`sent_pending`)
            run_dir, run_state = transitions.run_for_pr(url)
            if dry_run or sent_pending(run_dir, run_state, log):
                own["decision"] = view.get("reviewDecision")
                own["decision_at"] = time.time()


def sent_pending(run_dir, run_state, log):
    """Whether no line ak typed about that run's PR is left unsent in its seat's composer: the
    Enter of one typed and never seen sent (`decision_typed`, the receipt `type_at_prompt`
    hands back) is pressed first (`handback.finish_typed`) and the mark comes off the run; left
    there, it would hold every later line back as the owner's draft."""
    held = (run_state or {}).get("decision_typed")
    if not held:
        return True
    if not handback.finish_typed(transitions.launched_session(run_state), held, log):
        return False
    if run_dir:
        handback.mark_delivery(run_dir, run_state, decision_typed=None)
    return True


def say(dry_run, log, text, url, session, merged=False):
    """Hand the maintainer's decision to its run, and to the seat that opened it while live.

    Never to Discord.  The run learns it first, where the menu and `ak run status` were
    already showing `waiting for the maintainer` -- a seat that cannot be typed into never
    holds that back -- and a live seat is typed the line at its quiet prompt, never into a
    running turn (`type_at_prompt`), exactly as a run's ending is, its mark kept on the run
    (`decision_typed`) so a line typed and never seen sent gets its Enter, not a second copy,
    and is sent (`handback.finish_typed`) before a later decision is typed or a routine merge ends
    the following.  A merge is the exception: routine, recorded on the run and typed into no seat, unless its
    run's seat owes work (`handback.routine_ending`), as the follow-ups it put in that seat's plan that no run took.
    A decision already on the run is not recorded again, so a retry after a failed typing
    tells the seat without recording twice or starting fix runs twice.  True means it has landed everywhere it goes, or that there is nowhere left for it
    to land and following this PR is over; False means the seat is still owed its line and
    the next tick retries it.
    """
    if dry_run:
        log(f"would hand on: {text} ({url})")
        return False
    run_dir, run_state = transitions.run_for_pr(url)
    note = " ".join(text.split())
    if run_dir and not (run_state.get("merge_note") == note
                        and (not merged or run_state.get("merged"))):
        handback.record_decision(run_dir, run_state, text, merged=merged)
        log(f"recorded on run {run_dir.name}: {text}")
    def kept(mark):
        # a line typed and never seen sent gets only its Enter from the next tick
        if run_dir:
            handback.mark_delivery(run_dir, run_state, decision_typed=mark)

    held = (run_state or {}).get("decision_typed")

    def finished():
        # an earlier decision's line left unsent in the composer would hold this one, and
        # every later line, back as the owner's draft: it is sent first
        return sent_pending(run_dir, run_state, log)

    if merged and (not run_dir or handback.routine_ending(run_state)):
        return finished()
    seat = orch.find(config.resolve_session(session)) if session else None
    if seat and not any(seat.get(key) for key in ("exited", "resumable", "restart")):
        line = (f"{text} -- {url}. Nothing was posted to Discord; this is the maintainer's "
                "decision on a PR of ours, for you to act on or not.")
        if run_dir:
            line = handback.seat_notice(line, run_state, run_dir,
                                   f"run {run_dir.name}: the maintainer decided on its PR.")
        if held and held.get("line") != line and not finished():
            return False
        if not type_at_prompt(seat, line, log, typed=held, receipt=kept):
            return False
        kept(None)
        log(f"told the {seat['name']} seat: {text}")
        return True
    if run_dir:
        return True
    log(f"no live seat and no run for {url}; not followed further: {text}")
    return True


# --- after a merge: the target's checks and the project's live product ------
# A merge to a repository's target starts that repository's own checks on the merge
# commit -- for one project a release gate of 12-25 min that must pass before
# production deploys.  The tick follows them for three hours, and a failed one goes
# back to a seat that can fix the target, never to the owner. A project's health
# command follows its deploy in the same window. One break is said
# once, for its newest failing commit; a later commit all green ends the break.

AFTER_MERGE_WINDOW = 3 * 3600  # seconds a merge commit's checks are followed
AFTER_MERGE_PASS = ("success", "neutral", "skipped")  # the conclusions that mean green
HEALTH_TIMEOUT = 30  # a project's live probe must leave time for the rest of the tick


def health_command(repo, sha, command):
    """A bounded live probe and its last output, without inherited pipes holding the tick."""
    try:
        with tempfile.TemporaryFile() as output:
            proc = subprocess.Popen(["bash", "-c", command], cwd=repo,
                                    env={**os.environ, "AK_MERGE_SHA": sha},
                                    stdin=subprocess.DEVNULL, stdout=output,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            timed_out = False
            try:
                proc.wait(timeout=HEALTH_TIMEOUT)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                # Even a shell that exited can have left children in its process group.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if timed_out:
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            output.seek(0, os.SEEK_END)
            output.seek(max(0, output.tell() - 4096))
            tail = "\n".join(output.read(4096).decode("utf-8", errors="replace").splitlines()[-10:])
            if timed_out:
                tail += f"\nhealth command timed out after {HEALTH_TIMEOUT}s"
            return not timed_out and proc.returncode == 0, tail.strip()
    except OSError as exc:
        return False, str(exc)


def awaiting_live(state, now=None):
    """A merged run whose project proves itself live (`health:`) and has not yet: ak's own
    probe, read every tick, so its seat has nothing to do but wait on it -- the stop hook lets
    the turn end on it and the seat's ladder reads it as working.  Whether the project proves
    itself is the one record the merge left (`merge_record`) and the tick keeps until it
    passes (`after_merge_health`); nothing is read again here."""
    now = time.time() if now is None else now
    finished = state.get("finished_at")
    if (not state.get("merged") or state.get("live_at") or not state.get("repo")
            or not isinstance(finished, (int, float)) or isinstance(finished, bool)
            or not 0 <= now - finished <= AFTER_MERGE_WINDOW):
        return False
    return bool((state.get("health") or {}).get("command"))


def merge_record(repo, sha, pr_url=None):
    """What a merge leaves on its run's record beside `merged`, the one record the tick
    (`after_merge_health`) and the seat's word (`awaiting_live`) read: the `health:` the
    commit `sha` declares, `{}` where it declares none.  Read in `repo`, else from the PR's
    repository on GitHub where `pr_url` names one; nothing where neither holds the commit,
    and the tick asks again."""
    from . import run
    if not sha:
        return {}
    if repo and run.git_out(repo, "cat-file", "-e", f"{sha}^{{commit}}")[0] == 0:
        command = gitcall.declared_at(repo, sha, "health")
    else:
        # The merge may exist only on GitHub; discovering health must not depend on origin.
        parsed = after_merge_repo(pr_url)
        if not parsed:
            return {}
        owner, name, host, _ = parsed
        api = ("api",) if host == "github.com" else ("api", "--hostname", host)
        data, _ = gh_json(config.RUNS, *api,
                          f"repos/{owner}/{name}/contents/AGENTS.md?ref={sha}",
                          timeout=HEALTH_TIMEOUT)
        if not (isinstance(data, dict) and data.get("encoding") == "base64"):
            return {}
        text = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        command = gitcall.front_value(text, "health")
    return {"health": {"command": command} if command else {}}


def after_merge_health(run_dir, st, key, sha, pr_url, now, dry_run, log, probes):
    """Keep the merge commit `sha` on the run and its history row, for the next tick and the
    scoreboard; then follow the merge's declaration in its original checkout, stopping at its
    first pass."""
    from . import history
    if not dry_run:
        if st.get("merge_sha") != sha:
            with run_record.record(run_dir) as current:
                current["merge_sha"] = sha
            st["merge_sha"] = sha
        # every tick: history swallows a write that failed, and the next tick repeats it
        history.update_run(st.get("run_id") or run_dir.name, merge_sha=sha, log=log)
    inside = now - st["finished_at"] < AFTER_MERGE_WINDOW
    if not st.get("live_at") and "health" not in st and inside and st.get("repo"):
        # a merge that could not read its commit, or one recorded before merges did: the
        # commit it delivered decides, as it would have there, recorded once for both readers
        found = merge_record(st["repo"], st.get("delivery_sha") or sha, pr_url)
        if found and not dry_run:
            with run_record.record(run_dir) as current:
                current.update(found)
        st.update(found)
    health = st.get("health") or {}
    command = health.get("command")
    if not st.get("live_at"):
        if not command:
            return None
        if inside:
            if dry_run:
                log(f"would check run {run_dir.name}'s live product: {command}")
                return "pending", None, None
            probe = (key, sha)
            if probe not in probes:
                probes[probe] = health_command(st["repo"], sha, command)
            passed, output = probes[probe]
            with run_record.record(run_dir) as current:
                if passed:
                    current.setdefault("live_at", now)
                    current.pop("health", None)
                else:
                    current["health"] = {"command": command, "output": output}
                st.clear()
                st.update(current)
            if not passed:
                return "pending", None, None
        else:
            # One typed line: a line break would reach the seat as Enter and send half of it.
            output = health.get("output") or "command exited nonzero without output"
            return "failed", f"health: {command}", "; ".join(
                [pr_url, *(part for part in output.splitlines() if part.strip())])
    if dry_run:
        if not st.get("live_notified"):
            log(f"would tell its launching seat: {handback.live_sentence(st, run_dir)}")
        return "passed", None, None
    history.update_run(st.get("run_id") or run_dir.name, live_at=st["live_at"], log=log)
    # A prompt may have carried the notice since this tick read the run. The deciding,
    # typing and mark share its delivery lock, so either path tells it once.
    with handback.delivery_lock(run_dir):
        current = run_record.read_state(run_dir)
        if (not current or not handback.same_attempt(st, current)
                or current.get("live_notified")):
            return "passed", None, None
        st.clear()
        st.update(current)
        session = transitions.launched_session(st)
        if handback.seat_owes_nothing(st):
            # no turn of its seat's waits on this (`awaiting_live`), a repair's included:
            # recorded, never typed, and a line an earlier pass typed and never saw sent is sent
            if handback.finish_typed(session, st.get("live_typed"), log):
                handback.mark_delivery(run_dir, st, live_notified=now, live_typed=None)
                log(f"{handback.live_sentence(st, run_dir)} Recorded, not typed")
            return "passed", None, None
        seat = orch.find(session)
        if after_merge_live(seat):
            def kept(mark):
                handback.mark_delivery(run_dir, st, live_typed=mark)

            line = handback.live_line(st, run_dir)
            if type_at_prompt(seat, line, log, typed=st.get("live_typed"), receipt=kept):
                handback.mark_delivery(run_dir, st, live_notified=now, live_typed=None)
                log(f"told the {seat['name']} seat: {line}")
    return "passed", None, None


def after_merge_line(check, target, url):
    """The one line a target break is handed back with: what failed, where, and to fix it."""
    return f"{check} failed on {target} after this merge: {url}. Fix the target."


def after_merge_repo(pr_url):
    """(owner, repo, host, key) for that PR URL, or None when it names no repository."""
    try:
        pr = urlsplit(pr_url or "")
    except ValueError:
        return None
    match = re.fullmatch(r"/([^/\s]+)/([^/\s]+)/pull/(\d+)/?", pr.path or "")
    if (not match or pr.scheme != "https" or not pr.hostname or pr.username
            or pr.query or pr.fragment):
        return None
    owner, repo, _ = match.groups()
    host = pr.netloc
    return owner, repo, host, f"{host}/{owner}/{repo}".lower()


def after_merge_target(run_state):
    """The branch the run merged into, short: `origin/main` is `main` on the line."""
    target = run_state.get("target") or run_state.get("base") or "main"
    if not isinstance(target, str) or not target:
        return "main"
    return target.removeprefix("origin/") or "main"


def after_merge_sha(pr_url, run_state, log):
    """The merge commit to follow: the record's own, else the PR's on GitHub, else None.

    A `gh` that cannot say costs this tick for this run, never a notice: the next tick
    asks again.
    """
    for key in ("merge_sha", "merge_commit", "merge_commit_sha"):
        sha = run_state.get(key)
        if isinstance(sha, str) and sha.strip():
            return sha.strip()
    data, why = gh_json(config.RUNS, "pr", "view", pr_url, "--json", "mergeCommit")
    oid = None
    if isinstance(data, dict) and isinstance(data.get("mergeCommit"), dict):
        oid = data["mergeCommit"].get("oid")
    if isinstance(oid, str) and oid.strip():
        return oid.strip()
    log(f"WARN {pr_url}: cannot read its merge commit: {' '.join((why or '').split())[:160]}")
    return None


def after_merge_status(owner, repo, host, sha, log):
    """(verdict, name, url) for that merge commit's check runs.

    `failed` carries the first failing check by name; `passed` means every check green;
    `pending` is still running or not yet registered; `ignored` is only cancelled runs,
    which GitHub leaves behind when a newer commit superseded them.  `unknown` is a `gh`
    that could not say, which costs this tick and never a notice.
    """
    api = ("api",) if host == "github.com" else ("api", "--hostname", host)
    data, why = gh_json(config.RUNS, *api, "--paginate",
                        f"repos/{owner}/{repo}/commits/{sha}/check-runs"
                        "?filter=latest&per_page=100")
    try:
        if not isinstance(data, list):
            raise ValueError(why or "invalid check-runs response")
        runs = [check for page in data for check in page["check_runs"]]
    except (KeyError, TypeError, ValueError) as exc:
        log(f"WARN {owner}/{repo}@{sha[:12]}: cannot read its checks: {exc}")
        return "unknown", None, None
    failed, pending, passed, seen = [], False, False, False
    for check in runs:
        if not isinstance(check, dict):
            continue
        seen = True
        if check.get("status") != "completed":
            pending = True
            continue
        if check.get("conclusion") == "cancelled":
            continue
        if check.get("conclusion") in AFTER_MERGE_PASS:
            passed = True
            continue
        name = check.get("name") or "A check"
        url = check.get("html_url") or check.get("details_url") or check.get("url") or ""
        failed.append((str(name), str(url)))
    if failed:
        failed.sort()
        return "failed", failed[0][0], failed[0][1]
    if pending or not seen:
        return "pending", None, None
    if passed:
        return "passed", None, None
    return "ignored", None, None


def after_merge_live(seat):
    """Whether that seat is up to be typed into: what `say` asks before it types."""
    return bool(seat) and not any(seat.get(key) for key in ("exited", "resumable", "restart"))


def after_merge_fallback(repo_key):
    """The newest live seat whose runs merged into that repository, or None.

    Newest by the seat's own birth, by name where two share it: the seat most likely
    to still be working the repository the target broke in.
    """
    try:
        seats = orch.sessions()
    except (config.Error, OSError, ValueError, AttributeError):
        return None
    live = {}
    for seat in seats:
        if not after_merge_live(seat):
            continue
        name = seat.get("name")
        if not isinstance(name, str) or not name:
            continue
        try:
            name = config.resolve_session(name)
        except (config.Error, OSError):
            pass
        live[name] = seat
    if not live:
        return None
    try:
        directories = run_record.run_dirs()
    except OSError:
        return None
    qualified = set()
    for run_dir in directories:
        st = run_record.read_state(run_dir)
        if not st or not st.get("merged") or not st.get("pr"):
            continue
        try:
            seat_name = transitions.launched_session(st)
        except config.Error:
            continue
        if seat_name not in live:
            continue
        parsed = after_merge_repo(st.get("pr"))
        if parsed and parsed[3] == repo_key:
            qualified.add(seat_name)
    if not qualified:
        return None

    def age(name):
        created = live[name].get("created")
        return (created if isinstance(created, (int, float)) and not isinstance(created, bool)
                else 0)

    return live[max(qualified, key=lambda name: (age(name), name))]


def after_merge_deliver(run_dir, run_state, repo_key, line, log, cfg=None, typed=None,
                        receipt=lambda mark: None):
    """Type that target break into its seat, else the newest live one on the same repo.

    As a finished run is: only at its prompt, so a turn in flight means the next tick
    tries again, and with the composer's mark kept across retries, so a line whose Enter
    did not land is entered and never typed a second time.  The seat's name when the line was
    told, else None.
    """
    if run_dir is not None:
        line = handback.seat_notice(line, {}, run_dir,
                                  f"run {run_dir.name}: a check failed after its merge.",
                                  "Fix the target.")
    seat = after_merge_seat(run_state, repo_key)
    if seat is None:
        return None
    return seat["name"] if type_at_prompt(seat, line, log, cfg=cfg, typed=typed,
                                          receipt=receipt) else None


def after_merge_seat(run_state, repo_key):
    """The seat an after-merge notice goes to: its own when live, else the fallback."""
    try:
        session = transitions.launched_session(run_state)
    except config.Error:
        session = None
    if session:
        try:
            seat = orch.find(session)
        except (config.Error, OSError, ValueError, AttributeError):
            seat = None
        if after_merge_live(seat):
            return seat
    return after_merge_fallback(repo_key)


def broke_after_merge(run_id, source, log):
    """The merged change a break was handed back to broke main's checks or its live health
    (`source`, "checks" or "health", as the status that failed came from): written on its
    history row once, as the break is told, so the scoreboard counts what got past review and
    landing."""
    from . import history
    history.update_run(run_id, broke_after_merge=source, log=log)


def after_merge_checks(state, dry_run, log, now=None):
    """Follow target checks and health, and hand one break per repository back to fix.

    Each merge commit younger than three hours is read the way the loop reads a PR's:
    its latest check runs from `gh`.  Only the newest commit with a failed check is
    handed back, and only once -- that commit or a newer one `passed` ends it, and a
    `gh` that could not say, for the merge commit or for a newer commit's checks, waits
    a tick rather than saying anything on half an answer.  A line whose Enter did not
    land keeps its composer mark, as a finished run's does, so the next tick enters it
    instead of typing it twice; a break already told stays told when its commit slides
    out of the window, until a later green commit -- or quiet with no red left -- ends it.
    """
    now = time.time() if now is None else now
    episodes = state.setdefault("after_merge", {})
    if not isinstance(episodes, dict):
        episodes = state["after_merge"] = {}

    def _save():
        try:
            save_state(state)
        except (config.Error, OSError, ValueError, AttributeError, KeyError,
                TypeError) as exc:
            log(f"WARN could not record the after-merge mark: {exc}")

    def _when(value):
        return (value if isinstance(value, (int, float)) and not isinstance(value, bool)
                else None)

    try:
        directories = run_record.run_dirs()
    except OSError as exc:
        log(f"WARN merged runs were not followed this tick: {exc}")
        return
    grouped = {}
    probes = {}
    for run_dir in directories:
        st = run_record.read_state(run_dir)
        if not st or not st.get("merged"):
            continue
        finished = st.get("finished_at")
        if (not isinstance(finished, (int, float)) or isinstance(finished, bool)
                or not 0 <= now - finished):
            continue
        # past the window, only a probe that failed inside it is followed further: the
        # `health:` a merge recorded and no probe ever ran is let go, the merge commit unasked
        if (now - finished > AFTER_MERGE_WINDOW and "output" not in (st.get("health") or {})
                and not (st.get("live_at") and not st.get("live_notified"))):
            continue
        pr_url = st.get("pr")
        if not isinstance(pr_url, str) or not pr_url:
            continue
        parsed = after_merge_repo(pr_url)
        if not parsed:
            continue
        owner, repo, host, key = parsed
        sha = after_merge_sha(pr_url, st, log)
        grouped.setdefault(key, []).append(
            (finished, run_dir.name, run_dir, st, owner, repo, host, sha or None, pr_url))
    for key in sorted(set(grouped) | set(episodes)):
        found = sorted(grouped.get(key, []))
        statuses = []
        expired_health = []

        def close_health():
            # Once the episode owns the evidence, an expired probe no longer needs polling.
            if not dry_run:
                for directory in expired_health:
                    with run_record.record(directory) as current:
                        current.pop("health", None)

        for finished, name, run_dir, st, owner, repo, host, sha, pr_url in found:
            if sha is None:
                statuses.append((finished, name, run_dir, st, None, pr_url,
                                 "unknown", None, None, None))
                continue
            if now - finished <= AFTER_MERGE_WINDOW:
                verdict, check, url = after_merge_status(owner, repo, host, sha, log)
            else:
                verdict, check, url = "ignored", None, None
            try:
                health = after_merge_health(run_dir, st, key, sha, pr_url, now,
                                            dry_run, log, probes)
            except (config.Error, OSError, ValueError, AttributeError, KeyError, TypeError) as exc:
                # Until a command is known, discovery cannot change the target's check verdict.
                health = ("unknown", None, None) if st.get("health") or st.get("live_at") else None
                if health:
                    log(f"WARN run {name}'s health could not be followed: {exc}")
            if now - finished >= AFTER_MERGE_WINDOW and health and health[0] == "failed":
                expired_health.append(run_dir)
            source = "checks"   # where the verdict came from: a check's name can be any text
            if health and verdict != "failed" and (health[0] != "passed" or verdict == "ignored"):
                if health[0] == "failed" or verdict != "unknown":
                    (verdict, check, url), source = health, "health"
            statuses.append((finished, name, run_dir, st, sha, pr_url, verdict, check, url, source))
        episode = episodes.get(key)
        if isinstance(episode, str):
            episode = episodes[key] = {"notified": episode} if episode else {}
        elif not isinstance(episode, dict):
            if episode is not None:
                episodes.pop(key, None)
            episode = {}
        notified = episode.get("notified")
        if not isinstance(notified, str) or not notified:
            notified = None
        if notified:
            ended = _when(episode.get("finished"))
            if ended is None:
                ended = _when(episode.get("at"))
            shas = [entry[4] for entry in statuses]
            if notified in shas:
                at = max(i for i, sha in enumerate(shas) if sha == notified)
                # Its own re-run going green ends it too, so a later break gets told.
                if any(entry[6] == "passed" for entry in statuses[at:]):
                    episodes.pop(key, None)
                    notified = None
                else:
                    close_health()
                    continue
            elif ended is None:
                episodes.pop(key, None)
                notified = None
            elif any(entry[6] == "passed" and entry[0] > ended for entry in statuses):
                episodes.pop(key, None)
                notified = None
            elif not any(entry[6] in ("failed", "pending", "unknown")
                         for entry in statuses):
                episodes.pop(key, None)
                notified = None
            else:
                close_health()
                continue
            if notified:
                continue
            episode = {}
        pending = episode.get("pending") if isinstance(episode.get("pending"), dict) else None
        if pending:
            line = pending.get("line")
            typed = pending.get("typed")
            sha = pending.get("sha")
            finished = _when(pending.get("finished"))
            run_name = pending.get("run")
            check = pending.get("check")
            target = pending.get("target") or "main"
            session = pending.get("session")
            if (not isinstance(line, str) or not line
                    or not isinstance(sha, str) or not sha or finished is None
                    or not isinstance(run_name, str) or not run_name):
                episode.pop("pending", None)
                if not episode and episodes.get(key) is episode:
                    episodes.pop(key, None)
                pending = None
            # As a told break: its own re-run going green ends it too.
            elif any(entry[6] == "passed" and (entry[0] > finished or entry[4] == sha)
                     for entry in statuses):
                episodes.pop(key, None)
                log(f"run {run_name}'s after-merge notice is over: {key} went green")
                pending = None
            elif dry_run:
                log(f"would hand run {run_name} back for {check} on {target}: {line}")
                continue
            else:
                def kept(mark, pending=pending):
                    pending["typed"] = mark
                    _save()

                fake_state = {"launched_session": session} if session else {}
                if after_merge_deliver(config.RUNS / run_name, fake_state, key, line, log,
                                       typed=typed, receipt=kept):
                    episodes[key] = {"notified": sha, "at": now, "run": run_name,
                                     "check": check, "finished": finished}
                    _save()
                    # a break kept by an install that did not carry its source counts as checks
                    broke_after_merge(run_name, pending.get("source") or "checks", log)
                    log(f"handed run {run_name} back for {check} on {target} "
                        "after its merge")
                else:
                    log(f"run {run_name}'s after-merge notice sits in a composer; "
                        "the next tick presses Enter")
                close_health()
                continue
        candidate, at = None, -1
        for i in range(len(statuses) - 1, -1, -1):
            if statuses[i][6] == "failed":
                candidate, at = statuses[i], i
                break
        if candidate is None:
            close_health()
            continue
        if any(entry[6] == "passed" for entry in statuses[at + 1:]):
            close_health()
            continue
        if any(entry[6] == "unknown" for entry in statuses[at + 1:]):
            log(f"WARN {key}: a newer merge's checks are unreadable; "
                "the after-merge notice waits a tick")
            continue
        finished, name, run_dir, st, sha, pr_url, _, check, url, source = candidate
        target = after_merge_target(st)
        line = after_merge_line(check or "A check", target, url or pr_url)
        if dry_run:
            log(f"would hand run {name} back for {check} on {target}: {line}")
            continue
        try:
            session = transitions.launched_session(st)
        except config.Error:
            session = None
        composed = []

        def fresh(mark):
            episodes[key] = {"pending": {"sha": sha, "line": line, "typed": mark,
                                         "run": name, "check": check, "source": source,
                                         "finished": finished, "target": target,
                                         "session": session}}
            composed.append(True)
            _save()

        if expired_health:
            # Keep a deadline failure even when no seat is available to compose it yet.
            fresh(None)
            composed.clear()
            close_health()
        if after_merge_deliver(run_dir, st, key, line, log, typed=None, receipt=fresh):
            episodes[key] = {"notified": sha, "at": now, "run": name, "check": check,
                             "finished": finished}
            _save()
            broke_after_merge(name, source, log)
            log(f"handed run {name} back for {check} on {target} after its merge")
        elif composed:
            log(f"run {name}'s after-merge notice sits in a composer; "
                "the next tick presses Enter")
        elif after_merge_seat(st, key) is None:
            log(f"no live seat for {key}; run {name}'s after-merge notice waits for one")
        else:
            log(f"run {name}'s after-merge notice waits for a live seat at its prompt")


def doctor(argv):
    """`ak doctor`: where the agents run, whether the tick that watches them is alive, and any
    model set to an effort its model does not take, its `effort` or the one a role runs it at.

    The first two lines are read and never asked, so they cost nothing on a host already in
    trouble -- which is the host this is typed on -- and come out before the efforts, which
    ask each harness for its models.  A model the owner set to an effort it does not take is
    named here and left as it is: the owner chose it, and the `c` screen is where it changes.
    """
    if command_help.show("doctor", argv):
        return 0
    if argv:
        raise config.Error(f"usage: ak doctor  (got {argv[0]!r})")
    # the slice line says its own name, so only the tick's needs one
    print(orch.slice_line())
    print(f"tick  {tick_health()}", flush=True)
    cfg = config.load()
    wrong = []
    for name in config.offered(cfg):
        entry = cfg["models"][name]
        takes = config.efforts(entry.get("harness"), entry.get("model"))
        for key in config.ROLE_EFFORTS.values():
            if (key == "effort" or key in entry) and entry.get(key) not in takes:
                wrong.append(f"{key}  {name}: {entry.get('model')} takes {' '.join(takes)}, "
                             f"not {entry.get(key)}")
    print("\n".join(wrong) or "effort  every model takes the effort it is set to")
    return 0


# What a pass of the tick may raise and leave the rest of the tick to run: the pass says so in
# one WARN line, and the next pass starts as if nothing had happened.
PASS_ERRORS = (config.Error, OSError, TypeError, ValueError, AttributeError, KeyError)


def offer_endings(log):
    """Detect lost loops even when no phone opens the menu and GitHub is unavailable.

    A seat takes one line at each quiet prompt, so the endings that wait on its decision go
    before those of runs that merged, which only tell it so: a failed run's ending waited
    behind six merged runs' (6 Oct).  A seat found off its prompt is read once a pass: its
    other endings are marked waiting for the next pass instead of reading the same screen
    again each.
    """
    ended = []
    for run_dir in run_record.run_dirs():
        try:
            receipt = run_record.read_state(run_dir)
            if receipt:
                receipt = handback.reap(run_dir, receipt)
                if receipt.get("state") in run_record.ENDED:
                    ended.append((run_dir, receipt))
        except PASS_ERRORS as exc:
            log(f"WARN cannot check run {run_dir.name}: {exc}")
    busy = {}   # seats this pass found not taking a line, and what it read (`handback.hand_back`)
    for run_dir, receipt in sorted(ended, key=lambda found: bool(found[1].get("merged"))):
        try:
            # Every ending nobody has heard is offered again here, not only one a flag was left
            # on: a hand-back the run could not type goes in at the next quiet prompt, and so
            # does the ending of an attempt that was reaped without one.  `announce` decides
            # again which path it is, so a seat that died since gets the orphan one.
            if handback.owes_ending(receipt):
                handback.announce(receipt, run_dir, log, busy=busy)
            # A question the seat never took is typed again before the user hears it; one it
            # took whose ping failed is only pinged, and so is one kept before `asked` was,
            # whose typing nobody knows the end of.
            question = receipt.get("pending_inbox")
            if question and ask_inbox(
                    config.load(), question["question"], question["url"],
                    question["sha"], log, asked=question.get("asked", True),
                    typed=lambda: handback.mark_delivery(
                        run_dir, receipt, pending_inbox={**question, "asked": True})
                    ) == 0:
                # struck off the record as it stands, never off this copy of it: the run's own
                # loop can have handed the ending back while the question was going out, and a
                # whole save from here would put that back to undelivered and say it twice
                handback.mark_delivery(run_dir, receipt, pending_inbox=None)
        except PASS_ERRORS as exc:
            log(f"WARN cannot check run {run_dir.name}: {exc}")


def local_passes(state, dry_run, log):
    """The tick's passes that owe GitHub nothing, in the order they run.

    Each is (what its WARN line says when it raises, the pass, whether a dry run runs it too).
    A dry run runs only the passes it can tell `dry_run`, and reads usage off the cache as it
    stands: reading that file probes nothing, and a dry run changes nothing.

    Each pass re-derives placement or state from what it finds: a finding remembered from one
    tick to the next loses its race.
    """
    from . import job as jobs, leases, logins, matrix, retire
    providers = {}

    def read_usage():
        # Of the snapshot, not of the adapters: a provider is asked at most once per
        # usage.PROBE_EVERY, a minute, so with no menu open this tick is what keeps the
        # readings current. Muse's adapter keeps its paid probe on its own longer interval,
        # and this read never spends a reset. The read itself is handed on, never a copy:
        # a `usage.Readings` is what tells `readiness` to check each harness can run.
        nonlocal providers
        providers = (staffing._cached_providers() if dry_run
                     else usage.collect(config.load(), refresh=True))

    return (
        ("the boot resume pass did not run",
         lambda: resume_after_boot(config.load(), dry_run=dry_run, log=log), True),
        ("the held-line Enter pass did not run",
         lambda: finish_own_lines(config.load(), log), False),
        ("the set-aside text pass did not run", lambda: drafts_back(config.load()), False),
        ("the mid-turn continue pass did not run",
         lambda: continue_turns(config.load(), log), False),
        # the seats first, and never behind GitHub: a stalled seat is the one thing on this tick
        # that nothing else will ever get to, and a gh that is down is no reason to leave it stuck
        ("the session health pass did not run",
         lambda: health(config.load(), state, dry_run, log), True),
        ("the mid-turn continue pass did not run",
         lambda: continue_turns(config.load(), log, accounts=True), False),
        # A dead loop is resumed before the stall ladder and before reap, so the same tick
        # continues it and reap does not turn it into an interruption ...
        ("the dead-loop pass did not run",
         lambda: resume_dead_loops(config.load(), dry_run, log), True),
        # ... and a job whose launcher died is relaunched, so its waiting tasks start too.
        ("the dead-job pass did not run", lambda: resume_dead_jobs(dry_run, log), True),
        # Silent runs are recovered from outside the loop, whatever it is doing: nothing new
        # has to be started.
        ("the stall pass did not run", lambda: recover_runs(config.load(), dry_run, log), True),
        # which live runs of a repository change the same lines: the younger, before its
        # review, is stopped with its branch kept, and starts again once the older has
        # landed (`leases`); a dry run, which writes nothing, skips both
        ("the lease scan did not run", lambda: leases.scan_all(log), False),
        ("the lease restart pass did not run", lambda: leases.restart(log), False),
        ("the tick's watch.json was not saved", lambda: save_state(state), False),
        ("the usage refresh did not finish", read_usage, True),
        # when each subscription's login ends and whose it is, each asked hourly at most; one
        # ending within 3 days pages the owner once a day, and so does a worker token
        ("the login-end read did not run", lambda: logins.remind(config.load()), False),
        ("the worker-token reminder did not run",
         lambda: remind_worker_tokens(state.get("worker_tokens")), False),
        # the public boards once a day, and the matrix every pick reads, computed again only
        # when a board answered anew or the config's models or the harnesses installed changed;
        # a dry run reads nothing
        ("the boards pass did not run", lambda: matrix.refresh(config.load()), False),
        # An exhausted run waits for a provider window and resumes itself when one refills, on
        # the usage just read; a run parked on an expired login, the moment that harness's
        # `auth` verb passes again; a run in error, on the loop's transient ladder, hourly at
        # most; one waiting on a rebase conflict, after the next merge to main. All silently,
        # never waiting on the run.
        ("the exhausted-resume pass did not run",
         lambda: resume_exhausted(config.load(), providers, dry_run=dry_run, log=log), True),
        ("the login-resume pass did not run",
         lambda: resume_waiting_login(dry_run=dry_run, log=log), True),
        ("the error-retry pass did not run", lambda: resume_errored(dry_run=dry_run, log=log), True),
        ("the waiting-resume pass did not run",
         lambda: resume_waiting(dry_run=dry_run, log=log), True),
        # History is never replayed: endings older than an hour are marked here, in one line
        # with the count, before any of them is offered again.
        ("the pre-existing sweep did not run", lambda: sweep_preexisting(log), False),
        ("the ending pass did not run", lambda: offer_endings(log), False),
        # A job that finished while its seat was mid-turn hands its line back at the next quiet
        # prompt, the way one of its runs does; a seat whose `ak wait` names a pull request or
        # run that is over is told so, which ends the wait.
        ("a finished job was not handed back", lambda: jobs.deliver_job_handbacks(log), False),
        ("the wait pass did not run", lambda: wait_over(config.load(), log), False),
        # Every feature switch on for everyone for two weeks becomes a line in the plan of a seat
        # on its project, to take out of the code.
        ("the switch retirement pass did not run", lambda: retire.hand(log), False),
        ("the seat token pass did not run", lambda: seat_tokens.read(0, 0), False),
        # The first tick of a week writes the board with its largest loss, and the `audit`
        # seat, opened with `[audit]`'s models, is told it at its quiet prompt.
        ("the weekly audit pass did not run", lambda: tell_audit(config.load(), log), False),
        # What the owner typed into a seat's turn after it asked answers its question before
        # the cards are read, so no card goes out for a question they answered.
        ("the typed-answer pass did not run", lambda: notify.answer_typed(log=log), False),
        # Cards are derived from every session's current three-state word, including seats
        # whose panes were not available to the health pass.
        ("the card transition pass did not run", lambda: notify.tick_cards(log=log), False),
        # Late cards after it: a question that ended since the last tick has its card retired
        # by then (`notify._retire`), so none goes out late for it.
        ("the notification retry did not run",
         lambda: notify.retry_pending(dry_run=dry_run, log=log), True),
        # A seat that died under its running runs comes back, after its endings were announced
        # to it.
        ("the seat revival pass did not run", lambda: revive_seats(config.load(), log), False),
        ("git housekeeping did not finish", lambda: gc.git_housekeeping(log), False),
        # Expensive collection runs detached; malformed retention metadata cannot stop a tick.
        ("retention pass did not finish", lambda: gc.schedule_gc(log), False),
        ("retention pass did not finish", orch.stamp, False),
        ("retention pass did not finish", lambda: orch.sweep(log), False),
        ("the ended-login pass did not run", lambda: gc.stop_ended_logins(log), False),
        # The shared browser's idle tabs are reaped: a machine with no browser on CDP costs one
        # refused connection and nothing else.
        ("browser tidy did not finish", lambda: browser.tidy(log), False),
        # A merge to a project reaches its seats' rulebooks: their next prompts name it.
        ("the projects' rules were not fetched", orch.fetch_projects, False),
        # Merged agentkit goes live after every local pass, so as little of this tick's old
        # code as can be is left to run over new files; GitHub imports nothing new.
        ("agentkit did not go live", lambda: update.go_live(log), False),
        # ... and then every harness: a newer release is upgraded by a child started on that
        # new code, gated and put back where a gate fails, and no tick waits on it.
        ("the harness upgrade pass did not run", lambda: update.keep_current(log), False),
    )


def main(argv):
    if command_help.show("watch", argv):
        return 0
    dry_run = argv == ["--dry-run"]
    if argv and not dry_run:
        raise config.Error(f"usage: ak watch [--dry-run]  (got {argv[0]!r})")
    # every line of a real tick, the overlap line included, bounds the log on its way out; a
    # dry run renames nothing at all, and the log it may be printing into is no exception
    log = print if dry_run else tick_log
    if dry_run:
        log(tick_health())
        held = None
    else:
        config.ensure_dirs()
        held = tick_lock()
        if held is None:
            pid, holding = tick_holder()
            minutes = int(holding // 60)
            log(f"tick already running (pid {pid}, for {minutes} min)")
            if holding >= TICK_HUNG:
                log(f"WARN the tick holding the lock has been running for {minutes} min; "
                    "look at it, and kill it if it is hung")
            return 0
    # one reading of the process table for the whole tick: every seat it looks at is told
    # from a watcher loop by the same `ps`
    with held if held is not None else nullcontext(), orch.one_reading():
        state = load_state()
        for what, step, also_dry in local_passes(state, dry_run, log):
            if also_dry or not dry_run:
                try:
                    step()
                except PASS_ERRORS as exc:
                    log(f"WARN {what}: {exc}")
        user, why = gh_json(config.RUNS, "api", "user")
        me = user.get("login") if isinstance(user, dict) else None
        if not isinstance(me, str) or not me:
            # No GitHub is no reason to lose a tick: everything above has already run, and only
            # the GitHub passes are skipped.  gh's advice runs to several lines; one line
            # is the whole point here.
            reason = " ".join((why or "gh api user failed").split())[:160]
            if not LOGGED_OUT.search(reason):
                # A timeout or an outage is not a login to go and fix, and saying it is would
                # put a red word on seats whose credentials are perfectly good.  An expiry an
                # earlier tick did see stands until a tick can ask again and be answered.
                log(f"WARN GitHub is unavailable; PR checks skipped ({reason})")
                return 0
            # This one is the user's to fix, and the seats with a run that still owes GitHub
            # a push are written down for the menu to say so.
            log(f"gh is not logged in; PR checks skipped ({reason})")
            if not dry_run:
                state["gh_out"] = {"at": time.time(), "seats": pushing_seats()}
                save_state(state)
            return 0
        if not dry_run:
            state.pop("gh_out", None)
        incoming(state, me, dry_run, log)
        outgoing(state, me, dry_run, log)
        after_merge_checks(state, dry_run, log)
        if not dry_run:
            save_state(state)
        return 0
