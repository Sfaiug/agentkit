"""Machines alike, on the one a test runs on, for a standby's keys: each an akbin `Home` whose
host name, as `hostname` and `socket.gethostname()` give it, is its name, whose root, HOME
included, is at the one path every machine's is at, with a /tmp of its own, and whose `ssh`
reaches every machine by its name and fails as ssh does, 255, for any other.  `homes` puts a
machine's HOME at another path in its root, as a Mac's is under /Users.  Each has ak's
install (tests/fixtures/akinstall.py), `install`, and runs its ak: ~/agentkit, a clone of one bare
origin, which all machines share and no machine is, so it answers while any is off; that `ssh`
serves git's fetch of it, and its push, too.

    from fixtures.twohomes import Machines
    with Machines("acme-mini", "acme-vm") as (mini, vm):
        done = mini.run("ssh", "acme-vm", "hostname")
    with Machines("acme-mini", "acme-mac", homes={"acme-mac": "Users/acme"}) as (mini, mac):
        done = mac.run("ssh", "acme-mini", 'echo "$HOME"')

The key, the tick and ssh start every command on a machine one way, `Machine._popen`: in its
home, with its environment alone and its fakes first on PATH, so that what is on one machine is
there for all three: a variable a key sets in a machine's `env` too, and its `AK_CGROUP_ROOT`,
an empty folder of its own outside its home (`root / "cgroups"` on the test's side).  ssh asks
the machine's sshd, which this process runs outside every machine, as a real one runs outside
the machine that calls it: no machine sees another's files, nor its own where the test's side
keeps them (`path`, `write`, `calls`).  A path given to a command (`cwd`) is one on the
machine.  akbin's `boxable()` says whether bubblewrap can build the machines here.

A key holds one machine: `vm.client_of(mini)` makes it the other's client, as install.sh records
it; `mini.silence()` turns it off and `mini.hang()` has it take ssh and answer nothing, till
`mini.answer()`.  `machines.remote` breaks their origin for all of them, and `mini.remote` for
one, till `mend()`: `unreachable()` fails every git call to it, `silent()` takes the connection
and never answers (across `mend()` too, till its caller ends it), `lose_answer()` takes a push
and tells its writer it failed, and `write_between(value)` puts `value`, or None, on the remote
in the place of the value the next push expected.  Each machine's crontab is installer.py's, its
table `root / "crontab"` on the test's side, and `vm.copy()` is its `tree` but ak's tmp folder,
each machine's own: what a standby's pass copies, or leaves as it was.
"""

import contextlib
import errno
import json
import os
import select
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from .akbin import _FILES, AK, REPO, SYSTEM, Home, _binds, _end, _strays, _wait_gone
from .akinstall import FETCH, PUSH, Install, make
from .installer import CRONTAB

# ssh [-o OPTION | -FLAG]... NAME [COMMAND]...: NAME and COMMAND, a line however long, to the
# sshd on $1, with this ssh's own input and outputs, and its answer, the exit of COMMAND or 255,
# as this one's.
SSH = r"""
import json, socket, sys
sshd, *words = sys.argv[1:]
while words[:1] and words[0].startswith("-"):
    if words[0] == "--":
        words = words[1:]
        break
    words = words[2 if len(words[0]) == 2 and words[0][1] in "BbcDEeFIiJLlmOoPpQRSWw" else 1:]
name, *command = words or [""]
with socket.socket(socket.AF_UNIX) as asked:
    asked.connect(sshd)
    line = json.dumps([name, " ".join(command)]).encode() + b"\n"
    if rest := line[socket.send_fds(asked, [line], [0, 1, 2]):]:   # sending none fails, the
        asked.sendall(rest)                                            # sshd answered and gone
    sys.exit(int(asked.recv(16) or 255))
"""


