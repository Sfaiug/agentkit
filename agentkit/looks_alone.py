"""Which changes are of looks alone, and the tests each brings: every path a change names against
its target -- added, edited, removed, either side of a rename -- a stylesheet, a raster image, a
font or prose; or, beside one such path at least, a test of the project's own it edits or removes,
a path both the project's time record (`suite_times`) and the path itself call a test.  AGENTS.md,
which holds ak's own rules for the project, is never one of them.  It brings those it edits, as
the record spells them.  Only on a target that declares both `health:` and `deployed:`, so ak
reverts a release whose health breaks (`watch.after_merge_revert`), does such a change land on the
tests it brings and its own quick checks, no whole suite (`land._looks`), its merge saying so with
TRAILER.  What it breaks the next whole run finds as any red on the target.

A test the change adds waits as before, timed or not: a round times one before its change is on
the target.  A test is never a path of looks, whatever its suffix, so a change of tests alone,
doctest pages among them, waits too, as the owner's yes was to changes of looks.  The record's word
alone is not enough: a suite times a module whose doctests it runs, and tests written inside a
source file, and those ship.  Unclear is not a test.

Owner, 16 Nov 2026: "Yes, once auto-undo works" -- such a change waited a median 3.2 h in a line
for a suite that reads almost none of it.  Of one project's month of changes 28 named looks alone
and 46 more looks and tests of their own, 28 of them only tests the record timed.
"""

from pathlib import PurePosixPath
import re

from . import change_rules, gitcall, suite_times

TRAILER = "Looks-Alone-Tree"
# SVG and page wording inside markup are not here: either can hold a script.  Nor MDX, whose
# prose imports and runs components.
SUFFIXES = {".css", ".scss", ".sass", ".less",
            ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".ico",
            ".woff", ".woff2", ".ttf", ".otf", ".eot",
            *change_rules.PROSE} - {".mdx"}
# A path calls itself a test by a directory of one of these names, or one of them a word of its
# file's stem: `tests/a.py`, `test_a.py`, `a_test.go`, `a.spec.ts`.
TEST = {"test", "tests", "spec"}


def changes(repo, target, heads):
    """{each of `heads` whose change against `target` is of looks alone: the tests it brings},
    where `target` declares both `health:` and `deployed:`; none elsewhere, `heads` then never
    read, nor where git cannot say.  Only a target with a `tests:` line has tests to bring."""
    if not all(gitcall.declared_at(repo, target, key) for key in ("health", "deployed")):
        return {}
    # A record's `./tests/a.py::part` is git's `tests/a.py`.
    timed = {PurePosixPath(file): file for file in (
        test.partition("::")[0] for test in suite_times.read(suite_times.handed(repo)))
        } if gitcall.declared_at(repo, target, "tests") else {}
    alone = {}
    for head in heads:
        code, out = gitcall.git_out(repo, "diff", "--name-status", "--no-renames", "-z",
                                    f"{target}...{head}")
        fields = out.split("\0")
        named = {PurePosixPath(path): status for status, path in zip(fields[::2], fields[1::2])}
        if code or any(path.name == "AGENTS.md" for path in named):
            continue
        tests = {path for path in named
                 if path in timed and TEST & {*path.parent.parts, *re.split(r"[._-]", path.stem)}}
        looks = {path for path in named.keys() - tests if path.suffix.lower() in SUFFIXES}
        if (looks and looks | tests == named.keys()
                and all(named[path] in ("M", "D") for path in tests)):
            alone[head] = sorted(timed[path] for path in tests if named[path] == "M")
    return alone
