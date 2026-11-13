"""Machines alike, on the one a test runs on, for a standby's keys: each an akbin `Home` whose
host name, as `hostname` and `socket.gethostname()` give it, is its name, whose root, HOME
included, is at the one path every machine's is at, with a /tmp of its own, and whose `ssh`
reaches every machine by its name and fails as ssh does, 255, for any other.

    from fixtures.twohomes import Machines
    with Machines("acme-mini", "acme-vm") as (mini, vm):
        done = mini.run("ssh", "acme-vm", "hostname")

The key, the tick and ssh start every command on a machine one way, `Machine._popen`: in its
home, with its environment alone and its fakes first on PATH, so that what is on one machine is
there for all three.  ssh asks the machine's sshd, which this process runs outside every
machine, as a real one runs outside the machine that calls it: no machine sees another's files,
nor its own where the test's side keeps them (`path`, `write`, `calls`).  A path given to a
command (`cwd`) is one on the machine.  akbin's `boxable()` says whether bubblewrap can build
the machines here.
"""

import contextlib
import json
import os
import select
import shlex
import socket
import sys
import tempfile
import threading
from pathlib import Path

from .akbin import _FILES, AK, REPO, Home, _binds, _end

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
    asked.sendall(line[socket.send_fds(asked, [line], [0, 1, 2]):])
    sys.exit(int(asked.recv(16) or 255))
"""


class Machine(Home):
    """A machine, `name`, with its root at `at`, among `machines`."""

    def __init__(self, name, at):
        super().__init__(at=at)
        self.name, self.machines = name, [self]
        self.sshd = self.tmux_dir / "sshd.sock"     # short, as a socket's path must be
        self.fake("ssh", f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -I -c "
                         f'{shlex.quote(SSH)} {shlex.quote(str(self.sshd))} "$@"\n')

    def on(self, env=None, cwd=None):
        """bwrap's words starting a command on this machine, with `env` over its environment, in
        `cwd` on it or else its home; every machine's root, where the test's side keeps it,
        is an empty folder there, past every bind that holds it, a checkout's TMPDIR's too."""
        return ["bwrap", "--dev-bind", "/", "/", "--unshare-uts", "--hostname", self.name,
                "--bind", self.root / "tmp", "/tmp",
                *_binds(self.tmux_dir, REPO, Path(AK).resolve().parent),
                *(word for machine in self.machines
                  for word in ("--tmpfs", machine.root, "--remount-ro", machine.root)),
                "--bind", self.root, self.at, "--chdir", cwd or self.env["HOME"], "--clearenv",
                *(word for item in self._env(env).items() for word in ("--setenv", *item)), "--"]

    def _popen(self, argv, env, cwd, **kwargs):
        return super()._popen([*self.on(env, cwd), *argv], None, None, **kwargs)

    def box(self, box=_FILES):
        """`box` past the /tmp of its own it would make: a machine's is its own already."""
        return [*_FILES[:-2], *box[len(_FILES):], "--"]


class Machines(tuple):
    """Machines of these names, each with its sshd; `close` ends them all."""

    def __new__(cls, *names):
        at = Path(tempfile.mkdtemp(prefix="akbin-")).resolve()
        machines = super().__new__(cls, [Machine(name, at) for name in names])
        machines.sshds = []
        for machine in machines:
            machine.machines = machines
            listener = socket.create_server(str(machine.sshd), family=socket.AF_UNIX)
            thread = threading.Thread(target=_sshd, args=(listener, machines), daemon=True)
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


def _sshd(listener, machines):
    """Take each ssh's call on `listener` until it is shut down."""
    while True:
        try:
            peer = listener.accept()[0]
        except OSError:
            return
        threading.Thread(target=_session, args=(peer, machines), daemon=True).start()


def _session(peer, machines):
    """Run what an ssh asks on the machine it names, with its input and outputs, and answer its
    exit; an ssh gone before it ends ends it, as sshd does."""
    with peer:
        asked, fds, _, _ = socket.recv_fds(peer, 1 << 16, 3)
        machine, code = None, 255
        try:     # whatever it asks, its input and outputs are this side's no longer
            while not asked.endswith(b"\n"):     # the rest of its line
                more = peer.recv(1 << 16)
                if not more:
                    return
                asked += more
            name, command = json.loads(asked)
            machine = next((machine for machine in machines if machine.name == name), None)
            if machine is None:
                os.write(fds[2], f"ssh: Could not resolve hostname {name}: "
                                 "Name or service not known\n".encode())
            else:
                proc = machine._popen(["/bin/sh", "-c", command], None, None,
                                      stdin=fds[0], stdout=fds[1], stderr=fds[2])
        finally:
            for fd in fds:
                os.close(fd)
        if machine is not None:
            ended = os.pidfd_open(proc.pid)
            gone = peer in select.select([peer, ended], [], [])[0]
            os.close(ended)
            if gone:
                return _end(proc)
            code = proc.wait()
        with contextlib.suppress(OSError):      # gone meanwhile
            peer.sendall(b"%d" % (code if code >= 0 else 255))     # killed: 255, as ssh says
