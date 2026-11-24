"""A home standing still (`pause.paused`) that another machine says is ak's home becomes that
machine's client, with a standby's job: the work frozen in ak's slice is no longer the pair's, as
the other machine carries on from its copy.  This hides who is asked, the order of the steps, and
the kill file.

Asked, in the order of their names, is each machine a record here says takes over from this one
(`standby._records`), by the record's name, then the home the stamp of this machine's last pass
as a standby names (`standby._last`), where no record asked has its name: a machine that took
over keeps that stamp and has no record of its old home till that home has stepped down under
it.  Each record, and the stamp, is read at its turn, as one may change while a machine before it
is asked.  Each machine is asked whether it holds ak's lease by its own word (`ak standby
--home`): nothing is ended on what this machine lacks, as a lease it cannot read looks the same
as one taken, only on a machine it knows saying it is home.  The first that says so is told first
that this machine copies it, with this machine's name, that machine's stamp
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
        home = next((alias for alias in _machines() if _asked(alias, "--home")), None)
        # without this machine's name and that machine's stamp, no record of it is kept there
        held = standby._home_began(home) if home else []
        # the word read once the stamp is held: a pass of that machine's may write its record
        # here meanwhile, as `back` where that machine's own record of this one says `yes`
        if held and _asked(home, "--copied", *held, standby._told()):
            _kill()
            (config.TMP / standby.FOLDER).mkdir(parents=True, exist_ok=True)
            if standby._keep_job(home):
                checkout = update.agentkit_dir()
                versions.run([str(checkout / "install.sh"), "--client", home], checkout,
                             **update.PINS)


def _machines():
    """The name of each machine to ask, in its turn."""
    asked = set()
    for path in sorted(standby._records()):
        if standby._takes(path):
            asked.add(path.name)
            yield path.name
    if (home := standby._last()[1]) and home not in asked:
        yield home


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
