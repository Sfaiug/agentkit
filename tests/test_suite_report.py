"""A landing suite must run the test files a change adds."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import gate, land, run, suite_report
import every_file
from test_lander import LanderFixture

PYTEST_XUNIT1 = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">
<testcase classname="tests.test_billing" name="test_a" file="tests/test_billing.py" line="3"/>
<testcase classname="tests.test_menu.TestKeys" name="test_b"/>
<testcase classname="tests.test_skipped" name="test_c" file="tests/test_skipped.py"><skipped/></testcase>
<testcase classname="tests.test_red" name="test_d" file="tests/test_red.py"><failure/></testcase>
</testsuite></testsuites>"""


class SuiteReport(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-suite-report-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        for name in ("tests/test_billing.py", "tests/test_menu.py", "tests/test_skipped.py",
                     "tests/test_red.py", "tests/fixtures/test_data.py", "app/main.py",
                     "web/cart.test.js", "pkg/cart_test.go"):
            self.add(name)
        self.report = self.root / "report"
        self.report.mkdir()

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True,
                       env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})

    def add(self, name):
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text("x\n")

    def tree(self):
        self.git("add", "-A")
        return subprocess.run(["git", "-C", str(self.repo), "write-tree"], check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, text, name="piece-1.xml"):
        (self.report / name).write_text(text)

    def case_xml(self, *files):
        cases = "".join(f'<testcase classname="x" name="t" file="{name}"/>' for name in files)
        return f"<testsuite>{cases}</testsuite>"

    def judge(self, base, *ran, xml=None):
        """Check the index's tree on `base` with a report that ran `ran` (or `xml`)."""
        for old in self.report.glob("*.xml"):
            old.unlink()
        if ran or xml:
            self.write(xml or self.case_xml(*ran))
        return suite_report.judge(self.repo, self.report, self.tree(), base)

    def test_test_files_go_by_their_usual_names_and_skip_fixtures(self):
        self.assertEqual(suite_report.test_files(self.repo, self.tree()), {
            "tests/test_billing.py", "tests/test_menu.py", "tests/test_skipped.py",
            "tests/test_red.py", "web/cart.test.js", "pkg/cart_test.go"})

    def test_a_file_ran_when_a_case_ran_unskipped_by_path_or_module(self):
        self.write(PYTEST_XUNIT1)
        files = suite_report.test_files(self.repo, self.tree())
        self.assertEqual(suite_report.ran(self.report, files, self.repo),
                         ({"tests/test_billing.py", "tests/test_menu.py", "tests/test_red.py"}, False,
                          set()))

    def test_no_report_is_none_and_a_broken_one_proves_nothing(self):
        files = suite_report.test_files(self.repo, self.tree())
        self.assertIsNone(suite_report.ran(self.report, files, self.repo))
        self.write("<testsuite><testcase", "half.xml")
        self.write(self.case_xml(str(self.repo / "tests/test_menu.py")), "absolute.xml")
        self.assertEqual(suite_report.ran(self.report, files, self.repo),
                         ({"tests/test_menu.py"}, False, set()))

    def test_a_runner_started_in_a_subfolder_still_names_its_files(self):
        self.write('<testsuite><testcase classname="test_menu" name="a" file="test_menu.py"/>'
                   '<testcase classname="test_billing" name="b"/></testsuite>')
        files = suite_report.test_files(self.repo, self.tree())
        self.assertEqual(suite_report.ran(self.report, files, self.repo),
                         ({"tests/test_menu.py", "tests/test_billing.py"}, False, set()))
        # a tail two tracked files share credits neither, and leaves both unjudged
        base = self.tree()
        self.add("app/tests/test_menu.py")
        files = suite_report.test_files(self.repo, self.tree())
        self.assertEqual(suite_report.ran(self.report, files, self.repo),
                         ({"tests/test_billing.py"}, False,
                          {"tests/test_menu.py", "app/tests/test_menu.py"}))
        self.assertEqual(suite_report.judge(self.repo, self.report, self.tree(), base), "")

    def test_a_test_file_a_change_adds_must_run(self):
        base = self.tree()
        self.add("tests/test_new.py")
        said = self.judge(base, "tests/test_billing.py")
        self.assertEqual(said, "Test files the suite never ran: tests/test_new.py: add them "
                               "to the `tests:` suite, or delete them.")
        self.assertEqual(self.judge(base, "tests/test_billing.py", "tests/test_new.py"), "")
        # every one is named, never cut short
        for index in range(25):
            self.add(f"tests/test_many_{index:02}.py")
        said = self.judge(base, "tests/test_billing.py", "tests/test_new.py")
        self.assertTrue(all(f"tests/test_many_{index:02}.py" in said for index in range(25)), said)

    def test_test_files_the_base_has_are_never_this_change_s(self):
        # whatever the tree it lands on left unrun, or a merge outside the line added
        self.add("tests/test_outside.py")
        base = self.tree()
        self.add("app/feature.py")
        self.assertEqual(self.judge(base, "tests/test_billing.py"), "")
        self.assertEqual(self.judge(base, xml="<testsuite/>"), "")

    def test_a_suite_that_writes_no_report_is_not_judged(self):
        base = self.tree()
        self.add("tests/test_new.py")
        self.assertEqual(self.judge(base), "")

    def test_a_kind_the_report_cannot_name_is_not_judged(self):
        base = self.tree()
        # node's own junit reporter: cases sit under <testsuites> and name no file
        node = '<testcase name="adds" classname="test"/>'
        python = self.case_xml("tests/test_billing.py")
        xml = f"<testsuites>{node}{python[len('<testsuite>'):-len('</testsuite>')]}</testsuites>"
        self.add("web/new.test.js")
        self.assertEqual(self.judge(base, xml=xml), "")
        # what it can name stays judged
        self.add("tests/test_new.py")
        said = self.judge(base, xml=xml)
        self.assertIn("tests/test_new.py", said)
        self.assertNotIn(".js", said)

    def test_every_suite_gets_a_report_directory_it_may_write(self):
        env = {"AK_MAX_RUNS": "0", "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
               "AK_RUN_DEPTH": "0", "AK_TEST_REPORT": "/nowhere"}
        writes = 'test -d "$AK_TEST_REPORT" && echo "<testsuite/>" > "$AK_TEST_REPORT/a.xml"'
        with patch.dict(os.environ, env):
            log = self.root / "dw.log"
            ok, text = gate.run_done_when([writes], self.repo, log, set())
            self.assertTrue(ok, text)
            # a suite run on its own, as a red target's probe runs one
            with log.open("wb") as output:
                code, _, killed = gate.run_suite(writes, 60, cwd=self.repo, activity=log,
                                                 output=output)
            self.assertEqual((code, killed), (0, False))
            with gate.test_report() as report:
                ok, text = gate.run_done_when([writes], self.repo, log, set())
                self.assertTrue(ok, text)
                self.assertTrue((Path(report) / "a.xml").is_file())
            self.assertFalse(Path(report).exists())
            self.assertNotIn(suite_report.ENV, gate.suite_env())

    def test_agentkit_s_own_suite_reports_its_files_and_smoke_s(self):
        every_file.write_report(self.report, 2, 3, {Path("tests/test_menu.py"), Path("tests/test_red.py"),
                                                    Path("tests/test_skipped.py")},
                                {Path("tests/test_red.py")}, {Path("tests/test_skipped.py")},
                                {Path("tests/test_billing.py")})
        files = suite_report.test_files(self.repo, self.tree())
        self.assertEqual(suite_report.ran(self.report, files, self.repo),
                         ({"tests/test_menu.py", "tests/test_red.py", "tests/test_billing.py"}, False,
                          set()))
        self.assertEqual(every_file.cases_skipped("Ran 2 tests in 0.1s\n\nOK (skipped=2)\n"), 2)
        self.assertIn("<failure", (self.report / "every-file-2-of-3.xml").read_text())


