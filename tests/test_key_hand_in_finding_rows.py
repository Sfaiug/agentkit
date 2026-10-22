"""A review turn's `ak hand-in finding` keeps only a finding ak can check, and records its proof.

A reviewer's finding blocks the work and sends it back to be fixed, so ak takes one only at a
file and line that exist inside the checkout under review, with a quote found in that file or a
command that fails there.  It records the site relative to the checkout, what is wrong, why it
matters, and the quote, or the command with its exit status and its output, stdout and stderr
together, cut to its head and tail when long.  The command runs in the checkout and cannot hand
in for itself.  Anything else is refused with exit 2, saying what to fix, and nothing is
recorded; a turn closed by `done` takes no more.  In a run, a review whose every finding was
refused passes.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, the run on a project from gitrig.py with scripted harnesses from
fakeadapter.py.
"""

from itertools import count
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

PARSER = 'def parse(s):\n    return s.split(",")\n'
QUOTE = ("--quote", 'return s.split(",")')
WHAT, WHY = "empty input gives ['']", "callers expect []"
CUT = "\n[output truncated; rerun the command for full evidence]\n"
WHERE = "name a file that exists inside this checkout"
EVIDENCE = "supply evidence with exactly one of --run COMMAND or --quote LINES"
REFUSED = {
    "no such file": (["nope.py:1", WHAT, WHY, *QUOTE], WHERE),
    "a file outside the checkout": (["../outside.py:2", WHAT, WHY, *QUOTE], WHERE),
    "a link out of the checkout": (["link.py:2", WHAT, WHY, *QUOTE], WHERE),
    "a directory": (["lib:1", WHAT, WHY, *QUOTE], WHERE),
    "line 0": (["parser.py:0", WHAT, WHY, *QUOTE], "choose a line from 1 to 2 in parser.py"),
    "past the last line": (["parser.py:3", WHAT, WHY, *QUOTE],
                           "choose a line from 1 to 2 in parser.py"),
    "no line": (["parser.py", WHAT, WHY, *QUOTE],
                "name the location as path:line with a numeric line"),
    "a line that is no number": (["parser.py:two", WHAT, WHY, *QUOTE],
                                 "name the location as path:line with a numeric line"),
    "a quote not in the file": (["parser.py:2", WHAT, WHY, "--quote", "return None"],
                                "use a quote found verbatim in the named file"),
    "a blank quote": (["parser.py:2", WHAT, WHY, "--quote", "  "], EVIDENCE),
    "no evidence": (["parser.py:2", WHAT, WHY], EVIDENCE),
    "two kinds of evidence": (["parser.py:2", WHAT, WHY, *QUOTE, "--run", "false"], EVIDENCE),
    "a command that passes": (["parser.py:2", WHAT, WHY, "--run", "true"],
                              "the command exited 0; write it to fail while the defect exists, "
                              "or use --quote"),
    "a blank what": (["parser.py:2", " ", WHY, *QUOTE],
                     "supply both what is wrong and why it matters"),
    "no why": (["parser.py:2", WHAT],
               "use finding or follow-up with path:line, what, why it matters and evidence, "
               "dispute, or done alone"),
    "an unknown flag": (["parser.py:2", WHAT, WHY, "--proof", "false"],
                        "use one evidence flag, --run COMMAND or --quote LINES, and --before "
                        "PROOF for a follow-up that predates the task"),
    "--before on a finding": (["parser.py:2", WHAT, WHY, "--run", "false", "--before", "HEAD"],
                              "use follow-up for a defect that existed before the task"),
}
CLOSED = "this turn is already closed; hand in records before done, blocked or not-needed"


class FindingRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.ws = cls.home.path / "ws"
        cls.home.write("ws/parser.py", PARSER)
        cls.home.write("outside.py", PARSER)
        (cls.ws / "lib").mkdir()
        (cls.ws / "link.py").symlink_to(cls.home.path / "outside.py")
        cls.turns = count(1)

    def turn(self):
        """A fresh reviewer turn's record file, as the loop opens one."""
        return self.home.write(f"turns/{next(self.turns)}.jsonl", json.dumps(
            {"kind": "turn", "workspace": str(self.ws), "role": "reviewer",
             "findings": []}) + "\n")

    def hand_in(self, turn, *argv, cwd=None):
        return self.home.ak("hand-in", *argv, env={"AK_HAND_IN": str(turn)}, cwd=cwd or self.ws)

    def recorded(self, *argv, cwd=None):
        """The one row a hand-in that ak takes adds to a fresh turn."""
        turn = self.turn()
        done = self.hand_in(turn, "finding", *argv, cwd=cwd)
        self.assertEqual((done.code, done.out, done.err), (0, "", ""))
        rows = [json.loads(line) for line in turn.read_text().splitlines()]
        self.assertEqual(len(rows), 2, rows)
        return rows[1]

    def test_a_quoted_finding_is_recorded_at_its_site_in_the_checkout(self):
        for site in ("parser.py:2", "./parser.py:2", f"{self.ws}/parser.py:2"):
            with self.subTest(site):
                self.assertEqual(self.recorded(site, WHAT, WHY, *QUOTE), {
                    "kind": "finding", "path": "parser.py", "line": 2, "what": WHAT,
                    "why": WHY, "evidence": {"quote": 'return s.split(",")'}})

    def test_a_finding_proven_by_a_command_records_its_exit_status_and_output(self):
        self.assertEqual(self.recorded("parser.py:2", "x", "y", "--run", "echo bad; exit 3"), {
            "kind": "finding", "path": "parser.py", "line": 2, "what": "x", "why": "y",
            "evidence": {"run": "echo bad; exit 3", "returncode": 3, "output": "bad\n"}})

    def test_the_command_runs_in_the_checkout_without_the_turns_record_file(self):
        command = 'pwd; echo "${AK_HAND_IN:-unset}"; echo err >&2; exit 1'
        # handed in from HOME: the site and the command are the checkout's all the same
        row = self.recorded("parser.py:2", WHAT, WHY, "--run", command, cwd=self.home.path)
        self.assertEqual(row["evidence"], {"run": command, "returncode": 1,
                                           "output": f"{self.ws}\nunset\nerr\n"})

    def test_a_long_output_keeps_its_first_and_last_4_kib(self):
        command = "printf 'a%.0s' $(seq 6000); printf 'b%.0s' $(seq 6000); exit 1"
        row = self.recorded("parser.py:2", WHAT, WHY, "--run", command)
        self.assertEqual(row["evidence"]["output"], "a" * 4096 + CUT + "b" * 4096)

    def test_a_finding_ak_cannot_check_is_refused_and_nothing_is_recorded(self):
        cases = {**{case: ("finding", *argv, said) for case, (argv, said) in REFUSED.items()},
                 "a dispute": ("dispute", "parser.py:2", "no", "--run", "true",
                               "dispute is only for fixer turns")}
        for case, (*argv, said) in cases.items():
            with self.subTest(case):
                turn = self.turn()
                before = turn.read_text()
                done = self.hand_in(turn, *argv)
                self.assertEqual((done.code, done.out, done.err),
                                 (2, "", f"ak hand-in: {said}\n"))
                self.assertEqual(turn.read_text(), before)

    def test_a_turn_closed_by_done_takes_no_more_findings(self):
        turn = self.turn()
        self.assertEqual(self.hand_in(turn, "done").code, 0)
        closed = turn.read_text()
        done = self.hand_in(turn, "finding", "parser.py:2", WHAT, WHY, *QUOTE)
        self.assertEqual((done.code, done.err), (2, f"ak hand-in: {CLOSED}\n"))
        self.assertEqual(turn.read_text(), closed)
        self.assertEqual(json.loads(closed.splitlines()[-1]), {"kind": "done"})


# Each of these is refused in the reviewer's checkout, where retry.txt holds one line.
BAD = [["finding", "retry.txt:1", "a", "b", "--run", "true"],
       ["finding", "nope.txt:1", "a", "b", "--run", "false"],
       ["finding", "retry.txt:9", "a", "b", "--run", "false"],
       ["finding", "retry.txt:1", "a", "b"],
       ["finding", "retry.txt:1", "a", "b", "--quote", "goodbye"],
       ["dispute", "retry.txt:1", "no", "--run", "true"]]


class InARun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex={
            "final": "Handed in.", "hand_in": [*BAD, ["done"], ["done"]]})
        task = taskfile.write(cls.home, rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)

    def test_a_review_whose_every_finding_was_refused_passes(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        review, = self.fakes["codex"].runs()
        self.assertEqual(review["role"], "reviewer")
        self.assertEqual([call["code"] for call in review["hand_ins"]], [2] * len(BAD) + [0, 2])
        state = json.loads((self.run_dir / "run.json").read_text())
        self.assertEqual((state["state"], state["verdict"]), ("pass", "PASS"))
        self.assertEqual([summary["verdict"] for summary in state["round_summaries"]], ["PASS"])
        reviewer = self.run_dir / "round-1/reviewer"
        self.assertEqual(json.loads((reviewer / "findings.json").read_text()), [])
        rows = [json.loads(line) for line in
                (reviewer / "hand-in.jsonl").read_text().splitlines()]
        self.assertEqual([row["kind"] for row in rows], ["turn", "done"])


if __name__ == "__main__":
    unittest.main()
