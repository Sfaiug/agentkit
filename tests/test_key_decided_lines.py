"""AK_BIN carries settled task decisions to the reviewer and accepted limits to the PR."""

import json
from pathlib import Path
import unittest

from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


ACCEPTED = "Accepted: the export skips archived rows"
NOT_WANTED = "Not wanted: add an archive browser"
DECISIONS = (NOT_WANTED, ACCEPTED, "Accepted: the export uses UTC")
MARKER = "## Decided before the build"


class DecidedLines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home)
        cls.gh = GitHub(cls.home)
        cls.gh.grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, decided=DECISIONS,
                              constraints=("Keep the export small.",))
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)

    def test_the_task_runs_and_the_pr_lists_only_accepted_lines_as_risk(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        body = self.gh.prs()[0]["body"]
        self.assertEqual(body, (self.run_dir / "pr-body.md").read_text())
        self.assertIn("## Risk\n\n- " + "\n- ".join(DECISIONS[1:]), body)
        self.assertNotIn(NOT_WANTED, body)

    def test_reviewer_gets_the_decisions_as_settled_with_proven_defects_still_findings(self):
        prompt = Path(self.fakes["codex"].runs()[0]["argv"][3]).read_text()
        self.assertIn(MARKER, prompt)
        decided = prompt.split(MARKER, 1)[1]
        for line in DECISIONS:
            self.assertIn(line, decided)
        for rule in ("no finding against an Accepted line",
                     "no missing-work finding for a Not wanted line",
                     "a defect a command shows stays a finding"):
            self.assertIn(rule, decided)


class LaunchDecisions(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus", "astra"])
        self.fakes = fakeadapter.install(self.home, claude="work", codex="pass")

    def test_invalid_lines_and_duplicate_headings_are_refused_before_launch(self):
        cases = (("Wanted: a browser",), ("- Accepted: a limit",),
                 ("Some free prose.",), (ACCEPTED, "## Decided", NOT_WANTED))
        for decisions in cases:
            task = taskfile.write(self.home, "none", decided=decisions)
            for mode in ((), ("--bg",)):
                with self.subTest(decisions=decisions, mode=mode):
                    done = self.home.ak("run", str(task), *mode)
                    self.assertEqual(done.code, 2, done.out + done.err)
                    self.assertEqual(len(done.err.splitlines()), 1, done.err)
                    self.assertIn("## Decided", done.err)
                    if "## Decided" in decisions:
                        self.assertIn("only once", done.err)
                    else:
                        self.assertIn("Not wanted:", done.err)
                        self.assertIn("Accepted:", done.err)
                    self.assertEqual(taskfile.runs(self.home), [])
                    self.assertEqual([fake.n for fake in self.fakes.values()], [0, 0])

    def test_fenced_examples_and_other_headings_remain_free_prose(self):
        goal = ("An example, not decisions:\n```markdown\n## Decided\nexample prose\n```\n"
                "~~~markdown\n## Decided\nanother example\n~~~\n"
                "## Anything else\nFree prose.\n## Anything else\nMore prose.")
        task = taskfile.write(self.home, "none", goal=goal, decided=("", ACCEPTED, ""))
        done = self.home.ak("run", str(task), timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)

    def test_repository_decided_headings_are_not_task_decisions(self):
        prose = "Use Python for scripts.\nAccepted: repository rules are prose."
        rig = Rig(self.home, files={"AGENTS.md":
            "---\ntests: true\nhealth: none\n---\n# Project rules\n\n## Decided\n" + prose + "\n"})
        for decisions in ((), (ACCEPTED,)):
            with self.subTest(decisions=decisions):
                task = taskfile.write(self.home, rig.path, f"Task with {len(decisions)} decisions",
                                      decided=decisions)
                done = self.home.ak("run", str(task), "--no-merge", timeout=300)
                self.assertEqual(done.code, 0, done.out + done.err)
                prompt = Path(self.fakes["codex"].runs()[-1]["argv"][3]).read_text()
                self.assertIn(prose, prompt)
                if decisions:
                    settled = prompt.split(MARKER, 1)[1].split("\n## ", 1)[0]
                    self.assertIn(ACCEPTED, settled)
                    self.assertNotIn(prose, settled)
                else:
                    self.assertNotIn(MARKER, prompt)

    def test_accepted_lines_do_not_dismiss_a_failing_finding_proof(self):
        self.fakes["codex"].behave("fail")
        task = taskfile.write(self.home, "none", front={"rounds": 1},
                              decided=("Accepted: retry.txt remains present",))
        done = self.home.ak("run", str(task), timeout=300)
        self.assertEqual(done.code, 1, done.out + done.err)
        state = json.loads((taskfile.only_run(self.home) / "run.json").read_text())
        self.assertEqual(state["verdict"], "FAIL")
        self.assertTrue(any(row["kind"] == "finding" and row["evidence"]["returncode"] != 0
                            for row in state["review_records"]))


if __name__ == "__main__":
    unittest.main()
