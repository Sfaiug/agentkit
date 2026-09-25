"""Orchestrator seats: named tmux sessions, on whichever harness the model names.

`ak orch` starts or reattaches a seat.  A seat is named by the user -- `ak orch <name>`, or a
rename -- because the name is what the menu, the status bar and every Discord message call it;
one started from the menu's `n`, or a bare `ak orch`, is named for its orchestrator (`opus`, then
`opus-2`) until he renames it.  `ak attach` and a bare `ak` are the menu.

The seats live on a tmux server of agentkit's own (`tmux -L agentkit`), never the user's default
one: nothing the toolkit configures leaks into another tmux user's server, and a test cannot
reach it at all.  Seats started before that server existed are still listed, from the default
server, as `legacy`, and are attached where they are.

The session is tmux's, so it outlives the connection that made it -- and, with `remain-on-exit`,
the orchestrator process too: a harness that exits leaves the seat standing, marked `exited`,
and its number resumes its owned conversation or starts fresh in the same pane. A detached,
exited seat is retired automatically after a week. Live and attached seats, and seats with
unfinished run evidence, stay until `ak orch stop` (the menu's `x`).

Every seat agentkit starts is dressed on the way up: a one-line status bar saying who is in it,
what it is doing, and the one key to the menu, and `Ctrl-b m` bound to that menu in a popup
over whatever is running.
"""

import fnmatch
import json
import math
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from collections import Counter
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path

from . import command_help, config, retention, terminal, update, usage
from .harness import LAUNCHER, load as harness_plugin

MARK = "@ak_orch"          # the tmux session option that says agentkit opened this seat
STATE_OPTION = "@ak_state"  # ... and the one that says what it is doing, for the bar and title
RUNS_OPTION = "@ak_runs"    # ... and the one that says what its runs add up to, for the bar
SOCKET_ENV = "AGENTKIT_TMUX_SOCKET"   # the test suite's way to a server of its own
SOCKET = "agentkit"        # the toolkit's own tmux server, never the user's default one
JOBS = "-jobs"             # appended to it: the server the background jobs run on
SLICE = "agentkit.slice"   # the user systemd slice every agent process is started inside
SEATS_SLICE = "agentkit-seats.slice"  # interactive sessions keep the default weight
RUNS_SLICE = "agentkit-runs.slice"    # detached runs are deliberately below sessions
OWN_CGROUP = Path("/proc/self/cgroup")   # ... and where this process says which cgroup holds it
CGROUP_ROOT = Path("/sys/fs/cgroup")     # ... where that cgroup, and the slice, say what they hold
NO_SLICE = "no slice (no user systemd manager)"   # ... on a host that has no manager to ask
SLICE_WAIT = 30            # how long `systemd-run` has to say whether it took a unit
NO_SUCH_UNIT = 5           # what `systemctl` answers about a unit it was never given
# What a placed launch writes before it becomes the work: the pid `exec` hands over, in a
# file named after the unit.  The mark is the evidence that the work started at all.
WITNESS = 'printf %s "$$" >"$0"; exec "$@"'
MANAGER_SOCKET = "systemd/private"   # what a running `systemd --user` leaves in $XDG_RUNTIME_DIR
# The record keys that say nobody is in this seat any more: its process is gone, however it
# went, and its number is the way back into the conversation it left behind.
CLOSED = ("exited", "resumable", "restart")
NAME_CAP = 40              # a session name the menu, the status bar and a phone can all show
SEEN_EVERY = 300           # how often a live seat's record is stamped with the time
CANNOT_PIN = 3             # the adapter's answer when its TUI cannot be told a conversation id
POPUP_KEY = "m"            # Ctrl-b m inside a seat: the menu, over whatever is running
POPUP_SIZE = "-w 80% -h 70%"          # the popup on a screen with room to spare around it
POPUP_FULL = "-w 100% -h 100%"        # ... and on a phone, where the border is all it spares
SMALL_CLIENT = "#{||:#{e|<:#{client_width},60},#{e|<:#{client_height},25}}"
HINT = "Ctrl-b m  menu"   # the right half of every seat's status bar: the one key
CLOSE_HINT = "Ctrl-b m  x close"   # ... and of a done one's, which that menu's `x` closes at once
BAR_LEFT = 120            # status-left-length: the left half is cut to it here, never by tmux
# A seat's status line: tmux's own default one, less the window list a seat does not show, with
# the left half cut, with one `…`, where it would run into the right half on the client drawing
# it -- so the one key stays whole on every client, a phone's included.
BAR_FORMAT = ("#[align=left range=left #{E:status-left-style}]#[push-default]"
              "#{T;=/#{e|-:#{client_width},#{e|+:#{w:status-right},1}}/…:status-left}"
              "#[pop-default]#[norange default]"
              "#[nolist align=right range=right #{E:status-right-style}]#[push-default]"
              "#{T;=/#{status-right-length}:status-right}#[pop-default]#[norange default]")
UPDATE_JOB = "update"      # the tmux session an update runs in, on the jobs server
UPDATE_RESULT = "update-result"   # where it leaves the one line the menu shows when it is done
AGENT_LOOK_EVERY = 10      # how long one reading of the process table answers for every pane
# The programs that run a script they are handed, which may be a harness (`node .../bin/codex`),
# each by its own option grammar: what starts an option, the short letters and long options
# that take the next word as their argument, and those after which there is no script file at
# all -- a command string, stdin, a module -- so no word that follows names what runs.
INTERPRETERS = (
    (re.compile(r"(?:ba|da|z|k|mk)?sh"), "-+", "oO", ("--rcfile", "--init-file"), "cs", ()),
    (re.compile(r"python[0-9.]*"), "-", "WX", ("--check-hash-based-pycs",), "cm", ()),
    (re.compile(r"node(?:js)?"), "-", "rC",
     ("--require", "--import", "--loader", "--experimental-loader", "--conditions",
      "--input-type", "--title", "--inspect-port", "--env-file"), "ep", ("--eval", "--print")),
)
# a finished run nobody has been told about yet; `interrupted` is here because a run the loop
# was thrown out of is exactly the kind nothing else will ever mention
REPORTABLE = ("pass", "fail", "error", "blocked", "exhausted", "interrupted")
_VERSIONS = {}             # installed harness builds, asked for once and only to name a refusal
_MANAGER = {}              # whether this host has a user systemd manager, asked once
_SLICE = {}                # ... and what its slice says about itself, for the same reason
_PROCESSES = {}            # the last reading of the process table, when, and whether it is held


def choose(cfg, providers):
    """(model, reason).  The default orchestrator, while it has something left to spend.

    Pace does not enter into it.  The orchestrator is the seat the user works from, so the only
    reason to pass the default over is that it cannot be spent at all: its gate meter, or the
    5h session window it runs inside, reads 100% used.  Then the first model in list order that
    can still be spent takes the seat.  Never refuses either -- a refusal costs more than an
    overspend, so with every model spent the default is launched anyway with a WARN.
    """
    default = cfg["defaults"]["orchestrator"]
    notes = []
    for name in [default, *(name for name in config.offered(cfg) if name != default)]:
        spent, why = usage.model_spent(cfg, name, providers)
        if not spent:
            return name, "; ".join([why] + notes)
        notes.append(f"skipped {name}: {why}")
    return default, (f"WARN {'; '.join(notes)}; every model is exhausted, "
                     f"launching {default} anyway")


@contextmanager
def for_seat(name):
    """Which seat the adapters called inside are building a command line for.

    In $AGENTKIT_SESSION, the name every part of agentkit says a seat by, because the rulebook
    an adapter writes at launch is that seat's -- and a launch is often made from another seat,
    whose name is the one this process inherited.
    """
    before = os.environ.get(config.SESSION_ENV)
    os.environ[config.SESSION_ENV] = name or ""
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(config.SESSION_ENV, None)
        else:
            os.environ[config.SESSION_ENV] = before


def command(cfg, name, conversation=None, fresh=False):
    """The TUI command line for this model, straight from its harness's adapter.

    Every harness can hold the seat: the adapter owns the flags, exactly as it does for a
    headless run, and nothing here knows what a bypass flag is called -- nor what resuming a
    conversation is spelled like, which is why the id is handed over as one more argument.

    `fresh` says that id names a conversation the harness has not opened yet and has to open its
    next one under -- Claude Code's `--session-id <uuid>` -- which is what lets a seat's
    conversation be written down before the seat exists.  A TUI that cannot be told one answers
    CANNOT_PIN, and then the answer here is None: that seat gets no launcher-issued id.
    """
    entry = config.model(cfg, name)
    adapter = config.adapter(entry["harness"])
    proc = subprocess.run([str(adapter), "interactive", entry["model"], entry["effort"],
                           *([conversation] if conversation else []),
                           *(["new"] if conversation and fresh else [])],
                          capture_output=True, encoding="utf-8", errors="replace")
    if fresh and proc.returncode == CANNOT_PIN:
        return None
    line = proc.stdout.strip()
    if proc.returncode != 0 or not line:
        raise config.Error(f"{adapter.name} interactive exited {proc.returncode} without a command "
                           f"for {name}: {proc.stderr.strip()[-300:]}")
    try:
        cmd = shlex.split(line)
    except ValueError as exc:
        raise config.Error(f"{adapter.name} interactive printed a command that will not parse "
                           f"({exc}): {line[:200]}")
    if not cmd:
        raise config.Error(f"{adapter.name} interactive printed no command for {name}")
    return cmd


def fresh_command(cfg, name, seat=None):
    """(command, conversation) for a seat opening a conversation of its own.

    The id is generated here, before anything starts, and handed to the adapter as one its
    harness has not opened yet, so the seat owns it from the moment it is launched.  A TUI that
    cannot be told an id -- Codex's, OpenCode's, Muse's -- gets its command without one, and that
    seat has no pinned conversation id. Codex records its actual id through a launch hook and
    OpenCode through its seat plugin; Muse restarts fresh.
    """
    conversation = str(uuid.uuid4())
    with for_seat(seat):
        cmd = command(cfg, name, conversation, fresh=True)
        if cmd:
            return cmd, conversation
        return command(cfg, name), None


# --- tmux sessions ----------------------------------------------------------


def socket_name():
    """The tmux server agentkit's seats live on.  Its own, and never the user's default one."""
    return os.environ.get(SOCKET_ENV) or SOCKET


def jobs_socket():
    """The server the toolkit's background work runs on: updates, never a seat.

    A sibling of the seats' server, so nothing the menu lists is a job and nothing a job does
    can be taken for a seat.
    """
    return socket_name() + JOBS


# --- the slice every agent process is started inside -------------------------
# The toolkit's processes are the machine's heaviest, and they were the ones with no ceiling
# of their own: a limit could only be put on the whole user unit, where the owner's own shells
# and editors sit under it too.  tmux 3.4 and newer put every pane in a scope under the slice
# its server was started in, so starting the server inside a slice of agentkit's own puts every
# pane, harness and run under one ceiling -- and leaves everything the owner starts by hand
# outside it.  The slice is transient: no unit file, no root, and nothing left behind when the
# last process in it exits.  `install.sh` writes the ceiling as a drop-in in the user's own
# unit directory.


def slice_name(socket=None):
    """The parent slice a server's processes live in: `agentkit.slice`, or a test child.

    systemd reads the dashes in a slice name as a path, so `agentkit-jobs.slice` is inside
    `agentkit.slice` and under the same ceiling -- and a test server's `agentkit-test.slice`
    is a corner of it that nothing the owner is running shares.
    """
    socket = socket_name() if socket is None else socket
    return SLICE if socket in ("", SOCKET) else f"{socket}.slice"


def seat_slice_name(socket=None):
    """The child slice for an interactive session on this server."""
    socket = socket_name() if socket is None else socket
    return SEATS_SLICE if socket in ("", SOCKET) else f"{socket}.slice"


def run_slice_name(socket=None):
    """The child slice for a detached run on this server."""
    socket = socket_name() if socket is None else socket
    return RUNS_SLICE if socket in ("", SOCKET) else f"{socket}-runs.slice"


def bus_env(env=None):
    """`env` with the user manager's bus in it, for a caller that inherited none.

    A tick from cron has no session at all, so `systemd-run --user` from one cannot find the
    manager that a login shell's environment points straight at.  The runtime directory is the
    uid's own, and the bus is the socket inside it; whatever the caller already carries is
    left alone, because a session that has its own is the authority on where its manager is.
    """
    env = dict(os.environ if env is None else env)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={env['XDG_RUNTIME_DIR']}/bus")
    return env


def user_manager():
    """Is there a user systemd manager here?

    A connection to the manager's own control socket is the answer.  Only a running
    `systemd --user` listens on one in the uid's runtime directory, so this says what neither
    a session bus address nor a file that is merely there can: a D-Bus socket may be
    anybody's, an address may name no path at all, and a socket left behind by a manager that
    has gone refuses the connection.  Connecting rather than asking `systemctl` is deliberate:
    this is on the way into every launch the toolkit makes, and a launch may not depend on
    starting a process of its own to find out whether it may start one.  A Mac, a container
    and a host without systemd all say no -- and every launch below then makes the plain start
    it always made.  Asked once per process: the answer cannot change under one command.
    """
    if "answer" not in _MANAGER:
        _MANAGER["answer"] = False
        if shutil.which("systemd-run"):
            control = Path(bus_env()["XDG_RUNTIME_DIR"], MANAGER_SOCKET)
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(5)
                    probe.connect(str(control))
                _MANAGER["answer"] = True
            except (OSError, ValueError):
                pass
    return _MANAGER["answer"]


def can_scope():
    """Can this process have a child of its own placed in the slice?

    Only from inside the user manager's own subtree.  A scope moves a process that already
    exists, and the kernel lets an unprivileged manager move one only within what it was
    delegated: a tick from cron sits in the system's own cgroup and may not be moved out of
    it, however reachable the manager is.  Work detached from there goes in as a service
    instead, which the manager starts inside the slice to begin with.
    """
    try:
        return f"user@{os.getuid()}.service" in OWN_CGROUP.read_text()
    except OSError:
        return False


def in_slice(argv, unit, socket=None, env=None, target_slice=None, properties=()):
    """(argv, env) for a command that starts a server inside the slice, or both unchanged.

    A scope where this process may be moved with its child: the command is this process's,
    its output and its exit status are what the caller reports, and the server it leaves
    behind keeps the scope, and the slice, for as long as it runs.

    Where a scope cannot be made -- a tick from cron sits in the system's own cgroup, which
    nothing unprivileged may move a process out of -- the manager starts the command itself,
    as a service, so that the tick's servers are in the slice like everybody else's.  That
    one is `Type=forking`, because what the command leaves behind is the server: the command
    exits, systemd keeps what it forked, and the unit lives as long as the server does.  Its
    exit status still says whether the server came up; what tmux said about it is the plain
    retry's to report.
    """
    target_slice = seat_slice_name(socket) if target_slice is None else target_slice
    if not user_manager():
        return argv, env
    if can_scope():
        scope_properties = []
        values = iter(properties)
        for value in values:
            if value == "-p":
                property_value = next(values, "")
                if property_value == "Nice=10":
                    continue
                scope_properties.extend((value, property_value))
            else:
                scope_properties.append(value)
        return (["systemd-run", "--user", f"--slice={target_slice}", "--scope",
                 "--quiet", f"--unit={unit}", *scope_properties,
                 *( ("--",) if scope_properties else ()), *argv], bus_env(env))
    return detached_in_slice(argv, unit, dict(os.environ if env is None else env),
                             socket=socket, forking=True, target_slice=target_slice,
                             properties=properties)


