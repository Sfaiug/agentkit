"""The PATH shims a seat's commands run, in an answer-key Home: what they pass and refuse.

A seat finds ak's shims first on its PATH, in `~/.agentkit/bin` (tmux, gh, git, scp, rsync,
sftp), where ak puts them when a seat opens.  `Shims` opens one as a person does, from a
terminal, so they are the build's own, then stops that seat: the shims stay and no seat of the
launch's is left.  `run` is a command a seat runs, its name found on the seat's PATH: the shims
first, then the Home's own, so the real tool behind a shim is the Home's real tmux, held to the
Home's servers, or a fake.  Judge a shim by its exit code, what it printed, and whether the real
tool ran: what tmux holds and each pane received, or a fake's calls (`home.calls`).

    from fixtures.akbin import SOCKET, Home
    from fixtures.akseat import Seat
    from fixtures.shims import Shims
    with Home() as home:
        shims = Shims(home)
        Seat(home, "acme"), Seat(home, "beta")
        done = shims.run("tmux", "-L", SOCKET, "kill-session", "-t", "beta", seat="acme")
        assert done.code == 1 and "beta" in done.err
        shims.fake("gh")
        assert shims.run("gh", "pr", "merge", "7", seat=None).code == 0
        assert home.calls("gh") == [["pr", "merge", "7"]]

`seat=None` runs outside any seat; `env` adds to the environment, and a None value removes a
variable (`{"AK_RUN_ROLE": "worker"}` is a worker's).  The Home's tmux follows no TMUX variable,
so a seat's call reaches ak's server by its name, `-L SOCKET`.
"""

import os
import shlex
import sys
import time

from .akbin import LOG
from .akterm import Terminal


class Shims:
    """`name` is the seat opened to install them; it is stopped once they are in place."""

    def __init__(self, home, name="shimseat"):
        self.home = home
        self.dir = home.path / ".agentkit" / "bin"
        term = Terminal(home, "orch", name, "--model", "opus", "--workers", "opus")
        deadline = time.monotonic() + 60
        # a seat is open once the person's terminal is in it, or the launch has ended
        while not (home.tmux("list-clients", "-t", f"={name}").out or term.status.exists()):
            if time.monotonic() > deadline:
                raise AssertionError(f"no seat {name} opened; the terminal shows:\n"
                                     f"{term.screen()}")
            time.sleep(0.05)
        stopped = home.ak("orch", "stop", name)
        assert stopped.code == 0, f"ak orch stop {name} exited {stopped.code}: {stopped.err}"
        term.exit_code()
        assert self.dir.is_dir(), f"opening a seat put no shims in {self.dir}"

    def env(self, seat="acme", env=None):
        """A seat's command's environment: its name, and the shims first on its PATH."""
        return {"AGENTKIT_SESSION": seat,
                "PATH": os.pathsep.join([str(self.dir), self.home.env["PATH"]]), **(env or {})}

    def run(self, *argv, seat="acme", env=None, input=None, cwd=None):
        """Run a command as that seat's own, through its shim; see `Home.run`."""
        assert (self.dir / argv[0]).exists(), f"no {argv[0]} shim in {self.dir}"
        return self.home.run(*argv, input=input, env=self.env(seat, env), cwd=cwd)

    def fake(self, tool, code=0, out=""):
        """Put a real `tool` behind its shim that keeps each call for `home.calls(tool)`,
        prints `out` and exits `code`."""
        script = LOG.format(python=shlex.quote(sys.executable),
                            log=shlex.quote(str(self.home.log(tool))))
        return self.home.fake(tool, f"{script}printf %s {shlex.quote(out)}\nexit {code}\n")
