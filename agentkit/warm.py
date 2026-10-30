"""`Ctrl-b m`'s menu, warm: its first frame drawn by a process that was up before the key.

A cold `ak attach --overlay` starts Python, imports the menu and reads every seat, run and plan
before it draws: a second or more on a busy host.  `serve` is up with the imports done, one per
HOME and checkout, and beside it a reader keeps the last read of the seats (`menu.rows`), read
again when what a read reads changes (`menu.Live.recorded`), its reads spending at most DUTY of
one core.  The popup's `client`, Python without its site or agentkit, hands the server the
popup's terminal, directory, environment and words over a socket in STATE; the server forks a
menu onto that terminal under a fork that waits for it and hands the client its code.  The menu
draws the last read at once and reads again behind it, as a menu back from a seat does
(`menu.Live.back`), where the popup's environment is the reader's in what a seat's is made of
(`orch.seat_env`).  The menu is in no session of the terminal's, so the client forwards the
terminal's signals, a resize, a hang-up, a Ctrl-C, to the menu's process group: what the menu
runs, a login, hears them as it would cold.

Anything amiss goes cold: with no server, or one silent for WAIT, the client runs `bin/ak` as
the popup always did, and starts a server where an install is stamped -- only there can one
tell its code is old (`update.outdated`).  A server leaves once the install is newer than its
code, starting the next, or once its socket is not its own or its checkout is gone: an update
never serves old code, and a dead server costs one slow open, never a broken one.  It stays one
thread, so each fork is a whole copy of it: the reads, whose feature switches run in threads of
their own, are the reader's, a process apart.  And it stays in memory (`_resident`): a server idle
for hours is what a busy host swaps out first, and a menu forked from it read it back page by
page before its first frame, most of a second.  This file is the client too, run as a script, so
nothing above `serve` imports agentkit.
"""

import os
import sys
import time

WAIT = 1.0      # how long a client waits on the server before it goes cold
CHUNK = 1 << 20  # how much of its memory the server reads back at a time (`_resident`)
DUTY = 0.05     # the reader's share of one core at most: a read's CPU / DUTY before the next
NICE = 10       # ... and it gives way to the rest of the host meanwhile
# What the terminal signals the process in its session, the client, and the menu has to hear.
FORWARDED = ("SIGWINCH", "SIGHUP", "SIGTERM", "SIGINT", "SIGQUIT", "SIGTSTP", "SIGCONT")
_PRIMED = None  # in a forked menu: the reader's last read, for its first frame
MARK = "AK_OWNER"   # what an `ak` command marks all it starts with (`owner`): the client's too


def place(repo):
    """STATE, spelled from $HOME as config spells it, since the client imports no config, and
    the name checkout `repo`'s socket, lock and log share in it."""
    import zlib
    return (os.path.join(os.path.expanduser("~"), ".agentkit", "state"),
            "menu-%08x" % zlib.crc32(os.fsencode(repo)))


def client(repo, argv):
    """The popup's command: `ak <argv>` from the warm server, else from `bin/ak` (`cold`)."""
    import _signal
    import _socket
    state, name = place(repo)
    here = None
    try:
        here = os.open(".", os.O_RDONLY)   # the popup's directory, handed on whatever its path
        os.chdir(state)            # the socket by its name: a sandbox's path is past 108 bytes
        conn = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        conn.settimeout(WAIT)
        conn.connect(name + ".sock")
        # NUL is in no argument and no variable
        data = b"\0".join([os.fsencode(repo), b"%d" % len(argv), *map(os.fsencode, argv),
                           *(key + b"=" + value for key, value in os.environb.items())])
        data = len(data).to_bytes(4, "big") + data
        fds = b"".join(fd.to_bytes(4, sys.byteorder) for fd in (0, 1, 2, here))   # C ints
        sent = conn.sendmsg([data], [(_socket.SOL_SOCKET, _socket.SCM_RIGHTS, fds)])
        conn.sendall(data[sent:])
        ready = _exactly(conn, 5)
        if ready[:1] != b"R":
            raise OSError("refused")
        pid = int.from_bytes(ready[1:], "big")

        def forward(number, _frame):
            try:
                os.kill(-pid, number)   # the menu's group: it and what it runs
            except OSError:
                pass             # it has ended: its code is on the way
        for signame in FORWARDED:
            _signal.signal(getattr(_signal, signame), forward)
        conn.sendall(b"G")       # the terminal is the menu's from here: nothing goes cold after
    except OSError:
        if here is not None:
            os.fchdir(here)
        cold(repo, argv, state)
    conn.settimeout(None)
    try:
        code = conn.recv(1)
    except OSError:
        code = b""
    os._exit(code[0] if code else 1)   # none: the server went before its menu ended


def _exactly(conn, size):
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise OSError("closed")
        data += chunk
    return data