def detached_in_slice(argv, unit, env, output=None, socket=None, forking=False,
                      target_slice=None, properties=()):
    """(argv, env) for work the manager starts itself inside the slice.

    A service rather than a scope, because a scope moves the caller's own process into the
    slice and nothing unprivileged may move a process out of the system's cgroup, which is
    where cron puts a tick.  The manager starts a service itself, inside the slice, so it
    starts with the manager's environment and the manager's stdio instead of this process's:
    both are handed over by name.  `--collect` leaves nothing behind if it fails.

    A unit's command line is not a shell's: systemd reads a dollar there as the start of a
    variable and `$$` as one plain dollar, so every dollar in it is doubled and the command
    is handed exactly what it would have been handed by a scope.  Values handed over with
    `--setenv` are the unit's environment, not its command, and are left as they are.
    """
    target_slice = slice_name(socket) if target_slice is None else target_slice
    if not user_manager():
        return argv, env
    return (["systemd-run", "--user", f"--slice={target_slice}", "--quiet", "--collect",
             f"--unit={unit}",
             *([f"--property=StandardOutput=append:{output}"] if output else []),
             *(["--property=Type=forking"] if forking else []),
             *properties,
             *[f"--setenv={key}={value}" for key, value in sorted(env.items())],
             *( ("--",) if properties else ()),
             *[part.replace("$", "$$") for part in argv]],
            bus_env(env))


def marked_pid(marker, wait=0, parent=None):
    """The pid the placed work wrote for itself before it became the work, or None.

    `wait` is how long the manager is given to start the work: the mark is the only word on
    whether it ever ran, and that answer is worth waiting for.  `parent`, where the caller
    holds the process that carries the work, ends the wait early: a scope the manager never
    made takes its client with it, and there is nothing left to wait for.
    """
    deadline = time.monotonic() + wait
    while True:
        # read before the mark, so a client that went between the two is not believed over
        # the mark it left behind
        gone = parent is not None and parent.poll() is not None
        try:
            written = marker.read_text().strip()
        except OSError:
            written = ""
        if written.isdigit():
            marker.unlink(missing_ok=True)
            return int(written)
        if gone or time.monotonic() >= deadline:
            marker.unlink(missing_ok=True)
            return None
        time.sleep(0.02)


