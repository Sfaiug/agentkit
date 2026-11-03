"""Which runs a read must look at, so that a run long over costs an open screen next to nothing.

A run is open when it has no readable record, its state is not in `record.ENDED`, or its record
was written within the hour or too freshly for `parsed` to keep; otherwise it is at rest.  A read
looks at the open runs, resolving the paths only of a record that changed, and at the run
directories as one list of strings.  A full read looks at every run again, its paths resolved again
and itself classified again, so a run at rest that moved, or a symlink that did, shows by then.
"""

import os
from pathlib import Path
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
                         # CPU rather than show a staler row.  Also how long a screen holds git's
                         # answer about a checkout (`orch.git_dirs`).  Not derived from the machine:
                         # it bounds how stale a row may be, which the machine's speed does not
                         # change


def _directories(path):
    with os.scandir(path) as entries:
        return sorted(entry.path for entry in entries if entry.is_dir())


def _listed():
    """The run directories as strings, listed again only once the directory of them changed
    (`parsed`).  A lock file coming or going changes it: a Path for each of thousands of directories
    each time, and comparing those, was most of what an open screen spent on its runs."""
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
        self.listed = {}       # the run directories, sorted: each one's Path by its string
        self.found = {}        # those with a readable record: (that record, `attended` of it)
        self.open = set()      # those a read looks at
        self.every, self.shown = [], []       # every run's (directory, record), and `attended`'s
        self.split = (), [], []   # `shown`, those of it at rest at the last full read -- the same
                                  # list until the next, or until one of them goes -- and the
                                  # others, in its order: a new tuple every read (`menu.Folds`)
        self.due = 0.0         # when the next full read is, on time.monotonic

    def read(self, attended, save):
        """The (directory, record) of each run `attended(record, resolved)` holds, `resolved` being
        this read's, and asked only on a full read or of a record changed since this reader last
        held it; `record.runs()` in its pass answers every run's from it (`look`).  The list is
        the same object while nothing changed, and is never changed in place: only read it.
        `save(looked, went)` is told of the runs looked at and the names of those gone, `went` None
        when every run was looked at."""
        began, full = time.thread_time(), time.monotonic() >= self.due
        listed, went, moved = _listed(), [], False
        if listed != list(self.listed):        # the same: a lock file came or went among them
            before, self.listed = self.listed, {}
            for name in listed:
                directory = before.pop(name, None)
                if directory is None:
                    directory = Path(name)
                    self.open.add(directory)
                self.listed[name] = directory
            self.open.difference_update(before.values())
            went = [run.name for run in before.values() if self.found.pop(run, None)]
        looked, resolved = list(self.listed.values()) if full else list(self.open), {}
        for directory in looked:
            state, held = record.read_state(directory, shared=True), self.found.get(directory)
            if state is None:
                if self.found.pop(directory, None):
                    went.append(directory.name)
            elif full or held is None or held[0] != state:
                seen = state, attended(state, resolved)
                if seen != held:
                    self.found[directory], moved = seen, True
            (self.open.add if _open(directory, state) else self.open.discard)(directory)
        if moved or went:
            self.every = [(directory, self.found[directory][0])
                          for directory in self.listed.values() if directory in self.found]
            self.shown = [run for run in self.every if self.found[run[0]][1]]
        _, rest, moving = self.split
        if full:
            rest = [run for run in self.shown if run[0] not in self.open]
        elif went and any(directory not in self.found for directory, _ in rest):
            rest = [run for run in rest if run[0] in self.found]
        if moved or went or full:
            resting = {directory for directory, _ in rest}
            moving = [run for run in self.shown if run[0] not in resting]
        self.split = self.shown, rest, moving
        save([directory for directory in looked if directory in self.found],
             None if full else went)
        if full:
            self.due = time.monotonic() + min(CEILING, (time.thread_time() - began) / SHARE)
        self.lend()
        return self.shown

    def lend(self):
        """Have `record.runs()` in this pass answer with every run as the last read held it; with
        no read yet (a read's `due` is never 0), it reads for itself."""
        if self.due:
            look.once("runs", lambda: self.every)
