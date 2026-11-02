"""Which runs a read must look at, so that a run long over costs an open screen next to nothing.

A run is open when it has no readable record, its state is not in `record.ENDED`, or its record
was written within the hour or too freshly for `parsed` to keep; otherwise it is at rest.  A read
looks at the open runs and at the list of run directories.  A full read looks at every run again,
its paths resolved again and itself classified again, so a run at rest that moved shows by then.
"""

import time

from . import config, look, parsed, record

# The owner's call on 2 Nov 2026, to bring an idle screen near 0.05 cores: the screen re-reads only
# the runs that can change, and a row may show a run at rest stale until the next full read.
WRITTEN = 3600 * 10**9   # ns a record's write keeps its run open: a home writing more ended runs
                         # looks at more on every read, one writing fewer at fewer
SHARE = 0.005            # the part of a core looking at every run spends at most: more runs or a
                         # slower disk space full reads out up to CEILING, and few runs or a faster
                         # one bring them together until every read is a full one
CEILING = 60             # seconds a run at rest is late at most: a full read costing less comes
                         # sooner (SHARE), and one costing more than CEILING * SHARE spends more
                         # CPU rather than show a staler row


def _directories(_path):
    return record.run_dirs()


def _listed():
    """The run directories, listed again only once the directory of them changed (`parsed`)."""
    try:
        return parsed.read(config.RUNS, _directories)
    except OSError:
        return []


def _open(directory, state):
    if state is None or state.get("state") not in record.ENDED:
        return True
    written = parsed.written(directory / "run.json", record._state, state)
    return written is None or time.time_ns() - written < WRITTEN


class Reader:
    """What one process knows of the runs between its reads."""

    def __init__(self):
        self.listed = []       # the run directories
        self.found = {}        # those with a readable record: (that record, `attended` of it)
        self.open = set()      # those a read looks at
        self.every, self.shown = [], []       # every run's (directory, record), and `attended`'s
        self.due = 0.0         # when the next full read is, on time.monotonic

    def read(self, attended, save):
        """The (directory, record) of each run `attended(record, resolved)` holds, `resolved` being
        this read's; `record.runs()` in its pass answers every run's from it (`look`).  The list is
        the same object while nothing changed, and is never changed in place: only read it.
        `save(looked, went)` is told of the runs looked at and the names of those gone, `went` None
        when every run was looked at."""
        began, full = time.thread_time(), time.monotonic() >= self.due
        listed, went, moved = _listed(), [], False
        if listed != self.listed:      # the same directories: a lock file came or went among them
            before, after = set(self.listed), set(listed)
            self.listed, self.open = listed, (self.open & after) | (after - before)
            went = [run.name for run in before - after if self.found.pop(run, None)]
            moved = bool(went)
        looked, resolved = listed if full else list(self.open), {}
        for directory in looked:
            state = record.read_state(directory, shared=True)
            seen = None if state is None else (state, attended(state, resolved))
            if seen != self.found.get(directory):
                moved = True
                if seen is not None:
                    self.found[directory] = seen
                else:
                    del self.found[directory]
                    went.append(directory.name)
            if _open(directory, state):
                self.open.add(directory)
            else:
                self.open.discard(directory)
        if moved:
            self.every = [(directory, self.found[directory][0]) for directory in listed
                          if directory in self.found]
            self.shown = [run for run in self.every if self.found[run[0]][1]]
        save([directory for directory in looked if directory in self.found],
             None if full else went)
        if full:
            spent = time.thread_time() - began
            self.due = time.monotonic() + min(CEILING, spent / SHARE)
        look.once("runs", lambda: self.every)
        return self.shown
