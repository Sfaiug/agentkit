#!/usr/bin/env python3
"""Run an orchestrator seat's harness and compact it after a safe idle period.

Auto-compaction belongs to the seat and to no worker: a headless `ak worker` runs the same
harness with the same hooks, and nothing on that path is wrapped by this.  The rule is one rule
for every harness -- the table's minutes after the last turn ended, with the context at or above
the floor, the harness's own compact command is typed once, at a quiet prompt.  Nothing but a
new turn resets that clock: keys, clicks, pointer motion, focus and terminal replies all reach
the seat's stdin alike, and a seat open in the owner's window went hours uncompacted while they
held it back.  What differs between harnesses is data, in the `[compact]` table of
adapters/<harness>.toml:

  command  the keystrokes that compact that TUI, or "none" where it has no such command; a
           list is typed key group by key group, with a pause between, which is what a TUI whose
           slash-command chooser eats a return arriving in the same read as the text needs
  signal   "hook"   -- the harness runs hooks/seat-state.sh on a turn's end and it stamps the
                       time, the context size and whose turn it was into the state file below
           "screen" -- the harness has no hooks, so the manifest's at-the-prompt rule says when
                       a turn ended, read off the stream this wrapper is already copying
  context  where the context size is read, or "none" where the harness reports none
  idle     the minutes after a turn's end it compacts at: while the prompt cache still holds
           the conversation, summarizing it is much cheaper
  stash    the key that sets a draft in the composer aside and brings it back once the compact
           command is sent, pressed first; "none" where the harness has none, and then a seat
           whose record reads a draft is not typed into

A harness that cannot compact, or cannot say how big its context is, is never guessed at: the
reason is printed once and nothing is ever typed into that seat.

Two things this has to be careful about, both measured rather than assumed.

Whose state.  Any harness the owner starts inside the seat inherits IDLE_COMPACT_STATE and would
otherwise stamp the seat's file with its own numbers.  So the hook records the process that ran
it and that process's ancestors, and only state naming this wrapper's own forkpty child is used;
anything else is logged and ignored.  The chain is what is matched, not the immediate parent:
Claude Code 2.1.263 runs a hook as `sh -c bash ...`, and the `codex` on PATH is a node shim that
spawns the native binary, so the harness is never the hook's own parent.

Repaints.  Measured with Claude Code 2.1.258: after a Stop hook state update the TUI wrote 1,145
bytes during 60 idle seconds, 1,082 of them a prompt redraw in the first 0.38 s.  A reattach, a
resize or a status redraw writes far more than that, so output silence cannot be what the idle
minutes are measured on -- it would defer compaction indefinitely.  The decision rests on the
turn-end timestamp alone; output only has to be quiet for the few seconds right before anything
is typed, and output that follows a SIGWINCH is a repaint, not activity.
"""

import argparse
import datetime
import errno
import fcntl
import json
import math
import os
import re
import signal
import sys
import termios
import time
import tty
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config, notify, orch, watch
from agentkit.pty_relay import Relay

