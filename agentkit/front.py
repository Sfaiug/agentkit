"""Which seat goes first, by the weight of what already holds it.

Seats share their slice's CPU, and one seat's test suite took it from the harness the owner was
scrolling.  So within the seats' share, the seats with a client and the unit holding the tmux
server go ahead of the other seats, and every seat stays below the runs.  No process changes
cgroup: a scope that ends takes its weight with it, and a weight a lost hook left is at worst
wrong until the next tick.  A host with no cgroup v2 or systemd user manager gets nothing and
loses nothing.
"""

import fcntl
import re
import subprocess

from . import config, host, orch

SEAT_SCOPE = re.compile(r"agentkit-seat-(.+)-[0-9a-f]{8}\.scope")   # as `orch.seat_command` has it
BEHIND = 100    # what systemd gives a unit nobody set


def seat_now(launched):
    """The session of a scope, which keeps the name its seat launched under through a rename.  A
    rename chain that cannot be followed leads to no session, so that scope alone has no client."""
    try:
        return config.resolve_session(launched)
    except config.Error:
        return launched


def scopes():
    """{directory: the name its seat launched under} of each seat's scope under the seats' slice,
    {} where the slice cannot be read."""
    try:
        return {path: seat[1] for path in (orch.slice_cgroup() / orch.seat_slice_name()).iterdir()
                if (seat := SEAT_SCOPE.fullmatch(path.name)) and path.is_dir()}
    except OSError:
        return {}


def once():
    """Set each weight under the seats' slice that does not read what it should.  One attach
    starts two passes at once, from two of its hooks, so a pass reads and sets under one lock:
    whoever sets last has read last."""
    config.ensure_dirs()
    with (config.STATE / "front.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _weigh()


def _weigh():
    """systemd sets each weight, not the file: a value written straight into the cgroup is
    dropped by a later reload.  Each is read just before it is decided, since the first call
    turns the controller on for the rest."""
    code, out = orch.tmux_out("list-sessions", "-F",
                              "#{session_attached}\t#{pid}\t#{session_name}")
    rows = [row.split("\t", 2) for row in out.splitlines()] if code == 0 else []
    rows = [row for row in rows if len(row) == 3]
    if not rows:
        return
    attached = {name for clients, _, name in rows if clients != "0"}
    first = {path: seat_now(launched) in attached for path, launched in scopes().items()}
    server = (host.process_cgroup(rows[0][1]) or "").rpartition("/")[2]
    if server and (unit := orch.slice_cgroup() / orch.seat_slice_name() / server).is_dir():
        first[unit] = True
    try:
        for path, ahead in first.items():
            weight = host.CPU_WEIGHT_MAX if ahead else BEHIND
            if host._cpu_weight(path) != weight:
                subprocess.run(["systemctl", "--user", "set-property", "--runtime", path.name,
                                f"CPUWeight={weight}"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, env=orch.bus_env(),
                               timeout=orch.SLICE_WAIT)
    except (OSError, subprocess.SubprocessError):
        pass    # nothing to weigh, or nothing to ask: the rest would fare the same
