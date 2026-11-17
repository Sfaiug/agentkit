"""A seat that holds a core is told.

ak weighed its runs' use and never a seat's own shell's: from 12 to 17 Nov 2026 a seat waited on
a log with `read -t 20 < /dev/zero`, which never sleeps, and held a core at normal priority
beside suites at nice 19, a core `gate.derived_heavy_limit` took from the suites' room.  Each
tick keeps what CPU time each seat's scope has used or waited for, and reads the difference at
the next: a thread that never sleeps on a busy host is given less than a core and waits for the
rest, so its use alone misses it exactly when the core it takes is most missed.  Two samples
inside one tick (`host._cpu_rates`) cannot tell a wait that spins from a moment's work.  Only a
difference over a known interval counts, so a scope new since the last tick is no offence, and
a late tick's is spread over the time it took.
"""

import os
from pathlib import Path
import time

from . import front, host, orch, watch

FULL = 0.9      # of a core: one thread that never sleeps, whatever the host's size
AGAIN = 3600    # seconds before a seat still holding one is told again
LINE = ("This seat has held a whole CPU core for {held}{busiest}. A wait belongs in `sleep` "
        "inside a script, or in `ak wait`.")


def _now():
    """The time this module reads.  An answer key names its clock in `AK_CORES_CLOCK`, a file of
    Unix seconds read anew each time; unset, the real clock."""
    clock = os.environ.get("AK_CORES_CLOCK")
    return float(Path(clock).read_text()) if clock else time.time()


def tell(state, log):
    """Owe each seat whose scope used or waited for FULL a core or more over each of the last two
    intervals a line saying so, once, and again each AGAIN while it goes on; an interval under
    starts the count over.  Each scope's reading is kept in `state` for the next tick, and on one
    whose last interval was over, `since` the core was first held and each process's CPU time:
    its busiest is the one that spent most of the next interval, as a shell days old that has
    just begun to spin has spent little of its life."""
    now, before, state["seat_cores"] = _now(), state.get("seat_cores") or {}, {}
    for scope, launched in front.scopes().items():
        held = host.cpu_held_usec(scope)
        if held is None:
            continue
        last = before.get(scope.name)
        seen = state["seat_cores"][scope.name] = {"at": now, "usec": held}
        if not last or now <= last["at"] or held - last["usec"] < FULL * 1e6 * (now - last["at"]):
            continue
        seen.update(since=last.get("since", last["at"]), told=last.get("told"),
                    ticks=host.cpu_ticks(scope))
        if "since" in last and (seen["told"] is None or now - seen["told"] >= AGAIN):
            seen["told"] = now
            spent = {process: ticks - last["ticks"].get(process, 0)
                     for process, ticks in seen["ticks"].items()}
            busiest = max(spent, key=spent.get, default="").split(" ")[0]
            _tell(front.seat_now(launched), busiest and host.command(busiest), now - seen["since"],
                  log)


def _tell(name, command, held, log):
    """Owe that seat the line, as the tick's log says it, unless the last is still owed: two
    lines would each open a turn."""
    line = LINE.format(held=orch.span(held),
                       busiest=command and f"; its busiest process: `{command[:160]}`")
    log(f"{name}: {line}")
    if not any(owed.get("cores") for owed in watch.seat_read(name).get("owed_lines") or ()):
        watch.owe_line(name, None, {"line": line, "cores": True})