DEFAULT_HARNESS = "claude"
QUIET_BEFORE_INJECT = 5.0   # output has to have stopped this long before anything is typed
RESIZE_GRACE = 3.0          # ... and output this soon after a SIGWINCH is a repaint, not that
# Between the keys of a compact command.  Measured against Muse Code 1.2.1 and Codex 0.153.4:
# a return arriving in the same read as the text it is meant to send is absorbed by the
# slash-command chooser that the text opened, and the command sits unsent in the composer.  A
# gap of 0.10 s still lost it and 0.15 s did not, so a seat idle for half an hour waits half a
# second between them.
KEY_GAP = 0.5
SCREEN_TAIL = 8192          # how much of the stream the `screen` signal reads back
SCREEN_LINES = 8            # ... and how many of its lines an at-the-prompt rule may look at
CONTEXT_TAIL = 512 * 1024   # how much of a harness's own session file is read for its last size
MUSE_HEAD_LINES = 40        # ... and how far into one Muse's record of who opened it is looked for
MUSE_CANDIDATES = 20        # the newest sessions a seat looks through for the one it opened
# Everything a terminal writes that is not text: CSI and OSC sequences, two-byte escapes, and
# the control characters that are neither the newlines nor the carriage returns split on below.
ANSI = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]"
                  r"|\x1b[@-Z\\-_]|\x1b[()][0-9A-Za-z]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def positive_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def nonnegative_tokens(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def parse_args(argv):
    parser = argparse.ArgumentParser(
        usage="%(prog)s [--harness NAME] [--idle SEC] [--min-context TOKENS] [--poll SEC] "
              "-- command [args...]"
    )
    parser.add_argument("--harness", default=DEFAULT_HARNESS)
    parser.add_argument("--idle", type=positive_seconds)   # the manifest's minutes otherwise
    parser.add_argument("--min-context", type=nonnegative_tokens, default=40000)
    parser.add_argument("--poll", type=positive_seconds, default=5.0)
    if "--" not in argv:
        if any(arg in ("-h", "--help") for arg in argv):
            parser.parse_args(argv)
        parser.error("missing '--' before command")
    separator = argv.index("--")
    options = parser.parse_args(argv[:separator])
    command = argv[separator + 1 :]
    if not command:
        parser.error("missing command after '--'")
    return options, command


def plan(harness):
    """How that harness compacts, from its manifest, or why it cannot.

    The refusal is the manifest's own answer, not a guess: a harness with no compact command and
    a harness that reports no context size are different facts, and the seat is told which.
    """
    try:
        manifest = config.manifest(harness)
    except config.Error as exc:
        return None, str(exc)
    table = manifest.get("compact")
    table = table if isinstance(table, dict) else {}
    command = table.get("command") or "none"
    command = [command] if isinstance(command, str) else [str(key) for key in command]
    context = str(table.get("context") or "none")
    signal_name = str(table.get("signal") or "screen")
    if command == ["none"] or not command:
        return None, f"{harness} has no compact command"
    if context == "none":
        return None, f"{harness} does not report context size"
    if signal_name not in ("hook", "screen"):
        return None, f"{harness} declares no way to know a turn ended"
    idle = table.get("idle")
    if isinstance(idle, bool) or not isinstance(idle, (int, float)) or idle <= 0:
        return None, f"{harness} declares no idle minutes"
    stash = str(table.get("stash") or "none")
    built = {"command": [key.encode() for key in command], "signal": signal_name,
             "context": context, "idle": idle * 60.0,
             "stash": None if stash == "none" else stash.encode(),
             "composer": None, "blocked": (), "lines": SCREEN_LINES}
    if signal_name == "screen":
        screen = manifest.get("screen")
        composer = (screen or {}).get("composer") if isinstance(screen, dict) else None
        # the same rule the menu reads that seat's screen with: the composer drawn last, with
        # nothing above it that says a turn is still running
        rule = next((entry for entry in manifest.get("rule") or ()
                     if isinstance(entry, dict) and entry.get("state") == "at_prompt"
                     and entry.get("at_composer")), None)
        if not composer or rule is None:
            return None, f"{harness} has no at-the-prompt rule to read a turn's end from"
        try:
            built["composer"] = re.compile(composer)
            built["lines"] = max(1, int(rule.get("lines", SCREEN_LINES)))
        except (re.error, TypeError, ValueError) as exc:
            return None, f"adapters/{harness}.toml: {exc}"
        built["blocked"] = tuple(str(mark).lower() for mark in rule.get("none") or ())
    return built, ""


def write_all(fd, data):
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
        except InterruptedError:
            continue
        if written == 0:
            raise OSError(errno.EIO, "zero-byte write")
        view = view[written:]


def copy_winsize(source_fd, pty_fd):
    try:
        size = fcntl.ioctl(source_fd, termios.TIOCGWINSZ, b"\0" * 8)
        fcntl.ioctl(pty_fd, termios.TIOCSWINSZ, size)
    except OSError:
        pass


