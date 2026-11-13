"""A seat's event looked at by a process already warm: who runs hooks/seat-state.sh's look.

A fresh Python spends seconds on its imports and on reading every run before it looks
(`watch.hook_look`).  `serve`, forked by the warm server and leaving with it, has both done, at the
server's priority, and reads the runs again at each wake as the menu does (`menu.run_records`).
The hook's `ask`, Python without agentkit, hands it the event over a socket in STATE, and it forks
a child per event to look on the runs as read.  Anything amiss goes cold: with no looker, one older
than the install or one silent for `warm.WAIT`, `ask` looks itself.  Never lost nor run twice: a
child looks once the client says go, and the client, once it has, never looks itself.
"""

import os
import sys


def ask(repo, seat, answered, event):
    """The hook's look at that seat, the owner's words on stdin: the looker's, else this
    process's own.  In a session of its own: a harness ending the hook group ends none of it."""
    import _socket
    from warm import WAIT, place     # beside this file: run as a script, it imports no agentkit
    if os.getpgrp() != os.getpid():     # where it may, as a group leader may not
        os.setsid()
    said = sys.stdin.read()
    state, name = place(repo)
    here = None
    try:
        here = os.open(".", os.O_RDONLY)   # the hook's directory, where a cold look runs
        os.chdir(state)        # the socket by its name: a sandbox's path is past 108 bytes
        conn = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        conn.settimeout(WAIT)
        conn.connect(name + ".look")   # beside the server's socket, lock and log
        data = b"\0".join(map(os.fsencode, (seat, answered, event, said, os.environ.get("TMUX", ""),
                                            os.environ.get("TMUX_PANE", ""))))
        conn.sendall(len(data).to_bytes(4, "big") + data)     # NUL is in none of them
        if conn.recv(1) == b"R":
            conn.sendall(b"G")     # the look is the child's from here: nothing goes cold after
            return
    except OSError:
        pass
    if here is not None:
        os.fchdir(here)
    sys.path[0] = repo
    from agentkit import looker
    looker.look(seat, answered, event, said)


def look(seat, answered, event, said, records=None):
    """`watch.hook_look` for that event as hooks/seat-state.sh hears it, on `records`."""
    import json
    from . import watch
    card = event == "PostToolUse"
    watch.hook_look(seat, float(answered) if answered else None, "" if card else said,
                    prompt=event == "UserPromptSubmit", card=json.loads(said) if card else None,
                    records=records)


def serve():
    """The looker, in a fork of the warm server, until the server is gone, its code is older
    than the install or its socket is not its own: one that refuses sends each event cold."""
    import select
    import signal
    import socket
    from . import config, menu, update, warm
    server = os.getppid()
    records = menu.run_records(cache=False, rest_may_lag=True)   # no SQLite crosses a fork
    if os.getppid() != server or update.outdated():
        os._exit(0)            # its server went, or was installed over, as it read: no socket
    state, name = warm.place(str(config.REPO))
    os.chdir(state)            # the socket by its name, as `ask` reaches it
    sock = name + ".look"
    if os.path.lexists(sock):
        os.unlink(sock)        # an earlier looker's, which leaves once it is not its own
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(sock)
    listener.listen(16)
    ino = os.stat(sock).st_ino
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)   # each look reaped as it ends
    while True:
        warm._resident()       # a look forked from swapped memory reads it back first
        ready = select.select([listener], [], [], menu.STIR)[0]
        try:
            if os.getppid() != server or update.outdated() or os.stat(sock).st_ino != ino:
                os._exit(0)
        except OSError:
            os._exit(0)
        try:
            records = menu.run_records(cache=False, rest_may_lag=True)
        except (config.Error, OSError, ValueError, TypeError, KeyError):
            pass               # as a menu's read: what cannot be read now stays as last read
        if ready:
            try:
                conn, _ = listener.accept()
            except OSError:
                continue
            if os.fork() == 0:
                listener.close()
                _take(conn, records)
            conn.close()


def _take(conn, records):
    """In a fork of the looker: the look `conn`'s client asks for, once it says go."""
    import signal
    from . import update, warm
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)   # what the look runs is waited on
    try:
        conn.settimeout(warm.WAIT)
        asked = conn.makefile("rb")
        seat, answered, event, said, tmux, pane = map(
            os.fsdecode, asked.read(int.from_bytes(asked.read(4), "big")).split(b"\0"))
        if update.outdated():
            raise OSError("outdated")       # installed over while the looker read: not its look
        conn.sendall(b"R")
        if asked.read(1) != b"G":
            raise OSError("not taken")
    except (OSError, ValueError):
        os._exit(1)            # the client goes cold
    os.environ.update(TMUX=tmux, TMUX_PANE=pane)
    try:
        look(seat, answered, event, said, records)
    except BaseException:
        sys.excepthook(*sys.exc_info())     # into the server's log, as a cold look's to nowhere
    os._exit(0)                # Python's teardown would go over all the looker holds, for nothing


if __name__ == "__main__":
    sys.path[0] = os.path.dirname(os.path.realpath(__file__))   # warm.py, by its bare name
    ask(os.path.dirname(sys.path[0]), *sys.argv[1:4])
