"""How often each login refused runs since it last answered, and which runs it refused.

A login is a harness, as `worker.LoginExpired.harness` and a parked run's `waiting_for` name
it.  It refuses a run when a worker turn on it ends in `LoginExpired` (`refused`), and answers
when `turns.call_retrying` returns a turn on it (`answered`): a kill, a retried failure, a swap
or a hand-over is neither.  `auth` saying yes is no proof a key works, so the seat's login card
reads `owed`: a login that refused twice or more since it last answered is owed by every run it
refused in that time.  Those three are the whole interface, and no run path writes here: a
run's ending, resume or park neither clears the count nor keeps it.  How it is kept is this
module's alone.
"""

from pathlib import Path

from . import config


def _path():
    return config.STATE / "login-refusals.json"


def _kept(shared=False):
    """{login: {"times": refusals since it last answered, "runs": the ids of the runs}}."""
    try:
        kept = config._read_json(_path(), shared=shared)
    except config.Error:
        return {}       # unreadable is nothing refused: the next refusal writes it whole
    return kept if isinstance(kept, dict) else {}


def _write(change):
    """`change` the memory under its lock, so two runs refused at once both count.  One that
    cannot be written costs the card, never the turn."""
    try:
        with config._record_lock(_path()):
            kept = _kept()
            if change(kept):
                config._write_json(_path(), kept, prepare=False)
    except OSError:
        pass


def refused(login, run_dir):
    """A worker turn of the run at `run_dir` on `login` ended in `LoginExpired`."""
    def count(kept):
        mine = kept.setdefault(login, {"times": 0, "runs": []})
        mine["times"] += 1
        mine["runs"] = [*dict.fromkeys([*mine["runs"], Path(run_dir).name])]
        return True
    _write(count)


def answered(login):
    """`turns.call_retrying` returned a turn on `login`: what it refused before is over."""
    if login in _kept(shared=True):     # the usual answer reads, and writes nothing
        _write(lambda kept: kept.pop(login, None) is not None)


def owed(run_dir):
    """The login that refused the run at `run_dir` since it last answered, having refused twice
    or more in that time, else None."""
    return next((login for login, mine in _kept(shared=True).items()
                 if mine["times"] >= 2 and Path(run_dir).name in mine["runs"]), None)