def cold(repo, argv, state):
    """`bin/ak <argv>` here, as the popup ran it before there was a server, and a server for the
    next popup where an install is stamped, in a session of its own.  Never returns."""
    if os.path.exists(os.path.join(state, "installed-at")):
        _start(repo)
    os.execv(sys.executable, [sys.executable, os.path.join(repo, "bin", "ak"), *argv])


def _start(repo):
    """A server, unmarked: it outlives whatever `ak` started it."""
    try:
        os.posix_spawn(sys.executable,
                       [sys.executable, os.path.join(repo, "agentkit", "warm.py"), "serve"],
                       {key: value for key, value in os.environ.items() if key != MARK},
                       setsid=True,
                       file_actions=[(os.POSIX_SPAWN_OPEN, fd, os.devnull, os.O_RDWR, 0)
                                     for fd in (0, 1, 2)])
    except (OSError, NotImplementedError):
        pass             # the menu opens all the same, and the next popup starts one


def primed():
    """The reader's last read, once, in a menu the server forked; None in any other."""
    global _PRIMED
    taken, _PRIMED = _PRIMED, None
    return taken


def serve(lock):
    """The warm server, holding `lock`, its checkout's, until it leaves (see above)."""
    import select
    import signal
    import socket
    # the menu, and what `menu.main` and its fork (`_menu`) import on the way to its first frame
    from . import config, macbridge, menu, notify, orch, terminal, update, watch  # noqa: F401
    import pickle, pkgutil, runpy  # noqa: E401, F401
    config.load()                      # what it parses with, imported once here
    for name in (config.SESSION_ENV, "TMUX", "TMUX_PANE", terminal.PAD_ENV):
        os.environ.pop(name, None)     # the popup's that started it: no seat is the reader's
    names = sorted(set(orch.seat_env("", "")) - {config.SESSION_ENV})
    own = [os.environ.get(name) for name in names]
    state, base = place(str(config.REPO))
    os.chdir(state)                    # never made here: a HOME taken away stays away
    sock = base + ".sock"
    out = os.open(base + ".log", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    for fd in (1, 2):
        os.dup2(out, fd)
    os.close(out)
    if os.path.lexists(sock):
        os.unlink(sock)                # a dead server's: the lock says none is up
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(sock)                # in STATE, its owner's alone
    listener.listen(16)
    ino = os.stat(sock).st_ino
    reads, written = os.pipe()
    reader = os.fork()
    if reader == 0:
        listener.close()
        os.close(lock)
        os.close(reads)
        _read(written)
    os.close(written)
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)   # each menu's fork reaped as it ends
    latest, heard, moved = None, b"", False
    while True:
        _resident()
        ready = select.select([listener, reads], [], [], menu.STIR)[0]
        try:
            moved = update.outdated()
            if moved or os.stat(sock).st_ino != ino or not os.path.exists(__file__):
                break
        except OSError:
            break
        if reads in ready:
            chunk = os.read(reads, 1 << 16)
            if not chunk:
                break                  # the reader is gone
            heard += chunk             # each read framed by its length (`_read`)
            while len(heard) >= 4 and len(heard) >= 4 + int.from_bytes(heard[:4], "big"):
                end = 4 + int.from_bytes(heard[:4], "big")
                latest, heard = heard[4:end], heard[end:]
        if listener in ready:
            try:
                conn, _ = listener.accept()
            except OSError:
                continue
            if os.fork() == 0:
                listener.close()
                os.close(lock)
                os.close(reads)
                _menu(conn, latest, names, own)
            conn.close()
    try:
        if os.stat(sock).st_ino == ino:
            os.unlink(sock)            # the next popup goes cold rather than wait on this one
    except OSError:
        pass
    listener.close()
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)   # the reader waited on: gone before the lock
    try:
        os.kill(reader, signal.SIGTERM)
        os.waitpid(reader, 0)
    except OSError:
        pass                           # gone already
    os.close(lock)
    # the new code's, but for an install stamped ahead of the clock: the next would be as stale
    # as this one, and start another
    if moved and notify.installed_at() <= time.time():
        _start(str(config.REPO))
    os._exit(0)


def _resident():
    """Whatever of the server's memory the host swapped out, back in RAM, read through
    /proc/self/mem: each mapping /proc/self/smaps has anything of in swap, whatever its
    permissions, as a fork shares them.  With nothing swapped it reads its status alone, at each
    wake (`serve`)."""
    try:
        with open("/proc/self/status", "rb") as status:
            if not any(line.startswith(b"VmSwap:") and line.split()[1] != b"0" for line in status):
                return
        spans = []
        with open("/proc/self/smaps", "rb") as smaps:
            for line in smaps:
                field = line.split()
                if not field[0].endswith(b":"):
                    span = field[0]            # a mapping's first line: its addresses
                elif field[0] == b"Swap:" and field[1] != b"0":
                    spans.append(span)
        mem = os.open("/proc/self/mem", os.O_RDONLY)
    except OSError:
        return            # no /proc here: nothing to read it back by
    try:
        for span in spans:
            start, end = (int(edge, 16) for edge in span.split(b"-"))
            try:
                for at in range(start, end, CHUNK):
                    os.pread(mem, min(CHUNK, end - at), at)
            except OSError:
                pass  # gone since the list was read: the rest comes back all the same
    finally:
        os.close(mem)