def stop_placed(unit, scoped, proc):
    """End a placement that is still on its way; True when nothing of it can come up.

    Left alone it would come up beside the plain start that follows, and the task would run
    twice.  A scope is this process's own to end: everything that launch made is in a process
    group of its own -- the client, and whatever it forks or becomes -- so the group is the
    whole of it.  A service is the manager's, so the manager is asked, and only its word
    counts: stopped, or a unit it does not have.  Anything else -- a refusal, a `systemctl`
    that will not run, one that does not answer in time -- leaves the placement in doubt, and
    a launch in doubt is never started a second time.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, TypeError):
        pass                    # already gone, or never a group of its own
    if scoped:
        return True
    try:
        stop = subprocess.run(["systemctl", "--user", "stop", f"{unit}.service"],
                              capture_output=True, encoding="utf-8", errors="replace",
                              env=bus_env(), timeout=SLICE_WAIT)
    except (OSError, subprocess.SubprocessError):
        return False
    return stop.returncode in (0, NO_SUCH_UNIT)


def unit_loaded(unit, uncertain=True):
    """Is a unit of that name still one the manager has?  Anything under it may yet run.

    Asked where an earlier attempt was left unresolved: a transient unit that has ended is
    collected and forgotten, so `not-found` is how the manager says that work is over.  An
    answer that does not come counts as a unit that is there, because the whole reason for
    asking is to not start a second copy of something that may still be running. Naming a
    new attempt passes `uncertain=None` so an unanswered probe does not become a long search.
    """
    try:
        shown = subprocess.run(["systemctl", "--user", "show", unit, "-p", "LoadState",
                                "--value"], capture_output=True, encoding="utf-8",
                               errors="replace", env=bus_env(), timeout=SLICE_WAIT)
    except (OSError, subprocess.SubprocessError):
        return uncertain
    return uncertain if shown.returncode != 0 else shown.stdout.strip() != "not-found"


def next_scope_unit(unit):
    """Choose a free transient name when a previous attempt still owns the base name."""
    if not user_manager():
        return unit
    for suffix in range(1, 100):
        candidate = unit if suffix == 1 else f"{unit}-{suffix}"
        state = unit_loaded(f"{candidate}.scope", uncertain=None)
        if state is None:
            # Let the wrapper attempt the original name and make its usual plain fallback
            # if the bus is still unavailable.
            return unit
        if not state:
            return candidate
    raise OSError(f"no free systemd scope name for {unit}")


def start_in_slice(argv, unit, env, output, log=lambda _: None, target_slice=None,
                   properties=(), nice=False, placement=None):
    """Start detached work inside the slice, appending its output to `output`; its pid.

    A scope where this process may be moved with its child; a service, which the manager
    starts inside the slice itself, where it may not -- cron's cgroup is the system's, and
    nothing unprivileged is moved out of that one, so work detached from a tick would
    otherwise be the one thing running outside the ceiling.

    The work says for itself whether it started, and nothing else is read as evidence.  A
    mark means it ran, however briefly; no mark means nothing ran at all -- a scope the
    manager would not make, a unit it took and never forked, a `systemd-run` that could not
    be started -- and only then is the work started the plain way it always was.  Neither
    timing nor an exit status can tell those apart, because a task that finishes at once and
    a task that never began look the same in both, and guessing there is what would run a
    task twice.  Raises OSError where the plain start fails, and where a placement can be
    neither confirmed nor ended -- there the work may still come up, and a second start of
    it is worse than none: the caller says so, and the next try is a clean one.

    An attempt leaves a claim behind until it is resolved, and the next start of the same
    work reads it before anything else: while the manager still has that unit -- or cannot
    be asked about it at all -- nothing new is started, whatever the unit is doing.
    Otherwise the attempt that could not be ended and the attempt after it would be two of
    the same task, one of them started by a manager that was only slow or briefly away.
    """
    target_slice = seat_slice_name() if target_slice is None else target_slice

    def set_scope(value, reason=None):
        if placement is not None:
            placement["scope"] = value
            if reason:
                placement["scope_reason"] = reason

    def spawn(command, environment, lower_nice=False):
        with open(output, "a") as out:      # the child keeps a descriptor of its own
            kwargs = {"stdout": out, "stderr": subprocess.STDOUT,
                      "stdin": subprocess.DEVNULL, "start_new_session": True,
                      "env": environment}
            if lower_nice:
                kwargs["preexec_fn"] = lambda: os.nice(10)
            return subprocess.Popen(command, **kwargs)

    # The claim an earlier attempt left is read first of all, before this host is even asked
    # whether it has a manager: a unit that may still come up is the reason not to start the
    # work, and a bus that cannot be asked about it is no reason to believe it is gone -- a
    # plain start then would be the second of that work, outside the slice as well.
    claim, marker = config.TMP / f"{unit}.placed", config.TMP / f"{unit}.launched"
    try:
        held = claim.read_text().strip()
    except OSError:
        held = ""
    if held and unit_loaded(held):
        raise OSError(f"{held} from an earlier start is still in {slice_name()}; the work is "
                      f"not started again beside it (its claim is {claim})")
    claim.unlink(missing_ok=True)

    if not user_manager():
        reason = "no user systemd manager"
        set_scope("none", reason)
        return spawn(argv, env, lower_nice=nice).pid
    config.TMP.mkdir(parents=True, exist_ok=True)
    marker.unlink(missing_ok=True)
    scoped = can_scope()
    # A scope has no ExecContext, so Nice=10 is rejected as a unit property.  Lower the
    # actual work command inside the scope; the service fallback keeps Nice as its property.
    witness = ["sh", "-c", WITNESS, str(marker),
               *( (["nice", "-n", "10"] if nice and scoped else []) ), *argv]
    service_properties = (*properties, *( ("-p", "Nice=10") if nice else () ))
    placed, placed_env = (in_slice(witness, unit, env=env, target_slice=target_slice,
                                   properties=properties) if scoped
                          else detached_in_slice(witness, unit, env, output,
                                                 target_slice=target_slice,
                                                 properties=service_properties))
    # written before the launch, so that a start this process does not live to finish is
    # still an attempt the next one knows to ask the manager about
    claim.write_text(f"{unit}.{'scope' if scoped else 'service'}")
    note = "nothing started in it"
    try:
        proc = spawn(placed, placed_env)
    except OSError as exc:
        proc, note = None, str(exc)
    if proc is not None:
        if scoped:
            # the client waits on the manager before the work can exist, so a client that is
            # merely still there says nothing yet: only the mark says the work is running,
            # and a client gone without one says it never will
            pid = marked_pid(marker, wait=SLICE_WAIT, parent=proc)
            waiting = pid is None and proc.poll() is None
        else:
            # the client is gone as soon as the manager has the unit, so its own status says
            # whether there is anything to wait for, and the mark says whether it was forked
            try:
                status = proc.wait(timeout=SLICE_WAIT)
                refused = status != 0
                if refused:
                    note = f"systemd-run exited {status}"
            except subprocess.TimeoutExpired:
                refused = False
            pid = None if refused else marked_pid(marker, wait=SLICE_WAIT)
            waiting = pid is None and not refused
        if pid:
            claim.unlink(missing_ok=True)      # placed and running: the unit is the work's
            set_scope(unit)
            return pid
        if waiting and not stop_placed(unit, scoped, proc):
            # it never said it was running, it was never refused, and it could not be ended
            # either: the manager may yet bring it up, and the plain start below would be
            # the second of it.  Nothing is started here at all, and the claim stays for
            # whoever tries next.
            raise OSError(f"{unit} is neither running in {slice_name()} nor stopped")
    claim.unlink(missing_ok=True)              # nothing of it is left to come up
    reason = f"systemd-run failed ({note})"
    set_scope("none", reason)
    log(f"WARN {unit} did not go into {target_slice} ({note}); started plainly")
    return spawn(argv, env, lower_nice=nice).pid


def stop_scope(scope, log=lambda _: None, wait=True):
    """Ask systemd to stop a detached run scope, including escaped grandchildren."""
    if not isinstance(scope, str) or not scope or scope == "none" or scope.startswith("none ("):
        return False
    if not user_manager():
        return False
    unit = scope if scope.endswith(".scope") else f"{scope}.scope"
    command = ["systemctl", "--user", "stop", unit]
    try:
        if wait:
            subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, env=bus_env(), timeout=SLICE_WAIT)
        else:
            subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True,
                             env=bus_env())
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"WARN could not stop {scope}.scope: {exc}")
        return False
    return True


def slice_cgroup():
    """The slice's own directory under the cgroup filesystem.

    Read, because asking `systemctl` would put a command between every screen and one line it
    prints.  Everything the manager runs is under `user@<uid>.service`, which this process's
    own cgroup line names when it is in there too and the usual layout names when it is not;
    systemd reads the dashes in a slice name as the path below it, so `agentkit-jobs.slice`
    is a directory inside `agentkit.slice`.
    """
    service = f"user@{os.getuid()}.service"
    try:
        line = next(row for row in OWN_CGROUP.read_text().splitlines() if row.startswith("0::"))
        parts = [part for part in line[3:].split("/") if part]
        root = CGROUP_ROOT.joinpath(*parts[:parts.index(service) + 1])
    except (OSError, ValueError, StopIteration):
        root = CGROUP_ROOT / "user.slice" / f"user-{os.getuid()}.slice" / service
    pieces = slice_name().removesuffix(".slice").split("-")
    return root.joinpath(*[f"{'-'.join(pieces[:depth + 1])}.slice"
                           for depth in range(len(pieces))])


def slice_ceiling():
    """The task ceiling the drop-ins set, or None where nothing sets one.

    `pids.max` comes into being with the slice's first process, and the ceiling is real before
    that: it is in the drop-in `install.sh` wrote, or in the one `systemctl --user
    set-property` persists beside it.  The last file to name it wins, which is how systemd
    reads them too.
    """
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    found = None
    for base in ("systemd/user", "systemd/user.control"):
        for path in sorted((config_home / base / f"{slice_name()}.d").glob("*.conf")):
            try:
                lines = path.read_text().splitlines()
            except OSError:
                continue
            for line in lines:
                key, _, value = line.partition("=")
                if key.strip() == "TasksMax" and value.strip().isdigit():
                    found = int(value.strip())
    return found


def _mem_total_mb(meminfo=None):
    """MemTotal in mebibytes, from `meminfo` or `/proc/meminfo`."""
    path = Path(meminfo) if meminfo else Path("/proc/meminfo")
    try:
        for line in path.read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def memory_spec_mb(text, mem_total_mb=None):
    """One systemd memory value in mebibytes, or None for `max` / `infinity`.

    A bare number is bytes, the way the cgroup file writes it.  `K`, `M`, `G` and
    `T` are the 1024-based suffixes systemd uses.  A percentage is a share of
    `mem_total_mb`, and is None until that total is known: guessing a share of an
    unknown machine is how a cap ends up larger than the slice above it.
    """
    text = text.strip()
    if text.lower() in ("", "max", "infinity"):
        return None
    match = re.fullmatch(r"(\d+)([KMGT%]?)", text, re.IGNORECASE)
    if not match:
        return None
    number = int(match.group(1))
    suffix = match.group(2).upper()
    if suffix == "%":
        if not mem_total_mb:
            return None
        return mem_total_mb * number // 100
    scale = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}
    return number * scale[suffix] // (1024 * 1024)


def slice_memory_max_mb(mem_total_mb=None, meminfo=None):
    """The slice's MemoryMax in mebibytes, or None when it sets none.

    This is the ceiling a run's own cap is a fraction of.  It is read from the
    drop-in rather than from the live cgroup, because the ceiling is real before
    the slice's first process and the file is what survives a reboot.  The last
    file to name it wins, as it does for the task ceiling.  A percentage needs
    MemTotal; pass it, or it is read once from `meminfo`.  `max` and `infinity`
    are no ceiling.
    """
    total = mem_total_mb
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    found = None
    for base in ("systemd/user", "systemd/user.control"):
        for path in sorted((config_home / base / f"{slice_name()}.d").glob("*.conf")):
            try:
                lines = path.read_text().splitlines()
            except OSError:
                continue
            for line in lines:
                key, _, value = line.partition("=")
                if key.strip() != "MemoryMax":
                    continue
                text = value.strip()
                if text.lower() in ("max", "infinity"):
                    found = None
                    continue
                if text.endswith("%") and total is None:
                    total = _mem_total_mb(meminfo)
                parsed = memory_spec_mb(text, total)
                if parsed is not None:
                    found = parsed
    return found


def slice_tasks():
    """(tasks running, the ceiling) as the slice says; None for either nothing says.

    A slice with nothing in it has no directory at all -- so it holds no tasks, and its
    ceiling is whatever its drop-ins ask for -- and one nobody gave a ceiling says `max`,
    which is not a number and is not reported as one.
    """
    numbers = []
    for name in ("pids.current", "pids.max"):
        try:
            value = (slice_cgroup() / name).read_text().strip()
        except OSError:
            value = ""
        numbers.append(int(value) if value.isdigit() else None)
    current, ceiling = numbers
    return (0 if current is None and ceiling is None else current,
            ceiling if ceiling is not None else slice_ceiling())


def slice_line():
    """The one line the screens say about where the agents run.  Asked once per process.

    `no slice` is not a warning.  A host with no user systemd manager starts its seats plainly,
    the way the toolkit always did, and this says which of the two happened here.
    """
    if "line" not in _SLICE:
        if not user_manager():
            _SLICE["line"] = NO_SLICE
        else:
            tasks, ceiling = slice_tasks()
            room = (f"{round(100 * tasks / ceiling)}% of its ceiling"
                    if tasks is not None and ceiling else "no ceiling set")
            count = tasks or 0
            _SLICE["line"] = (f"slice {slice_name()} · {count} "
                              f"task{'' if count == 1 else 's'} · {room}")
    return _SLICE["line"]


def tmux_argv(socket, *args):
    """One tmux command line.  `socket=""` is the default server, where the legacy seats are."""
    return ["tmux", *(["-L", socket] if socket else []), *args]


def tmux_env(client=False):
    """The environment a tmux command runs with: $TMUX dropped unless a client is wanted.

    Inside somebody else's tmux, $TMUX is what a bare tmux command would follow -- so it goes,
    and the server named on the command line is the only one that can be reached.  Only
    `switch-client` keeps it, because without it there is no client to switch.
    """
    return dict(os.environ) if client else {k: v for k, v in os.environ.items() if k != "TMUX"}


def tmux_out(*args, socket=None, client=False, unit=None):
    """(exit code, output) of one tmux command; 127 when there is no tmux to ask.

    `unit` names the transient scope a command that starts a server runs in, so that the
    server -- and every pane it ever opens -- lives in agentkit's slice.  Where the scope
    cannot be made, the command is run again plainly: a seat outside the ceiling is worth
    more than no seat at all, and the same is true of a job.
    """
    fix_term()
    socket = socket_name() if socket is None else socket
    argv, env = tmux_argv(socket, *args), tmux_env(client)
    if unit:
        argv, env = in_slice(argv, unit, socket, env)
    try:
        proc = subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace",
                              env=env)
    except OSError as exc:
        return 127, str(exc)
    if proc.returncode != 0 and unit and argv[0] != "tmux":
        return tmux_out(*args, socket=socket, client=client)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def dead(socket):
    """The sessions on that server whose panes have all exited but which tmux still holds."""
    rc, out = tmux_out("list-panes", "-a", "-F", "#{session_name}\t#{pane_dead}", socket=socket)
    if rc != 0:
        return set()
    alive, gone = set(), set()
    for line in out.splitlines():
        name, _, flag = line.partition("\t")
        (gone if flag == "1" else alive).add(name)
    return gone - alive


def agent_programs():
    """The names a process in a pane goes by when it is an agent: every adapter's harness.

    Each adapter names its harness's program as the first word of its `[update] version`
    command -- `grok` for Grok's -- and the adapter's own name stands for it besides;
    `[launch] programs` adds the names, as patterns, of what that command goes on to run --
    Muse's launcher execs `muse-bin-<build>`.  Read the way `config.seat_env_names` reads
    them: the adapter directory first, this checkout's own beside it.
    """
    override = os.environ.get(config.ADAPTER_DIR_ENV)
    roots = ([Path(override).expanduser(), config.REPO / "adapters"] if override
             else [config.REPO / "adapters"])
    found = set()
    for root in roots:
        try:
            paths = sorted(root.glob("*.toml"))
        except OSError:
            continue
        for path in paths:
            found.add(path.stem)
            try:
                facts = config.manifest(path.stem)
            except config.Error:
                continue
            block = facts.get("update")
            version = block.get("version") if isinstance(block, dict) else None
            if isinstance(version, list) and version and isinstance(version[0], str):
                found.add(Path(version[0]).name)
            block = facts.get("launch")
            named = block.get("programs") if isinstance(block, dict) else None
            found.update(n for n in named or [] if isinstance(n, str))
    return found


def program(words):
    """What a process is running: its own program, or the script file an interpreter was handed.

    Only an interpreter's script operand is a program, read past its options by its own grammar
    -- `bash -e /opt/bin/claude` and `python3 -O /opt/bin/claude` run claude -- and nothing is
    one where the interpreter was handed no file: `bash -c 'claude || sleep 600'` outlives the
    claude it started, and is bash.  `ssh claude sleep 600` runs ssh, whatever its host is called.
    """
    name = Path(words[0]).name if words else ""
    grammar = next((g for g in INTERPRETERS if g[0].fullmatch(name)), None)
    if grammar is None:
        return name
    _, starts, takes, long_takes, modes, long_modes = grammar
    rest = iter(words[1:])
    for word in rest:
        if word == "--":
            word = next(rest, "")
            return Path(word).name if word else name
        if word.startswith("--"):
            option = word.split("=", 1)[0]
            if option in long_modes:
                return name
            if option in long_takes and "=" not in word:
                next(rest, None)
            continue
        if word == "-":
            return name                   # the script is stdin
        if word[:1] in starts:
            for place, letter in enumerate(word[1:], 1):
                if letter in modes:
                    return name
                if letter in takes:
                    if place == len(word) - 1:
                        next(rest, None)  # its argument is the next word, not the script
                    break                 # ... or the rest of this one
            continue
        return Path(word).name
    return name


@contextmanager
def one_reading():
    """Everything inside shares one reading of the process table, however long it takes.

    The watch tick runs in one: its every `find` and every card asks what the panes are
    running, and one `ps` answers all of them.  Nested, it is the outer one's reading.
    """
    if _PROCESSES.get("held"):
        yield
        return
    _PROCESSES.clear()
    _PROCESSES["held"] = True
    try:
        yield
    finally:
        _PROCESSES.clear()


def processes():
    """{pid: (ppid, the words of its command)} from one `ps`, or None where there is none.

    Held for as long as `one_reading` lasts, else for AGENT_LOOK_EVERY seconds: a menu draw
    asks for every seat, and one table answers them all.  A failed reading is held too.
    """
    if "table" in _PROCESSES and (_PROCESSES.get("held")
                                  or time.monotonic() - _PROCESSES["at"] < AGENT_LOOK_EVERY):
        return _PROCESSES["table"]
    table = None
    try:
        proc = subprocess.run(["ps", "-A", "-ww", "-o", "pid=", "-o", "ppid=", "-o", "args="],
                              capture_output=True, encoding="utf-8", errors="replace")
    except OSError:
        proc = None
    if proc is not None and proc.returncode == 0:
        table = {}
        for line in proc.stdout.splitlines():
            words = line.split()
            try:
                table[int(words[0])] = (int(words[1]), words[2:])
            except (IndexError, ValueError):
                continue
    _PROCESSES.update(at=time.monotonic(), table=table)
    return table


def agentless(socket, names):
    """Of those sessions, the ones with no agent harness anywhere under a live pane of theirs.

    A pane the reading has not seen is newer than it, and says nothing yet; neither does
    anything tmux or `ps` could not answer, and nothing is called agentless on it.
    """
    if not names:
        return set()
    rc, out = tmux_out("list-panes", "-a", "-F", "#{session_name}\t#{pane_pid}\t#{pane_dead}",
                       socket=socket)
    if rc != 0:
        return set()
    panes = {name: [] for name in names}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] in panes and parts[1].isdigit() and parts[2] != "1":
            panes[parts[0]].append(int(parts[1]))
    table = processes()
    if table is None:
        return set()
    children = {}
    for pid, (ppid, _) in table.items():
        children.setdefault(ppid, []).append(pid)
    patterns = agent_programs()
    found = set()
    for name, pids in panes.items():
        if any(pid not in table for pid in pids):
            continue
        stack, seen = list(pids), set()
        while stack:
            pid = stack.pop()
            if pid in seen:
                continue
            seen.add(pid)
            running = program(table[pid][1])
            if any(fnmatch.fnmatchcase(running, pattern) for pattern in patterns):
                break
            stack.extend(children.get(pid, []))
        else:
            found.add(name)
    return found


def server_sessions(socket, marked_only, legacy):
    """The seats one tmux server is holding: name, path, created, attached, exited.

    On agentkit's own server a session agentkit did not start -- no mark and no record -- is a
    seat only while an agent runs in it: somebody's `tmux new` with a harness in it is one, and
    a watcher loop an orchestrator left there is nobody's, so it is never listed, carded or
    counted.  The process table is read only when there is such a session to ask about.
    """
    rc, out = tmux_out("list-sessions", "-F",
                       f"#{{session_name}}\t#{{session_path}}\t#{{session_created}}\t"
                       f"#{{session_attached}}\t#{{{MARK}}}", socket=socket)
    if rc != 0:
        return []
    found, strangers = [], set()
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 4:
            parts.append("")   # no mark: the last line's empty field went with the output's strip
        if len(parts) != 5 or (marked_only and parts[4] != "1"):
            continue
        try:
            created = int(parts[2])
        except ValueError:
            created = int(time.time())
        found.append({"name": parts[0], "path": parts[1], "created": created,
                      "attached": parts[3] not in ("", "0"), "exited": False,
                      "legacy": legacy, "resumable": False})
        if parts[4] != "1":
            strangers.add(parts[0])
    if strangers:
        idle = agentless(socket, strangers - set(config.session_records()))
        found = [session for session in found if session["name"] not in idle]
    exited = dead(socket) if found else set()   # a second ask, and only where there is a seat
    for session in found:
        session["exited"] = session["name"] in exited
    return found


def sessions():
    """Every seat tmux is holding, agentkit's own server first and the legacy ones after.

    The toolkit's server is the toolkit's, so every agent on it is a seat -- including one made
    by hand with `tmux new`, which is listed with no models rather than not at all -- and what
    runs no agent there is not (see server_sessions).  The user's
    default server is theirs, so only what carries agentkit's own mark is taken from it: the
    seats started before the toolkit had a server of its own.  Those are `legacy`; they attach
    where they are, and no new one is ever made there.
    """
    ours = server_sessions(None, False, False)
    names = {s["name"] for s in ours}
    legacy = [s for s in server_sessions("", True, True) if s["name"] not in names]
    return sorted(ours + legacy, key=lambda s: s["name"])


def find(name):
    """The seat by that exact name.  tmux targets below are `=name` for the same reason."""
    name = config.normalize_session(name)
    found = sessions()
    exact = next((s for s in found if config.normalize_session(s["name"]) == name), None)
    if exact or " " not in name:
        return exact
    return next((s for s in found if s["name"] == session_name(name)), None)


def on_own_server(session):
    """Is this seat on agentkit's own tmux server, the only one anything here writes to?

    The others are the user's, from before the toolkit had a server of its own; no option,
    no bar and no title is ever set on them.
    """
    return not session.get("legacy")


def watching(name):
    """Is anyone in that seat?  A seat whose harness has exited answers for nothing."""
    session = find(name)
    return bool(session) and not session.get("exited")


def ghost(name, record):
    """A seat only its record still holds: gone from tmux, resumable from the conversation."""
    return {"name": name, "path": record.get("cwd", ""),
            "created": record.get("created") or record.get("seen") or int(time.time()),
            "attached": False, "exited": False, "legacy": False, "resumable": True}


def listing(reconcile=True):
    """Every seat the menu offers: the ones tmux holds, and the ones only their record does.

    A seat whose tmux instance is gone is not a seat that never was -- the orchestrator's
    conversation is still in its harness's own store, and the record here says which one -- so
    it keeps its row, and its number opens the conversation where it stopped.
    A record whose harness keeps its row without owning anything -- `[conversation]
    always_offered`, because there ownership is evidence and not a field -- keeps it with that
    harness's own fresh-start explanation.

    `reconcile=False` is the reading one: deciding what a seat is may not rewrite its record
    on the way, so it takes the records exactly as they stand and infers no project for an old
    one.  The names and their order are the same either way, which is what keeps a seat's
    number the same on every screen.
    """
    found = sessions()
    kept = records() if reconcile else config.session_records()
    names = {s["name"] for s in found}
    for session in found:
        record = kept.get(session["name"], {})
        plugin = seat_plugin(record)
        if session.get("exited") and plugin.always_offered:
            session["resumable"] = bool(plugin.conversation(record, record.get("cwd")))
            if not session["resumable"]:
                session["restart"] = plugin.restart_word(record) or "starts fresh"
            else:
                session.pop("restart", None)
    ghosts = []
    for name, record in kept.items():
        if name in names:
            continue
        plugin = seat_plugin(record)
        owned = resumable(record)
        if owned or plugin.always_offered or unread_question(name):
            row = ghost(name, record)
            row["resumable"] = owned
            if not owned:
                row["restart"] = (plugin.restart_word(record)
                                  or "starts fresh; unread question retained")
            ghosts.append(row)
    found = found + ghosts
    projects = (session_projects(kept) if reconcile else
                {name: record.get("repo") for name, record in kept.items()})
    for session in found:
        session["repo"] = projects.get(session["name"])
    return sorted(found, key=lambda s: s["name"])


def checkouts():
    """Named checkouts directly under ~/code, including git worktrees (.git is a file),
    and agentkit's own checkout ~/agentkit, which lives beside ~/code rather than in it."""
    found = ([path for path in config.CODE.iterdir() if path.is_dir() and (path / ".git").exists()]
             if config.CODE.is_dir() else [])
    own = update.agentkit_dir()
    if (own / ".git").exists() and all(path.resolve() != own.resolve() for path in found):
        found.append(own)
    return sorted(found, key=lambda path: path.name)


def checkout_of(repo):
    """The checkout a repo path *is*, or None when it is none of them.

    A project is a named checkout under `~/code` or agentkit's own, so only a repo
    that is one of `checkouts()` names one: a run's worktree, a throwaway repo under
    ~/.agentkit/tmp, any other path outside ~/code and an unset repo are all no project.
    """
    if not repo:
        return None
    try:
        path = Path(repo).resolve()
    except (OSError, ValueError):
        return None
    for checkout in checkouts():
        try:
            if checkout.resolve() == path:
                return checkout
        except OSError:
            continue
    return None


def cwd_project(cwd):
    cwd = Path(cwd).resolve()
    return next((path for path in checkouts()
                 if cwd == path.resolve() or path.resolve() in cwd.parents), None)


