"""A seat that holds `FLOOR` of a core is told.

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

# Of a core: a wait that polls hard, reading a long log every second or two between short
# sleeps, holds 0.5 to 0.8 for hours, while on 18 Nov 2026 the busiest of 19 seats at work used
# 0.07 over a tick's interval and waited for 0.02 more.  A seat's own shell needs no more beside
# more cores, so no host's size moves it.
FLOOR = 0.5
AGAIN = 3600    # seconds before a seat still holding FLOOR is told again
LINE = ("This seat has held {cores:.1f} CPU cores for {held}{busiest}. A wait belongs in `sleep` "
        "inside a script, or in `ak wait`.")


def _now():
    """The time this module reads: seconds since boot, which no change of the wall clock steps
    and on which each process's start is read.  An answer key names its clock in
    `AK_CORES_CLOCK`, a file of those seconds read anew each time; unset, the real clock."""
    clock = os.environ.get("AK_CORES_CLOCK")
    return float(Path(clock).read_text()) if clock else time.clock_gettime(time.CLOCK_BOOTTIME)


def tell(state, log):
    """Owe each seat whose scope used or waited for FLOOR of a core or more over each of the last
    two intervals a line saying so, once, and again each AGAIN while it goes on; an interval under
    starts the count over.  Each scope's reading is kept in `state` for the next tick, its waiting
    as last read and when (`waited`, `waited_at`: a tick may leave it unread), and on one whose
    last interval was over, `since` it was first held, what it had held by then (`since_held`:
    the line says what it held over that time) and each process's CPU time: its busiest is the
    one that spent most of the next interval, as a shell days old that has just begun to spin has
    spent little of its life.  One not read then counts from nothing only if it began since: one
    moved into the scope brings the time it spent before."""
    now, before, state["seat_cores"] = _now(), state.get("seat_cores") or {}, {}
    for scope, launched in front.scopes().items():
        used, waited = host.cpu_held_usec(scope)
        if used is None:
            continue
        # A reading under `usec` counted used time alone: against one with a lifetime's waiting
        # its interval would be over, so it is no reading.
        last = before.get(scope.name) or {}
        # Each count rises from where it was itself last read: waiting a tick leaves unread
        # stands as it was read, and when, and all a scope ever waited, read for the first time,
        # is no part of an interval.
        was, read = last.get("waited"), now
        if waited is None:
            waited, read = was, last.get("waited_at")
        held = used + (waited or 0)
        seen = state["seat_cores"][scope.name] = {"at": now, "held": held, "waited": waited,
                                                  "waited_at": read}
        if "held" not in last or now <= last["at"]:
            continue
        # A streak goes on from one reading's time and count together: one saved with a time
        # alone (before 18 Nov 2026) starts over, as a count read later would say less was held.
        going = "since_held" in last
        rose, more = used - last["held"] + (was or 0), 0 if was is None else waited - was
        unsure = 0
        if "waited" not in last:
            # A reading saved until 18 Nov 2026 does not say whether its count has the waiting in
            # it.  One greater than all the scope has used since has, and a scope that never
            # waited has none to count (`sure`).  Past another count the interval held what was
            # used and perhaps all the scope ever waited besides (`unsure`), and a streak begun
            # at one starts over: a count with the waiting and one without differ by it all.
            sure = lambda count: waited == 0 or count > used
            if sure(last["held"]):
                rose += waited or 0
            else:
                unsure = waited or 0
            going = going and sure(last["since_held"])
        # Waiting read again after ticks that left it unread rose over all of them, and over no
        # stretch of them by more than the time that passed: what of it came since `start` is
        # at least what the time before could not hold.
        within = lambda start: more and max(0, more - 1e6 * max(0, start - last["waited_at"]))
        floor = FLOOR * 1e6 * (now - last["at"])
        if rose + within(last["at"]) < floor:
            # Under.  Where what is unsure may have made it up, nothing says the seat let go, so
            # when it was told stands.
            if rose + unsure >= floor:
                seen["told"] = last.get("told")
            continue
        # `since_held` is this count less what the streak held, whatever a count rose besides.
        since = last["since"] if going else last["at"]
        streak = rose + within(since) + (last["held"] - last["since_held"] if going else 0)
        seen.update(since=since, since_held=held - streak, told=last.get("told"),
                    ticks=host.cpu_ticks(scope))
        if going and (seen["told"] is None or now - seen["told"] >= AGAIN):
            seen["told"] = now
            # a start is read in whole ticks, rounded down: one born in the reading's own tick
            # but after it reads as that tick
            spent = {process: ticks - last["ticks"].get(process, 0)
                     for process, ticks in seen["ticks"].items() if process in last["ticks"]
                     or int(process.split(" ")[1]) >= int(last["at"] * os.sysconf("SC_CLK_TCK"))}
            busiest = max(spent, key=spent.get, default="").split(" ")[0]
            _tell(front.seat_now(launched), busiest and host.command(busiest),
                  held - seen["since_held"], now - seen["since"], log)


def holding(state):
    """[(seat, seconds)] of each seat whose scope the tick's last reading (`tell`) found holding
    FLOOR of a core, `since` when, and how long it had by then, longest first.  A respawn's new
    scope may sit beside its old one: a seat holding it in both is named once, with the longest."""
    launched = {}
    for scope, seen in (state.get("seat_cores") or {}).items():
        if "since" in seen:
            name = front.SEAT_SCOPE.fullmatch(scope)[1]
            launched[name] = max(launched.get(name, 0), seen["at"] - seen["since"])
    held = {}
    for name, seconds in launched.items():
        # asked once for a launch name: a rename between two askings named one seat twice
        seat = front.seat_now(name)
        held[seat] = max(held.get(seat, 0), seconds)
    return sorted(held.items(), key=lambda seat: -seat[1])


def _tell(name, command, usec, seconds, log):
    """Owe that seat the line for the CPU time it held over those seconds, as the tick's log says
    it, unless the last is still owed: two lines would each open a turn."""
    line = LINE.format(cores=usec / 1e6 / seconds, held=orch.span(seconds),
                       busiest=command and f"; its busiest process: `{command[:160]}`")
    log(f"{name}: {line}")
    if not any(owed.get("cores") for owed in watch.seat_read(name).get("owed_lines") or ()):
        watch.owe_line(name, None, {"line": line, "cores": True})