def read_state(path, child_pid):
    """The hook's last turn-end stamp, if it was written for this wrapper's own child.

    Returns (ts, context_tokens) for state that is this seat's, ("foreign", pid) for state some
    other harness in the seat wrote, and None when there is nothing usable to read at all.
    """
    try:
        with open(path, "r", encoding="utf-8") as state_file:
            state = json.load(state_file)
        ts = float(state["ts"])
        context_tokens = state["context_tokens"]
        if (
            not math.isfinite(ts)
            or isinstance(context_tokens, bool)
            or not isinstance(context_tokens, int)
        ):
            return None
        wrote = [state.get("pid")] + list(state.get("pids") or ())
        wrote = [pid for pid in wrote if isinstance(pid, int) and not isinstance(pid, bool)]
        if child_pid not in wrote:
            return "foreign", (wrote[0] if wrote else None)
        return ts, context_tokens
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def tail_records(path, limit=CONTEXT_TAIL):
    """The decodable JSON lines of the tail of a harness's own session file.

    Only the tail: a seat's session file grows all day and only its last numbers matter.  A
    first line the window cut in half is not a line, and is dropped rather than guessed at.
    """
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            chunk = handle.read()
    except OSError:
        return
    lines = chunk.decode("utf-8", "replace").splitlines()
    if size > limit and lines:
        lines.pop(0)
    for line in lines:
        try:
            yield json.loads(line)
        except ValueError:
            continue


def opened_by(path, child_pid):
    """Did the process this wrapper forked open that Muse session?

    Muse writes a `runtime.session.route_facts` record among the first few of every session,
    naming the pid of the process that opened it.  `env`, the `muse` launcher script and the
    binary it runs all exec in place, so that pid is the forkpty child exactly -- which is what
    picks the seat's own session out of every other seat's on the machine, with nothing guessed
    from directory order or timestamps.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for _ in range(MUSE_HEAD_LINES):
                line = handle.readline()
                if not line:
                    return False
                try:
                    payload = json.loads(line).get("payload")
                except (ValueError, AttributeError):
                    continue
                if isinstance(payload, dict) and payload.get("kind") == "route_facts":
                    facts = payload.get("record")
                    return isinstance(facts, dict) and facts.get("pid") == child_pid
    except OSError:
        return False
    return False


def muse_context(child_pid):
    """The context size of the Muse session this wrapper's own child opened.

    The size is the last main-agent provider usage record's input tokens, which already include
    the cached prefix and so are the whole context that turn sent.  A session once identified is
    remembered: only a seat whose file has gone looks for another.
    """
    found = _MUSE_SESSION.get("path")
    if found is None or not found.exists():
        _MUSE_SESSION["path"] = found = None
        root = (Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
                / "muse/sessions")
        try:
            # YYYY/MM/DD/<session-uuid>/session.jsonl; a subagent's is not the seat's
            candidates = [path for path in root.glob("*/*/*/*/session.jsonl")
                          if "subagent" not in path.parts]
            candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        except OSError:
            return None
        for path in candidates[:MUSE_CANDIDATES]:
            if opened_by(path, child_pid):
                _MUSE_SESSION["path"] = found = path
                break
    if found is None:
        return None
    size = None
    for record in tail_records(found):
        payload = record.get("payload") if isinstance(record, dict) else None
        event = payload.get("event") if isinstance(payload, dict) else None
        if not isinstance(event, dict) or event.get("kind") != "goal_usage_attribution":
            continue
        usage = event.get("record")
        if not isinstance(usage, dict) or usage.get("usage_family") != "provider":
            continue
        owner, quantity = usage.get("owner"), usage.get("quantity")
        if not isinstance(owner, dict) or owner.get("owner_type") != "main_root":
            continue
        tokens = quantity.get("input_tokens") if isinstance(quantity, dict) else None
        if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens > 0:
            size = tokens
    return size


_MUSE_SESSION = {}

# Where a harness the wrapper has to read itself keeps its context size.  A `hook` harness is
# not here: its hook has already put the number in the state file.
CONTEXT_READERS = {"muse-session": muse_context}


def screen_lines(tail):
    """The text that stream last painted, newest last.

    The wrapper has a byte stream where the menu has a pane, so what a rule is applied to is the
    stream's own text with its escape sequences taken out.  A manifest's composer pattern is
    anchored at the end of a line, which makes matching it against the last of these exactly the
    test that the last thing painted was the composer.  Measured against Muse Code 1.2.1 over one
    recorded turn: this read at-the-prompt before the prompt, working while the turn ran, and
    at-the-prompt again when it ended.
    """
    clean = ANSI.sub("", tail.decode("utf-8", "replace"))
    lines = [line.strip() for chunk in clean.split("\n") for line in chunk.split("\r")]
    return [line for line in lines if line]


def busy(lines, built):
    """Does the region carry one of the marks that rule says a running turn puts there?"""
    region = "\n".join(lines[-built["lines"]:]).lower()
    return any(mark in region for mark in built["blocked"])


def at_prompt(lines, built):
    """Is that harness sitting at its prompt, by its manifest's own at-the-prompt rule?"""
    return bool(lines) and bool(built["composer"].search(lines[-1])) and not busy(lines, built)


