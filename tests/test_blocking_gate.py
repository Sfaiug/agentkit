"""A later review round re-proves the earlier findings and judges only the fix delta.

Before the reviewer runs, ak replays each earlier blocking finding's proof on the new commit:
one still failing blocks whatever the reviewer hands in, one fixed is a note.  The reviewer is
given the diff since the commit the last review judged, and a new finding outside that delta is
kept as a note, never a blocker: it was judged in an earlier round.  A review of the same commit
again replays nothing and judges the whole change, as before.  Offline: a real git repository, a
scripted reviewer that hands in through `ak hand-in`.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import account_home
from agentkit import config, run, stop, worker
from fixtures.hand_in import scripted, stateful


def finding(site, what, command):
    return ["finding", site, what, "breaks callers", "--run", command]


def quoted(site, what, quote):
    return ["finding", site, what, "breaks callers", "--quote", quote]


def probe(expression):
    return "python3 -c " + shlex.quote(f"import api; raise SystemExit(0 if ({expression}) else 7)")


class BlockingGate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-gate-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(account_home(self.root))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "", "PYTHONPYCACHEPREFIX": "",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        for module, name, value in (
                (worker, "auth_ok", (True, "fixture")), (worker, "marked_pids", []),
                (worker, "kill_marked", True), (stop, "marker_pids", []),
                (run.orch, "stop_scope", None), (run, "note_turn_meters", None),
                (run, "history_role_tokens", None), (run, "memory_cap_note", None),
                (run.history, "update_run", None)):
            self.stack.enter_context(patch.object(module, name, return_value=value))
        config.ensure_dirs()
        self.cfg = config.load()
        self.wt = self.root / "acme"
        self.wt.mkdir()
        run.git(self.wt, "init", "-qb", "main")
        run.git(self.wt, "config", "user.name", "Fixture")
        run.git(self.wt, "config", "user.email", "fixture@example.invalid")
        (self.wt / "api.py").write_text('mode = "base"\nflag = "base"\nextra = 1\n')
        (self.wt / ".gitignore").write_text("__pycache__/\n")
        self.commit("Existing behaviour")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        run.git(self.wt, "checkout", "-qb", "ak/fix-api")
        (self.wt / "api.py").write_text('mode = "branch"\nflag = "branch"\nextra = 1\n')
        self.commit("Change both settings")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        self.directory = self.root / "run"
        self.directory.mkdir()
        self.plan = self.root / "plan.json"
        adapter = self.root / "adapter"
        body = f'''import json, pathlib, subprocess, sys
plan = pathlib.Path({str(self.plan)!r})
rows = json.loads(plan.read_text())
row = rows.pop(0) if len(rows) > 1 else rows[0]
plan.write_text(json.dumps(rows))
for args in row.get("commands", []) + [["done"]]:
    subprocess.run([sys.executable, {str(REPO / "bin/ak")!r}, "hand-in", *args], check=True)
out = pathlib.Path(sys.argv[6])
(out / "final.md").write_text("Handed in.")
(out / "session_id").write_text("fixture-session")
'''
        adapter.write_text(f"#!{sys.executable}\n{scripted(body)}")
        adapter.chmod(0o755)
        stateful(adapter, self.root, {m["harness"] for m in self.cfg["models"].values()})
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(self.root)}))
        self.stack.enter_context(patch.object(config, "adapter", return_value=adapter))
        state = {"run_id": "gate-fixture", "title": "Later rounds", "state": "running",
                 "base": "main", "base_sha": self.base, "branch": "ak/fix-api", "rounds": 3,
                 "executor": "opus", "reviewer": "astra", "round_summaries": [],
                 "repo": str(self.wt), "worktree": str(self.wt)}
        self.logs = []
        self.lp = run.Loop(self.cfg, self.directory, state, {}, self.logs.append, self.wt,
                           "# Fixture", ["true"], "context", [])
        self.lp.rnd = 0
        self.lp.validation = run.commit_identity(self.wt)
        self.mode_fixed = probe('api.mode == "fixed"')
        self.flag_fixed = probe('api.flag == "fixed"')
        self.never = probe("False")

    def commit(self, message):
        run.git(self.wt, "add", ".")
        run.git(self.wt, "commit", "-qm", message)

    def write(self, content, message):
        """A new commit on the branch: what a fix round leaves behind."""
        (self.wt / "api.py").write_text(content)
        self.commit(message)
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        self.lp.validation = run.commit_identity(self.wt)

    def review(self, *commands, record=True):
        """One review round: the scripted reviewer hands in `commands`, then done."""
        self.lp.rnd += 1
        self.plan.write_text(json.dumps([{"commands": commands}]))
        verdict = run.review(self.lp, "## Summary\nFixture", True, "$ true\n[exit 0]", record=record)
        self.assertEqual(run.git(self.wt, "rev-parse", "HEAD"), self.head)
        self.assertEqual(run.git(self.wt, "status", "--porcelain"), "")
        return verdict

    def dispute(self, path, line, what, command):
        """The fixer disputed that finding with a passing command: what its turn leaves for the
        next reviewer (`dispute_files`)."""
        finding = next(row for row in self.lp.state["review_records"]
                       if row["kind"] == "finding" and (row["path"], row["line"]) == (path, line))
        file = self.directory / f"round-{self.lp.rnd + 1}" / "executor" / "hand-in.jsonl"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("".join(json.dumps(row) + "\n" for row in (
            {"kind": "turn", "workspace": str(self.wt), "role": "fixer", "findings": []},
            {"kind": "dispute", "path": path, "line": line, "what": what, "why": "it is right",
             "evidence": {"run": command, "returncode": 0, "output": ""}, "finding": finding})))
        self.lp.state.setdefault("dispute_files", []).append(str(file))

    def records(self, kind):
        return [(row["path"], row["line"], row.get("replayed") or row.get("outside") or "")
                for row in self.lp.state["review_records"] if row["kind"] == kind]

    def prompt(self):
        [path] = (self.directory / f"round-{self.lp.rnd}").glob("reviewer*/prompt.md")
        return path.read_text()

    def test_round_two_re_proves_the_earlier_findings_and_judges_only_the_fix_delta(self):
        self.assertEqual(self.review(finding("api.py:1", "mode is wrong", self.mode_fixed),
                                     finding("api.py:2", "flag is wrong", self.flag_fixed)), "FAIL")
        self.assertEqual(self.lp.state["round_summaries"][-1]["finding_count"], 2)
        self.assertNotIn("## Fix delta", self.prompt())
        # the fix round mends the first and leaves the second; the reviewer re-finds nothing
        # and raises something new on a line the fix never touched
        self.write('mode = "fixed"\nflag = "branch"\nextra = 1\n', "Fix the mode")
        self.assertEqual(self.review(finding("api.py:3", "extra is odd", self.never)), "FAIL")
        self.assertEqual(self.records("finding"),
                         [("api.py", 2, "still failing; it blocks until its proof passes")])
        self.assertEqual(sorted(self.records("note")), [
            ("api.py", 1, "fixed; its proof passes now"),
            ("api.py", 3, f"the fix delta since {self.lp.state['round_summaries'][0]['head_sha'][:12]}; "
                          "judged in an earlier round")])
        self.assertEqual(self.lp.state["round_summaries"][-1]["finding_count"], 1)
        prompt = self.prompt()
        self.assertIn("## Fix delta", prompt)
        self.assertIn("## Earlier findings, re-proven by ak on this commit", prompt)
        self.assertIn("api.py:1 - mode is wrong - fixed (the proof passes now)", prompt)
        self.assertIn("api.py:2 - flag is wrong - still fails (exit 7)", prompt)
        self.assertNotIn("anything new", prompt)
        # the reviewer's conversation resumes, so it holds the whole change already
        self.assertNotIn("## Diff (main...HEAD", prompt)
        self.assertIn("Re-proven by ak on this commit: still failing", self.lp.findings)
        self.assertIn("Outside the fix delta", self.lp.findings)

    def test_a_new_finding_inside_the_fix_delta_blocks_and_everything_fixed_passes(self):
        self.assertEqual(self.review(finding("api.py:1", "mode is wrong", self.mode_fixed)), "FAIL")
        self.write('mode = "fixed"\nflag = "branch"\nextra = 1\n', "Fix the mode, badly")
        self.lp.review_sid = None     # a conversation that cannot resume sees the whole change too
        both = probe('api.mode == "fixed" and api.flag == "fixed"')
        self.assertEqual(self.review(finding("api.py:1", "the fix is half of it", both)), "FAIL")
        self.assertEqual(self.records("finding"), [("api.py", 1, "")])
        self.assertEqual(self.records("note"), [("api.py", 1, "fixed; its proof passes now")])
        prompt = self.prompt()
        self.assertIn("## Diff (main...HEAD", prompt)
        self.assertIn("## Fix delta", prompt)
        self.write('mode = "fixed"\nflag = "fixed"\nextra = 1\n', "Fix it properly")
        self.assertEqual(self.review(), "PASS")
        self.assertEqual(self.records("finding"), [])
        self.assertEqual(self.records("note"), [("api.py", 1, "fixed; its proof passes now")])
        self.assertEqual(self.lp.state["round_summaries"][-1]["finding_count"], 0)

    def test_a_finding_handed_in_again_at_its_moved_line_upholds_it(self):
        # by quote: the fix mends line 1 and adds a line above the flag, which moves untouched
        self.assertEqual(self.review(quoted("api.py:2", "flag is wrong", 'flag = "branch"')), "FAIL")
        self.write('mode = "fixed"\nimport os\nflag = "branch"\nextra = 1\n', "Fix the mode, add an import")
        self.assertEqual(self.review(quoted("api.py:3", "flag is wrong", 'flag = "branch"')), "FAIL")
        self.assertEqual(self.records("finding"), [("api.py", 3, "")])
        prompt = self.prompt()
        self.assertIn("## Earlier findings left to you", prompt)
        self.assertIn("api.py:2 - flag is wrong - a quote, which ak cannot re-prove", prompt)
        # ... and after a dispute: the --run finding is the reviewer's to weigh, not ak's
        self.setUp()
        self.assertEqual(self.review(finding("api.py:2", "flag is wrong", self.flag_fixed)), "FAIL")
        self.write('mode = "fixed"\nimport os\nflag = "branch"\nextra = 1\n', "Fix the mode, add an import")
        self.dispute("api.py", 2, "flag is wrong", probe("True"))
        # ... rejected in the reviewer's own words, at the line the flag sits on now
        self.assertEqual(self.review(finding("api.py:3", "the flag still reads branch", self.flag_fixed)), "FAIL")
        self.assertEqual(self.records("finding"), [("api.py", 3, "")])
        prompt = self.prompt()
        self.assertIn("api.py:2 - flag is wrong - disputed by the fixer", prompt)
        self.assertNotIn("still fails", prompt)

    def test_a_round_after_a_landing_re_review_gets_the_delta_and_the_replay(self):
        # a landing re-review judges the whole change and records nothing of its own ...
        self.assertEqual(self.review(finding("api.py:1", "mode is wrong", self.mode_fixed),
                                     record=False), "FAIL")
        self.assertNotIn("## Fix delta", self.prompt())
        # ... yet the fix round after it stands on the commit it judged
        self.lp.state.update(verdict=None, review=None)     # what execute() clears before a fixer
        self.write('mode = "fixed"\nflag = "branch"\nextra = 1\n', "Fix the mode")
        self.assertEqual(self.review(), "PASS")
        prompt = self.prompt()
        self.assertIn("## Fix delta", prompt)
        self.assertIn("api.py:1 - mode is wrong - fixed (the proof passes now)", prompt)

    def test_a_review_of_the_same_commit_again_replays_nothing(self):
        self.assertEqual(self.review(finding("api.py:1", "mode is wrong", self.mode_fixed)), "FAIL")
        self.assertEqual(self.review(), "PASS")
        self.assertNotIn("## Fix delta", self.prompt())
        self.assertEqual(self.records("note"), [])

    def test_the_prompts_no_longer_ask_for_anything_new_or_every_instance(self):
        for role, text in worker.PREAMBLES.items():
            with self.subTest(role=role):
                self.assertNotIn("anything new", text)
                self.assertNotIn("every instance", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