class Remote:
    """The origin, as `machines` reach it: broken one way or mended."""

    def __init__(self, machines, lock):
        self._machines, self._lock, self._taken = machines, lock, threading.Event()

    def _set(self, *fault):
        self._taken = taken = threading.Event()
        state = [*fault, taken] if fault else None
        with self._lock:
            for machine in self._machines:
                machine._remote = state

    def unreachable(self):
        """Have every git call to the remote fail."""
        self._set("unreachable", None)

    def silent(self):
        """Have the remote take git's connection and never answer; a waiting call keeps waiting
        across `mend`, till its caller ends it."""
        self._set("silent", None)

    def lose_answer(self):
        """Have the remote take a push and tell its writer that it failed."""
        self._set("lose_answer", None)

    def write_between(self, value):
        """Have the next push find `value`, a commit origin holds or None, on the remote in the
        place of the value it expected."""
        if value is not None:
            self._machines[0].install.commit(value)
        self._set("write_between", value)

    def mend(self):
        """Have the remote answer again."""
        self._set()


class Machine(Home):
    """A machine, `name`, with its root at `at`, its HOME at `home` in it, and its install a
    clone of `origin`'s."""

    def __init__(self, name, at, origin, home="home", lock=None):
        super().__init__(at=at)
        if self.path != self.root / home:   # before anything names it
            (self.root / home).parent.mkdir(parents=True, exist_ok=True)
            self.path = self.path.rename(self.root / home)
            self.env["HOME"] = str(self.at / home)
        self.name = name
        self.down = None    # how ssh to it fails: "silent", or "hang"
        self._remote = None
        self.remote = Remote((self,), lock or threading.Lock())
        self._starting, self._started = threading.Lock(), []
        self.sshd = self.tmux_dir / "sshd.sock"     # short, as a socket's path must be
        # ak's cgroups beside its home, never in it: a copy of a home carries none to another
        # machine, and what a key freezes or empties there is none of the host's
        (self.root / "cgroups").mkdir()
        self.env["AK_CGROUP_ROOT"] = str(self.at / "cgroups")
        # Python's bytecode beside it too: the ak it runs leaves its home's tree as it was
        self.env["PYTHONPYCACHEPREFIX"] = str(self.at / "pycache")
        self.install = Install(self, origin)
        self.program = self.install.ak     # ak moves an install only when it runs from it
        # over the install's: a machine's one ssh reaches the origin and the machines alike
        self.fake("ssh", f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -I -c "
                         f'{shlex.quote(SSH)} {shlex.quote(str(self.sshd))} "$@"\n')
        self.fake("crontab", CRONTAB.format(table=shlex.quote(str(self.at / "crontab"))))

    def on(self, env=None, cwd=None):
        """bwrap's words starting a command on this machine, with `env` over its environment, in
        `cwd` on it or else its home.  Its root, bound over `at` past every bind that holds it,
        a checkout's TMPDIR's too, covers every machine's, kept there on the test's side."""
        return ["bwrap", "--dev-bind", "/", "/", "--unshare-uts", "--hostname", self.name,
                "--bind", self.root / "tmp", "/tmp",
                *_binds(self.tmux_dir, REPO, Path(AK).resolve().parent),
                "--bind", self.root, self.at, "--chdir", cwd or self.env["HOME"], "--clearenv",
                *(word for item in self._env(env).items() for word in ("--setenv", *item)), "--"]

    def _popen(self, argv, env, cwd, **kwargs):
        """Start `argv` on this machine, or refuse while it is off: `silence` holds `_starting`
        and ends every command started here, bwrap's still setting up the machine included."""
        with self._starting:
            if self.down == "silent":
                raise OSError(errno.EHOSTUNREACH, os.strerror(errno.EHOSTUNREACH))
            proc = super()._popen([*self.on(env, cwd), *argv], None, None, **kwargs)
            self._started = [*(each for each in self._started if each.returncode is None), proc]
        return proc

    def client_of(self, server):
        """Make this machine `server`'s client, as `install.sh --client NAME` here and
        `install.sh --server` there leave them: this one's record names it, and it keeps none."""
        (server.path / ".agentkit" / "state" / "server").unlink(missing_ok=True)
        self.write(".agentkit/state/server", f"{server.name}\n")

    def copy(self):
        """`tree` but ak's tmp folder."""
        return {path: data for path, data in self.tree().items()
                if not Path(path).is_relative_to(".agentkit/tmp")}

    def silence(self):
        """Turn this machine off till it `answer`s: nothing starts on it, ssh to it fails, 255,
        and every process on it ends."""
        with self._starting:
            self.down = "silent"
            for proc in self._started:
                if proc.returncode is None:     # not yet reaped: its group is its own still
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGKILL)
            # what detached, and forked meanwhile: what its close would end
            while running := _strays(self.root, self.tmux_dir, self.at):
                for pid in running:
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(pid, signal.SIGKILL)
                for pid in running:
                    _wait_gone(pid)

    def hang(self):
        """Have ssh to this machine take the connection and answer nothing, its command neither
        run nor failed, till whoever called gives up, or the test ends it; `answer` lets a later
        ssh through."""
        self.down = "hang"

    def answer(self):
        """Have this machine answer ssh again."""
        self.down = None

    def box(self, box=_FILES):
        """`box` past the /tmp of its own it would make: a machine's is its own already."""
        return [*_FILES[:-2], *box[len(_FILES):], "--"]