def project_name(repo, fallback="no project"):
    return Path(repo).name if repo else fallback


def session_projects(kept):
    """Infer old records once, from launched runs; ties use the checkout's name."""
    from . import run
    missing = {name for name, record in kept.items() if "repo" not in record}
    votes = {name: Counter() for name in missing}
    if missing:
        for directory in run.run_dirs():
            if "smoke-" in directory.name:
                continue
            state = run.read_state(directory) or {}
            name = run.launched_session(state)
            repo = state.get("repo")
            if name in votes and isinstance(repo, str) and repo:
                votes[name][repo] += 1
        for name, counts in votes.items():
            repo = min(counts, key=lambda repo: (-counts[repo], project_name(repo), repo)) if counts else None
            config.update_session(name, repo=repo)
            kept[name]["repo"] = repo
    return {name: record.get("repo") for name, record in kept.items()}


def file_projectless(found, runs):
    """File each seat in `found` with no project under the one its runs vote for.

    A seat whose runs were all still queued when it last launched had nothing to vote then,
    and its record says no project until one of its runs votes.  `runs` are the run records
    the menu's draw or the tick has read anyway, so no run.json is read twice; the filing is
    `run.join_session_project`'s, under its lock, and a seat with no record is left alone.
    """
    from . import run
    orphans = {session["name"]: [] for session in found if not session.get("repo")}
    if orphans and runs:
        for state in runs:
            try:
                orphans.get(run.launched_session(state), []).append(state)
            except config.Error:
                continue
    for session in found:
        states = orphans.get(session["name"])
        if states and run.session_vote(session["name"], states):
            session["repo"] = run.join_session_project(session["name"], states)


BACK = object()  # `q` at a new-seat question: back to the menu, nothing created


def _seat_read(prompt):
    """One stripped line for a new-seat choice: Enter and the end of input take the default.

    Through `terminal.readline` like every other question the menu asks, because the screen
    that asked this one is waiting on the same stdin and must not find its next key gone.
    """
    answer = terminal.readline(prompt)
    if not sys.stdout.isatty():
        print()
    return "" if answer is None else answer.strip()


def alias_names(names=None):
    """The names a rename still leads from, which are nobody's to take.

    `ak orch rename`'s pointer: the seat that was renamed still carries its old name in
    $AGENTKIT_SESSION, so a new seat under that name would inherit its notifications and its
    model selection.  A pointer is in the way for as long as it leads somewhere -- to a session,
    to a record, or nowhere it can work out -- and free the moment it leads nowhere, which is
    what happens when the seat it led to is stopped or swept.  This is the one rule the menu
    and `create` both go by, so that they cannot disagree about whether a name is free.
    """
    names = {s["name"] for s in listing()} if names is None else names
    kept = records()
    return {old for old, target in config.session_aliases().items()
            if target == old or target in names or target in kept}


def taken_names():
    """Every name a new seat may not have: one the menu lists, one a rename still leads from,
    and one tmux holds for a session that is no seat, which `new-session` would refuse."""
    names = {s["name"] for s in listing()}
    return names | alias_names(names) | held_names()


def held_names():
    """Every session name agentkit's own tmux server holds, a seat's or not."""
    rc, out = tmux_out("list-sessions", "-F", "#{session_name}", socket=socket_name())
    return set(out.splitlines()) if rc == 0 else set()


def refuse_held(name):
    """Refuse a new seat a name tmux already holds, before its record or its card is touched.

    A watcher loop is no seat, but tmux will not start one beside it under the same name --
    and a record written first would make that watcher a seat.
    """
    if name in held_names():
        raise config.Error(f"tmux already holds a session named {name!r}, and it is no seat; "
                           f"pick another name")


def drop_aliases(name):
    """Forget the pointers a rename left leading to a seat that is gone.

    `ak orch rename foo bar` leaves `foo` pointing at `bar`, because the orchestrator in there
    was started as `foo` and hands that name to every `ak` it runs.  Once `bar` is stopped there
    is nobody left answering to either, so the pointer goes with the record it led to and `foo`
    is a name again -- rather than a file that outlives everything it referred to.
    """
    for old, target in config.session_aliases().items():
        if target == name:
            config.session_path(old).unlink(missing_ok=True)


def span(seconds):
    """A length of time in the one unit that says the most about it: `2d`, `3h`, `20m`, `45s`."""
    secs = max(0, int(seconds))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"{secs // size}{unit}"
    return f"{secs}s"


def age(created):
    return span(time.time() - created)


def session_name(raw):
    """The name as it will be carried everywhere: by tmux, by the menu, by every message.

    Lowercased, with spaces and slashes -- and the `:` and `.` tmux reads as target syntax --
    turned into dashes, so that one answer is both a tmux session name and one component of its
    state file's path.  Cut to 40 characters, which is what a phone shows whole.  Empty is
    empty: the caller asks again rather than inventing a name.
    """
    name = re.sub(r"[^a-z0-9_-]+", "-", config.normalize_session(raw).lower())
    return re.sub(r"-+", "-", name).strip("-")[:NAME_CAP].strip("-")


def seat_cwd():
    """Where a seat opened from the menu runs: ~/code, which is where the checkouts go."""
    config.CODE.mkdir(parents=True, exist_ok=True)
    return config.CODE


def tmux_word(text):
    """One word of a tmux config line.

    tmux quotes the way a shell does: inside single quotes everything is literal, and there is
    no escape for a `'` in there, so a string carrying one is written double-quoted instead,
    where the backslash, the quote, `$` and `#` are what tmux would otherwise read.
    """
    if "'" not in text:
        return f"'{text}'"
    for char in ("\\", '"', "$", "#"):
        text = text.replace(char, "\\" + char)
    return f'"{text}"'


def tmux_text(text):
    """Literal text for a tmux option: `#` is what starts a format, so it is doubled."""
    return text.replace("#", "##")


def popup_command():
    """What `Ctrl-b m` runs: this checkout's `ak`, on the interpreter it is installed against."""
    return shlex.join([sys.executable, str(config.REPO / "bin" / "ak"), "attach", "--overlay"])


def tmux_conf():
    """Write agentkit's own tmux config file and return its path.

    Its own file, handed to tmux with `-f`, because the user's ~/.tmux.conf is theirs: nothing
    here reads it and nothing here writes to it.  It holds the one binding a seat needs --
    `Ctrl-b m`, the menu in a popup over whatever is running -- and nothing else, because
    everything else a seat wants is a session option, set on the session itself.

    `-f` is only read when the tmux command is the one that starts the server, so `start` also
    loads this file into a server that was already up.  On agentkit's own server that is the
    whole of it; a key table and the two global options below belong to the server, so on the
    default server -- where the legacy seats are -- they reach the user's own sessions too.

    `mouse on` is what makes a touch scroll on the phone scroll the session's output instead of
    sending arrow keys into the harness, and 50000 lines of history is what there is to scroll.
    `remain-on-exit` is here as well as on the session itself, because a seat whose harness
    exits in the moment it opens has to survive that too, and the file is read before it runs.

    The popup is sized for the client that opens it, read when the key is pressed: on a
    phone -- under sixty columns or twenty-five rows -- it takes the whole screen but the
    border, because a popup of 80% by 70% of forty by twelve holds a key line and nothing to
    press it on; anywhere larger it is the 80% by 70% it always was.  `display-popup` takes
    no format for its size, so the choice is `if-shell -F`'s.
    """
    config.ensure_dirs()
    path = config.STATE / "tmux.conf"
    popup = tmux_word(popup_command())
    text = ("# written by `ak orch`; agentkit's own tmux config, never the user's ~/.tmux.conf\n"
            "set -g mouse on\n"
            "set -g history-limit 50000\n"
            "set -g remain-on-exit on\n"
            "set -g allow-passthrough on\n"
            'set -as terminal-features ",*:RGB"\n'
            f"bind-key {POPUP_KEY} if-shell -F {tmux_word(SMALL_CLIENT)} "
            f"{tmux_word(f'display-popup -E {POPUP_FULL} {popup}')} "
            f"{tmux_word(f'display-popup -E {POPUP_SIZE} {popup}')}\n")
    try:
        if not path.exists() or path.read_text() != text:
            path.write_text(text)
    except OSError as exc:
        raise config.Error(f"cannot write the tmux config {path}: {exc}")
    return path


def bar(name, orchestrator, word=None, last="", workers=()):
    """(status-left, status-right, set-titles-string): the seat's status bar, as text.

    The left half is the name, the orchestrator and the workers it hands runs to, the state
    word and the last column -- `herdr · fable → opus astra · ● working · tasks ███░░░░░ 2/5`
    -- the same values the menu row shows for that seat, in the same words, from the same
    function, cut to BAR_LEFT here with one ellipsis, since tmux would cut it anywhere,
    mid-glyph included; the right half is the one
    key, `Ctrl-b m  menu`, on every client -- `Ctrl-b m  x close` once the seat is done, the
    two keys that close it; the title is the name and the word.  Text
    rather than formats, so a rename and a change of word each rewrite the bar instead of
    the bar following an option: the tick and every menu draw write it through the one
    writer, and a rename writes it at once.  Without a word yet -- a seat just started --
    the bar carries the name and the orchestrator and the title the name, and never a
    guessed word.  `#` is doubled throughout, because a reason may carry one (`Merged
    #75`) and tmux would otherwise read it as a format.
    """
    head = f"{name} · {orchestrator}"
    if workers:
        head += f" {'→' if terminal.utf8() else '->'} {' '.join(workers)}"
    if word:
        head += f" · {terminal.state_text(word)}"
    if last:
        head += f" · {last}"
    head = terminal.cut(head, BAR_LEFT - 2)       # the two spaces that pad it are in the length
    title = f"{name} · {word}" if word else name
    hint = CLOSE_HINT if word == "done" else HINT
    return f" {tmux_text(head)} ", f" {tmux_text(hint)} ", tmux_text(title)


def dress(name, orchestrator, socket=None):
    """The seat's one-line status bar, before its first classification: who is in it.

    Only this session's options are touched, never the global ones, so a user's own tmux
    sessions on the same server keep the status bar they had.  The window list in the middle
    is blanked: a seat is one window, and the two halves are the whole line.  The tick or
    the next menu draw fills in the word and the last column through the one writer both
    share; until then the bar carries the name, the orchestrator and the one key.
    """
    left, right, title = bar(name, orchestrator)
    # set-titles is set here rather than in tmux.conf because that file is read by the default
    # server too, where the legacy seats are, and the user's own sessions there are theirs.
    for option, value in (("set-titles", "on"),
                          ("set-titles-string", title),
                          ("status", "on"),
                          ("status-left", left),
                          # the left half's length, which bar() cuts its own text to: tmux
                          # would cut past it mid-word, and mid-glyph
                          ("status-left-length", str(BAR_LEFT)),
                          ("status-right", right),
                          ("status-right-length", "80"),
                          ("window-status-format", ""),
                          ("window-status-current-format", "")):
        # set-option takes the session name plain: it is the one target that rejects `=name`
        tmux_out("set-option", "-t", name, option, value, socket=socket)


def set_runs(name, tally, socket=None):
    """Put that seat's run tally on its own status bar, in the tally's exact words.

    `tally` is what `ak orch list` says for that seat's runs (`<n> running`,
    `<n> needs you`) or nothing at all: merges and empty seats the list shows
    another way, so a seat with nothing going and nothing to look at draws no
    tally, not `0 running` -- so clearing is unsetting the option, and the bar
    draws what it always drew.  The one writer every tally source goes through (`ak run`,
    the tick, the menu), so three places never shell out with three formats.  Never
    raises: a seat gone mid-draw, tmux away, or a draw under test must not break the
    draw or the tick that is only dressing a bar.
    """
    socket = socket_name() if socket is None else socket
    try:
        if not tally or tally == "no runs yet":
            tmux_out("set-option", "-u", "-t", name, RUNS_OPTION, socket=socket)
        else:
            tmux_out("set-option", "-t", name, RUNS_OPTION, tally, socket=socket)
    except Exception:  # noqa: BLE001 - dressing a bar never breaks the work beneath it
        pass


def start(name, cwd, cmd, orchestrator):
    """Create the seat detached with AGENTKIT_SESSION in its environment, and mark it as ours.

    `remain-on-exit` is what makes the seat outlive the orchestrator process: a harness that
    exits, crashes or is quit leaves the session, its scrollback and its name where they were,
    and its number opens it again in the same pane -- on the conversation it was launched with,
    or, for a seat that was never given one, fresh.  Only `ak orch stop` ends a seat.
    """
    conf = tmux_conf()
    env = ["-e", f"{config.SESSION_ENV}={name}"]
    if os.environ.get(SOCKET_ENV):
        # the seat's own `ak` -- and the menu its Ctrl-b m opens -- has to reach this server
        env += ["-e", f"{SOCKET_ENV}={os.environ[SOCKET_ENV]}"]
    # First, into whatever server is already up: `-f` is read only by the command that starts
    # one, and `remain-on-exit` has to be in force before the seat exists, not a moment after --
    # a harness that exits as it starts would otherwise take the session with it.  On a server
    # that is not up this says so and does nothing, and `-f` below is what dresses that one.
    # Its answer is also what says whether this command is the one starting the server: only
    # that one can put the server, and every pane under it, in agentkit's slice.
    running = tmux_out("source-file", str(conf))[0] == 0
    rc, out = tmux_out("-f", str(conf), "new-session", "-d", "-s", name, "-c", str(cwd),
                       *env, shlex.join(cmd), unit=None if running else f"agentkit-seat-{name}")
    if rc != 0:
        raise config.Error(f"tmux could not start the session {name} in {cwd}: {out}")
    # set-option takes the session name plain: it is the one target that rejects `=name`
    tmux_out("set-option", "-t", name, MARK, "1")
    tmux_out("set-option", "-t", name, "remain-on-exit", "on")
    dress(name, orchestrator)


def unknown_term():
    """A replacement TERM when this box has no terminfo for the one in the environment, else None.

    tmux refuses a terminal it cannot describe -- "missing or unsuitable terminal" (seen from
    Ghostty as `missing or unsuitable terminal: xterm-ghostty`) -- so from a terminal whose
    terminfo was never installed here (Ghostty, kitty, Termius, anything new) it is not only
    the attach that fails: run from a tty, even `list-sessions` sets the terminal up first and
    refuses, and the menu then shows no seats for seats that are running.  `infocmp "$TERM"`
    is the check; when it fails the tmux command is run with TERM=xterm-256color.  The harness
    inside the session gets tmux's own TERM either way, so only this end is substituted.
    """
    term = os.environ.get("TERM")
    if not term or term == "xterm-256color":
        return None
    try:
        proc = subprocess.run(["infocmp", term], capture_output=True)
    except OSError:
        return "xterm-256color"  # no infocmp at all: assume the type is unknown here
    return None if proc.returncode == 0 else "xterm-256color"


_TERM_FIX = None