def _read(out):
    """The reader, forked from the server: each read framed onto `out` as it lands."""
    import pickle
    from . import config, menu
    os.nice(NICE)
    server = os.getppid()
    live = menu.Live(config.load())    # for `recorded`: what a read is news to
    seen, due = None, 0.0
    while os.getppid() == server:
        noted = live.recorded() if time.monotonic() >= due else seen
        if noted != seen:
            began = sum(os.times()[:4])    # its CPU, its ended children's with it
            try:
                found, _, groups = menu.rows(config.load())
                frame = pickle.dumps([found, groups])
                frame = len(frame).to_bytes(4, "big") + frame
                while frame:
                    frame = frame[os.write(out, frame):]
                seen = noted
            except (config.Error, OSError, ValueError, TypeError, KeyError):
                pass    # as a menu's read: what cannot be read now stays as last read
            due = time.monotonic() + (sum(os.times()[:4]) - began) / DUTY
        time.sleep(menu.STIR)
    os._exit(0)


def _menu(conn, latest, names, own):
    """In a fork of the server: the menu `conn`'s client asked for, in a fork of this one, on
    the client's terminal, its first frame `latest`, the reader's last read, where the client's
    environment is the reader's on `names` (`own`); this one waits and tells the client its
    code.  Never returns."""
    import pickle
    import runpy
    import signal
    import socket
    from . import config
    global _PRIMED
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)   # the menu waited on, and what it starts
    try:
        conn.settimeout(WAIT)
        head, fds, _, _ = socket.recv_fds(conn, 4, 4)   # the descriptors come with its first
        head += _exactly(conn, 4 - len(head))            # byte, its length in its first four
        fields = _exactly(conn, int.from_bytes(head, "big")).split(b"\0")
        count = int(fields[1])
        if len(fds) != 4 or os.fsdecode(fields[0]) != str(config.REPO):
            raise OSError("not this checkout's")
        go, went = os.pipe()
        menu = os.fork()
        if menu:
            os.close(go)
            os.setpgid(menu, menu)   # a group of its own, before the client can signal it
            conn.sendall(b"R" + menu.to_bytes(4, "big"))
            if _exactly(conn, 1) != b"G":
                raise OSError("not taken")
            os.write(went, b"G")
    except (OSError, ValueError, IndexError):
        os._exit(1)        # the client goes cold, and a menu not told to go ends unseen
    if menu:
        for fd in fds:
            os.close(fd)   # the terminal is the menu's
        code = os.waitstatus_to_exitcode(os.waitpid(menu, 0)[1])
        try:
            conn.sendall(bytes([(code if code >= 0 else 128 - code) & 0xFF]))  # as a shell's
        except OSError:
            pass           # the popup is gone
        os._exit(0)
    conn.close()
    os.close(went)
    if os.read(go, 1) != b"G":
        os._exit(1)
    os.close(go)
    for number, fd in enumerate(fds[:3]):
        os.dup2(fd, number)
    try:
        os.fchdir(fds[3])
    except OSError:
        pass
    for fd in fds:
        os.close(fd)
    os.environb.clear()
    os.environb.update((key, value) for key, _, value in
                       (item.partition(b"=") for item in fields[2 + count:]) if key)
    sys.argv = [str(config.REPO / "bin" / "ak"), *map(os.fsdecode, fields[2:2 + count])]
    if latest and [os.environ.get(name) for name in names] == own:
        _PRIMED = pickle.loads(latest)
    sys.stdout.reconfigure(line_buffering=True)   # a terminal's now, as a cold menu's is
    try:
        runpy.run_path(sys.argv[0], run_name="__main__")
        code = 0
    except SystemExit as exc:
        code = 0 if exc.code is None else exc.code if isinstance(exc.code, int) else 1
    except BaseException:
        sys.excepthook(*sys.exc_info())
        code = 1
    try:
        sys.stdout.flush()
    except (OSError, ValueError):
        pass               # the terminal went with the popup
    os._exit(code)         # Python's teardown would go over all the server holds, for nothing


if __name__ == "__main__":
    REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    if sys.argv[1:] == ["serve"]:
        import fcntl
        state, base = place(REPO)
        try:
            lock = os.open(os.path.join(state, base + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            sys.exit(0)                # one is up already
        sys.path[0] = REPO             # the package, not this directory's modules by bare names
        from agentkit import warm
        warm.serve(lock)
    client(REPO, sys.argv[1:])