class Machines(tuple):
    """Machines of these names, each with its sshd and its install of their one origin, and its
    HOME where `homes` names one for it, else at `home` in its root; `close` ends them all."""

    def __new__(cls, *names, homes=None):
        at = Path(tempfile.mkdtemp(prefix="akbin-")).resolve()
        origin = make(at)     # beside the machines' roots, in no machine
        lock = threading.Lock()
        machines = super().__new__(cls, [
            Machine(name, at, origin, (homes or {}).get(name, "home"), lock) for name in names])
        machines.remote = Remote(machines, lock)
        machines.sshds = []
        for machine in machines:
            listener = socket.create_server(str(machine.sshd), family=socket.AF_UNIX)
            thread = threading.Thread(target=_sshd, args=(listener, machine, machines),
                                      daemon=True)
            thread.start()
            machines.sshds.append((listener, thread))
        return machines

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self):
        sshds, self.sshds = self.sshds, []      # each ended once, however often `close` runs
        for listener, thread in sshds:
            listener.shutdown(socket.SHUT_RDWR)     # wakes its `accept`, as `close` would not
            listener.close()
            thread.join()
        for machine in self:
            machine.close()


def _sshd(listener, caller, machines):
    """Take each ssh's call on `listener` until it is shut down."""
    while True:
        try:
            peer = listener.accept()[0]
        except OSError:
            return
        threading.Thread(target=_session, args=(peer, caller, machines), daemon=True).start()


def _session(peer, caller, machines):
    """Run what an ssh asks on the machine it names, or git's fetch or push of the origin on this
    side, with its input and outputs, and answer its exit; an ssh gone before it ends ends it, as
    sshd does."""
    with peer:
        asked, fds, _, _ = socket.recv_fds(peer, 1 << 16, 3)
        proc = hung = after = None
        try:     # whatever it asks, its input and outputs are this side's no longer
            while not asked.endswith(b"\n"):     # the rest of its line
                more = peer.recv(1 << 16)
                if not more:
                    return
                asked += more
            name, command = json.loads(asked)
            machine = next((machine for machine in machines if machine.name == name), None)
            if (name, command) in (FETCH, PUSH):
                proc, hung, after = _origin(caller, (name, command) == PUSH, command, fds,
                                            machines[0].install)
            elif machine is None:
                os.write(fds[2], f"ssh: Could not resolve hostname {name}: "
                                 "Name or service not known\n".encode())
            elif machine.down == "hang":
                hung = True
            else:
                try:
                    proc = machine._popen(["/bin/sh", "-c", command], None, None,
                                          stdin=fds[0], stdout=fds[1], stderr=fds[2])
                except OSError as error:     # off
                    os.write(fds[2], f"ssh: connect to host {name} port 22: "
                                     f"{error.strerror}\n".encode())
        finally:
            for fd in fds:
                os.close(fd)
        if hung:
            return peer.recv(1)     # an ssh sends nothing past its line: till it is gone
        code = 255
        if proc is not None:
            ended = os.pidfd_open(proc.pid)
            gone = peer in select.select([peer, ended], [], [])[0]
            os.close(ended)
            if gone:
                return _end(proc)
            code = proc.wait()
            if after is not None:
                code = after(code)
        with contextlib.suppress(OSError):      # gone meanwhile
            peer.sendall(b"%d" % (code if code >= 0 else 255))     # killed: 255, as ssh says


