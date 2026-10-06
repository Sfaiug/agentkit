"""Whether a landing suite ran the test files a change adds.

Every suite ak runs gets an empty directory in `AK_TEST_REPORT`; a project's `tests:` line
writes JUnit XML there, one file per piece.  A test file counts as run when one of its cases
ran and was not skipped.  At landing, every test file the checked tree has beyond the tree it
lands on must have run (`judge`), so a new test file runs before it lands; a miss is an
ordinary red the lander narrows down to its change.  A suite that writes no report is not
judged.  A kind of test file (Python, Go, JavaScript) the report names no case of is not
judged when the report also holds cases it does not tie to a file (node's own junit reporter
names none), nor a file whose name in the report several test files share.
"""

import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

ENV = "AK_TEST_REPORT"
# The usual test file names across Python, Go and JavaScript; files under a fixtures
# folder are a test's data, not tests.
TEST_FILE = re.compile(r"(?:^|/)(?:test_[^/]+\.py|[^/]+_test\.(?:py|go)"
                       r"|[^/]+\.(?:test|spec)\.[cm]?[jt]sx?)$")
NEVER_RAN = "Test files the suite never ran: "


def test_files(checkout, tree="HEAD"):
    """The test files in `tree` of `checkout`, by name."""
    out = subprocess.run(["git", "-C", str(checkout), "ls-tree", "-r", "-z", "--name-only", tree],
                         capture_output=True, stdin=subprocess.DEVNULL, check=True,
                         timeout=120).stdout
    return {path for path in out.decode("utf-8", "replace").split("\0")
            if path and TEST_FILE.search(path) and "fixtures" not in path.split("/")[:-1]}


def kind(name):
    return "py" if name.endswith(".py") else "go" if name.endswith(".go") else "js"


def ran(report_dir, files, checkout):
    """(the `files` a report under `report_dir` ran a case of, whether it also ran cases it
    ties to no test file, the `files` behind a name several of them share), or None when it
    holds no report."""
    reports = sorted(Path(report_dir).rglob("*.xml"))
    if not reports:
        return None
    # A runner started in a subfolder names its files from there: match on a path's tail,
    # and only when one tracked test file has it.
    tails = {}
    for name in files:
        parts = name.split("/")
        for start in range(len(parts)):
            tails.setdefault("/".join(parts[start:]), set()).add(name)
    seen, blind, unsure, known = set(), False, set(), {}
    for path in reports:
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            continue        # a half-written report proves nothing ran
        for parent in root.iter():
            for case in parent.findall("testcase"):
                if case.find("skipped") is not None:
                    continue
                key = (case.get("file") or parent.get("file"), case.get("classname"))
                if key not in known:
                    known[key] = _file(*key, tails, checkout)
                hit, shared = known[key]
                if hit:
                    seen.add(hit)
                elif shared:
                    unsure |= shared
                else:
                    blind = True
    return seen, blind, unsure


def _file(path, classname, tails, checkout):
    """(the one test file a case belongs to, by its own path, else its dotted module name, or
    None; the files sharing the name it gave when none is the one)."""
    candidates = []
    if path:
        if os.path.isabs(path):
            path = os.path.relpath(path, checkout)
        candidates.append(path.removeprefix("./"))
    if classname:
        parts = classname.split(".")
        candidates += ["/".join(parts[:end]) + ".py" for end in range(len(parts), 0, -1)]
        candidates.append(classname)        # JavaScript reporters put the path here
    shared = set()
    for candidate in candidates:
        found = tails.get(candidate, set())
        if len(found) == 1:
            return next(iter(found)), set()
        shared = shared or found
    return None, shared


def judge(checkout, report_dir, tree, base):
    """'' when the passed suite of the checked `tree` ran every test file `tree` has beyond
    `base`, the tree it lands on; else why not."""
    files = test_files(checkout, tree)
    try:
        added = files - test_files(checkout, base)
    except (OSError, subprocess.SubprocessError):
        return ""       # a base gone from the repository bars nothing
    report = ran(report_dir, files, checkout) if added else None
    if report is None:
        return ""       # nothing added, or no report to judge it by
    seen, blind, unsure = report
    judged = {kind(name) for name in seen} if blind else {kind(name) for name in added}
    new = sorted(name for name in added - seen - unsure if kind(name) in judged)
    if not new:
        return ""
    return f"{NEVER_RAN}{', '.join(new)}: add them to the `tests:` suite, or delete them."
