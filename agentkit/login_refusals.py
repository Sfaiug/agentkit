"""Which runs each login refused since it last answered, once for each refusal.

A login is a harness, as `worker.LoginExpired.harness` and a parked run's `waiting_for` name
it.  It refuses a run when a worker turn on it ends in `LoginExpired` (`refused`), and answers
when `turns.call_retrying` returns a turn on it (`answered`); the seat's login card reads
`owed`, because `auth` saying yes is no proof a key works.  These three are the whole
interface, and no run path writes here: a run's ending, resume or park neither clears the
count nor keeps it.  How it is kept is this module's alone.
"""

from pathlib import Path

from . import config


def _path():
    return config.STATE / "login-refusals.json"


def _kept(shared=False):
    """{login: [the id of the run, for each refusal since it last answered]}; an unreadable
    file is nothing refused, and the next refusal writes it whole."""
    try:
        kept = config._read_json(_path(), shared=shared)
    except config.Error:
        return {}
    return kept if isinstance(kept, dict) else {}


def _write(change):
    """`change` the memory under its lock, so two runs refused at once both count.  One that
    cannot be written costs the card, never the turn."""
    try:
        with config._record_lock(_path()):
            kept = _kept()
            change(kept)
            config._write_json(_path(), kept, prepare=False)
    except OSError:
        pass


def refused(login, run_dir):
    """A worker turn of the run at `run_dir` on `login` ended in `LoginExpired`."""
    _write(lambda kept: kept.setdefault(login, []).append(Path(run_dir).name))


def answered(login):
    """`turns.call_retrying` returned a turn on `login`: what it refused before is over."""
    if login in _kept(shared=True):     # the usual answer reads, and writes nothing
        _write(lambda kept: kept.pop(login, None))


def owed(run_dir):
    """The login that refused the run at `run_dir` since it last answered, having refused twice
    or more in that time, else None."""
    return next((login for login, runs in _kept(shared=True).items()
                 if len(runs) >= 2 and Path(run_dir).name in runs), None)
