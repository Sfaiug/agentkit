"""Which `ak` command a process was started under: the mark, and the starts kept free of it.

A run's processes carry its marker (`worker.RUN_MARKER`).  Every `ak` command carries MARK,
which `bin/ak` sets just before it runs one (`mark`), so all it starts inherits it: what an `ak`
outside a run -- the menu, the tick, an `ak` a seat or a hook runs -- leaves running is told
apart by it.  What ak starts to outlive the command -- a unit, a tmux server, a seat's pane, the
warm server, a detached start, a sign-in whose browser is the owner's -- is started `unmarked`:
it is no command's leftover.  What one leaves in its session, the tick ends once it is gone.
"""

import os
import re
import shlex
import signal
import time

from . import host
from .warm import MARK   # its home there, as the warm client imports no agentkit

GRACE = 5   # seconds a leftover sent TERM has to end before the sweep's second look KILLs it


def mark(command):
    """Mark this process, and so everything it starts, as `ak <command>`'s.

    The value is `<pid namespace> <pid> <start> <session> <command>`: the namespace's inode,
    the pid and the start in clock ticks name this process alone, as no process given its pid
    later starts at the same tick, and its POSIX session tells what it left there from what left
    for a session of its own.  Where /proc cannot say, the mark inherited, if any, stays.
    """
    namespace, stat = _namespace(), host.proc_stat("self")
    if namespace is not None and stat is not None:
        os.environ[MARK] = f"{namespace} {os.getpid()} {stat.start} {stat.session} {command}"


def unmarked(env=None):
    """`env`, this process's own where none is given, without the mark."""
    return {key: value for key, value in (os.environ if env is None else env).items()
            if key != MARK}


def leftovers():
    """Each process a gone `ak` left in its session, by a look of its own at /proc: (pid, start,
    its command's words, that `ak`'s pid, its command).  Gone: the mark's pid names no process,
    an exited one, or one with another start.  Never one in another session: a service someone
    started on purpose, as is all of its session.  Nor one of a run, a tmux server or anything
    below it, another HOME's, or one marked in another pid namespace, whose pids are not ours.
    """
    from .worker import RUN_MARKER   # here, not at the top: every `ak` imports this module
    namespace, home = _namespace(), os.environ.get("HOME")
    try:
        stats = {pid: stat for pid in map(int, filter(str.isdigit, os.listdir(host.PROC)))
                 if (stat := host.proc_stat(pid)) is not None}
    except OSError:
        return []
    found = []
    for pid, stat in stats.items():
        env = dict(pair.split("=", 1) for pair in _proc(pid, "environ").split("\0") if "=" in pair)
        marked = re.fullmatch(r"(\d+) (\d+) (\d+) (\d+) (.+)", env.get(MARK, ""))
        if not marked or stat.exited or RUN_MARKER in env or env.get("HOME") != home:
            continue
        inode, ak, start, session = map(int, marked.groups()[:4])
        if (inode == namespace and stat.session == session and not _under_tmux(pid, stats)
                and ((was := stats.get(ak)) is None or was.exited or was.start != start)):
            words = [word for word in _proc(pid, "cmdline").split("\0") if word]
            found.append((pid, stat.start, words, ak, marked[5]))
    return found


def sweep(log):
    """End what gone `ak`s left in their sessions: TERM to each process a look finds and, only
    where one went, KILL GRACE later to each a second look finds.  Each look starts from
    scratch, so one that has become a process the sweep never ends meanwhile gets no KILL."""
    if _signal(signal.SIGTERM, log):
        time.sleep(GRACE)
        _signal(signal.SIGKILL, log)


def _signal(number, log):
    """That signal to each process a look finds, each logged; whether any got it."""
    sent = [found for found in leftovers() if _send(*found[:2], number)]
    for pid, _, words, ak, command in sent:
        log(f"{number.name.removeprefix('SIG')} to {shlex.join(words)} (pid {pid}), "
            f"which a gone `ak {command}` (pid {ak}) left running")
    return bool(sent)


def _send(pid, start, number):
    """Whether that signal went to the process at that pid, sent only if it started at `start`:
    a pidfd holds the process the pid named as it opened, and while the pid names one with that
    start, that one is it."""
    try:
        held = os.pidfd_open(pid)
        try:
            if (stat := host.proc_stat(pid)) is None or stat.start != start:
                return False
            signal.pidfd_send_signal(held, number)
            return True
        finally:
            os.close(held)
    except OSError:
        return False


def _namespace():
    """This process's pid namespace, by its inode, or None where /proc cannot say."""
    try:
        return os.stat("/proc/self/ns/pid").st_ino
    except OSError:
        return None


def _under_tmux(pid, stats):
    """Whether that process is a tmux server, by the name tmux gives it, or below one.  `stats`
    is read a process at a time, so a pid given anew between two reads can close a loop of
    parents: the walk ends where it would come back."""
    seen = set()
    while pid in stats and pid not in seen:
        if _proc(pid, "comm") == "tmux: server\n":
            return True
        seen.add(pid)
        pid = stats[pid].ppid
    return False


def _proc(pid, name):
    """That file of the process in /proc, as text; empty where it cannot be read."""
    try:
        return (host.PROC / str(pid) / name).read_bytes().decode(errors="replace")
    except OSError:
        return ""
