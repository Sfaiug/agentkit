"""Which changes are of looks alone, and the tests each brings: every path a change names against
its target -- added, edited, removed, either side of a rename -- a raster image, a font or prose,
known by its suffix alone; or, beside one such path at least, a test of the project's own it edits
or removes, a path both the project's time record (`suite_times`) and the path itself call a test.
AGENTS.md, which holds ak's own rules for the project, is never one of them, nor a schema path
(`change_rules.schema`), which a revert cannot undo.  It brings those it edits, as the record
spells them.
Nor is a stylesheet or a page, whatever its edit: a style can hide or cover a login or payment
control, which a project's whole suite that drives a browser sees, and only a browser's reading of
a page tells its words from its styles.  Owner, 13 Nov 2026: "Money, login, member data, e-mails
and database changes must never break: always fully tested before going live."
Only on a target that declares both `health:` and `deployed:`, so ak reverts a release whose
health breaks (`watch.after_merge_revert`; owner, 16 Nov 2026: "Yes, once auto-undo works"), and
whose project has a time record of its suite (`suite_times`), so a repository whose runner reports
no tests completes whole landing checks and its sessions are told (`stop.untested`,
`suite_times.unreported`; owner, 18 Nov 2026: "Keep trying to enforce"), does such a change land
on the tests it brings and its own quick checks, no whole suite (`land._looks`), its merge saying
so with TRAILER.  What it breaks the next whole run finds as any red on the target.

A change that adds a test waits as before, even one a round timed before the change was on the
target, and so does a change of tests alone, as the owner's yes was to changes of looks: a test is
never a path of looks, whatever its suffix, a doctest page among them.  The record's word alone is
not enough: a suite times a module whose doctests it runs, and tests written inside a source
file, and those ship.  Unclear is not a test.
"""

from pathlib import PurePosixPath
import re

from . import change_rules, gitcall, suite_times

TRAILER = "Looks-Alone-Tree"
# SVG is not here: it can hold a script.  Nor MDX, whose prose imports and runs components.
SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".ico",
            ".woff", ".woff2", ".ttf", ".otf", ".eot",
            *change_rules.PROSE} - {".mdx"}
# A path calls itself a test by a directory of one of these names, or one of them a word of its
# file's stem: `tests/a.py`, `test_a.py`, `a_test.go`, `a.spec.ts`.
TEST = {"test", "tests", "spec"}


def changes(repo, target, heads):
    """{each of `heads` whose change against `target` is of looks alone: the tests it brings},
    where `target` declares both `health:` and `deployed:` and the project has a time record of
    its suite (`suite_times`); none elsewhere, `heads` then never read, nor where git cannot say.
    Only a target with a `tests:` line has tests to bring."""
    if not (all(gitcall.declared_at(repo, target, key) for key in ("health", "deployed"))
            and (times := suite_times.read(suite_times.handed(repo)))):
        return {}
    # A record's `./tests/a.py::part` is git's `tests/a.py`.
    timed = {PurePosixPath(file): file for file in (
        test.partition("::")[0] for test in times)
        } if gitcall.declared_at(repo, target, "tests") else {}
    alone = {}
    for head in heads:
        code, out = gitcall.git_out(repo, "diff", "--name-status", "--no-renames", "-z",
                                    f"{target}...{head}")
        if code:
            continue
        fields = out.split("\0")
        named = {PurePosixPath(path): status for status, path in zip(fields[::2], fields[1::2])}
        if any(path.name == "AGENTS.md" or change_rules.schema(path) for path in named):
            continue
        tests = {path for path in named
                 if path in timed and TEST & {*path.parent.parts, *re.split(r"[._-]", path.stem)}}
        looks = named.keys() - tests
        if (looks and all(named[path] in ("M", "D") for path in tests)
                and all(path.suffix.lower() in SUFFIXES for path in looks)):
            alone[head] = sorted(timed[path] for path in tests if named[path] == "M")
    return alone