def _origin(caller, is_push, command, fds, install):
    """Run git's `command` where GitHub's repositories are, under `caller`'s remote fault."""
    with caller.remote._lock:
        state = caller._remote
        fault, value = (state[0], state[1]) if state else (None, None)
        if fault and (is_push or fault in ("unreachable", "silent")):
            if fault == "write_between":
                state[0] = None
            state[2].set()
        else:
            fault = None
    if fault == "unreachable":
        os.write(fds[2], f"ssh: connect to host github.com port 22: "
                         f"{os.strerror(errno.EHOSTUNREACH)}\n".encode())
        return None, False, None
    if fault == "silent":
        return None, True, None
    stdin, stdout, stderr = fds
    after = None
    if fault == "lose_answer":
        source, stdout = os.pipe()
        drain = threading.Thread(target=_drop_answer, args=(source, os.dup(fds[1])), daemon=True)
        drain.start()
        stderr, after = subprocess.DEVNULL, lambda _code: (drain.join(), 255)[1]
    elif fault == "write_between":
        stdin, sink = os.pipe()
        threading.Thread(target=_slip_write, args=(os.dup(fds[0]), sink, install, value),
                         daemon=True).start()
    try:
        proc = subprocess.Popen(shlex.split(command), cwd=install.bare.parents[1],
                                stdin=stdin, stdout=stdout, stderr=stderr,
                                env={"PATH": os.pathsep.join(SYSTEM)}, start_new_session=True)
    finally:
        for extra in ((stdout,) if fault == "lose_answer" else
                      (stdin,) if fault == "write_between" else ()):
            os.close(extra)
    return proc, False, after


def _drop_answer(source, client):
    """Pass receive-pack's ref listing to `client`, then swallow its answer."""
    with os.fdopen(source, "rb", 0) as sent:
        with contextlib.suppress(OSError), os.fdopen(client, "wb") as out:
            for header, body in _until_flush(source):
                out.write(header + body)
        with contextlib.suppress(OSError):
            while sent.read(1 << 16):
                pass


def _slip_write(client, sink, install, value):
    """Put `value` on each ref the push updates before receive-pack locks it."""
    with os.fdopen(client, "rb", 0) as sent, contextlib.suppress(OSError), \
            os.fdopen(sink, "wb") as into:
        for header, body in _until_flush(client):
            parts = body.split(b"\0", 1)[0].rstrip(b"\n").split(b" ", 2) if body else ()
            if len(parts) == 3:
                install.set_ref(os.fsdecode(parts[2]), value)
            into.write(header + body)
        into.flush()
        while chunk := sent.read(1 << 16):
            into.write(chunk)
            into.flush()


def _until_flush(fd):
    """Each pkt-line `(header, body)` on `fd`, through git's `0000` flush."""
    while len(header := _read_exact(fd, 4)) == 4:
        size = int(header, 16)
        body = _read_exact(fd, max(0, size - 4))
        if len(body) < size - 4:
            return
        yield header, body
        if size == 0:
            return


def _read_exact(fd, size):
    data = b""
    while len(data) < size:
        more = os.read(fd, size - len(data))
        if not more:
            break
        data += more
    return data
