"""The project's own tests a round runs before its review: those its change edits, and those that
stopped the most landings.

It hides which they are.  First each file the change adds or edits (`suite_times.origins`) that
the project's time record (`suite_times`) times, whole or in parts, handed whole as the record
spells it; a test file the change adds has no time yet: the task's own check names it, and landing
runs it.  Then those landing checks of the last WINDOW were red on, flakes aside
(`history.test_audit`), the most runs stopped first, as many as their recorded times fit in one
piece of the suite: the median a piece took, or the whole record for a suite that runs uncut.
Left out are one the record times not, one whose file is gone, and one the target is red on now
by its landing line's record (`land.red_tests`), which no round can fix; one it was red on and
repaired runs again.  A project with no record runs none: only a runner that reports to ak keeps
one, and nothing is declared.  The whole suite runs at landing alone (10 Nov 2026); on 3-16 Nov
these cost 2.0-2.5% of it and would have caught 62-67% of the reds a landing blamed on a change,
each of which ran its whole stack's suite again (16 Nov 2026).
"""

import os
from pathlib import Path
import time

from . import gitcall, history, suite_times

# The landings looked back over: a ceiling on what a round spends, never a target, so a project
# whose landings were red on fewer tests runs fewer.
WINDOW = 14 * 86400


def _now():
    """The time WINDOW ends at.  An answer key names its clock in `AK_ROUND_CLOCK`, a file of Unix
    seconds; unset, the real clock."""
    clock = os.environ.get("AK_ROUND_CLOCK")
    return float(Path(clock).read_text()) if clock else time.time()


def chosen(lp):
    """(the target's `tests:` line, the tests of it the round runs), or None where the round has
    no change of its own (scratch, another's PR) or none to run.  A record's `./tests/a.py` is
    git's `tests/a.py`."""
    from . import deliver, gate, land    # here, not at the top: they reach roundloop
    if lp.scratch or lp.state.get("review_pr"):
        return None
    line = gitcall.declared_suite(lp.wt, lp.upstream, ref=lp.state.get("target_sha"))
    times = suite_times.read(suite_times.handed(lp.wt)) if line else {}
    if not times:
        return None
    changed = set(suite_times.origins(lp.wt, lp.base_sha))
    tests = sorted({file for file in (test.partition("::")[0] for test in times)
                    if os.path.normpath(file) in changed})
    reds, piece, _ = history.test_audit(Path(lp.state["repo"]).name, _now() - WINDOW)
    held = land.red_tests(deliver.turn_path(lp, lp.upstream), gitcall.git(
        lp.wt, "rev-parse", f"{lp.state.get('target_sha') or lp.upstream}^{{tree}}"))
    # One piece of the suite, a ceiling as WINDOW is: a suite cut finer runs fewer.  One the
    # target runs uncut, whatever it ran as before, or whose pieces nothing timed yet, the whole.
    left = piece if piece is not None and gate.names_shard(line) else sum(times.values())
    for test, red in sorted(reds.items(), key=lambda item: (-item[1]["landings"], item[0])):
        file = test.partition("::")[0]
        if (red["landings"] and test in times and times[test] <= left and test not in held
                and file not in tests and os.path.isfile(os.path.join(lp.wt, file))):
            tests.append(test)
            left -= times[test]
    return (line, tests) if tests else None
