"""A seat's event heard and looked at by a process already warm: who runs hooks/seat-state.sh's
and watch.start_look's look, and hears every event but a Stop, which its hook writes itself.

A fresh Python spends seconds on its imports and on reading every run before it writes or looks
(`watch.hook_look`).  `serve`, forked by the warm server and leaving with it, has both done, at the
server's priority, and reads the runs again at each wake as the menu does (`menu.run_records`).
`ask`, Python without agentkit, hands it the look over a socket in STATE, and it forks a child
per call to hear the event (`record`, a prompt's `prompted`) and look on the runs as read.
Anything amiss goes cold: with no looker, one older than the install or one silent for
`warm.WAIT`, `ask` does both itself.
Never lost nor run twice: a child acts once the client says go, and the client, once it has, never
acts itself.
"""

import os
import sys


def ask(repo, seat, owner="", event="", *kind):
    """Look at that seat, the words said on stdin, the owner's where `owner` is "true": the
    looker's, else this process's own, returning once the look ends.  With the event's `kind`,
    and its own words after a NUL on stdin -- a prompt's caller after its kind, and its payload
    after its words (`prompted`) --, the event is heard there first and this returns once its
    fact is down, having printed what hearing it said, the look going on behind.  In a session
    of its own: a harness ending the hook group ends none of it."""
    import _socket
    from warm import WAIT, place     # beside this file: run as a script, it imports no agentkit
    if os.getpgrp() != os.getpid():     # where it may, as a group leader may not
        os.setsid()
    said, *text = sys.stdin.read().split("\0")
    fact = (*kind, *text)
    state, name = place(repo)
    here = None
    try:
        here = os.open(".", os.O_RDONLY)   # the hook's directory, where a cold look runs
        os.chdir(state)        # the socket by its name: a sandbox's path is past 108 bytes
        conn = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        conn.settimeout(WAIT)
        conn.connect(name + ".look")   # beside the server's socket, lock and log
        # in the environment it is heard in, as a cold hearing is: its pane, the adapters that
        # say what it means, where its harness keeps its conversations (`_take`)
        data = b"\0".join([*map(os.fsencode, (seat, owner, event, said)), b"%d" % len(fact),
                           *map(os.fsencode, fact),
                           *(key + b"=" + value for key, value in os.environb.items())])
        conn.sendall(len(data).to_bytes(4, "big") + data)     # NUL is in none of them
        if conn.recv(1) == b"R":
            conn.sendall(b"G")     # the look is the child's from here: nothing goes cold after
            try:
                conn.settimeout(None)
                # what the child says is the hook's output, until it lets go: once its fact is
                # down, or as its look ends
                while told := conn.recv(1 << 16):
                    sys.stdout.buffer.write(told)
            except OSError:
                pass
            return
    except OSError:
        pass
    if here is not None:
        os.fchdir(here)
    sys.path[0] = repo
    from agentkit import looker
    looker.take(seat, owner, event, said, fact, sys.stdout.buffer.write, _behind)


def _behind():
    """The hook goes on as this process leaves, its fact down and what it said with it: the look
    is a child's, holding none of the hook's output."""
    sys.stdout.flush()
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
    if os.fork():
        os._exit(0)


def take(seat, owner, event, said, fact, say, go, records=None):
    """That event as hooks/seat-state.sh hears it: one handed over with its `fact` is heard first
    -- a prompt by `prompted`, which `say`s the hook's output, any other by `record` --, the
    owner's word answering at that moment, and `go()` lets the hook go on; then the look."""
    answered = ""
    if fact:
        mine = owner == "true"
        at = (prompted(seat, said if mine else None, *fact, say, records)
              if event == "UserPromptSubmit" else record(seat, event, *fact))
        answered = at if mine else ""
        go()
    look(seat, answered, event, said, records)


def prompted(seat, said, kind, pid, text, payload, say, records=None):
    """A prompt as hooks/seat-state.sh hears it, `said` the owner's words or None: its moment
    (`config.heard_at`) starts the turn hooks/orchestrator-stop.sh judges its end against, before
    anything may fail or run late; the seat goes on in the conversation its hook's caller `pid`
    went to (`Harness.follow`), and the prompt's news, read on `records`, is `say`d
    (`orch.prompt_news`); only then does its fact take the place of the question that news read.
    A failure following or reading the news says nothing and stops neither."""
    import contextlib
    import json
    from . import config
    at = config.heard_at(seat)
    # under the name its harness was launched with, which the stop hook reads it by
    config.write_latch(config.stop_path(seat), {"session": seat, "turn": at, "blocks": 0})
    with contextlib.suppress(Exception):
        from . import orch
        payload = json.loads(payload)
        if pid:
            with contextlib.suppress(Exception):    # the seat stays put, and its news still goes
                orch.seat_plugin(config.session_records().get(config.resolve_session(seat), {})
                                 ).follow(seat, payload, int(pid))
        news = orch.prompt_news(seat, payload.get("session_id"), said, records)
        if news:
            say(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                   "additionalContext": news}}).encode() + b"\n")
    config.record_hook_fact(config.resolve_session(seat), {
        "session": seat, "event": "UserPromptSubmit", "kind": kind, "text": text, "at": at})
    return at


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
        fields = asked.read(int.from_bytes(asked.read(4), "big")).split(b"\0")
        seat, owner, event, said = map(os.fsdecode, fields[:4])
        count = int(fields[4])
        fact = [*map(os.fsdecode, fields[5:5 + count])]
        environ = {key: value for key, _, value in
                   (item.partition(b"=") for item in fields[5 + count:]) if key}
        if update.outdated():
            raise OSError("outdated")       # installed over while the looker read: not its look
        adapters = os.fsencode(config.ADAPTER_DIR_ENV)
        if environ.get(adapters, b"") != os.environb.get(adapters, b""):
            raise OSError("other adapters")     # what an event means is the hook's adapters' to say
        conn.sendall(b"R")
        conn.settimeout(None)   # its go or its end: one given up on as it said go would be lost
        if asked.read(1) != b"G":
            raise OSError("not taken")
    except (OSError, ValueError, IndexError):
        os._exit(1)            # the client goes cold
    os.environb.clear()
    os.environb.update(environ)

    def go():               # the client goes on
        asked.close()
        conn.close()
    try:
        take(seat, owner, event, said, fact, conn.sendall, go, records)
    except BaseException:
        sys.excepthook(*sys.exc_info())     # into the server's log, as a cold look's to nowhere
    os._exit(0)                # Python's teardown would go over all the looker holds, for nothing


if __name__ == "__main__":
    sys.path[0] = os.path.dirname(os.path.realpath(__file__))   # warm.py, by its bare name
    ask(os.path.dirname(sys.path[0]), *sys.argv[1:])
