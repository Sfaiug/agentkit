"""The project's own tests a round runs before its review: those its change edits.

It hides which they are: each file the change adds or edits (`suite_times.origins`) that the
project's time record (`suite_times`) times, whole or in parts, handed whole as the record spells
it.  A project with no record runs none: only a runner that reports to ak keeps one, and nothing is
declared.  A test file the change adds has no time yet: the task's own check names it, and landing
runs it.  The whole suite runs at landing alone (10 Nov 2026); these cost a few thousandths of it
(16 Nov 2026).
"""

import os

from . import gitcall, suite_times


def chosen(lp):
    """(the target's `tests:` line, the tests of it the round's change edits), or None where the
    round has no change of its own (scratch, another's PR) or edits none of them.  A record's
    `./tests/a.py` is git's `tests/a.py`."""
    if lp.scratch or lp.state.get("review_pr"):
        return None
    line = gitcall.declared_suite(lp.wt, lp.upstream, ref=lp.state.get("target_sha"))
    times = suite_times.read(suite_times.handed(lp.wt)) if line else {}
    changed = set(suite_times.origins(lp.wt, lp.base_sha)) if times else set()
    tests = sorted({file for file in (test.partition("::")[0] for test in times)
                    if os.path.normpath(file) in changed})
    return (line, tests) if tests else None