def fix_term():
    """Put a TERM tmux can work with in the environment, once, and return what to say about it."""
    global _TERM_FIX
    if _TERM_FIX is None:
        fallback = unknown_term()
        _TERM_FIX = ("" if not fallback else
                     f"note: this box has no terminfo for TERM={os.environ.get('TERM')}; "
                     f"tmux is run as {fallback}")
        if fallback:
            os.environ["TERM"] = fallback
    return _TERM_FIX


def seat_socket(session):
    """Which server holds that seat: agentkit's own, or -- for a legacy one -- the default."""
    return "" if (session or {}).get("legacy") else socket_name()


def inside(session):
    """Is this process a tmux client on the very server that seat is on?

    $TMUX names the socket the client is talking to, so this is what tells a switch-client
    (same server, no nesting) from an attach (another server, or no tmux at all).
    """
    tmux = os.environ.get("TMUX")
    if not tmux:
        return False
    return Path(tmux.split(",")[0]).name == (seat_socket(session) or "default")


def seen_by_user(name):
    """An interactive open records a baseline; reading a question does not answer it."""
    from . import notify, watch   # here, not at the top: watch imports this module
    try:
        name = config.resolve_session(name)
        session = find(name)
        if session and not session.get("exited"):
            # Cancel a tick already considering a nudge. An unanswered notice retains
            # its stop latch and row state; the generation alone is not acknowledgement.
            watch.forget(name, acknowledge=False, opening=True)
            watch.opened_now(name)      # `waiting for you` becomes `idle` from here on
            harness, _ = watch.seat_model(config.load(), name)
            notify.opened(name, lambda: watch.progress_output(harness, watch.pane_text(session)))
    except (config.Error, OSError) as exc:
        print(f"WARN could not record opening {name}: {exc}", file=sys.stderr)


def attach(name, log=print, wait=False):
    """Hand this terminal over to that session.  Never returns when it succeeds, unless `wait`.

    With no terminal to hand over -- a pipe, a script, the smoke suite -- there is nothing to
    attach to it: the session is running, and saying where it is is the whole answer.  `wait`
    is the menu's way in: it comes back when the user detaches, and the menu is drawn again.
    """
    name = config.resolve_session(name)
    session = find(name)
    socket = seat_socket(session)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        log(f"session {name} is running; attach it with "
            f"`{shlex.join(tmux_argv(socket, 'attach', '-t', name))}`")
        return 0
    if inside(session):
        # a client on this seat's own server: switch it, rather than nest one tmux in another
        rc, out = tmux_out("switch-client", "-t", f"={name}", socket=socket, client=True)
        if rc != 0:
            raise config.Error(f"cannot switch to the session {name}: {out}")
        seen_by_user(name)
        return 0
    note = fix_term()
    if note:
        log(note)
    cmd = tmux_argv(socket, "attach-session", "-t", f"={name}")
    env = tmux_env()      # $TMUX gone: from a client on another server this one nests on purpose
    seen_by_user(name)    # before the exec below, which never comes back here
    try:
        if wait:
            return subprocess.run(cmd, env=env).returncode
        os.execvpe(cmd[0], cmd, env)
    except OSError as exc:
        raise config.Error(f"cannot attach the session {name}: {exc}")


def resume(cfg, name, log=print, dry_run=False, wait=False, detached=False, hand_over=True):
    """Put the orchestrator back in a seat whose process is gone, and hand the terminal over.

    Two ways in, and the same ownership check either way. A seat tmux is still holding -- the
    harness exited under `remain-on-exit` -- gets its pane respawned, so the name, the
    scrollback and the window all stay where they were.  A seat tmux has lost is started again
    where it ran, out of its record.  The harness is handed the conversation id the record
    kept, and only that one, so what comes back is the seat's own conversation and never a
    stranger's.  A seat whose record names none -- one whose TUI could not be told an id, one
    from before any of this -- starts fresh under the same name, and owns whatever id the
    launcher can give it this time.

    `hand_over=False` is the same way in for a caller with no terminal -- a run whose seat is
    gone, the tick -- and it answers what came back instead of an exit code: "resumed" for
    the seat's own conversation, "fresh" for one under its name that has no past, and False
    for a seat that was live all along.
    """
    name = config.resolve_session(name)
    record = (config.session_records() if detached else records()).get(name) or {}
    session = find(name)
    if detached:
        if session:
            return 0       # automatic recovery never touches a surviving or legacy pane
        if not resumable(record):
            raise config.Error(f"{name}: conversation ownership is no longer verified")
    if session and not session.get("exited"):
        return attach(name, log=log, wait=wait) if hand_over else False
    if not session and not record:
        raise config.Error(f"no session {name!r} to resume and no record of one")
    selection = config.load_session(cfg, name, required=False)
    if not selection:
        raise config.Error(f"{config.session_path(name)} does not say which model held {name!r}")
    orchestrator = selection["orchestrator"]
    harness = config.model(cfg, orchestrator)["harness"]
    recorded = seat_conversation(record, harness)
    # the directory it ran in, unless that is gone -- a run's worktree, a checkout since
    # deleted -- in which case the seat opens where a new one would rather than not at all.
    # Whether its harness has opened that conversation yet is still asked where it ran: a
    # harness's store outlives the directory it was written for.
    ran_in = Path(record.get("cwd") or (session or {}).get("path") or "")
    if detached and (not record.get("cwd") or not ran_in.is_dir()):
        raise config.Error(f"{name}: recorded directory is unavailable: {ran_in}")
    cwd = ran_in if ran_in.is_dir() else seat_cwd()
    if recorded:
        cmd, conversation = resume_command(cfg, orchestrator, recorded, ran_in, seat=name), recorded
    else:
        cmd, conversation = fresh_command(cfg, orchestrator, seat=name)
    where = "in the same window" if session else f"in {cwd}"
    log(f"orch: resuming {name} on {orchestrator} {where}"
        + (f" (conversation {recorded})" if recorded
           else f" ({harness_plugin(harness).fresh_words})"))
    if dry_run:
        print(shlex.join(cmd))
        return 0
    launch(name, orchestrator, cwd, cmd, conversation, session)
    if not hand_over:
        # its own conversation only where the harness has opened it: an id nothing wrote
        # down is handed over as one to open, and the seat comes back with no past
        return "resumed" if recorded and opened(harness, ran_in, recorded) else "fresh"
    if detached:
        return 0           # restarting is neither attaching nor reading the seat
    config.update_session(name, seen=int(time.time()))
    return attach(name, log=log, wait=wait)


# --- the conversation a seat holds ------------------------------------------
#
# Claude owns a launcher-issued id. Codex owns only its launch hook's recorded thread.
# OpenCode owns the session its seat plugin reported into that launch's receipt.
# Muse still starts fresh. Cwd and timestamps never establish ownership.


def opened(harness, cwd, conversation):
    """Has that harness opened the conversation the seat was given, where it keeps them?

    Not a question of which conversation is the seat's -- that was settled by the launcher --
    only of whether the harness has written this one down yet, which is its plugin's to answer
    because only that harness knows where it keeps them.  A store nothing here knows is taken at
    its word: the id came from a launch, so it stands.
    """
    return harness_plugin(harness).opened(cwd, conversation)


def seat_harness(record):
    try:
        return config.model(config.load(), record.get("orchestrator"))["harness"]
    except config.Error:
        return None


def seat_plugin(record):
    """The harness plugin behind that seat: every hook, defaulted where it declares none."""
    return harness_plugin(seat_harness(record))


def records():
    """Let each harness reconcile its own evidence before anything claims a seat is resumable."""
    kept = config.session_records()
    for name, record in kept.items():
        fields = seat_plugin(record).reconcile(record)
        if fields:
            kept[name] = config.update_session(name, **fields) or record
    return kept


def resumable(record):
    """A conversation its harness owns: a launcher-issued id, or evidence of its own."""
    plugin = seat_plugin(record)
    cwd = record.get("cwd")
    return bool(plugin.resumable(record, cwd, plugin.conversation(record, cwd)))


def seat_conversation(record, harness=None):
    """The conversation that seat's harness says it owns, and never a guess at one."""
    plugin = harness_plugin(harness) if harness else seat_plugin(record)
    return plugin.conversation(record, record.get("cwd"))


def resume_command(cfg, model, conversation, cwd, seat=None):
    """The TUI command for a seat coming back on the conversation it owns.

    Its harness may never have opened one under that id, and then the id is handed over as one
    to open instead of one to resume; the seat keeps what it owns either way.
    """
    harness = config.model(cfg, model)["harness"]
    with for_seat(seat):
        if not opened(harness, cwd, conversation):
            fresh = command(cfg, model, conversation, fresh=True)
            if fresh:
                return fresh
        return command(cfg, model, conversation)


def launch(name, model, cwd, cmd, conversation, session=None):
    """Put the harness in the seat, and write down the conversation it was launched with.

    `session` is an exited pane to respawn.  What a launch owns is the harness's to write
    down -- a launcher-issued id by default -- and whatever else its plugin needs for that,
    Codex's per-invocation receipt among them, is carried into the command as environment.
    """
    env = seat_plugin({"orchestrator": model}).launched(name, cwd, conversation)
    if env:
        cmd = ["env", *(f"{key}={value}" for key, value in env.items()), *cmd]
    if session:
        # `=name:` -- the session, exactly, and its current window: respawn-pane wants a
        # pane, on whichever server holds the seat, which for a legacy one is not ours
        server = seat_socket(session)
        rc, out = tmux_out("respawn-pane", "-k", "-t", f"={name}:", shlex.join(cmd),
                           socket=server)
        if rc != 0:
            raise config.Error(f"cannot resume the session {name}: {out}")
        dress(name, model, server)
    else:
        start(name, cwd, cmd, model)
    from . import watch
    # launched under the name again: not the stopped one, and not the owner's closed one
    watch.seat_write(name, stopped_at=None, closed_by_owner=None)


def stamp():
    """Start an exit-retention clock once; dead panes must not keep winding `seen`."""
    now = int(time.time())
    found = {s["name"]: s for s in sessions()}
    for name, record in records().items():
        seat = found.get(name)
        if seat and (not seat.get("exited") or seat.get("attached")):
            if (record.get("exited_since") or type(record.get("seen")) not in (int, float)
                    or now - record["seen"] > SEEN_EVERY):
                config.update_session(name, seen=now, exited_since=None)
        elif seat and not record.get("exited_since"):
            config.update_session(name, exited_since=now)
        elif not seat and not record.get("seen"):
            config.update_session(name, seen=now)


def retire_exited(name):
    """tmux itself rechecks dead/attached/owned in the command that removes the seat.

    Only a single dead pane is automatically retired. An unfamiliar multi-pane layout, an
    unknown option, a legacy server or a failed probe can never authorize a kill.
    """
    rc, value = tmux_out("display-message", "-p", "-t", f"={name}:",
                         "#{session_id} #{pane_id} #{pane_dead_time}")
    parts = value.split()
    if rc or len(parts) != 3 or not re.fullmatch(r"\$[0-9]+ %[0-9]+ [0-9]+", value):
        return False
    sid, pane, died = parts
    if time.time() - int(died) < config.SESSION_STALE:
        return False                    # a respawn may have exited since the previous stamp
    conditions = ["#{pane_dead}", "#{==:#{session_attached},0}", "#{==:#{session_windows},1}",
                  "#{==:#{window_panes},1}", "#{==:#{@ak_orch},1}",
                  f"#{{==:#{{session_id}},{sid}}}", f"#{{==:#{{pane_id}},{pane}}}",
                  f"#{{==:#{{pane_dead_time}},{died}}}"]
    condition = conditions[0]
    for term in conditions[1:]:
        condition = "#{&&:" + condition + "," + term + "}"
    rc, _ = tmux_out("if-shell", "-F", "-t", f"={name}:", condition,
                     f"kill-session -t {shlex.quote('=' + name)}")
    return rc == 0 and session_absent(name)


def session_absent(name):
    """A failed tmux probe is not proof of absence (permissions and transport can fail too)."""
    rc, out = tmux_out("has-session", "-t", f"={name}")
    return rc == 1 and ("can't find session:" in out or "no server running on" in out or
                        ("error connecting to" in out and "(No such file or directory)" in out))


def seatless(name):
    """No seat holds that name, on tmux's own word: no session by it, or one with no agent in it.

    Asked of that one session afresh, and never taken from a listing a failed probe left empty.
    """
    if find(name) is not None:
        return False
    if tmux_out("has-session", "-t", f"={name}")[0] != 0:
        return session_absent(name)
    return name in agentless(None, {name})


def unread_question(name):
    path = config.notify_path(name)
    if not retention.present(path):
        return False
    # Seat maintenance is allowed to read normally, including on macOS and linked homes.
    # GC's strict no-atime reader must not turn every ordinary notice into an unread question.
    try:
        notice = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return True                   # an unreadable notice might still need an answer
    return not isinstance(notice, dict) or (notice.get("kind") == "needs" and not notice.get("seen"))


def sweep(log):
    """Retire old detached dead seats and stale records; preserve active job evidence."""
    from . import notify, run
    found = {s["name"]: s for s in sessions()}
    protected = set()
    for directory in run.run_dirs():
        state = run.read_state(directory)
        if state and run.unfinished(state):
            try:
                protected.add(run.launched_session(state))
            except (config.Error, TypeError, ValueError, AttributeError) as exc:
                log(f"WARN cannot identify the owner of {directory.name}: {exc}")
    now = time.time()
    for name, record in records().items():
        seat = found.get(name)
        since = record.get("exited_since") if seat else record.get("seen")
        if (name in protected or unread_question(name)
                or not retention.expired(since, now, config.SESSION_STALE)):
            continue
        # Resolve the configured directory, not the record itself: linked home directories
        # are supported, while linked/foreign/hard-linked record files remain ineligible.
        configured = config.session_path(name)
        path = configured.parent.resolve() / configured.name
        if not retention.safe(path) or path.with_suffix(".tmp").exists():
            continue
        if not seat and not session_absent(name):
            continue
        if seat and (seat.get("legacy") or not seat.get("exited") or seat.get("attached")
                     or not retire_exited(name)):
            continue
        log(f"forgot the session {name}, {'exited' if seat else 'gone'} for {age(since)}")
        for configured in (config.session_path(name), config.notify_path(name),
                           config.seat_state_path(name), config.hook_facts_path(name),
                           compact_path(name)):
            path = configured.parent.resolve() / configured.name
            if retention.safe(path):
                path.unlink(missing_ok=True)
        notify.forget_card(name, log)     # its questions on Discord closed, not left standing
        seat_plugin(record).forget(record)
        drop_aliases(name)


# --- background jobs, on a server of their own -------------------------------


def job_running(name):
    """Is that background job up?  They live on the jobs server, invisible to the menu."""
    return tmux_out("has-session", "-t", f"={name}", socket=jobs_socket())[0] == 0