def seat_record(seat):
    """That seat's record, the one every screen reads it by, under the name it goes by now."""
    if not seat:
        return {}
    try:
        record = json.loads(config.seat_state_path(config.resolve_session(seat)).read_text(
            encoding="utf-8"))
    except (OSError, ValueError, config.Error):
        return {}
    return record if isinstance(record, dict) else {}


def drafted(seat):
    """Does that seat's record say its composer holds a draft?"""
    return seat_record(seat).get("state") == "draft"


def at_rest(seat, harness):
    """Is that seat at a quiet prompt by its own hooks and record: no turn running, no question?

    The turn-end stamp alone counts from the last turn that ended: a turn that began since and
    runs past the idle minutes, or a question it put up, is nothing it can see, and a question
    dialog sits silent -- `/compact` and its return were typed into one, which answered the
    owner's question with its first option.  A seat no name is known for has nothing to read.
    """
    if not seat:
        return True
    try:
        hooked = watch.hook_state(harness, watch.hook_facts(config.resolve_session(seat)))[0]
    except (OSError, ValueError, config.Error):
        hooked = None
    return hooked not in ("working", "asking") and seat_record(seat).get("state") != "asking"


def append_log(path, wrapper_pid, message):
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    line = f"{stamp} pid={wrapper_pid} {message}\n".encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        write_all(fd, line)
    finally:
        os.close(fd)


def record_compaction(harness, context_tokens, when):
    """Say so where `ak orch list --why` will look: a seat that compacted itself is not silent.

    Only a named seat has a row to say it on; a wrapper run outside one records nothing here and
    leaves its line in the log.
    """
    seat = os.environ.get(config.SESSION_ENV) or ""
    try:
        path = config.compact_path(seat)
    except config.Error:
        return
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"session": seat, "harness": harness,
                                   "last_compact_at": when, "context_tokens": context_tokens}))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)


def type_compaction(relay, built, log, ready=lambda seat: True):
    """Keep pty-injected commands under the same lock and receipt as tmux typing.

    `ready` is asked again under that lock, with the name the seat goes by now: a question
    or a turn that came up while another sender held it is still nothing to type into.
    """
    def send(_text):
        # A draft set aside first comes back once the command is sent.
        stash = [built["stash"]] if built["stash"] else []
        return (0, "") if relay.send(stash + built["command"], KEY_GAP) else (1, "terminal closed")

    seat = config.current_session()
    if not seat:
        return send("") == (0, "")
    line = b"".join(built["command"]).decode("utf-8").rstrip("\r\n")
    with notify.session_lock(seat, wait=False) as name:
        return bool(name) and ready(name) and watch._send_line({"name": name}, line, log, send=send)


def exit_code(wait_status):
    code = os.waitstatus_to_exitcode(wait_status)
    return 128 - code if code < 0 else code


