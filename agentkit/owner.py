"""Which `ak` command a process was started under: the mark, and the starts kept free of it.

A run's processes carry AGENTKIT_RUN (`worker.RUN_MARKER`).  Every `ak` command carries MARK,
which `bin/ak` sets just before it runs one (`mark`), so all it starts inherits it: what an `ak`
outside a run -- the menu, the tick, an `ak` a seat or a hook runs -- leaves running is told
apart by it.  What ak starts to outlive the command -- a unit, a tmux server, a seat's pane, the
warm server, a detached start, a sign-in whose browser is the owner's -- is started `unmarked`:
it is no command's leftover.
"""

import os

from . import config, host

MARK = "AK_OWNER"   # `warm.MARK` spells it again: the warm client imports no agentkit


def mark(command):
    """Mark this process, and so everything it starts, as `ak <command>`'s.

    The value is `<pid namespace> <pid> <start> <command> <seat>`: the namespace's inode, the
    pid and the start in clock ticks name this process alone, as no process given its pid later
    starts at the same tick; the seat, last as the one free-form field, is $AGENTKIT_SESSION, ""
    outside a seat.  Where /proc cannot say, the mark inherited, if any, stays.
    """
    stat = host.proc_stat("self")
    try:
        namespace = os.stat("/proc/self/ns/pid").st_ino
    except OSError:
        return
    if stat is not None:
        os.environ[MARK] = (f"{namespace} {os.getpid()} {stat.start} {command} "
                            f"{os.environ.get(config.SESSION_ENV, '')}")


def unmarked(env=None):
    """`env`, this process's own where none is given, without the mark."""
    return {key: value for key, value in (os.environ if env is None else env).items()
            if key != MARK}