def job_env():
    """The `-e` pairs a job is started with: this process's environment, not the server's.

    A session tmux creates inherits whatever environment the command that started that server
    happened to carry, which for a server-of-jobs is nobody's idea of a promise.  What a job
    needs is handed over by name instead.  $AGENTKIT_SESSION is not one of them: a job speaks
    for no seat.
    """
    keep = [key for key in ("HOME", "PATH", "SHELL", "USER", "LANG", "TERM", "TMUX_TMPDIR")
            if os.environ.get(key)]
    keep += [key for key in sorted(os.environ)
             if key.startswith("AGENTKIT_") and key not in (config.SESSION_ENV,
                                                            config.RUN_DIR_ENV)]
    return [arg for key in dict.fromkeys(keep) for arg in ("-e", f"{key}={os.environ[key]}")]


def start_update():
    """Start `ak update` detached on the jobs server, and say so in one line.

    Never in the menu's own process: an update runs the whole acceptance gate, and the phone
    that started it would take it down with the connection the moment its app is closed.  What
    it comes to is left in a file the menu reads once, so the answer arrives even though the
    question came back empty-handed.
    """
    if job_running(UPDATE_JOB):
        return "update is already running; the result will show here when it is done"
    config.ensure_dirs()
    log = config.TMP / f"update-job-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex}.log"
    path = config.STATE / UPDATE_RESULT
    result, half, ok = (shlex.quote(str(path)), shlex.quote(str(path) + ".part"),
                        shlex.quote(str(log)))
    ak = shlex.join([sys.executable, str(config.REPO / "bin" / "ak"), "update"])
    # written aside and moved into place, because the menu takes that file the moment it is
    # there: an empty one, read and deleted while the update was still running, would be the
    # whole answer the user ever got
    owner = shlex.join([sys.executable, "-m", "agentkit.retention"])
    register = f"PYTHONPATH={shlex.quote(str(config.REPO))} {owner}"
    script = (f"(set -C; : >{ok}) || exit 1; "
              f"{register} begin {ok} update $$ || :; "
              f"trap {shlex.quote(f'{register} finish {ok} || :')} EXIT; "
              f"if {ak} >{ok} 2>&1; then printf 'update: done (%s)\\n' {ok}; "
              f"else printf 'update: FAILED (%s)\\n' {ok}; fi >{half}; mv {half} {result}")
    running = tmux_out("list-sessions", socket=jobs_socket())[0] == 0
    rc, out = tmux_out("new-session", "-d", "-s", UPDATE_JOB, *job_env(), "sh", "-c", script,
                       socket=jobs_socket(),
                       unit=None if running else f"agentkit-job-{UPDATE_JOB}")
    if rc != 0:
        raise config.Error(f"could not start the update: {out}")
    return "update started; result will show here"


def job_notices():
    """What a finished background job left for the menu: shown once, then forgotten."""
    path = config.STATE / UPDATE_RESULT
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return []
    path.unlink(missing_ok=True)
    return [line.strip() for line in text.splitlines() if line.strip()]


def rename(old, new):
    """Give a running seat a new name, and move everything that carries it.

    tmux, the record, and every state file -- notify, seat, hook, compact, plan, card and
    stop -- all move, and every run the seat launched answers to the new name in its
    record; a pointer stays behind at the old name, because the orchestrator inside was
    started with the old name in its environment and hands it to every `ak` it runs --
    see config.resolve_session.  The bar is rewritten at once, so it never shows the old
    name until a tick.  `ak orch rename` and the in-session menu's `r` are both this one
    function.
    """
    old = config.resolve_session(old)
    new = session_name(new)
    session = find(old)
    if not session:
        known = ", ".join(s["name"] for s in sessions()) or "none"
        raise config.Error(f"no orchestrator session {old!r} (running: {known})")
    if new == old:
        return new
    if new in taken_names():
        raise config.Error(f"the name {new!r} is already spoken for")
    # on whichever server holds the seat: a legacy one is on the default server, and renaming it
    # there is the whole point of keeping it attachable
    from . import notify, run as run_mod, watch
    with watch.state_lock(), notify.session_lock(old), notify.session_lock(new):
        server = seat_socket(session)
        rc, out = tmux_out("rename-session", "-t", f"={old}", new, socket=server)
        if rc != 0:
            raise config.Error(f"tmux could not rename {old} to {new}: {out}")
        # New windows get the new name; the running orchestrator follows the alias.
        tmux_out("set-environment", "-t", new, config.SESSION_ENV, new, socket=server)
        config.rename_session(old, new)
        state = watch.load_state()
        if old in state["stalls"]:
            state["stalls"][new] = state["stalls"].pop(old)
        # Tombstone both generations so an in-flight tick cannot restore the old key or
        # overwrite the moved stop latch. The notice carries its open/progress facts itself.
        stamp = max(time.time(), math.nextafter(max(state["seen_at"].values(), default=0), math.inf))
        state["seen_at"].update({old: stamp, new: stamp})
        watch._write_state(state)
        for run_dir in run_mod.run_dirs():
            try:
                record = run_mod.read_state(run_dir)
            except (config.Error, OSError, ValueError):
                continue
            if not isinstance(record, dict):
                continue
            moved = False
            for key in ("launched_session", "session"):
                if record.get(key) == old:
                    record[key] = new
                    moved = True
            if moved:
                try:
                    run_mod.save_state(run_dir, record)
                except (config.Error, OSError, ValueError):
                    pass
        moved_seat = find(new)
        if moved_seat is not None and on_own_server(moved_seat):
            try:
                watch.announce_state(moved_seat)
            except (config.Error, OSError, ValueError):
                pass
    return new


# --- what `ak orch` does on the way in --------------------------------------


def reconcile(run, log):
    """Reap every run on the way in, so a loop that died is recoverable work and not `working`.

    Nothing is printed and nothing is marked reported: a run launched from a seat is that
    orchestrator's to hand back.  But a run whose process is gone still has to be found by
    something, and the overview's own draw is deliberately read-only, so this is where the
    menu notices -- `reap` marks it interrupted and raises its recovery notice, which goes to
    the seat that launched it and to nobody when no seat did.  A record too broken to read
    costs that run and no other.
    """
    for run_dir in run.run_dirs():
        try:
            state = run.read_state(run_dir)
            if state is not None:
                run.reap(run_dir, state)
        except (config.Error, OSError, TypeError, ValueError, AttributeError, KeyError) as exc:
            log(f"WARN cannot reconcile run {run_dir.name}: {exc}")


def maintenance(log=print):
    """Reap the dead loops and retire the stale seats -- everything before the seat opens.

    Nothing here runs a command against a repository.  Not the fast-forward and re-install this
    used to make on every menu open, and not the collection either: `run.schedule_gc` would
    start a collector that can `git worktree remove` a finished run's checkout, and a key
    pressed for the menu is no reason to run git anywhere.  The `ak watch` tick schedules it
    instead -- every three minutes, beside this same stamp and sweep -- and `ak run gc` does
    it on demand.

    The endings are not among them.  A run launched from a seat is the orchestrator's to hand
    back, and it does, with `ak notify done`; printing it to the owner as well opened the menu
    on a list of runs already reported, and on a smoke suite's throwaway runs besides.  What
    finished is in `r`, in the project overview and in `ak run status`.
    """
    from . import run   # here, not at the top: run.py imports this module to find the seats
    try:
        config.ensure_dirs()
        reconcile(run, log)
    except (config.Error, OSError, TypeError, ValueError, AttributeError, KeyError) as exc:
        log(f"WARN could not check the runs: {exc}")
    try:
        stamp()
        sweep(log)
    except (config.Error, OSError, TypeError, ValueError, AttributeError, KeyError) as exc:
        log(f"WARN could not check the sessions: {exc}")


# --- the commands -----------------------------------------------------------


def state_word(session, cfg=None):
    """What the listing calls a seat: working, needs you or done, and nothing else.

    One function decides it -- `watch.session_state` -- so the list, the menu, the overlay,
    the status bar and the window title can never say different words about the same seat.
    A listing reads the seat's own screen first, as it always did, and publishes the answer
    to that seat's bar; it writes no word of its own.
    """
    from . import watch   # here, not at the top: watch imports this module
    return watch.announce_state(session, cfg=cfg, look=True)["word"]


def harness_version(harness):
    """The installed build of that harness, for a line that has to name what cannot compact."""
    if harness not in _VERSIONS:
        from . import update   # here, not at the top: it is only wanted to name a refusal
        try:
            entry = next((h for h in update.harnesses() if h["name"] == harness), None)
            _VERSIONS[harness] = (update.version(entry) if entry else "") or "(version unknown)"
        except config.Error:
            # a config.toml or an adapter toml nobody can read names no build either
            _VERSIONS[harness] = "(version unknown)"
    return _VERSIONS[harness]


def compacts(session, cfg):
    """Whether this seat compacts itself, how, and when it last did.

    Auto-compaction is the seat's and never a worker's, and tools/idle-compact.py performs it the
    same way whatever the harness; the `[compact]` table of adapters/<harness>.toml says what
    that harness can do.  One that has no compact command, or reports no context size, is named
    with its installed build rather than guessed at.
    """
    record = config.session_records().get(session["name"], {})
    try:
        harness = config.model(cfg, record.get("orchestrator"))["harness"]
    except config.Error:
        return "unknown: this seat names no harness to read a [compact] table from"
    table = config.manifest(harness).get("compact")
    table = table if isinstance(table, dict) else {}
    if not table.get("command") or table.get("command") == "none":
        return f"no: {harness} {harness_version(harness)} has no compact command"
    if not table.get("context") or table.get("context") == "none":
        return f"no: {harness} {harness_version(harness)} does not report context size"
    answer = f"yes ({harness}, {table.get('signal') or 'screen'})"
    try:
        when = float(json.loads(compact_path(session["name"]).read_text())["last_compact_at"])
        # a record left by an earlier seat of this name compacted that one, not this one
        created = session.get("created")
        if not isinstance(created, (int, float)) or when >= created:
            return f"{answer}, compacted {age(when)} ago"
    except (config.Error, OSError, ValueError, TypeError, KeyError):
        pass
    return answer


def compact_path(name):
    """Where tools/idle-compact.py writes down that it compacted that seat."""
    return config.session_path(name).with_name(f"compact-{config.normalize_session(name)}.json")


def explain(session, cfg):
    """The `--why` block for one seat: its word, why it has it, on what, and since when.

    The word is one of the three every screen says; the evidence lines under it are the facts
    behind it.  A seat whose process is gone was never classified, and saying so is the honest
    answer rather than inventing a rule that matched.
    """
    from . import watch   # here, not at the top: watch imports this module
    found = watch.announce_state(session, cfg=cfg, look=True)
    lines = [f"{session['name']}  {found['word']}"]
    lines.append(f"  reason:    {found['reason'] or '-'}")
    if any(session.get(key) for key in CLOSED):
        lines.append("  authority: -     the process is gone; nothing here read its screen")
        lines.append(f"  compacts:  {compacts(session, cfg)}")
        return lines
    live = watch.seat_read(session["name"])
    since = found.get("since")
    when = (time.strftime("%Y-%m-%d %H:%M", time.localtime(since)) + f" ({age(since)} ago)"
            if isinstance(since, (int, float)) else "unknown")
    lines.append(f"  authority: {live.get('authority') or 'default'}"
                 f"  rule: {live.get('rule') or '-'}")
    lines.append(f"  evidence:  {live.get('evidence') or 'nothing on the screen said otherwise'}")
    lines.append(f"  since:     {when}")
    lines.append(f"  compacts:  {compacts(session, cfg)}")
    return lines


def cmd_why(argv):
    """`ak orch why NAME`: the same explanation, for one seat."""
    if command_help.show("orch why", argv):
        return 0
    if len(argv) != 1:
        raise config.Error("usage: ak orch why NAME")
    name = config.resolve_session(argv[0])
    session = next((s for s in listing() if s["name"] == name), None)
    if session is None:
        raise config.Error(f"no orchestrator session {argv[0]!r}; `ak orch list` shows them")
    print("\n".join(explain(session, config.load())))
    # Where there is no manager the seat's tmux server was started the way it always was, and
    # this is the one place that says so.
    plainly = "" if user_manager() else "; this seat's tmux server was started plainly"
    print(f"  slice:     {slice_line()}{plainly}")
    return 0


LIST_HEADERS = ["name", "project", "state", "tally", "orchestrator", "workers", "age"]


def _wrap_workers(workers, room):
    """One seat's worker list in whole names: wrapped at commas where the room
    runs out, never cut mid-name.

    A continued chunk keeps its trailing comma, so the pieces rejoin to the
    list; the last chunk stays bare. The comma is budgeted a cell, so a
    continued chunk still fits the room.
    """
    if terminal.cells(workers) <= room:
        return [workers]
    names, current, chunks = workers.split(","), "", []
    for name in names:
        added = name if not current else current + "," + name
        if current and terminal.cells(added + ",") > room:
            # the comma is budgeted, so a continued chunk still fits; only a
            # first name already filling the room keeps no comma to keep
            chunks.append(current + "," if terminal.cells(current) < room else current)
            current = name
        else:
            current = added
    if current:
        chunks.append(current)
    return chunks or [""]


def _narrow_table(rows, texts, notes, natural, width, gutter):
    """One seat's lines on a narrow screen: name and project first, then the
    state with its tally, the orchestrator with its age, then the workers.

    The project wraps whole onto a continuation, the tail splits across two
    lines, and each worker chunk keeps whole names: at phone widths every line
    stays within the width with nothing cut, and only a word longer than the
    screen itself is ever split.
    """
    name_room = natural[0]
    first_room = max(1, width - name_room - gutter)
    header = terminal.table_row(LIST_HEADERS[:2], [name_room, first_room], "", ["dim"] * 2)
    groups = []
    for row, text in zip(rows, texts):
        headed = terminal.title_lines(row[1], first_room)
        group = [terminal.table_row([row[0], headed[0]], [name_room, first_room])]
        for extra in headed[1:]:
            group.append(" " * (name_room + gutter) + extra)
        tail = [text, row[3], row[4], row[6]]
        if terminal.cells("  " + "  ".join(tail)) <= width:
            group.append(("  " + "  ".join(tail)).rstrip())
        else:
            group.append(("  " + "  ".join(tail[:2])).rstrip())
            group.append(("  " + "  ".join(tail[2:])).rstrip())
        room = max(1, width - gutter)
        group.extend("  " + chunk for chunk in _wrap_workers(row[5], room))
        if notes.get(row[0]):
            group.append("  " + notes[row[0]])
        groups.append(group)
    return header, groups


