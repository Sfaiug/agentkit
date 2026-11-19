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
`mini.answer()`.  `machines.break_remote(how)` breaks their origin for the machines it names, or
all, till `machines.mend_remote()`.  Each machine's crontab is installer.py's, its table
`root / "crontab"` on the test's side, and `vm.copy()` is its `tree` but ak's tmp folder, each
machine's own: what a standby's pass copies, or leaves as it was.
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
    words = words[2 if words[0] == "-o" else 1:]
name, *command = words or [""]
with socket.socket(socket.AF_UNIX) as asked:
    asked.connect(sshd)
    line = json.dumps([name, " ".join(command)]).encode() + b"\n"
    if rest := line[socket.send_fds(asked, [line], [0, 1, 2]):]:   # sending none fails, the
        asked.sendall(rest)                                            # sshd answered and gone
    sys.exit(int(asked.recv(16) or 255))
"""


class Machine(Home):
    """A machine, `name`, with its root at `at`, its HOME at `home` in it, and its install a
    clone of `origin`'s."""

    def __init__(self, name, at, origin, home="home"):
        super().__init__(at=at)
        if self.path != self.root / home:   # before anything names it
            (self.root / home).parent.mkdir(parents=True, exist_ok=True)
            self.path = self.path.rename(self.root / home)
            self.env["HOME"] = str(self.at / home)
        self.name = name
        self.down = None    # how ssh to it fails: "silent", or "hang"
        self.remote = (None, None)      # how its git calls to the origin fail: `break_remote`
        self._faulting = threading.Lock()   # while a call takes its fault: a write's, one push's
        self.held = threading.Semaphore(0)      # released for each call the origin holds silent
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
        machines = super().__new__(cls, [Machine(name, at, origin, (homes or {}).get(name, "home"))
                                         for name in names])
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

    def break_remote(self, how, *machines, refs=None):
        """Have the origin fail `machines`, or else all, `how`, till `mend_remote`: "unreachable",
        every git call to it failing; "silent", each taken and never answered, mended meanwhile
        or not, till its caller ends it, a machine's `held` released for each; "lost", each push
        taken whole and its writer told that it failed; "between", the next push of each finding
        `refs`, each named with a commit origin holds or None, on the origin in the place of the
        values it expected, as when another machine wrote between this one's read and its
        push."""
        for machine in machines or self:
            machine.remote = (how, refs)

    def mend_remote(self, *machines):
        """Have the origin answer `machines`, or else all, again."""
        self.break_remote(None, *machines)

    def close(self):
        sshds, self.sshds = self.sshds, []      # each ended once, however often `close` runs
        for listener, thread in sshds:
            listener.shutdown(socket.SHUT_RDWR)     # wakes its `accept`, as `close` would not
            listener.close()
            thread.join()
        for machine in self:
            machine.close()


def _sshd(listener, caller, machines):
    """Take each ssh's call on `listener`, `caller`'s sshd, until it is shut down."""
    while True:
        try:
            peer = listener.accept()[0]
        except OSError:
            return
        threading.Thread(target=_session, args=(peer, caller, machines), daemon=True).start()


def _session(peer, caller, machines):
    """Run what an ssh on `caller` asks on the machine it names, or git's fetch or push of the
    origin on this side, as `caller`'s remote fails, with its input and outputs, and answer its
    exit; an ssh gone before it ends ends it, as sshd does."""
    with peer:
        asked, fds, _, _ = socket.recv_fds(peer, 1 << 16, 3)
        proc = hung = lost = None
        try:     # whatever it asks, its input and outputs are this side's no longer
            while not asked.endswith(b"\n"):     # the rest of its line
                more = peer.recv(1 << 16)
                if not more:
                    return
                asked += more
            name, command = json.loads(asked)
            machine = next((machine for machine in machines if machine.name == name), None)
            if (name, command) in (FETCH, PUSH):    # as GitHub runs it, where its repositories are
                with caller._faulting:
                    how, refs = caller.remote
                    if how == "between" and (name, command) == PUSH:     # its next push alone
                        caller.remote = (None, None)
                        for ref, value in refs.items():
                            machines[0].install.set_ref(ref, value)
                lost = how == "lost" and (name, command) == PUSH
                if how == "unreachable":
                    os.write(fds[2], "ssh: connect to host github.com port 22: "
                                     f"{os.strerror(errno.EHOSTUNREACH)}\n".encode())
                elif how == "silent":
                    hung = True
                    caller.held.release()
                else:
                    proc = subprocess.Popen(shlex.split(command),
                                            cwd=machines[0].install.bare.parents[1],
                                            stdin=fds[0], stdout=fds[1], stderr=fds[2],
                                            env={"PATH": os.pathsep.join(SYSTEM)},
                                            start_new_session=True)
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
        with contextlib.suppress(OSError):      # gone meanwhile
            # killed, or its answer lost once the push is whole: 255, as ssh says
            peer.sendall(b"%d" % (255 if lost or code < 0 else code))
