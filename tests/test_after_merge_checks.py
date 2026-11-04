"""After a merge, the tick follows live health and hands a break back to fix.

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
from agentkit import config, history, orch, watch
from agentkit import record

PR = "https://github.com/acme/widget/pull/7"
NOW = 2000000
SEAT = "fix-api"
CHECK = "health: probe"
URL = PR + "; down"

FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if args[:2] == ["pr", "view"]:
    url = args[2] if len(args) > 2 else ""
    try:
        mapping = json.loads(open(os.environ["AFTER_MERGE_PRS"]).read())
    except (OSError, ValueError, KeyError):
        mapping = {}
    oid = mapping.get(url)
    if not isinstance(oid, str) or not oid or oid == "__FAIL__":
        print("fake gh: pr view failed", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"mergeCommit": {"oid": oid}}))
    sys.exit(0)
print(f"fake gh: unexpected call: {args}", file=sys.stderr)
sys.exit(1)
"""


class AfterMerge(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-after-merge-", dir=REPO)
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
        self.health = {}
        self.stack.enter_context(patch.object(
            watch, "after_merge_health",
            lambda directory, st, key, sha, *_args, **_kw: self.health.get(sha)))
        self.prs_path = self.root / "prs.json"
        self.prs_path.write_text("{}")
        self.stack.enter_context(patch.dict(os.environ, {
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
            "AFTER_MERGE_PRS": str(self.prs_path)}))
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

    def merged(self, name, sha=None, age=600, seat=SEAT, pr=PR, target="origin/main"):
        directory = config.RUNS / name
        directory.mkdir()
        state = {"run_id": name, "title": f"Merge {name}", "state": "pass",
                 "verdict": "PASS", "merged": True, "pr": pr, "target": target,
                 "base": "origin/main", "launched_session": seat,
                 "started_at": NOW - age - 60, "finished_at": NOW - age}
        if sha is not None:
            state["merge_sha"] = sha
        record.save_state(directory, state)
        return directory

    def set_health(self, mapping):
        self.health = mapping

    def set_prs(self, mapping):
        self.prs_path.write_text(json.dumps(mapping))

    def follow(self, state=None):
        state = watch.load_state() if state is None else state
        watch.after_merge_checks(state, False, self.logs.append, now=NOW)
        return state

    def test_failed_health_hands_back_to_its_seat(self):
        sha = "a" * 40
        self.merged("run-old", sha)
        history.start_run("run-old", started_at=NOW - 660)
        self.set_health({sha: ("failed", CHECK, URL)})
        self.rows = [self.live(SEAT)]
        self.follow()
        self.assertEqual(self.typed, [(SEAT, (
            f"run run-old NOT LIVE (0 of 0): {CHECK} failed on main after this merge. {URL}. "
            "Fix the target. Next: launch the fix the result names. "
            f"Result: {config.tilde(config.RUNS / 'run-old/result.md')}"))])
        # what got past review and landing is on the change's row once it is told
        self.assertEqual(history.get("run-old")["broke_after_merge"], "health")

    def test_two_failing_commits_hand_back_only_the_first_once(self):
        old, new = "a" * 40, "b" * 40
        self.merged("run-old", old, age=1200)
        self.merged("run-new", new, age=600)
        self.set_health({old: ("failed", "health: old", URL + "/old"),
                         new: ("failed", "health: new", URL + "/new")})
        self.rows = [self.live(SEAT)]
        state = self.follow()
        self.assertEqual(len(self.typed), 1)
        seat, line = self.typed[0]
        self.assertEqual(seat, SEAT)
        self.assertIn("health: old", line)
        self.assertIn(URL + "/old", line)
        self.assertNotIn("health: new", line)
        self.follow(state)
        self.assertEqual(len(self.typed), 1)

    def test_passing_or_absent_health_sends_nothing(self):
        sha = "a" * 40
        self.merged("run-old", sha)
        self.rows = [self.live(SEAT)]
        self.set_health({sha: ("passed", None, None)})
        self.follow()
        self.set_health({sha: None})
        self.follow()
        self.assertEqual((self.typed, [line for line in self.logs if "handed" in line]),
                         ([], []))

    def test_only_the_first_failure_after_the_latest_pass_is_told(self):
        for number, verdict in enumerate(("failed", "passed", "failed", "failed")):
            sha = str(number) * 40
            self.merged(f"run-{number}", sha, age=2400 - number * 600)
            self.health[sha] = verdict, CHECK, URL
        self.rows = [self.live(SEAT)]
        self.follow()
        self.assertEqual(len(self.typed), 1)
        self.assertTrue(self.typed[0][1].startswith("run run-2 NOT LIVE"))

    def test_a_newer_pass_ends_the_break_without_a_notice(self):
        old, new = "a" * 40, "b" * 40
        self.merged("run-old", old, age=1200)
        self.merged("run-new", new, age=600)
        self.set_health({old: ("failed", CHECK, URL), new: ("passed", None, None)})
        self.rows = [self.live(SEAT)]
        self.assertEqual(self.follow()["after_merge"], {})
        self.assertEqual(self.typed, [])

    def test_composed_line_retries_with_its_mark_and_completes(self):
        sha = "a" * 40
        self.merged("run-old", sha)
        self.set_health({sha: ("failed", CHECK, URL)})
        self.rows = [self.live(SEAT, created=100)]
        calls, marks = [], []

        def flaky(session, text, log, cfg=None, typed=None, receipt=lambda mark: None):
            calls.append((session.get("name"), text, typed))
            if typed is None:
                mark = {"line": text, "seat": session.get("created")}
                marks.append(mark)
                receipt(mark)
                return False
            self.typed.append((session.get("name"), text))
            return True

        with patch.object(watch, "type_at_prompt", flaky):
            state = self.follow()
            self.assertEqual(self.typed, [])
            self.follow(state)
        self.assertEqual(len(calls), 2)
        self.assertIsNone(calls[0][2])
        self.assertEqual(calls[1][2], marks[0])
        self.assertEqual(len(self.typed), 1)
        seat, line = self.typed[0]
        self.assertEqual(seat, SEAT)
        self.assertIn(CHECK, line)
        self.assertIn(URL, line)
        with patch.object(watch, "type_at_prompt", flaky):
            self.follow(state)
        self.assertEqual(len(self.typed), 1)

    def test_a_kept_break_says_it_waits_for_a_seat_at_its_prompt_while_nothing_is_typed(self):
        sha = "a" * 40
        self.merged("run-old", sha)
        self.set_health({sha: ("failed", CHECK, URL)})
        self.rows = [self.live(SEAT)]
        with patch.object(watch, "type_at_prompt", lambda *_a, **_kw: False):
            self.follow(self.follow())
        self.assertEqual([line for line in self.logs if "after-merge notice" in line], [
            "run run-old's after-merge notice waits for a live seat at its prompt"] * 2)

    def test_notified_break_is_not_handed_back_again_when_it_ages_out(self):
        old, new = "a" * 40, "b" * 40
        old_age = 3 * 3600 + 600
        self.merged("run-old", old, age=old_age)
        self.merged("run-new", new, age=600)
        self.set_health({new: ("failed", CHECK, URL + "/new")})
        self.rows = [self.live(SEAT)]
        key = watch.after_merge_repo(PR)[3]
        state = {"after_merge": {key: {"notified": old, "at": NOW - 1000,
                                       "run": "run-old", "check": CHECK,
                                       "finished": NOW - old_age}}}
        self.follow(state)
        self.assertEqual(self.typed, [])
        self.assertEqual(state["after_merge"][key]["notified"], old)

    def test_a_health_the_merge_recorded_and_no_probe_ran_is_let_go_past_the_window(self):
        directory = self.merged("run-late", age=watch.AFTER_MERGE_WINDOW + 60)
        record.save_state(directory, {**record.read_state(directory), "health": {"command": "true"}})
        self.set_prs({PR: "__FAIL__"})          # a merge commit gh can never name
        self.rows = [self.live(SEAT)]
        self.follow()
        self.assertEqual(self.typed, [])
        self.assertFalse(any("merge commit" in line for line in self.logs), self.logs)

    def test_unreadable_merge_commit_keeps_the_told_break(self):
        sha = "a" * 40
        self.merged("run-old")
        self.set_health({sha: ("failed", CHECK, URL)})
        self.rows = [self.live(SEAT)]
        key = watch.after_merge_repo(PR)[3]
        state = {"after_merge": {key: {"notified": sha, "at": NOW - 1000,
                                       "run": "run-old", "check": CHECK,
                                       "finished": NOW - 600}}}
        self.set_prs({PR: "__FAIL__"})
        self.follow(state)
        self.assertEqual(self.typed, [])
        self.assertEqual(state["after_merge"][key]["notified"], sha)
        self.set_prs({PR: sha})
        self.follow(state)
        self.assertEqual(self.typed, [])
        self.assertEqual(state["after_merge"][key]["notified"], sha)


if __name__ == "__main__":
    unittest.main()
