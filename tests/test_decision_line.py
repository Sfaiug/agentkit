"""An ending that needs its seat's decision reaches it as one line under 400 characters, its result
holding the rest.  30 Oct 2026: the median FAIL line was 985 characters; Claude folded it into
`[Pasted text #N]`, and a seat spent about 18K tokens before it knew what failed.

Offline: a temporary HOME (`Sandbox`) and its adapters' folds.
"""

import re
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, gitcall, handback, record, run, watch

LINE = re.compile(r"run (\S+) ([A-Z ]+) \((\d) of 3\): (.+[.!?]) Next: ([^.]+)\. Result: (\S+)")
FINDING = "- parse.py:12 - " + "The parser drops the last row of every acme table. " * 40   # past 2,000
CLAIM = {"kind": "finding", "path": "parse.py", "line": 12, "why": "rows go missing", "evidence": {"quote": "rows[:-1]"},
         "what": "The parser silently\ndrops the last row of every acme table. " * 40}     # a claim may hold newlines
LONG = "20261030-1200-acme-task-title-long-enough-for-a-whole-slug"
ENDINGS = (     # name, rounds spent, record, word, how its why starts and ends, next step
    ("acme-fail", 3, {"state": "fail", "verdict": "FAIL", "review_records": [CLAIM, {"kind": "done"}]},
     "FAIL", "parse.py:12 - The parser silently drops", "acme table.", "split the task"),
    (LONG, 1, {"state": "blocked", "verdict": "BLOCKED", "error": (
        "The change adds 912 lines. " + "A first review takes 300; split it. " * 50)},
     "BLOCKED", "The change", "split it.", f"rewrite the task and relaunch it with `from: ak/{LONG}`"),
    ("acme-unmerged", 3, {"state": "pass", "merge_failed": True, "merge_note": (
        "the delivery stopped: " + "the push to origin was refused! " * 40)},
     "NOT MERGED", "the delivery", "refused!", f"{handback.RESULT_NAMES}, `ak run merge acme-unmerged`"),
    ("acme-error", 2, {"state": "error", "verdict": "ERROR", "error": "git cannot write here. " * 30},
     "ERROR", "git cannot", "here.", "read the result"),
    ("acme-window", 1, {"state": "exhausted", "quota_dry": True, "error": "every provider is spent"},
     "FAIL", "every provider", "spent.", "wait for the provider"))


class DecisionLine(Sandbox):
    def ending(self, name, spent=3, **extra):
        directory = self.ended(name, owner="fix-api", rounds=3, repo=str(self.root),
                               branch=f"ak/{name}", base_sha="a" * 40, worktree=str(self.root),
                               round_summaries=[{"round": n + 1, "summary": "acme", "done_when": True,
                                                 "verdict": "FAIL"} for n in range(spent)],
                               **{"findings": "", **extra})
        state = record.read_state(directory)
        state["review"].update(head_sha="b" * 40, tree_sha="c" * 40)    # what a repo's PASS holds
        record.save_state(directory, state)
        with patch.object(gitcall, "git", return_value="(fixture diff)"):
            run.write_result(directory, state, [])
        return directory, state

    def test_each_ending_is_one_line_cut_at_a_sentence_with_its_next_step(self):
        for name, spent, extra, word, starts, ends, move in ENDINGS:
            directory, state = self.ending(name, spent, **extra)
            line = handback.handback_line(state, directory, self.cfg)
            self.assertLess(len(line), 400, line)
            found = LINE.fullmatch(line).groups()
            self.assertEqual(found[:3], (name, word, str(spent)), line)
            self.assertTrue(found[3].startswith(starts) and found[3].endswith(ends), line)
            self.assertEqual(found[4:], (move, config.tilde(directory / "result.md")))
            for harness, _ in config.manifests():
                self.assertLessEqual(len(line), watch.screen(harness)["folds_over"] or len(line))
            with patch.object(watch, "longest", return_value=240):  # a harness folding sooner: details go
                short = handback.handback_line(state, directory, self.cfg)
            self.assertLessEqual(len(short), 240, short)
            self.assertTrue(LINE.fullmatch(short), short)

    def test_a_break_after_its_merge_says_what_broke_and_its_result_keeps_the_rest(self):
        directory, _ = self.ending("acme-live", merged=True, pr="https://github.com/acme/widget/pull/7")
        told = watch.after_merge_line("health: probe", "main", "acme/pull/7; " + "deployment gone " * 100)
        line = handback.not_live_line(told, directory)
        self.assertEqual(line, "run acme-live NOT LIVE (3 of 3): health: probe failed on main after this merge. "
                               f"Next: {handback.RESULT_NAMES}. Result: {config.tilde(directory / 'result.md')}")
        self.assertIn(told, (directory / "result.md").read_text())
        self.assertEqual(handback.not_live_line(told, directory.with_name("acme-gone")), told)   # no result to lead to

    def test_what_the_line_cannot_hold_is_whole_in_its_result(self):
        cause = "a process stopped during a remote write " * 30 + "and nothing ended it"
        directory, state = self.ending("acme-stop", state="interrupted", verdict=None,
                                       recovery_pending=True, interruption_reason=cause)
        (directory / "result.md").write_text("# FAIL\n")     # written before its cause was
        self.assertIn(handback.UNSAID, handback.handback_line(state, directory, self.cfg))
        self.assertIn(cause, (directory / "result.md").read_text())
        directory, _ = self.ending("acme-many", state="fail", verdict="FAIL", findings=f"{FINDING}\n", findings_file="/acme/final.md")
        self.assertIn("Every one in full: /acme/final.md", (directory / "result.md").read_text())

    def test_an_ending_nothing_decides_about_has_no_decision_line(self):
        for name, extra in (("acme-merged", {"merged": True, "pr": "https://github.com/a/b/pull/1"}),
                            ("acme-stopped", {"state": "stopped"})):
            directory, state = self.ending(name, **extra)
            self.assertIsNone(handback.decision_line(state, directory, self.cfg))


if __name__ == "__main__":
    unittest.main()
