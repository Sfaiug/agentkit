"""Which `ak` command a process was started under: the mark, and the starts kept free of it.

A run's processes carry its marker (`worker.RUN_MARKER`).  Every `ak` command carries MARK,
which `bin/ak` sets just before it runs one (`mark`), so all it starts inherits it: what an `ak`
outside a run -- the menu, the tick, an `ak` a seat or a hook runs -- leaves running is told
apart by it.  What ak starts to outlive the command -- a unit, a tmux server, a seat's pane, the
warm server, a detached start, a sign-in whose browser is the owner's -- is started `unmarked`:
it is no command's leftover.
"""

import os

from . import host
from .warm import MARK   # its home there, as the warm client imports no agentkit


def mark(command):
    """Mark this process, and so everything it starts, as `ak <command>`'s.

    The value is `<pid namespace> <pid> <start> <session> <command>`: the namespace's inode,
    the pid and the start in clock ticks name this process alone, as no process given its pid
    later starts at the same tick, and its POSIX session tells what it left there from what left
    for a session of its own.  Where /proc cannot say, the mark inherited, if any, stays.
    """
    try:
        namespace = os.stat("/proc/self/ns/pid").st_ino
    except OSError:
        return
    stat = host.proc_stat("self")
    if stat is not None:
        os.environ[MARK] = f"{namespace} {os.getpid()} {stat.start} {stat.session} {command}"


def unmarked(env=None):
    """`env`, this process's own where none is given, without the mark."""
    return {key: value for key, value in (os.environ if env is None else env).items()
            if key != MARK}