def name_input_tty(path):
    """The pane owns this fact across renames; its next wrapper replaces it at start."""
    pane = os.environ.get("TMUX_PANE")
    server = os.environ.get("TMUX", "").partition(",")[0]
    if not os.environ.get(config.SESSION_ENV) or not pane or not server:
        return
    rc, out = orch.tmux_out("-S", server, "set-option", "-p",
                            "-t", pane, watch.INPUT_TTY_OPTION, path,
                            socket="", timeout=5)
    if rc:
        raise OSError(errno.EIO, f"cannot name the harness terminal: {out}")


def run(options, command):
    wrapper_pid = os.getpid()
    built, refusal = plan(options.harness)
    state_dir = config.STATE / "idle-compact"
    # named for its seat as well, so stopping the seat takes it (`orch.session_owned_files`)
    seat = config.normalize_session(os.environ.get(config.SESSION_ENV) or "")
    named = seat and "/" not in seat and seat not in (".", "..")
    state_path = state_dir / (f"{seat}-{wrapper_pid}.json" if named else f"{wrapper_pid}.json")
    log_path = state_dir / "log"
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    state_path.unlink(missing_ok=True)
    if refusal:
        print(f"idle-compact.py: this seat will not compact itself: {refusal}", file=sys.stderr)

    child_env = os.environ.copy()
    child_env["IDLE_COMPACT_STATE"] = str(state_path)
    child_pid, master_fd = os.forkpty()
    if child_pid == 0:
        try:
            # Only the forkpty child has the slave fd. Publish before the harness starts.
            name_input_tty(os.ttyname(0))
            os.execvpe(command[0], command, child_env)
        except OSError as exc:
            message = f"idle-compact.py: {command[0]}: {exc.strerror}\n".encode()
            try:
                write_all(2, message)
            finally:
                os._exit(127)

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    terminal_attrs = None
    child_status = None
    relay = None
    resize_pending = True
    last_resize_mono = float("-inf")
    forwarded_signals = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT, signal.SIGQUIT)
    old_handlers = {}

    terminal_fd = next(
        (fd for fd in (stdin_fd, stdout_fd, sys.stderr.fileno()) if os.isatty(fd)),
        None,
    )

    def request_resize(_signum, _frame):
        nonlocal resize_pending, last_resize_mono
        resize_pending = True
        last_resize_mono = time.monotonic()

    def forward_signal(signum, _frame):
        try:
            os.kill(child_pid, signum)
        except ProcessLookupError:
            pass

    try:
        if os.isatty(stdin_fd):
            terminal_attrs = termios.tcgetattr(stdin_fd)
            tty.setraw(stdin_fd, termios.TCSANOW)

        old_handlers[signal.SIGWINCH] = signal.getsignal(signal.SIGWINCH)
        signal.signal(signal.SIGWINCH, request_resize)
        for signum in forwarded_signals:
            old_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, forward_signal)

        last_output_mono = time.monotonic()
        last_injected_ts = float("-inf")
        next_poll_mono = time.monotonic()
        # the `screen` signal's own half of the state: the tail it reads, whether that tail was
        # at the prompt last time it was read, whether a turn has run since it left, and when it
        # last arrived there
        tail = bytearray()
        tail_fresh = True
        seen_at_prompt = False
        ran = False
        screen_ts = None
        complained = None
        # a turn end has to stand still for this long before anything is typed, but never for
        # longer than the idle window itself: the quiet is a guard on the injection, not a
        # second waiting period on top of it
        idle = options.idle or (built or {}).get("idle") or 0.0
        quiet = min(QUIET_BEFORE_INJECT, idle)

        def free_to_type(seat):
            """Nothing of the owner's under the composer: no draft it cannot set aside, no turn
            running, no question up -- asked before the typing lock and again under it."""
            return (relay.caught_up(output=built["signal"] == "screen")
                    and (bool(built["stash"]) or not drafted(seat))
                    and at_rest(seat, options.harness))

        def output(data):
            nonlocal last_output_mono, tail_fresh
            output_mono = time.monotonic()
            if output_mono - last_resize_mono > RESIZE_GRACE:
                last_output_mono = output_mono
            if built is not None and built["signal"] == "screen":
                tail.extend(data)
                del tail[:-SCREEN_TAIL]
                tail_fresh = True

        def alive():
            nonlocal resize_pending, child_status
            if resize_pending:
                if terminal_fd is not None:
                    copy_winsize(terminal_fd, master_fd)
                resize_pending = False
            if child_status is None:
                waited_pid, wait_status = os.waitpid(child_pid, os.WNOHANG)
                if waited_pid:
                    child_status = wait_status
            return child_status is None

        relay = Relay(master_fd, stdin_fd, stdout_fd, output, alive)
        while relay.active and alive():
            now_mono = time.monotonic()
            relay.poll(max(0.0, next_poll_mono - now_mono))

            polling = now_mono >= next_poll_mono
            if polling:
                next_poll_mono = now_mono + options.poll
            if polling and relay.master_open and built is not None:
                now_wall = time.time()
                turn = None
                if built["signal"] == "hook":
                    state = read_state(state_path, child_pid)
                    if state is not None and state[0] == "foreign":
                        if complained != state[1]:
                            complained = state[1]
                            append_log(log_path, wrapper_pid,
                                       f"ignored state written for pid={state[1]} "
                                       f"(this seat is pid={child_pid})")
                    elif state is not None:
                        turn = state
                else:
                    if tail_fresh:
                        tail_fresh = False
                        lines = screen_lines(bytes(tail))
                        now_at_prompt = at_prompt(lines, built)
                        if not now_at_prompt and busy(lines, built):
                            ran = True
                        # the prompt a seat opens on ended a turn; every one after it has to
                        # have had a turn running before it, or the owner typing a character
                        # they have not sent yet would look like one and be compacted over
                        if now_at_prompt and not seen_at_prompt and (screen_ts is None or ran):
                            screen_ts, ran = now_wall, False
                        seen_at_prompt = now_at_prompt
                    if screen_ts is not None and seen_at_prompt:
                        turn = (screen_ts, None)
                if turn is not None:
                    ts, context_tokens = turn
                    if (
                        ts > last_injected_ts
                        and now_wall - ts >= idle
                        and now_mono - last_output_mono >= quiet
                        and free_to_type(os.environ.get(config.SESSION_ENV))
                    ):
                        if context_tokens is None:
                            reader = CONTEXT_READERS.get(built["context"])
                            try:
                                context_tokens = reader(child_pid) if reader else None
                            except (OSError, ValueError, TypeError, AttributeError, KeyError):
                                # a size nobody could read is not a size: the seat carries on
                                context_tokens = None
                        if context_tokens is not None and context_tokens >= options.min_context:
                            if not type_compaction(relay, built, lambda message: append_log(
                                    log_path, wrapper_pid, message), free_to_type):
                                continue
                            last_injected_ts = ts
                            append_log(log_path, wrapper_pid,
                                       f"compacted {options.harness} "
                                       f"context_tokens={context_tokens}")
                            record_compaction(options.harness, context_tokens, now_wall)

        relay.finish()

        if child_status is None:
            _, child_status = os.waitpid(child_pid, 0)
        return exit_code(child_status)
    finally:
        if relay is not None:
            relay.close()
        if terminal_attrs is not None:
            termios.tcsetattr(stdin_fd, termios.TCSANOW, terminal_attrs)
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
        try:
            os.close(master_fd)
        except OSError:
            pass
        if child_status is None:
            try:
                os.kill(child_pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                waited_pid, _ = os.waitpid(child_pid, os.WNOHANG)
                if waited_pid:
                    break
                time.sleep(0.02)
            else:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    os.waitpid(child_pid, 0)
                except ChildProcessError:
                    pass
        state_path.unlink(missing_ok=True)


def main():
    options, command = parse_args(sys.argv[1:])
    try:
        return run(options, command)
    except Exception as exc:
        print(f"idle-compact.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
