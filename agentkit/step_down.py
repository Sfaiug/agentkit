"""A home standing still (`pause.paused`) that another machine says is ak's home becomes that
machine's client, with a standby's job: the work frozen in ak's slice is no longer the pair's, as
the other machine carries on from its copy.  This hides who is asked, the order of the steps, and
the kill file.

Asked, in the order of their names, is each machine a record here says takes over from this one
(`standby._records`), by the record's name, whether it holds ak's lease by its own word
(`ak standby --home`): nothing is ended on what this machine lacks, as a lease it cannot read
looks the same as one taken, only on a machine it knows saying it is home.  The first that says
so is told first that this machine copies it, with this machine's name, that machine's stamp
(`standby._home_began`) and the word the records here give then (`standby._told`), which says this
machine takes over, `back` or `yes`, or the step fails, so it keeps a record of that before this
machine can ever watch its lease.  Then what ak's slice holds is ended by its `cgroup.kill`, the
slice left frozen, which a firing of this machine as a home again thaws; the standby's folder is
made, with which a client's install keeps this machine's runs, checkouts and work; the standby's
job is kept; and `install.sh --client` runs last, whose record of a server makes the next firing
a client's.
A step that fails or raises leaves the rest to the next paused firing, from the first.  Each
leaves what a second firing doing the same at once would, so no lock is taken.
"""

import contextlib
import os
import subprocess

from . import config, orch, standby, update, versions


def where_another_is_home():
    """This machine made the client of the first machine asked that says it is home; nothing
    where none does, nor past a step that fails or raises."""
    with contextlib.suppress(Exception):
        home = next((path.name for path in sorted(standby._records())
                     if standby._takes(path) and _asked(path.name, "--home")), None)
        # without this machine's name and that machine's stamp, no record of it is kept there
        held = standby._home_began(home) if home else []
        # the records as the word is sent, which may say `no` by then, as a pass of that machine's
        # may have written meanwhile: told so, it would keep no record of this one taking over
        if (held and (told := standby._told()) in standby.OVER
                and _asked(home, "--copied", *held, told)):
            _kill()
            (config.TMP / standby.FOLDER).mkdir(parents=True, exist_ok=True)
            if standby._keep_job(home):
                checkout = update.agentkit_dir()
                versions.run([str(checkout / "install.sh"), "--client", home], checkout,
                             **update.PINS)


def _asked(alias, *words):
    """Whether `ak standby` with `words` exits 0 on `alias`, asked as a pass sends `--copied`:
    past `standby.TIMEOUT` raises."""
    return subprocess.run(standby._home(alias, *words), stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          timeout=standby.TIMEOUT).returncode == 0


def _kill():
    """Every process in ak's slice ended: `1` written to its `cgroup.kill`, opened without waiting
    and never made, so a slice with none raises, as does a write that takes no byte."""
    kill = os.open(orch.slice_cgroup() / "cgroup.kill", os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if not os.write(kill, b"1"):
            raise OSError("cgroup.kill took no byte")
    finally:
        os.close(kill)
