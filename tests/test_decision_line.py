"""An ending that needs its seat's decision reaches it as one line under 400 characters, and its
result opens with that line.  30 Oct 2026: the median FAIL line was 985 characters; Claude folded
it into `[Pasted text #N]`, and a seat spent about 18K tokens before it knew what failed.

Offline: a temporary HOME (`Sandbox`) and its adapters' folds.
"""

import re
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, gitcall, handback, record, run, watch

LINE = re.compile(r"run (\S+) ([A-Z ]+) \((\d) of 3\): (.+[.!?]) Next: ([^.]+)\. Result: (\S+)")
FINDING = "- parse.py:12 - " + "The parser drops the last row of every acme table. " * 40   # past 2,000
ENDINGS = (     # name, rounds spent, record, word, how its why starts and ends, next step
    ("acme-fail", 3, {"state": "fail", "verdict": "FAIL", "findings": (
        f"VERDICT: FAIL\n\n## Findings\n{FINDING}\n- b.py:2 - two - why\n")},
     "FAIL", "parse.py:12 - The parser", "acme table.", "split the task"),
    ("acme-blocked", 1, {"state": "blocked", "verdict": "BLOCKED", "error": (
        "The change adds 912 lines. " + "A first review takes 300; split it. " * 50)},
     "BLOCKED", "The change", "split it.", "rewrite the task and relaunch it with `from: ak/acme-blocked`"),
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
            self.assertTrue((directory / "result.md").read_text().startswith(
                f"## Seat notice\n\n{line}\n\n# "))
            for harness, _ in config.manifests():
                self.assertLessEqual(len(line), watch.screen(harness)["folds_over"] or len(line))
            with patch.object(watch, "longest", return_value=240):  # a harness folding sooner
                short = handback.handback_line(state, directory, self.cfg)
            self.assertLessEqual(len(short), 240, short)
            self.assertEqual(LINE.fullmatch(short).groups()[4:], found[4:], short)

    def test_a_break_after_its_merge_says_what_broke_and_its_result_keeps_the_rest(self):
        directory, _ = self.ending("acme-live", merged=True, pr="https://github.com/acme/widget/pull/7")
        told = watch.after_merge_line("health: probe", "main", "acme/pull/7; " + "deployment gone " * 100)
        line = handback.not_live_line(told, directory)
        self.assertEqual(line, "run acme-live NOT LIVE (3 of 3): health: probe failed on main after this merge. "
                               f"Next: {handback.RESULT_NAMES}. Result: {config.tilde(directory / 'result.md')}")
        text = (directory / "result.md").read_text()
        self.assertTrue(text.startswith(f"## Seat notice\n\n{line}\n\n# PASS"), text[:300])
        self.assertIn(told, text)

    def test_what_the_line_cannot_hold_is_whole_in_its_result(self):
        cause = "a process stopped during a remote write " * 30 + "and nothing ended it"
        directory, state = self.ending("acme-stop", state="interrupted", verdict=None,
                                       recovery_pending=True, interruption_reason=cause)
        self.assertIn("The reason is longer", handback.handback_line(state, directory, self.cfg))
        self.assertIn(cause, (directory / "result.md").read_text())
        directory, _ = self.ending("acme-many", state="fail", verdict="FAIL", findings=f"{FINDING}\n", findings_file="/acme/final.md",
                                   final_check={"outcome": "failed", "sha": "a" * 40, "line": "acme-check " * 80})
        self.assertIn("Every one in full: /acme/final.md", (directory / "result.md").read_text())
        self.assertIn("acme-check " * 79, (directory / "result.md").read_text())

    def test_an_ending_nothing_decides_about_opens_no_block(self):
        for name, extra, heading in (("acme-merged", {"merged": True, "pr": "https://github.com/a/b/pull/1"}, "# PASS"),
                                     ("acme-stopped", {"state": "stopped"}, "# FAIL")):
            directory, state = self.ending(name, **extra)
            self.assertIsNone(handback.decision_line(state, directory, self.cfg))
            self.assertTrue((directory / "result.md").read_text().startswith(heading))


if __name__ == "__main__":
    unittest.main()
