"""The project's own tests a round runs once its reviewer passed it (`roundloop.chosen_tests`):
those its change edits, and those that stopped the most landings.

It hides which they are.  First each file the change adds or edits (`suite_times.origins`) that
the project's time record (`suite_times`) times, whole or in parts, handed whole as the record
spells it; a test file the change adds has no time yet: the task's own check names it, and landing
runs it.  Then those landing checks of the last WINDOW were red on, flakes aside
(`history.test_audit`), each as the name the record times it by: its own, else its file's, for a
runner that reports a file's seconds and names the test that failed (`tests/a.py::test_b`).  A
name stands once, by the most runs one red of it stopped, the most first, as many as their
recorded times fit in one piece of the suite: the median piece of the latest landing check that
ran it whole, or the whole record for a suite that runs uncut or no landing ran whole in pieces
yet.  A test taken by its own name whose file is taken too is not handed, as the file runs it;
the piece a ceiling, its time goes to no other.  Left out are one the record
times by neither name, one whose file is gone, and one the target is red on now by its landing
line's record (`land.red_tests`), a file by a test of it, which no round can fix; one it was red
on and repaired runs again.  A project with no record runs none: only a runner that reports to ak
keeps one, and nothing is declared.  The whole suite runs at landing alone (10 Nov 2026); on 3-16
Nov these cost 2.0-2.5% of it and would have caught 62-67% of the reds a landing blamed on a
change, each of which ran its whole stack's suite again (16 Nov 2026).
"""

import os
from pathlib import Path
import time

from . import config, gitcall, history, suite_times

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
    none to run or does not answer for this change: it answers for a task run and for the review
    of a seat's own PR (`own_pr`) with a checkout of its own (`worktrees.checkout_removable`),
    never for scratch or another's PR, and for a `--no-worktree` task run only where git reads its
    target's tree.  A record's `./tests/a.py` is git's `tests/a.py`."""
    from . import deliver, gate, land, worktrees    # here, not at the top: they reach roundloop
    own = worktrees.checkout_removable(lp.state)
    if lp.scratch or (lp.state.get("review_pr") and not (lp.state.get("own_pr") and own)):
        return None
    line = gitcall.declared_suite(lp.wt, lp.upstream, ref=lp.state.get("target_sha"))
    times = suite_times.read(suite_times.handed(lp.wt)) if line else {}
    if not times:
        return None
    changed = set(suite_times.origins(lp.wt, lp.base_sha))
    tests = sorted({file for file in (test.partition("::")[0] for test in times)
                    if os.path.normpath(file) in changed})
    reds, piece, _ = history.test_audit(Path(lp.state["repo"]).name, _now() - WINDOW)
    try:
        tree = gitcall.git(lp.wt, "rev-parse",
                           f"{lp.state.get('target_sha') or lp.upstream}^{{tree}}")
    except config.Error:
        if own:
            raise
        # A run in the repository itself may aim at a branch origin has none of: with no tree,
        # what the target is red on now cannot be left out, so the round runs none.
        return None
    held = {name for test in land.red_tests(deliver.turn_path(lp, lp.upstream), tree)
            for name in (test, test.partition("::")[0])}
    # One piece of the suite, a ceiling as WINDOW is: a suite cut finer runs fewer.  One the
    # target runs uncut, whatever it ran as before, or no landing ran whole in pieces yet, the
    # whole.
    left = piece if piece is not None and gate.names_shard(line) else sum(times.values())
    runs = {}
    for test, red in reds.items():
        name = test if test in times else test.partition("::")[0]
        if red["landings"] and name in times:
            runs[name] = max(runs.get(name, 0), red["landings"])
    taken = []
    for name, _ in sorted(runs.items(), key=lambda item: (-item[1], item[0])):
        file = name.partition("::")[0]
        if (times[name] <= left and name not in held and file not in tests
                and os.path.isfile(os.path.join(lp.wt, file))):
            taken.append(name)
            left -= times[name]
    tests += [name for name in taken if not ("::" in name and name.partition("::")[0] in taken)]
    return (line, tests) if tests else None