def list_table(found, cfg, tallies, width, selections=None):
    """The seats table: the same design as `ak run status`.

    Fixed columns with two-space gutters, sized once from the rows on screen:
    name, project, state (glyph and word from terminal.STATES), tally,
    orchestrator, workers (all of them, wrapped onto a continuation under the
    workers column if they do not fit, never cut), age. The checkout path
    shows only with `--why`. On a
    screen too narrow for the seven columns the header names the seat and its
    project, and the state, tally, orchestrator, age and workers ride their own
    lines under it, every name whole. `selections` carries the seat records the
    caller already loaded, so each record is read once per listing.
    """
    from . import menu   # here, not at the top: menu imports this module
    if not found:
        widths = [terminal.cells(head) for head in LIST_HEADERS]
        return terminal.table_row(LIST_HEADERS, widths, "", ["dim"] * 7), []
    try:
        installed_at = float((config.STATE / "installed-at").read_text())
    except (OSError, ValueError):
        installed_at = 0
    rows, notes = [], {}
    for s in found:
        if selections is not None and s["name"] in selections:
            selection = selections[s["name"]]
        else:
            try:
                selection = config.load_session(cfg, s["name"], required=False)
            except config.Error:
                selection = None
        word = state_word(s, cfg)
        rows.append([s["name"], project_name(s.get("repo")), word,
                     menu.tally(tallies.get(s["name"])),
                     selection["orchestrator"] if selection else "?",
                     ",".join(selection["workers"]) if selection else "?",
                     terminal.format_age(time.time() - s["created"])])
        restart = (selection and s["created"] < installed_at and harness_plugin(
            config.model(cfg, selection["orchestrator"])["harness"]).hooks_from_config)
        note = ("  ".join(part for part in ("legacy" if s.get("legacy") else "",
                                            "restart to pick up updates" if restart else "")
                           if part))
        if note:
            notes[s["name"]] = note
    texts = [terminal.state_text(row[2]) for row in rows]
    fixed = [0, 1, 3, 4, 6]
    natural = [max([terminal.cells(row[i]) for row in rows] + [terminal.cells(LIST_HEADERS[i])])
               for i in fixed]
    # natural is [name, project, tally, orchestrator, age]; the workers take
    # what is left beside them, wrapped at commas onto a continuation under
    # the workers column where they do not fit. Every width is sized once
    # here, from all the rows, so no column drifts from row to row.
    state_room = max([terminal.cells(line) for line in texts] +
                     [terminal.cells(LIST_HEADERS[2])])
    gutter = 2
    workers_room = max(1, width - sum(natural) - state_room - gutter * 6)
    if workers_room < 12:
        # The seven columns cannot stand side by side here: the header names
        # the seat and its project, and the state, tally, orchestrator, age
        # and workers ride their own lines under it, every name whole.
        return _narrow_table(rows, texts, notes, natural, width, gutter)
    wrapped = [_wrap_workers(row[5], workers_room) for row in rows]
    workers_width = max([terminal.cells(chunks[0]) for chunks in wrapped] +
                        [terminal.cells(LIST_HEADERS[5])])
    widths = [natural[0], natural[1], state_room, natural[2], natural[3],
              workers_width, natural[4]]
    header = terminal.table_row(LIST_HEADERS, widths, "", ["dim"] * 7)
    # a wrapped worker list continues under the workers column, the way a
    # wrapped title continues under the title column in `ak run status`
    worker_col = sum(widths[:5]) + gutter * 5
    groups = []
    for row, text, chunks in zip(rows, texts, wrapped):
        kinds = [None, None, terminal.state_colour(row[2]), None, None, None, "dim"]
        line = terminal.table_row([*row[:2], text, row[3], row[4], chunks[0], row[6]],
                                  widths, "", kinds)
        if notes.get(row[0]):
            line += "  " + notes[row[0]]
        groups.append([line.rstrip()] + [" " * worker_col + extra for extra in chunks[1:]])
    return header, groups


def print_slice():
    """The listing's last line: where the agents run, wrapped to the same layout as the rows."""
    for line in terminal.wrap(slice_line(), terminal.content_width()):
        print(terminal.styled(line, "dim"))


def cmd_list(argv):
    why = "--why" in argv
    if [arg for arg in argv if arg != "--why"] or argv.count("--why") > 1:
        raise config.Error("usage: ak orch list [--why]")
    found = listing()
    if not found:
        print("no orchestrator session; `ak orch <name>` starts one")
        print_slice()
        return 0
    from . import menu, run   # here, not at the top: menu imports this module
    cfg = config.load()
    # the same tally the seat's status bar carries, from the same one pass over the records
    tallies = run.seat_tallies(state for _, state in menu.run_records())
    # each seat's record is read once here and carried into the table, which
    # would otherwise read every seat again for the same rows
    selections, warnings = {}, []
    for s in found:
        try:
            selections[s["name"]] = config.load_session(cfg, s["name"], required=False)
        except config.Error as exc:
            selections[s["name"]] = None
            warnings.append(str(exc))
    header, groups = list_table(found, cfg, tallies, terminal.content_width(), selections)
    print(header)
    for s, group in zip(found, groups):
        print("\n".join(group))
        if why:
            # the checkout path and the seat's explanations, under its own row
            print(f"  path: {s['path']}")
            print("\n".join(explain(s, cfg)[1:]))
    print_slice()
    for warning in warnings:
        print(f"WARN {warning}", file=sys.stderr)
    return 0


def mark_owner_closed(name):
    """The mark a pause script leaves when it ends a seat the way `ak orch stop` does.

    The seat stays closed: no hand-back reopens it, and the endings wait for the owner's own
    reopening instead.  A launch under the name clears it again.
    """
    from . import watch
    watch.seat_write(name, stopped_at=time.time(), closed_by_owner=True)


# Every per-seat file kind a stop removes, and the daily collector takes once the seat is
# gone. Anything else under STATE with a hyphen -- usage resets, the browser's tabs, a
# preview record -- belongs to nobody's seat.
SEAT_FILE_KINDS = frozenset({"session", "seat", "notify", "card", "hook", "compact",
                             "plan", "stop", "rulebook"})


def session_owned_files(name):
    """Every `<kind>-<name>.*` file this seat owns, for a known per-seat kind, and the
    `idle-compact/<name>-<pid>.json` stamps its harness wrappers left -- under its name, or
    under an old one a rename left leading to it, since a rename moves neither its rulebook
    nor a stamp a running wrapper still writes to.

    The kind is the first component and the name the rest, so stopping `fix`
    takes `hook-fix.json` but leaves `session-atoll-fix.json`, `browser-tabs.json`
    and `<provider>-reset.json` alone. The seat-state file is included: the stop
    mark is written back afterwards, and it is the one record a later hand-back
    still reads.
    """
    name = config.normalize_session(name)
    if not isinstance(name, str) or not name or not config.STATE.is_dir():
        return []
    names = {name} | {old for old, now in config.session_aliases().items() if now == name}
    found = []
    for path in config.STATE.iterdir():
        stem, dot, ext = path.name.rpartition(".")
        kind, sep, rest = stem.partition("-")
        if (dot and ext and sep and kind in SEAT_FILE_KINDS and rest in names
                and path.is_file() and not path.is_symlink()):
            found.append(path)
    stamps = config.STATE / "idle-compact"
    for path in stamps.iterdir() if stamps.is_dir() else ():
        seat, dash, pid = path.name.removesuffix(".json").rpartition("-")
        if (path.name.endswith(".json") and dash and seat in names and pid.isdigit()
                and path.is_file() and not path.is_symlink()):
            found.append(path)
    return found


def cmd_stop(argv):
    """End a seat and everything it owns.

    The tmux session if there is one, and always the record behind it. Every run
    it launched is stopped the way `ak run stop` stops one, and each run's checkout
    and local branch go with it. The run directories stay: their results are collected
    by age. Its Discord card is closed as `Answered`, the way a gone seat's is, and the
    seat's `<kind>-<name>.*` state files go, then the stop mark is written
    back into the seat file so a hand-back still knows the owner ended it; the locks that
    writing it takes again go last, and the daily collector takes the mark a day later.
    A card Discord would not take the edit for stays, for the tick to close.
    Browser tabs the seat or its runs opened close; a tab with no recorded opener is left
    to the idle rule.

    The record is what would otherwise keep offering the seat back as `resumable`, so stopping
    takes both -- the conversation it owned with them, so that nothing can be resumed into it
    and no name is held by a pointer to a seat that is gone.  This is the one thing that ends a
    seat, and it is only ever the user's doing.

    A record is enough on its own: it is what holds the name, whether or not tmux still has the
    session -- a restarted server leaves nothing to kill -- and whether or not there was ever a
    conversation to come back to, since a seat that was given no id keeps its record and its
    name after tmux has lost it.  So either one is enough to stop, and whatever there is of
    each is taken.
    """
    if len(argv) != 1:
        raise config.Error("usage: ak orch stop <name>")
    from . import notify, watch
    # Stopping the session this runs in -- the overlay's `x`, or `ak orch stop` from the seat
    # itself -- hangs this very process up halfway through, and the menu redraws the moment
    # the attach drops, ahead of any unlink that comes after the kill: either way the record
    # stays behind as a ghost row.  So the files go first and the kill second, with SIGHUP
    # ignored across both; only the print at the end may still die on the dead pane, after
    # everything it reports is already true.
    old = signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        from . import run as run_mod
        name = config.resolve_session(argv[0])
        # Unfinished runs stop before the lock: each one costs up to STALL_KILL_WAIT
        # inside kill_tree, and nothing it touches is the seat's state. The peek is
        # best effort -- the lock below decides authoritatively -- so a name nobody
        # answers to stops nothing before it is refused.
        if find(name) is not None or name in records():
            run_mod.stop_owned_runs(name)
            notify.forget_card(name)   # before the lock too: a slow Discord holds up no tick
        # A stop and automatic boot recovery must agree on whether this seat exists.
        with watch.state_lock():
            session = find(name)
            record = records().get(name)
            if not session and not record:
                known = ", ".join(s["name"] for s in listing()) or "none"
                raise config.Error(f"no orchestrator session {name!r} (running: {known})")
            run_mod.release_session(name)
            if record:
                seat_plugin(record).forget(record)
            for path in session_owned_files(name):
                if path == config.card_path(name):
                    continue      # one Discord did not take the edit for: the tick closes it
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    print(f"WARN could not remove {path.name}: {exc}", file=sys.stderr)
            if session:
                rc, out = tmux_out("kill-session", "-t", f"={name}", socket=seat_socket(session))
                if rc != 0:
                    raise config.Error(f"could not stop the session {name}: {out}")
            # the owner ended this seat: a run of its that finishes later, or is still going,
            # brings it back through neither run.announce nor the tick, until a seat is
            # launched under the name again.  The hand-back reads `closed_by_owner` for the
            # same decision, and a pause script that ends a seat writes the same mark through
            # `mark_owner_closed`.
            watch.seat_write(name, stopped_at=time.time(), closed_by_owner=True)
        watch.forget(name)   # a new seat with this name must not inherit the old stop latch
        drop_aliases(name)
        # The mark and the latch above took the seat's and its notices' locks again, and a
        # seat that is gone has nothing left for them to serialize.
        for path in session_owned_files(name):
            try:
                if path.suffix == ".lock":
                    path.unlink(missing_ok=True)
            except OSError as exc:
                print(f"WARN could not remove {path.name}: {exc}", file=sys.stderr)
    finally:
        signal.signal(signal.SIGHUP, old)
    print(f"stopped {name}")
    return 0


def cmd_rename(argv):
    """`ak orch rename <new>` renames the seat this runs in; `rename <old> <new>` any seat."""
    if len(argv) == 1:
        old = config.current_session()
        if not old:
            raise config.Error("ak orch rename <new> renames the session it runs in, and this is "
                               "not one; use ak orch rename <old> <new>")
        new = argv[0]
    elif len(argv) == 2:
        old, new = config.resolve_session(argv[0]), argv[1]
    else:
        raise config.Error("usage: ak orch rename <new> | ak orch rename <old> <new>")
    if new.startswith("-"):
        raise config.Error(f"not a session name: {new!r}")
    new = rename(old, new)
    print(f"renamed {old} -> {new}")
    return 0


USAGE = ("usage: ak orch [name] [--model NAME] [--workers A,B] [--dry-run] | "
         "ak orch list [--why] | ak orch why NAME | "
         "ak orch stop <name> | ak orch rename [<old>] <new>")


def parse(argv):
    """The name and selection flags may come in either order."""
    name, forced, forced_workers, dry_run, i = None, None, None, False, 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--dry-run":
            dry_run, i = True, i + 1
        elif arg == "--model":
            if i + 1 >= len(argv):
                raise config.Error("--model needs a model name")
            forced, i = argv[i + 1], i + 2
        elif arg == "--workers":
            if i + 1 >= len(argv):
                raise config.Error("--workers needs a comma-separated list of model names")
            forced_workers, i = argv[i + 1], i + 2
        elif arg.startswith("-") or name is not None:
            raise config.Error(f"{USAGE}  (got {arg!r})")
        else:
            name, i = session_name(arg), i + 1
    return name, forced, forced_workers, dry_run


def unique_name(base, taken):
    """The base lowercased name made unique against taken names: `atoll`, then `atoll-2`.

    The number is kept inside NAME_CAP, the base giving way to it, so the name checked here is
    the very one `create` normalizes it to -- and never a name that is taken after all.
    """
    base = session_name(base or "")
    if not base or base not in taken:
        return base or None
    number = 2
    while True:
        name = session_name(f"{base[:NAME_CAP - len(str(number)) - 1]}-{number}")
        if name not in taken:
            return name
        number += 1


def default_name(orchestrator, taken):
    """Name after model choice: the orchestrator's lowercased name made unique."""
    return unique_name(orchestrator, taken)


def ask_name(taken, default=None):
    """`Name:` or `Name [default]:`, until there is one. `q` goes back.

    A seat is what the user calls it: the menu row, the status bar, the Discord title and the
    file the selection lives in are all this one word, so nothing here invents it.  Enter takes
    the default; an empty answer with no default asks again, and so does a name another seat
    already has. End of input (a script, a Ctrl-D) is the way out: None, and the caller goes
    back where it came from.
    """
    prompt = f"Name{f' [{default}]' if default else ''}: "
    while True:
        line = terminal.readline(prompt)
        if line is None:
            if not sys.stdout.isatty():
                print()
            return None
        raw = line.strip()
        if not sys.stdout.isatty():
            print()
        if raw.lower() == "q" or raw == terminal.ESC:
            return BACK
        if terminal.is_sequence(raw):
            continue
        name = session_name(raw or default or "")
        if not name:
            print("a session needs a name")
        elif name in taken:
            print(f"a session named {name} is already there; pick another name")
        else:
            return name


def prompt_orchestrator(cfg, default, providers, reason):
    """Orchestrator first: a number or a model name. Enter takes the default; `q` goes back.

    Every model is a choice.  When `choose()` passed the default orchestrator over, its reason
    follows the bracket in its own words: the skipped models, or the whole WARN when every
    model is spent anyway.  With the default taken, nothing follows.
    """
    names = config.offered(cfg)
    suffix = ""
    if default != cfg["defaults"]["orchestrator"] or reason.startswith("WARN"):
        _, own_why = usage.model_spent(cfg, default, providers)
        lead = own_why + "; "
        suffix = f" ({reason[len(lead):] if reason.startswith(lead) else reason})"
    answer = terminal.ask("Orchestrator", default, names, read=_seat_read, suffix=suffix)
    if answer is None:
        return BACK
    if answer == "":
        return default
    return answer


