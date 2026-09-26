"""After a merge, the tick follows the target's checks and hands a break back to fix.

Offline: a temporary HOME, fake run records, a fake `gh` on PATH and fake seats.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, run, watch

PR = "https://github.com/acme/widget/pull/7"
NOW = 2000000
SEAT = "fix-api"
CHECK = "release-gate"
URL = "https://github.com/acme/widget/actions/runs/123"

FAKE_GH = """#!/usr/bin/env python3
import json, os, re, sys
args = sys.argv[1:]
endpoint = next((a for a in args if "check-runs" in a), None)
if endpoint:
    match = re.search(r"commits/([^/]+)/check-runs", endpoint)
    sha = match.group(1) if match else ""
    try:
        mapping = json.loads(open(os.environ["AFTER_MERGE_CHECKS"]).read())
    except (OSError, ValueError, KeyError):
        mapping = {}
    print(json.dumps({"check_runs": mapping.get(sha, [])}))
    sys.exit(0)
print(f"fake gh: unexpected call: {args}", file=sys.stderr)
sys.exit(1)
"""


def completed(name, conclusion, url=URL):
    return {"name": name, "status": "completed", "conclusion": conclusion,
            "html_url": url}


class AfterMerge(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".after-merge-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root)}))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.cfg = config.load()
        config.ensure_dirs()
        bindir = self.root / "bin"
        bindir.mkdir()
        gh = bindir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.checks_path = self.root / "checks.json"
        self.checks_path.write_text("{}")
        self.stack.enter_context(patch.dict(os.environ, {
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
            "AFTER_MERGE_CHECKS": str(self.checks_path)}))
        self.rows = []
        self.typed = []
        self.logs = []
        self.stack.enter_context(patch.object(orch, "sessions", lambda: list(self.rows)))
        self.stack.enter_context(patch.object(orch, "find", self.find))
        self.stack.enter_context(patch.object(watch, "type_at_prompt", self.send))

    def find(self, name):
        try:
            want = config.resolve_session(name)
        except config.Error:
            want = name
        return next((seat for seat in self.rows if seat["name"] == want), None)

    def send(self, session, text, log, cfg=None, typed=None, receipt=lambda mark: None):
        self.typed.append((session.get("name"), text))
        return True

    def live(self, name, created=100):
        return {"name": name, "created": created, "exited": False}

    def merged(self, name, sha, age=600, seat=SEAT, pr=PR, target="origin/main"):
        directory = config.RUNS / name
        directory.mkdir()
        state = {"run_id": name, "title": f"Merge {name}", "state": "pass",
                 "verdict": "PASS", "merged": True, "pr": pr, "target": target,
                 "base": "origin/main", "merge_sha": sha, "launched_session": seat,
                 "started_at": NOW - age - 60, "finished_at": NOW - age}
        run.save_state(directory, state)
        return directory

    def set_checks(self, mapping):
        self.checks_path.write_text(json.dumps(mapping))

    def follow(self, state=None):
        state = watch.load_state() if state is None else state
        watch.after_merge_checks(state, False, self.logs.append, now=NOW)
        return state

    def test_failed_check_hands_back_to_its_seat(self):
        sha = "a" * 40
        self.merged("run-old", sha)
        self.set_checks({sha: [completed(CHECK, "failure")]})
        self.rows = [self.live(SEAT)]
        self.follow()
        self.assertEqual(self.typed, [(SEAT, (
            f"{CHECK} failed on main after this merge: {URL}. Fix the target."))])

    def test_two_failing_commits_hand_back_only_the_newer_once(self):
        old, new = "a" * 40, "b" * 40
        self.merged("run-old", old, age=1200)
        self.merged("run-new", new, age=600)
        self.set_checks({old: [completed("gate-old", "failure", URL + "/old")],
                         new: [completed("gate-new", "failure", URL + "/new")]})
        self.rows = [self.live(SEAT)]
        state = self.follow()
        self.assertEqual(len(self.typed), 1)
        seat, line = self.typed[0]
        self.assertEqual(seat, SEAT)
        self.assertIn("gate-new", line)
        self.assertIn(URL + "/new", line)
        self.assertNotIn("gate-old", line)
        self.follow(state)
        self.assertEqual(len(self.typed), 1)

    def test_passing_or_cancelled_check_sends_nothing(self):
        sha = "a" * 40
        self.merged("run-old", sha)
        self.rows = [self.live(SEAT)]
        self.set_checks({sha: [completed(CHECK, "success")]})
        self.follow()
        self.set_checks({sha: [completed(CHECK, "cancelled")]})
        self.follow()
        self.assertEqual((self.typed, [line for line in self.logs if "handed" in line]),
                         ([], []))


if __name__ == "__main__":
    unittest.main()
