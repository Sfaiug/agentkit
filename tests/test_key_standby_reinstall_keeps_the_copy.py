"""A reinstall as a client keeps a standby's copy of its home's runs, checkouts and work as it
was, whatever state its runs are in, and its summary names nothing left to do about it: install.sh
run with the home's name, or with none, as a move runs it.  A standby is what `ak standby HOME`
makes of HOME's client, though its first pass fails here, where no home answers.  A client that
is no standby loses those folders, or, with a run not at rest among them, keeps them and says so.
Black-box: install.sh of the checkout `AK_BIN` names runs from outside in a Home of
tests/fixtures/akbin.py, the host's tools the refusing fakes of tests/fixtures/installer.py.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import Home

HOME = "acme-mini"
LOOP = ("runs", "wt", "work")
AT_REST = {".agentkit/runs/20261116-0900-fix-api/run.json":
           {"run_id": "fix-api", "state": "pass", "finished_at": 1789000000},
           ".agentkit/wt/20261116-0900-fix-api/main.py": "print('acme')\n",
           ".agentkit/work/acme/notes.md": "the home's work\n"}
OPEN = {".agentkit/runs/20261116-0910-add-docs/run.json":
        {"run_id": "add-docs", "state": "running"},
        ".agentkit/runs/20261116-0910-add-docs/round-1/events.jsonl": "{}\n"}


class AReinstall(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        installer.prepare(self.home)
        self.summary("--client", HOME)

    def summary(self, *args):
        """What install.sh run with `args` says from its summary on."""
        done = installer.run(self.home, *args)
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out[done.out.index("summary: "):]

    def holding(self, files):
        for name, data in files.items():
            self.home.write(name, data)
        return self.loop()

    def loop(self):
        """Each folder and file under ak's runs, checkouts and work, with each file's text."""
        ak = self.home.path / ".agentkit"
        return {str(path.relative_to(ak)): path.read_text() if path.is_file() else None
                for top in LOOP if (ak / top).exists()
                for path in [ak / top, *(ak / top).rglob("*")]}

    def kept_by_a_standby(self, files):
        self.home.ak("standby", HOME)
        copy = self.holding(files)
        for args in (("--client", HOME), ()):
            with self.subTest(args=args):
                self.assertRegex(self.summary(*args),
                                 rf"^summary: client of {HOME}; nothing left to do")
                self.assertEqual(self.loop(), copy)

    def test_a_standby_keeps_a_copy_holding_a_run_not_at_rest(self):
        self.kept_by_a_standby({**AT_REST, **OPEN})

    def test_a_standby_keeps_a_copy_holding_only_runs_at_rest(self):
        self.kept_by_a_standby(AT_REST)

    def test_a_client_that_is_no_standby_loses_them_with_only_runs_at_rest(self):
        self.holding(AT_REST)
        self.summary("--client", HOME)
        self.assertEqual(self.loop(), {})

    def test_a_client_that_is_no_standby_keeps_them_with_a_run_not_at_rest_and_says_so(self):
        kept = self.holding({**AT_REST, **OPEN})
        self.assertRegex(self.summary("--client", HOME), r"could not do:\n.*\bkept\b.*\bruns\b")
        self.assertEqual(self.loop(), kept)


if __name__ == "__main__":
    unittest.main()
