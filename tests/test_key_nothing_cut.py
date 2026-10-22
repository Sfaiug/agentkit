"""Nothing ak hands a model is cut: a failing check's output reaches its fixer, and the host's
rules reach a seat whole.

A fixer can only fix what it can read, so when the done-when commands fail, its prompt carries
each failing command with what it printed under `## The done-when commands failed. Fix the root
cause.`: output that fits whole, and output too long for a prompt as its end beneath a line
naming a file in the run's directory that holds every byte of it.  The host's own
`~/.agentkit/rules.md` is the owner's word for every seat, so a seat's rulebook is ak's rules
followed by all of it, however long (owner rules: "Nothing ak hands a model is cut").
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py with scripted harnesses from fakeadapter.py, and a seat on the adapter
fixture tests/fixtures/adapters/echo.sh; this test fails against `/bin/false`.
"""

import re
import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, REPO, Home
from fixtures.gitrig import Rig

HEADING = "## The done-when commands failed. Fix the root cause.\n```\n"
SHORT = "seq -f 'café short %g' 1 40; test -f fixed.txt"
LONG = "seq -f 'café long %g' 1 30000; test -f fixed.txt"     # about 500 KB
PRINTED = {SHORT: "".join(f"café short {n}\n" for n in range(1, 41)),
           LONG: "".join(f"café long {n}\n" for n in range(1, 30001))}
FIX = {"write": {"fixed.txt": "ok\n"}, "commit": "fix the checks",
       "final": "## Summary\nfixed", "hand_in": [["done"]]}
ORCHESTRATOR = (REPO / "orchestrator.md").read_text()
# Far past any size a prompt or file was ever cut at, multi-byte text in it.
HOST_RULES = ("# Acme host rules\n\n" + "".join(f"Rule {n}: the café widget {n} keeps its name.\n"
                                                for n in range(2000))
              + "LAST HOST RULE: acme-end\n")
ECHO = {"one": {"harness": "echo", "model": "echo-1", "provider": "test"},
        "two": {"harness": "echo", "model": "echo-2", "provider": "test"}}


class FailedChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude=["work", FIX], codex="pass")
        task = taskfile.write(cls.home, rig.path, "Add retry file", done_when=(SHORT, LONG),
                              front={"rounds": 1})
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)

    def block(self):
        """The fixer's failed-checks block, as the prompt its harness was handed holds it."""
        turns = self.fakes["claude"].runs()
        self.assertEqual(len(turns), 2, self.done.out + self.done.err)
        prompt = Path(turns[1]["argv"][3]).read_text()
        self.assertEqual(prompt.count(HEADING), 1, prompt[-2000:])
        block = prompt.split(HEADING, 1)[1]
        self.assertIn("\n```", block)
        return block[:block.rindex("```")]

    def test_the_fixer_runs_and_its_fix_passes(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual([turn["role"] for turn in self.fakes["claude"].runs()],
                         ["executor", "fixer"])

    def test_output_that_fits_reaches_the_fixer_whole_under_its_command(self):
        self.assertIn(f"$ {SHORT}\n[exit 1]\n{PRINTED[SHORT]}", self.block())

    def test_longer_output_is_its_end_under_a_line_naming_a_file_holding_all_of_it(self):
        record = f"$ {LONG}\n[exit 1]\n"
        self.assertIn(record, self.block())
        named, shown = self.block().split(record, 1)[1].split("\n", 1)
        kept = Path(re.search(r"/[^\s\]]+", named)[0])
        self.assertTrue(kept.is_relative_to(self.run_dir), named)
        self.assertEqual(kept.read_bytes(), PRINTED[LONG].encode())
        # the end is what the command finally said about itself
        self.assertTrue(PRINTED[LONG].endswith(shown), shown[-200:])
        self.assertGreater(shown.count("\n"), 100)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class HostRules(unittest.TestCase):
    def test_a_seat_s_rulebook_is_ak_s_rules_then_the_host_s_whole(self):
        with Home() as home:
            adapters = home.root / "adapters"
            shutil.copytree(REPO / "tests/fixtures/adapters", adapters)
            akconfig.write(home, ECHO)
            home.write(".agentkit/rules.md", HOST_RULES)
            cwd = home.path / "code" / "acme"
            cwd.mkdir(parents=True)
            done = home.ak("orch", "acme", "--model", "one", "--workers", "two", tty=True,
                           cwd=cwd, env={"AGENTKIT_ADAPTER_DIR": str(adapters)})
            self.assertEqual(done.code, 0, done.err)
            book = (home.path / ".agentkit/state/rulebook-acme.md").read_text()
            self.assertTrue(book.startswith(ORCHESTRATOR.rstrip()))
            self.assertEqual(book[len(ORCHESTRATOR.rstrip()):].strip(), HOST_RULES.strip())


if __name__ == "__main__":
    unittest.main()
