"""A later review round re-proves the earlier findings and judges only the fix delta.

Before the reviewer runs, ak replays each earlier blocking finding's proof on the new commit:
one still failing blocks whatever the reviewer hands in, one fixed is a note.  The reviewer is
given the diff since the commit the last review judged, and a new finding outside that delta is
kept as a note, never a blocker: it was judged in an earlier round.  A review of the same commit
again (a fixer turn that left no commit) judges the whole change and still replays them: a
finding ak proved failing on that very commit blocks until its proof passes.  A replayed proof
on a line the fix put back as base has it is judged on base, as any finding there is.  Offline:
a real git repository, a scripted reviewer that hands in through `ak hand-in`.
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
from agentkit import config, hand_in, run, stop, worker
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

    def review(self, *commands, record=True, ok=True):
        """One review round: the scripted reviewer hands in `commands`, then done."""
        self.lp.rnd += 1
        self.plan.write_text(json.dumps([{"commands": commands}]))
        verdict = run.review(self.lp, "## Summary\nFixture", ok,
                             "$ true\n[exit 0]" if ok else "$ false\n[exit 1]", record=record)
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

    def records_text(self):
        """What the next turn is handed: the earlier findings where they stand now."""
        listed = self.directory / f"round-{self.lp.rnd}" / "earlier.json"
        return "" if not listed.is_file() else "\n".join(
            f"{row['path']}:{row['line']} - {row['what']}" for row in json.loads(listed.read_text()))

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
        self.assertIn("api.py:3 - flag is wrong - a quote, which ak cannot re-prove", prompt)   # listed where it stands
        # ... and after a dispute: the --run finding is the reviewer's to weigh, not ak's
        self.setUp()
        self.assertEqual(self.review(finding("api.py:2", "flag is wrong", self.flag_fixed)), "FAIL")
        self.write('mode = "fixed"\nimport os\nflag = "branch"\nextra = 1\n', "Fix the mode, add an import")
        self.dispute("api.py", 2, "flag is wrong", probe("True"))
        # ... rejected in the reviewer's own words, at the line the flag sits on now
        self.assertEqual(self.review(finding("api.py:3", "the flag still reads branch", self.flag_fixed)), "FAIL")
        self.assertEqual(self.records("finding"), [("api.py", 3, "")])
        self.assertEqual(self.lp.state.get("disputes", []), [])      # the dispute lost: nothing dropped
        prompt = self.prompt()
        self.assertIn("api.py:3 - flag is wrong - disputed by the fixer", prompt)
        self.assertNotIn("still fails", prompt)
        # ... and where the fix rewrote the disputed line and added one above it: upheld at the
        # line the fix put in its place
        self.setUp()
        self.assertEqual(self.review(finding("api.py:2", "flag is wrong", self.flag_fixed)), "FAIL")
        self.write('import os\nmode = "fixed"\nflag = "still wrong"\nextra = 1\n', "Rewrite the flag, add an import")
        self.dispute("api.py", 2, "flag is wrong", probe("True"))
        self.assertEqual(self.review(finding("api.py:3", "the flag still reads wrong", self.flag_fixed)), "FAIL")
        self.assertEqual(self.records("finding"), [("api.py", 3, "")])
        self.assertEqual(self.lp.state.get("disputes", []), [])

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

    def test_a_replay_that_cannot_run_or_finish_proves_no_fix(self):
        (self.wt / "probe.sh").write_text('python3 -c \'import api; raise SystemExit(0 if api.flag == "fixed" else 7)\'\n')
        self.commit("A probe on the branch")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        self.lp.validation = run.commit_identity(self.wt)
        self.assertEqual(self.review(finding("api.py:2", "flag is wrong", "bash probe.sh")), "FAIL")
        (self.wt / "probe.sh").unlink()                  # the fix deletes the probe; the flag stays
        self.commit("Remove the probe")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        self.lp.validation = run.commit_identity(self.wt)
        self.assertEqual(self.review(), "FAIL")
        self.assertEqual(self.records("finding"), [("api.py", 2, "still failing; it blocks until its proof passes")])
        self.assertIn("api.py:2 - flag is wrong - could not run (exit 127); it blocks until its proof passes",
                      self.prompt())

    def test_a_still_failing_finding_is_weighed_where_the_fix_moved_its_line(self):
        self.assertEqual(self.review(finding("api.py:2", "flag is wrong", self.flag_fixed)), "FAIL")
        self.write('mode = "fixed"\nimport os\nflag = "branch"\nextra = 1\n', "Fix the mode, add an import")
        self.assertEqual(self.review(), "FAIL")           # the reviewer hands in nothing
        self.assertEqual(self.records("finding"), [("api.py", 3, "still failing; it blocks until its proof passes")])
        # the record this review took of the earlier findings outlives an attempt that
        # overwrote the last review's records before giving a verdict
        self.lp.state["review_pending"] = {"earlier": [{"kind": "finding", "path": "api.py", "line": 3,
                                                        "what": "flag is wrong", "evidence": {"run": self.flag_fixed}}]}
        self.lp.state["review_records"] = []
        self.assertEqual([row["line"] for row in run.earlier_findings(self.lp)], [3])

    def on_main(self, content, message):
        """Main moves, and the branch is rebased onto it: what a push after a rebase is."""
        run.git(self.wt, "checkout", "-q", "main")
        (self.wt / "api.py").write_text(content)
        self.commit(message)
        run.git(self.wt, "checkout", "-q", "ak/fix-api")
        run.git(self.wt, "rebase", "-q", "main")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        self.lp.validation = run.commit_identity(self.wt)
        self.lp.state["base_sha"] = run.git(self.wt, "rev-parse", "main")    # the merge base now

    def test_an_earlier_finding_is_placed_in_the_reviewed_commits_own_coordinates(self):
        run.git(self.wt, "checkout", "-q", "main")
        (self.wt / "api.py").write_text("# a\n# b\n# c\nvalue = 1\n")
        self.commit("A base with room above the value")
        run.git(self.wt, "checkout", "-q", "-B", "ak/fix-api", "main")
        self.lp.state["base_sha"] = run.git(self.wt, "rev-parse", "main")
        self.write("# a\n# b\n# c\nvalue = 2\n", "Change the value")
        self.assertEqual(self.review(finding("api.py:4", "the value is wrong", probe("api.value == 1"))), "FAIL")
        reviewed = self.head
        # a push rebased onto a main that grew above the value: the finding moves with its line
        self.on_main("# top\n# a\n# b\n# c\nvalue = 1\n", "Main grows a line above")
        self.assertEqual(run.moved_lines(self.lp, "api.py", 4, reviewed, self.head), (range(5, 6), False))
        self.assertEqual(self.review(), "FAIL")
        self.assertEqual(self.records("finding"), [("api.py", 5, "still failing; it blocks until its proof passes")])

    def test_a_line_only_the_base_changed_after_the_fork_is_not_the_changes(self):
        # a base ahead of the branch's fork point: a `from:` launch whose merge of the target
        # conflicted, a run on a branch behind origin
        run.git(self.wt, "checkout", "-q", "main")
        (self.wt / "api.py").write_text('mode = "base"\nflag = "base"\nextra = 3\n')
        self.commit("Main changes extra")
        self.lp.state["base_sha"] = run.git(self.wt, "rev-parse", "main")
        run.git(self.wt, "checkout", "-q", "ak/fix-api")
        self.assertTrue(run.changed_line(self.lp, {"path": "api.py", "line": 1}, self.head))
        self.assertFalse(run.changed_line(self.lp, {"path": "api.py", "line": 3}, self.head))
        self.assertEqual(self.review(quoted("api.py:3", "extra is odd", "extra = 1")), "PASS")

    def test_a_touched_line_still_failing_is_one_finding_with_the_reviewers_own(self):
        self.assertEqual(self.review(finding("api.py:2", "flag is wrong", self.flag_fixed)), "FAIL")
        # the fix rewrites the flag's line, still wrongly, and adds a line above it
        self.write('mode = "fixed"\nimport os\nflag = "still wrong"\nextra = 1\n', "Rewrite the flag, badly")
        self.assertEqual(self.review(finding("api.py:3", "the flag still reads wrong", self.flag_fixed)), "FAIL")
        self.assertEqual(self.records("finding"), [("api.py", 3, "")])      # no copy beside it
        # ... while another check at that site leaves ak's own replay blocking beside it
        self.write('mode = "fixed"\nimport os\nflag = "still wrong"\nextra = 2\n', "Still wrong")
        self.assertEqual(self.review(finding("api.py:3", "another defect", self.never)), "FAIL")
        self.assertEqual(sorted(self.records("finding")),
                         [("api.py", 3, ""), ("api.py", 3, "still failing; it blocks until its proof passes")])
        self.write('mode = "fixed"\nimport os\nflag = "fixed"\nextra = 2\n', "Fix the flag")
        self.assertEqual(self.review(finding("api.py:3", "another defect", self.never)), "FAIL")
        self.assertEqual(self.records("finding"), [("api.py", 3, "")])      # the flag's proof passes now
        # ... and a new finding at the old number, on a line the fix never touched, is a note
        self.setUp()
        self.assertEqual(self.review(finding("api.py:2", "flag is wrong", self.flag_fixed)), "FAIL")
        self.write('flag = "fixed"\nextra = 1\n', "Drop the mode line, mend the flag")
        self.assertEqual(self.review(finding("api.py:2", "extra is odd", self.never)), "PASS")
        self.assertEqual(self.records("finding"), [])
        self.assertIn(("api.py", 2, f"the fix delta since {self.lp.state['round_summaries'][0]['head_sha'][:12]}; "
                                    "judged in an earlier round"), self.records("note"))

    def test_a_review_of_the_same_commit_again_still_replays_the_earlier_findings(self):
        self.assertEqual(self.review(finding("api.py:1", "mode is wrong", self.mode_fixed)), "FAIL")
        self.assertEqual(self.review(), "FAIL")           # nothing fixed, nothing handed in: it blocks
        prompt = self.prompt()
        self.assertNotIn("## Fix delta", prompt)
        self.assertIn("## Earlier findings, re-proven by ak on this commit\n- api.py:1 - mode is wrong - still fails", prompt)
        self.assertIn("the commit the last review judged, again", prompt)
        self.assertEqual(self.records("finding"), [("api.py", 1, "still failing; it blocks until its proof passes")])

    def test_a_rewritten_line_is_placed_among_what_the_fix_put_there(self):
        self.assertEqual(self.review(finding("api.py:2", "the flag is wrong", self.flag_fixed)), "FAIL")
        # the fix adds a line above and rewrites the flag, still wrongly: it blocks where it is now
        self.write('import os\nmode = "branch"\nflag = "still wrong"\nextra = 1\n', "Rewrite the flag, add an import")
        self.assertEqual(self.review(), "FAIL")
        self.assertEqual(self.records("finding"),
                         [("api.py", 3, "still failing; it blocks until its proof passes; the fix changed its line")])
        # ... and rewritten to base's text, it is base's: judged there, a follow-up
        self.write('import os\nmode = "branch"\nflag = "base"\nextra = 1\n', "Put the flag back as base has it")
        self.assertEqual(self.review(), "PASS")
        self.assertEqual(self.records("follow-up"),
                         [("api.py", 3, "still failing, on base too: a defect from before the task, kept as a follow-up")])

    def test_a_deleted_line_still_failing_blocks(self):
        self.assertEqual(self.review(finding("api.py:2", "the flag is wrong", self.flag_fixed)), "FAIL")
        self.write('mode = "branch"\nextra = 1\n', "Delete the flag")
        self.assertEqual(self.review(), "FAIL")
        # it stands at the removal's anchor, the line before where it was, inside the change
        anchored = [("api.py", 1, "still failing; it blocks until its proof passes; the fix changed its line")]
        self.assertEqual(self.records("finding"), anchored)
        # ... in every round after
        self.write('mode = "branch"\nextra = 1\n# noted\n', "Note something else")
        self.assertEqual(self.review(), "FAIL")
        self.assertEqual(self.records("finding"), [("api.py", 1, "still failing; it blocks until its proof passes")])

    def test_a_deleted_lines_finding_is_disputed_and_upheld_at_its_anchor(self):
        self.assertEqual(self.review(finding("api.py:2", "the flag is wrong", self.flag_fixed)), "FAIL")
        self.write('mode = "branch"\nextra = 1\n', "Delete the flag")
        self.dispute("api.py", 2, "the flag is wrong", probe("True"))
        self.assertEqual(self.review(finding("api.py:1", "the flag is gone, not fixed", self.flag_fixed)), "FAIL")
        self.assertIn("api.py:1 - the flag is wrong", self.records_text())      # listed where it stands
        self.assertEqual(self.records("finding"), [("api.py", 1, "")])
        self.assertEqual(self.lp.state.get("disputes", []), [])
        self.assertIn("api.py:1 - the flag is wrong - disputed by the fixer", self.prompt())

    def test_a_finding_on_a_deleted_file_is_the_fixers_to_dispute_and_the_reviewers_to_uphold(self):
        self.assertEqual(self.review(finding("api.py:2", "the flag is wrong", self.flag_fixed)), "FAIL")
        [handed] = [row for row in self.lp.state["review_records"] if row["kind"] == "finding"]
        (self.wt / "api.py").unlink()
        self.commit("Delete api.py")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        self.lp.validation = run.commit_identity(self.wt)
        # the fixer disputes the finding at the site it was handed, though the file is gone
        row = hand_in.checked(["dispute", "api.py:2", "the file was dead code", "--run", "true"],
                              self.wt, role="fixer", findings=[handed])
        self.assertEqual((row["kind"], row["path"], row["line"]), ("dispute", "api.py", 2))
        with self.assertRaisesRegex(config.Error, "exists inside this checkout"):
            hand_in.checked(["finding", "api.py:2", "x", "y", "--run", "false"], self.wt)    # unlisted: as ever
        self.dispute("api.py", 2, "the flag is wrong", "true")
        # ... and the reviewer upholds it where it stands, the removal's anchor, file or no file
        self.assertEqual(self.review(finding("api.py:1", "the flag went with the file", self.flag_fixed)), "FAIL")
        self.assertEqual(self.records("finding"), [("api.py", 1, "")])
        self.assertEqual(self.lp.state.get("disputes", []), [])
        self.assertIn("api.py:1 - the flag is wrong - disputed by the fixer", self.prompt())

    def test_a_dispute_silences_only_the_finding_it_names(self):
        self.assertEqual(self.review(finding("api.py:2", "flag is wrong", self.flag_fixed),
                                     finding("api.py:2", "flag is misnamed", self.never)), "FAIL")
        self.write('mode = "fixed"\nflag = "branch"\nextra = 1\n', "Fix the mode only")
        self.dispute("api.py", 2, "flag is wrong", probe("True"))
        self.assertEqual(self.review(), "FAIL")
        self.assertEqual(self.records("finding"), [("api.py", 2, "still failing; it blocks until its proof passes")])
        prompt = self.prompt()
        self.assertIn("api.py:2 - flag is misnamed - still fails", prompt)
        self.assertIn("api.py:2 - flag is wrong - disputed by the fixer", prompt)

    def test_a_dispute_nobody_upheld_is_dropped_though_ak_blocks_at_its_site(self):
        self.assertEqual(self.review(finding("api.py:2", "flag is wrong", self.flag_fixed),
                                     finding("api.py:2", "flag is misnamed", self.never)), "FAIL")
        self.write('mode = "fixed"\nflag = "branch"\nextra = 1\n', "Fix the mode only")
        self.dispute("api.py", 2, "flag is wrong", probe("True"))
        self.assertEqual(self.review(), "FAIL")            # ak's replay of the other finding blocks there
        self.assertEqual(self.records("finding"), [("api.py", 2, "still failing; it blocks until its proof passes")])
        [dropped] = self.lp.state["disputes"]
        self.assertTrue(dropped.startswith("Dropped: api.py:2 - flag is wrong"), dropped)

    def test_a_round_after_a_fail_on_the_checks_alone_judges_the_whole_change(self):
        self.assertEqual(self.review(ok=False), "FAIL")           # the checks were red, nothing found
        self.write('mode = "branch"\nflag = "branch"\nextra = 2\n', "Mend the check")
        self.assertEqual(self.review(finding("api.py:1", "mode is wrong", self.mode_fixed)), "FAIL")
        self.assertEqual(self.records("finding"), [("api.py", 1, "")])
        prompt = self.prompt()
        self.assertNotIn("## Fix delta", prompt)
        self.assertEqual(prompt.count("## Diff ("), 1)

    def test_placing_a_finding_on_a_long_rewrite_costs_no_process_per_line(self):
        self.assertEqual(self.review(finding("api.py:2", "the flag is wrong", self.flag_fixed)), "FAIL")
        self.write('mode = "branch"\nflag = "still wrong"\n' + "".join(f"pad_{n} = {n}\n" for n in range(3000)),
                   "Rewrite the file")
        real, diffs = run.git, []

        def counting(repo, *args, **kwargs):
            if args and args[0] == "diff":
                diffs.append(args)
            return real(repo, *args, **kwargs)

        with patch.object(run, "git", side_effect=counting):
            self.assertEqual(self.review(), "FAIL")
        self.assertLess(len(diffs), 40)
        self.assertEqual(self.records("finding"),
                         [("api.py", 2, "still failing; it blocks until its proof passes; the fix changed its line")])

    def test_a_replayed_proof_failing_on_base_too_is_a_follow_up_once_its_line_is_base_s(self):
        self.assertEqual(self.review(finding("api.py:2", "the flag is wrong", self.never)), "FAIL")
        self.write('mode = "branch"\nflag = "base"\nextra = 1\n', "Put the flag back as base has it")
        # the reviewer handing it in again there, with its very proof, is weighed the same: one
        # follow-up, ak's replay of that proof adding no second copy beside it
        self.assertEqual(self.review(finding("api.py:2", "the flag is wrong", self.never)), "PASS")
        self.assertEqual(self.records("finding"), [])
        self.assertEqual(self.records("follow-up"), [("api.py", 2, "")])
        self.assertEqual(len(self.lp.state["followups"]), 1)

    def test_a_proof_handed_in_away_from_its_site_leaves_aks_own_replay_blocking(self):
        self.assertEqual(self.review(finding("api.py:2", "the flag is wrong", self.never)), "FAIL")
        self.write('flag = "branch"\nmode = "branch"\nextra = 1\n', "Move the flag up, still wrong")
        # the reviewer hands the proof in at a line the fix did not touch, outside the fix
        # delta: a note in its own right, beside which ak's own replay of the proof still blocks
        self.assertEqual(self.review(finding("api.py:3", "the flag is wrong", self.never)), "FAIL")
        self.assertEqual(self.records("finding"),       # ak's replay, where the fix moved the line
                         [("api.py", 1, "still failing; it blocks until its proof passes")])
        self.assertEqual(len(self.records("note")), 1)

    def test_the_prompts_no_longer_ask_for_anything_new_or_every_instance(self):
        for role, text in worker.PREAMBLES.items():
            with self.subTest(role=role):
                self.assertNotIn("anything new", text)
                self.assertNotIn("every instance", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
