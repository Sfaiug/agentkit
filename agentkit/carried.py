"""How many sessions the home carries at once, the value of `sessions at once` on its page under
Machines (menu.config_machines): a rough measure for its owner to inspect (24 Nov 2026), read off
the waits for a slot its runs of the last DAYS days measured (history.slot_waits), with no model
of the machine. The week and the tenth are the owner's: shown both on 24 Nov 2026, they said to
build it. A session is the `session` its row holds, so a seat renamed between two of its runs
that overlap counts as two for that time."""

from collections import Counter

from . import history

DAYS = 7


def value(now):
    """Going up from the fewest sessions working at once, the most before the first number whose
    time had a run waiting for its slot a tenth of it or more, said with what it is read from:
    `about N`, `all N seen` where none reached a tenth, `under K` where the fewest did. A run
    waits from its start for its slot_wait_seconds, at most its whole length."""
    steps = []      # (moment, session, its runs started, runs waiting started)
    for session, start, end, wait in history.slot_waits(now - DAYS * 86400, now):
        steps += [(start, session, 1, 1), (min(end, start + wait), session, 0, -1),
                  (end, session, -1, 0)]
    spent, waited = Counter(), Counter()     # seconds with N sessions working, and a run waiting
    working, waiting, last = Counter(), 0, None
    # stable on equal moments, so a run's own steps keep their order and no count goes below 0
    for moment, session, runs, waits in sorted(steps, key=lambda step: step[0]):
        sessions = len(+working)
        if sessions and moment > last:
            spent[sessions] += moment - last
            waited[sessions] += (moment - last) * bool(waiting)
        working[session] += runs
        waiting += waits
        last = moment
    seen, days = sorted(spent), f"(last {DAYS} days)"
    if not seen:
        return f"no runs in the last {DAYS} days"
    over = next((number for number in seen if 10 * waited[number] >= spent[number]), None)
    if over is None:
        return f"all {seen[-1]} seen · no run waited a tenth of the time {days}"
    if over == seen[0]:
        return f"under {over} · with {over} a run waited over a tenth of the time {days}"
    return (f"about {seen[seen.index(over) - 1]} · with more a run waited over a tenth of the "
            f"time {days}")