class CoverageInTheLine(LanderFixture, unittest.TestCase):
    """The lander sends back the change that adds a test file its suite does not run."""

    def suite(self, ran):
        run.git(self.repo, "checkout", "main")
        (self.repo / "AGENTS.md").write_text("---\ntests: python3 report.py\n---\n")
        (self.repo / "report.py").write_text(
            "import os, pathlib\n"
            "ran = pathlib.Path('ran.txt').read_text().split()\n"
            "cases = ''.join(f'<testcase name=\"t\" file=\"{f}\"/>' for f in sorted(ran))\n"
            "pathlib.Path(os.environ['AK_TEST_REPORT'], 'r.xml').write_text("
            "f'<testsuite>{cases}</testsuite>')\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/test_old.py").write_text("x\n")
        (self.repo / "ran.txt").write_text(ran)
        self.commit("acme suite writes its report")
        run.git(self.repo, "push", "origin", "main")
        self.base = run.git(self.repo, "rev-parse", "HEAD")

    def test_a_stack_that_adds_an_unrun_test_file_is_the_one_sent_back(self):
        self.suite("tests/test_old.py\n")
        head = self.member("head", **{"tests/test_new.py": "x\n",
                                      "ran.txt": "tests/test_old.py\ntests/test_new.py\n"})
        later = self.member("later", joined=2, **{"tests/test_other.py": "x\n"})
        self.advance()
        with patch.object(gate, "derived_heavy_limit", return_value=2):
            land.check_line(self.turn)
        self.assertIn("land", self.wait(head))
        fix = self.wait(later)["fix"]
        self.assertIn("Test files the suite never ran: tests/test_other.py", fix["line"])
        self.assertIn("tests/test_other.py", Path(fix["log"]).read_text())

    def test_a_landing_check_fails_a_clean_pass_that_left_an_added_file_unrun(self):
        self.suite("tests/test_old.py\n")
        base = run.git(self.repo, "rev-parse", "HEAD^{tree}")
        state = {"repo": str(self.repo), "waiting_on": {"joined": 1.0, "line": "main"}}
        scratch = self.root / "scratch"

        def check(log):
            # the lander checks a pinned scratch checkout of the tree, never the repository
            head = run.git(self.repo, "rev-parse", "HEAD")
            if scratch.exists():
                run.git(scratch, "checkout", "-q", "--detach", head)
            else:
                run.git(self.repo, "worktree", "add", "-q", "--detach", str(scratch), head)
            return land._check(self.root, state, scratch, ["python3 report.py"], self.root / log,
                               lambda _: None,
                               coverage=(run.git(scratch, "rev-parse", "HEAD^{tree}"), base))
        (self.repo / "tests/test_new.py").write_text("x\n")
        self.commit("adds a test file the suite does not run")
        ok, text = check("l1.log")
        self.assertFalse(ok)
        self.assertIn("Test files the suite never ran: tests/test_new.py", text)
        self.assertTrue(run.LOOP_NOTE.match(text.splitlines()[-1]))
        (self.repo / "ran.txt").write_text("tests/test_old.py\ntests/test_new.py\n")
        self.commit("runs it")
        ok, text = check("l2.log")
        self.assertTrue(ok, text)

    def test_a_change_to_its_own_tests_line_is_not_judged_by_the_target_s(self):
        self.suite("tests/test_old.py\n")
        # it adds a test file and a line that runs it: the target's line cannot know it
        mine = self.member("mine", **{"tests/test_new.py": "x\n", "AGENTS.md":
                                      "---\ntests: python3 report.py && echo also new\n---\n"})
        self.advance()
        with patch.object(gate, "derived_heavy_limit", return_value=2):
            land.check_line(self.turn)
        self.assertIn("land", self.wait(mine))

    def test_a_change_that_narrows_the_suite_never_holds_up_the_ones_after_it(self):
        self.suite("tests/test_old.py\n")
        narrows = self.member("narrows", **{"ran.txt": ""})
        after = self.member("after", joined=2, **{"notes.txt": "x\n"})
        self.advance()
        with patch.object(gate, "derived_heavy_limit", return_value=2):
            land.check_line(self.turn)
        self.assertIn("land", self.wait(narrows))
        self.assertIn("land", self.wait(after))


if __name__ == "__main__":
    unittest.main()
