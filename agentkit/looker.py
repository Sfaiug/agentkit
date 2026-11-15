"""A seat's event heard and looked at by a process already warm: who runs hooks/seat-state.sh's
look, and writes the fact of every event but a prompt and a Stop, which the hook writes itself.

A fresh Python spends seconds on its imports and on reading every run before it writes or looks
(`watch.hook_look`).  `serve`, forked by the warm server and leaving with it, has both done, at the
server's priority, and reads the runs again at each wake as the menu does (`menu.run_records`).
The hook's `ask`, Python without agentkit, hands it the event over a socket in STATE, and it forks
a child per event to hear it (`record`) and look on the runs as read.  Anything amiss goes cold:
with no looker, one older than the install or one silent for `warm.WAIT`, `ask` does both itself.
Never lost nor run twice: a child acts once the client says go, and the client, once it has, never
acts itself.
"""

import os
import sys


def ask(repo, seat, answered, event, *kind):
    """The hook's look at that seat, the owner's words on stdin: the looker's, else this
    process's own.  With the event's `kind`, and its words after a NUL on stdin, the event is
    heard there first (`record`): this returns once its fact is down, the look going on behind.
    In a session of its own: a harness ending the hook group ends none of it."""
    import _socket
    from warm import WAIT, place     # beside this file: run as a script, it imports no agentkit
    if os.getpgrp() != os.getpid():     # where it may, as a group leader may not
        os.setsid()
    said, *text = sys.stdin.read().split("\0", 1)
    fact = (*kind, *text)
    state, name = place(repo)
    here = None
    try:
        here = os.open(".", os.O_RDONLY)   # the hook's directory, where a cold look runs
        os.chdir(state)        # the socket by its name: a sandbox's path is past 108 bytes
        conn = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        conn.settimeout(WAIT)
        conn.connect(name + ".look")   # beside the server's socket, lock and log
        # with the pane it is heard in and the adapters that say what it means (`_take`)
        data = b"\0".join(map(os.fsencode, (seat, answered, event, said, *(
            os.environ.get(var, "") for var in ("TMUX", "TMUX_PANE", "AGENTKIT_ADAPTER_DIR")),
            *fact)))
        conn.sendall(len(data).to_bytes(4, "big") + data)     # NUL is in none of them
        if conn.recv(1) == b"R":
            conn.sendall(b"G")     # the event is the child's from here: nothing goes cold after
            if fact:
                try:
                    conn.settimeout(None)
                    conn.recv(1)   # the child lets go once its fact is down
                except OSError:
                    pass
            return
    except OSError:
        pass
    if here is not None:
        os.fchdir(here)
    sys.path[0] = repo
    from agentkit import looker
    looker.take(seat, answered, event, said, fact, _behind)


def _behind():
    """The hook goes on as this process leaves, its fact down: the look is a child's."""
    if os.fork():
        os._exit(0)


def take(seat, answered, event, said, fact, go, records=None):
    """That event as hooks/seat-state.sh hears it: one handed over with its `fact`, its kind and
    words, is heard first (`record`), the owner's word on a card answering at that moment, and
    `go()` lets the hook go on; then the look."""
    if fact:
        at = record(seat, event, *fact)
        answered = at if said else ""
        go()
    look(seat, answered, event, said, records)


def record(seat, event, kind, text):
    """The moment that seat heard an event neither a prompt nor a Stop (`config.heard_at`),
    taken first, its fact then put in place of the one standing (`config.record_hook_fact`)
    unless that one is kept.

    Claude says its prompt is idle a minute after a turn ends whether or not background work is
    in flight: a seat waiting on work it started is not idle, and the Stop that said so stands
    until that work's notification begins a turn; a question going up still replaces it.  A
    notice the seat's own manifest gives no state writes nothing, and nor does one meaning what
    the fact standing means -- a permission notice six seconds after the PermissionRequest that
    wrote its question down.  An event it marks `interrupt` always writes: the owner stopped a
    turn a harness with no prompt hook began under an earlier Stop's at_prompt, which that Stop
    does not say.  Where nothing can say -- no record names the harness, or the asking fails,
    however late -- the event is written all the same."""
    from . import config
    at = config.heard_at(seat)      # before the classifier's imports, however long they take
    row = config.resolve_session(seat)
    fact = {"session": seat, "event": event, "kind": kind, "text": text, "at": at}

    def background(standing):
        return ((event, kind, standing.get("event"), standing.get("kind"))
                == ("Notification", "idle_prompt", "Stop", "background"))
    try:
        from . import watch
        harness = watch.seat_model(config.load(), row)[0]
        state, named = watch.hook_state(harness, fact)[:2]
        passive = bool(harness) and named not in watch.marked_events(harness, "interrupt")

        def kept(standing):
            return background(standing) or passive and state in (
                None, watch.hook_state(harness, standing)[0])
        config.record_hook_fact(row, fact, kept)
    except Exception:       # the asking failed, before the fact standing was read or as it was
        config.record_hook_fact(row, fact, background)
    return at


def look(seat, answered, event, said, records=None):
    """`watch.hook_look` for that event as hooks/seat-state.sh hears it, on `records`: a card's
    answer is the owner's word only where they gave one."""
    import json
    from . import watch
    card = event == "PostToolUse" and bool(said)
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
    """In a fork of the looker: the event `conn`'s client hands over, once it says go."""
    import signal
    from . import config, update, warm
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)   # what the look runs is waited on
    try:
        conn.settimeout(warm.WAIT)
        asked = conn.makefile("rb")
        seat, answered, event, said, tmux, pane, adapters, *fact = map(
            os.fsdecode, asked.read(int.from_bytes(asked.read(4), "big")).split(b"\0"))
        if update.outdated():
            raise OSError("outdated")       # installed over while the looker read: not its look
        if adapters != os.environ.get(config.ADAPTER_DIR_ENV, ""):
            raise OSError("other adapters")     # what an event means is the hook's adapters' to say
        conn.sendall(b"R")
        conn.settimeout(None)   # its go or its end: one given up on as it said go would be lost
        if asked.read(1) != b"G":
            raise OSError("not taken")
    except (OSError, ValueError):
        os._exit(1)            # the client goes cold
    os.environ.update(TMUX=tmux, TMUX_PANE=pane)

    def go():               # the client goes on
        asked.close()
        conn.close()
    try:
        take(seat, answered, event, said, fact, go, records)
    except BaseException:
        sys.excepthook(*sys.exc_info())     # into the server's log, as a cold look's to nowhere
    os._exit(0)                # Python's teardown would go over all the looker holds, for nothing


if __name__ == "__main__":
    sys.path[0] = os.path.dirname(os.path.realpath(__file__))   # warm.py, by its bare name
    ask(os.path.dirname(sys.path[0]), *sys.argv[1:])