def prompt_workers(cfg):
    """Workers second: names or numbers separated by spaces or commas, or all.

    Every model is a choice, and Enter takes the default workers.  The visible prompt is
    `Workers [` followed by that list.  The parser is handed to `terminal.ask` so invalid input
    repeats the same choices and prompt, including its usual `not a choice` line.
    """
    names = config.offered(cfg)
    default = " ".join(cfg["defaults"]["workers"])

    def answer(raw):
        if raw.strip().lower() == "all":
            return names.copy()
        parts = [part for part in re.split(r"[\s,]+", raw.strip()) if part]
        if not parts:
            return None
        selected = []
        for part in parts:
            if part.isdigit() and 1 <= int(part) <= len(names):
                name = names[int(part) - 1]
            else:
                matches = [name for name in names if name.lower() == part.lower()]
                if len(matches) != 1:
                    return None
                name = matches[0]
            if name in selected:
                return None
            selected.append(name)
        return selected or None

    print()
    picked = terminal.ask("Workers", default, names, read=_seat_read, allow=answer)
    if picked is None:
        return BACK
    if picked == "":
        return list(cfg["defaults"]["workers"])
    return [picked] if isinstance(picked, str) else picked


def model_title(cfg, name):
    """`Opus 5.5`: the model's name and the version its id carries, as the screen lists it."""
    found = re.search(r"\d+(?:[.-]\d+)?", config.model(cfg, name)["model"])
    return f"{name.capitalize()} {found.group().replace('-', '.')}" if found else name.capitalize()


def spent_note(cfg, name, providers):
    """`spent · resets Fri 14:00` for a model with nothing left to spend, else ""."""
    meter = usage.spent_meter(cfg, name, providers)
    if meter is None:
        return ""
    when = usage.reset_when(meter)
    return f"spent · resets {when}" if when else "spent"


def picker_lines(cfg, notes, model, workers, at, room):
    """The new-session screen's body `room` columns wide, and the body lines each row is drawn on.

    Two groups, every model once in each: the orchestrator is one choice (`●`/`○`), the
    workers several (`■`/`□`).  Beside each model its harness and effort, dim, and where it is
    spent that too; a spent model reads dim all along.  The names take at most a third of the
    width, a longer one cut, so a long one cannot push the rest off a phone; a row still too
    wide wraps its detail under itself and puts the spent note on a line of its own under the
    name.  Row `at` is highlighted.
    """
    names = list(notes)
    marks = ("●", "○", "■", "□") if terminal.utf8() else ("(*)", "( )", "[x]", "[ ]")
    titles = {name: model_title(cfg, name) for name in names}
    wide = min(max(terminal.cells(title) for title in titles.values()), max(1, room // 3))
    lines, rows = [], []
    for group, heading in enumerate(("Orchestrator", "Workers")):
        lines += ["", terminal.styled(heading, "accent")]
        for name in names:
            chosen = name in workers if group else name == model
            entry = config.model(cfg, name)
            head = f"  {marks[2 * group + (not chosen)]} {terminal.pad(titles[name], wide)}   "
            detail, note = f"{entry['harness']} · {entry['effort']}", notes[name]
            parts = [f"{head}{detail}{f' · {note}' if note else ''}"]
            if terminal.cells(parts[0]) > room:
                parts = [*terminal.hang(head + detail, room),
                         *([f"    {terminal.cut(note, room - 4)}"] if note else [])]
            cut, first = 2 if note else len(head), len(lines)
            for number, part in enumerate(parts):
                line = part[:cut] + terminal.styled(part[cut:], "dim")
                lines.append(terminal.highlight(line, number == 0) if len(rows) == at else line)
            rows.append(range(first, len(lines)))
    return lines, rows


def pick(cfg, providers, default):
    """(orchestrator, workers) off one screen of selectors, BACK, or None with no terminal.

    `agentkit · new session`, `n` on a terminal: what Enter takes is chosen before a key is
    pressed -- `default`, which is `choose()`'s, and the default workers with something left
    to spend, or failing either the first model that has, the way `choose()` falls back.  A
    spent model is still a choice, only never a preselected one, so with every model spent
    nothing is chosen and Enter takes the highlight to the list that still wants a choice.
    ↑/↓, k/j and the wheel move through both groups, space or a click chooses, Enter starts
    from anywhere, Esc or `q` goes back.  The last worker stays chosen: a seat needs somebody
    to work for it.

    None where there is no terminal to take -- a pipe, a file, the smoke suite -- and the
    caller asks its two questions a line at a time.
    """
    names = config.offered(cfg)
    notes = {name: spent_note(cfg, name, providers) for name in names}
    fresh = [name for name in names if not notes[name]]
    model = next((name for name in [default, *names] if name in fresh), None)
    workers = [name for name in cfg["defaults"]["workers"] if name in fresh] or fresh[:1]
    with closing(terminal.Keyboard()) as keyboard:
        if not keyboard.take():
            return None
        return _picking(cfg, notes, model, workers)


@terminal.clicks_its_own
def _picking(cfg, notes, model, workers):
    """`pick`'s screen, drawn over in place and read with the keys, the way `terminal.scroll`
    is; the rows scroll to keep the highlight on a screen too short for both groups."""
    names = list(notes)
    at, top = names.index(model) if model in names else 0, 0
    keys = (f"{'↑↓' if terminal.utf8() else 'j/k'} move   space choose   "
            f"{'⏎' if terminal.utf8() else 'enter'} start   esc back")
    while True:
        body, rows = picker_lines(cfg, notes, model, workers, at, terminal.layout_width())
        room = max(1, terminal.height() - 5 - len(terminal.key_line(keys)))
        top = min(top, rows[at].start - (2 if at in (0, len(names)) else 0))
        top = max(0, min(max(top, rows[at].stop - room), len(body) - room))
        lines = [terminal.header_line("new session", time.strftime("%H:%M")),
                 terminal.rule_line(), *body[top:top + room], ""]
        spans = [(len(lines) + number, begin, end, key)
                 for number, line in enumerate(terminal.key_line(keys), 1)
                 for begin, end, key in terminal.key_spans(line)]
        lines += terminal.key_line(keys)
        sys.stdout.write("\033[H" + "".join(f"{line}\033[K\n" for line in lines) + "\033[J")
        sys.stdout.flush()
        key = terminal.read_key()
        if key is None:
            continue              # a resize: draw again
        if key.name == "click":
            item = next((item for row, begin, end, item in spans
                         if row == key.row and begin <= key.col <= end), "")
            line = key.row - 3 + top if 2 < key.row <= 2 + room else -1
            hit = next((row for row, drawn in enumerate(rows) if line in drawn), None)
            if item in ("⏎", "enter", "esc", "space"):
                key = terminal.Key({"⏎": "enter"}.get(item, item))
            elif hit is not None:
                at, key = hit, terminal.Key("space")
        if terminal.step(key):
            at = min(max(at + terminal.step(key), 0), len(rows) - 1)
        elif key.name == "space":
            name = names[at % len(names)]
            if at < len(names):
                model = name
            elif name not in workers:
                workers.append(name)
            elif len(workers) > 1:
                workers.remove(name)
        elif key.name == "enter":
            if model and workers:
                return model, list(workers)
            at = len(names) if model else 0     # the list that still wants a choice
        elif key.name in ("esc", "eof") or key.char in ("q", "Q"):
            return BACK


def worker_names(cfg, raw):
    names = [part.strip() for part in raw.split(",")]
    if not names or any(not name for name in names):
        raise config.Error("--workers needs a comma-separated list of model names")
    for name in names:
        config.model(cfg, name)
    if len(set(names)) != len(names):
        raise config.Error("--workers contains duplicate model names")
    return names


def select(cfg, providers, forced=None, forced_workers=None, prompting=True):
    """(orchestrator, reason, workers): the screen on a terminal, else the two prompts a line at
    a time, or their flags and defaults."""
    default, default_reason = choose(cfg, providers)
    picked = pick(cfg, providers, default) if prompting and not forced and forced_workers is None \
        else None
    if picked is BACK:
        return BACK
    if picked:
        return picked[0], default_reason if picked[0] == default else "selected", picked[1]
    if forced:
        config.model(cfg, forced)
        model, reason = forced, "--model"
    elif prompting:
        model = prompt_orchestrator(cfg, default, providers, default_reason)
        if model is BACK:
            return BACK
        reason = default_reason if model == default else "selected"
    else:
        model, reason = default, default_reason
    if forced_workers is not None:
        workers = worker_names(cfg, forced_workers)
    elif prompting:
        workers = prompt_workers(cfg)
        if workers is BACK:
            return BACK
    else:
        workers = list(cfg["defaults"]["workers"])
    return model, reason, workers


def create(cfg, name, cwd, forced=None, forced_workers=None, prompting=True, dry_run=False,
           selection=None, repo=None):
    """Select the models, record them, start the seat detached.  The TUI command it runs."""
    name = session_name(name)
    if not name:
        raise config.Error("a session needs a name")
    if name in alias_names():
        raise config.Error(f"{name!r} is what the session {config.resolve_session(name)!r} used "
                           f"to be called, and the orchestrator in it still answers to it; "
                           f"pick another name")
    refuse_held(name)
    if selection is None:
        providers = usage.collect(cfg)
        selected = select(cfg, providers, forced, forced_workers, prompting)
        if selected is BACK:
            return None
        selection = providers, selected
    providers, (model, reason, workers) = selection
    cmd, conversation = fresh_command(cfg, model, seat=name)
    # where and when, because that is what opens the seat again once tmux has lost it -- and the
    # conversation it owns, written down before it starts wherever its harness can be told one.
    # Not for a dry run: a conversation nothing ever opened is nobody's to be resumed into.
    extra = {"cwd": str(cwd), "repo": str(repo) if repo else None, "created": time.time()}
    if conversation and not dry_run:
        extra["conversation"] = conversation
        extra["id_source"] = LAUNCHER
    config.save_session(cfg, name, model, workers, extra)
    # a name may be used again once its seat is gone, and this seat has said nothing yet: the
    # last message of the one before it is not this one's state, and a question it left
    # standing on Discord is closed rather than dropped with its card -- by a start, never by
    # a preview of one
    if not dry_run:
        from . import notify
        notify.forget_card(name)
    config.notify_path(name).unlink(missing_ok=True)
    if dry_run:
        print(f"orch: {model} ({reason})")
        print(f"session {name} in {cwd} (new)")
        # before printing the tmux command, check infocmp "$TERM" the same way starting or
        # attaching would: an unknown type is exported as xterm-256color for the tmux command
        note = fix_term()
        if note:
            print(f"TERM=xterm-256color {shlex.join(cmd)}")
        else:
            print(shlex.join(cmd))
        return cmd
    from . import watch
    watch.forget(name)       # this is a new conversation, including when reusing a saved name
    if shutil.which("tmux") is None:
        # no tmux to outlive the connection: the seat is this terminal and ends with it, so
        # there is no record to keep and nothing to come back to
        os.environ[config.SESSION_ENV] = name
        try:
            os.execvp(cmd[0], cmd)
        except OSError as exc:
            raise config.Error(f"cannot exec {cmd[0]}: {exc}")
    launch(name, model, cwd, cmd, conversation)
    return cmd


def ensure(cfg, name, log=print, saved=False):
    """The seat by that name, started with the default selection if it is not running.

    For a caller with no terminal and nobody to ask -- `ak watch`, from cron -- so nothing here
    prompts, and the seat's cwd is where the checkouts are.  A name that was renamed leads to
    the seat it became, rather than to a second seat under a name that is already spoken for.

    `saved` is for a seat that was somebody's and whose process is gone: it comes back the way
    its number in the menu opens it -- on the conversation its record holds, in its own pane
    where tmux still has one -- and fresh only where nothing was recorded, never on this
    function's own selection.  The answer is then resume's: "resumed", "fresh", or False for a
    seat that is live; a seat with neither a pane nor a record is an error, not a new seat.
    """
    name = config.resolve_session(name)
    if saved:
        session = find(name)
        if session and not session.get("exited"):
            return False
        if not session and not records().get(name):
            raise config.Error(f"no session {name!r} to reopen and no record of one")
        return resume(cfg, name, log=log, hand_over=False)
    if find(name):
        return False
    refuse_held(name)
    providers = usage.collect(cfg)
    model, reason, workers = select(cfg, providers, prompting=False)
    cmd, conversation = fresh_command(cfg, model, seat=name)
    extra = {"cwd": str(seat_cwd()), "repo": None, "created": time.time()}
    if conversation:
        extra["conversation"] = conversation
        extra["id_source"] = LAUNCHER
    config.save_session(cfg, name, model, workers, extra)
    from . import watch
    watch.forget(name, acknowledge=False)  # cron may reset a latch, never answer a question
    launch(name, model, seat_cwd(), cmd, conversation)
    log(f"orch: started {name} on {model} ({reason})")
    return True


def main(argv):
    if command_help.show("orch", argv):
        return 0
    if argv[:1] == ["list"]:
        return cmd_list(argv[1:])
    if argv[:1] == ["why"]:
        return cmd_why(argv[1:])
    if argv[:1] == ["stop"]:
        return cmd_stop(argv[1:])
    if argv[:1] == ["rename"]:
        return cmd_rename(argv[1:])
    name, forced, forced_workers, dry_run = parse(argv)
    if not dry_run:
        maintenance()
    cfg = config.load()
    if name:
        session = find(name)
        if session and not session.get("exited"):
            print(f"orch: attaching to {name} in {session['path']} "
                  f"({age(session['created'])} old)")
            return 0 if dry_run else attach(name)
        if session or (records().get(name) and not (forced or forced_workers)):
            # the seat is not gone, only its process -- or the seat is gone and its record is
            # not.  Either way it is opened again as what it was, on the conversation it was
            # launched with where it was given one, and fresh where it was not.
            # Naming a model or a worker list is the one way to ask for a new seat by that name.
            return resume(cfg, name, dry_run=dry_run)
    selection = None
    if forced is not None and forced_workers is None:
        # Reject invalid flags before asking any interactive question.
        providers = usage.collect(cfg)
        select(cfg, providers, forced, prompting=False)
    elif forced_workers is not None and forced is None:
        # A worker flag skips that question, but the orchestrator still needs to be chosen.
        providers = usage.collect(cfg)
        worker_names(cfg, forced_workers)
    cwd = Path.cwd()
    repo = cwd_project(cwd)
    if selection is None and not name:
        providers = usage.collect(cfg)
        selected = select(cfg, providers, forced, forced_workers, prompting=True)
        if selected is BACK:
            return 0
        selection = providers, selected
    if not name:
        name = default_name(selection[1][0], taken_names())
    # A direct shell invocation keeps its working directory when no project is chosen.
    # The menu's n deliberately starts unassigned seats in ~/code instead.
    result = create(cfg, name, repo or cwd, forced, forced_workers, True, dry_run, selection, repo)
    if result is None:
        return 0
    return 0 if dry_run else attach(name)


def attach_main(argv):
    """`ak attach`: the menu, the way the phone key and the old habit both reach it."""
    from . import menu   # here, not at the top: menu imports this module
    return menu.main(argv)
