"""Done refuses the workspace's scope and rule failures, then takes a fix in the same turn.

Black-box through AK_BIN and fakeadapter, on a base holding an answer key. Neither attempt
commits or stages the executor's work; the loop still commits and checks it after the turn.
"""

import json
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import AK, Home
from fixtures.gitrig import Rig

WORK = """\
import json, os, subprocess
from pathlib import Path
out = Path(os.environ['AK_HAND_IN']).parent
def git(*args):
    return subprocess.check_output(['git', *args], text=True)
before = Path(os.environ['AK_HAND_IN']).read_bytes()
head, index = git('rev-parse', 'HEAD'), git('ls-files', '--stage')
attempts = []
for n in range(2):
    result = subprocess.run([AK, 'hand-in', 'done'], capture_output=True, text=True)
    attempts.append([result.returncode, result.stdout + result.stderr])
    if n == 0:
        unchanged = before == Path(os.environ['AK_HAND_IN']).read_bytes()
        exec(REPAIR)
(out / 'attempts.json').write_text(json.dumps({
    'attempts': attempts, 'unchanged': unchanged,
    'head': head == git('rev-parse', 'HEAD'), 'index': index == git('ls-files', '--stage'),
    'dirty': git('status', '--porcelain')}))
"""


class DoneWaitsForTheRules(unittest.TestCase):
    def run_turn(self, write, repair, refusal, front=None):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={"widget.py": "VALUE = 1\n",
                  "tests/test_key_widget.py": "# the base's answer key\n",
                  "docs/guide.md": "Acme.\n"})
        akconfig.write(home, ["opus", "astra"])
        script = f"AK = {AK!r}\nREPAIR = {repair!r}\n" + WORK
        fakes = fakeadapter.install(home, claude={"write": write,
            "sh": "python3 -c " + shlex.quote(script), "final": "## Summary\nFixed the work."},
            codex="pass")
        task = taskfile.write(home, rig.path, front=front, done_when=("true",))
        done = home.ak("run", str(task), "--no-merge", timeout=300)
        run_dir = taskfile.only_run(home)
        turn = Path(fakes["claude"].runs()[0]["argv"][4])
        evidence = json.loads((turn / "attempts.json").read_text())
        self.assertEqual([item[0] for item in evidence["attempts"]], [2, 0], evidence)
        self.assertIn(refusal, evidence["attempts"][0][1])
        for name in ("unchanged", "head", "index"):
            self.assertTrue(evidence[name], evidence)
        self.assertTrue(evidence["dirty"], evidence)
        rows = [json.loads(line) for line in (turn / "hand-in.jsonl").read_text().splitlines()]
        self.assertEqual(rows[1:], [{"kind": "done"}])
        self.assertEqual(rows[0]["checks"]["base"], rig.head())
        self.assertEqual(rows[0]["checks"]["files"], [front["files"]] if front else [])
        self.assertFalse(rows[0]["checks"]["scratch"])
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual([call["role"] for call in fakes["claude"].runs()], ["executor"])
        state = json.loads((run_dir / "run.json").read_text())
        self.assertEqual(state["state"], "pass")
        self.assertEqual(state["round_summaries"][0]["done_when"], True)

    def test_uncommitted_python_needs_a_key_and_an_untracked_key_closes_the_turn(self):
        self.run_turn({"widget.py": "VALUE = 2\n", "new.py": "VALUE = 3\n"},
            "Path('tests/test_key_turns.py').write_text('# checks the change\\n')",
            "Python changed with no answer key: new.py, widget.py. A change to a .py file "
            "outside tests/ adds, edits or moves in a tests/test_key_*.py in the same change: "
            "a black-box test of what it does.")

    def test_a_path_outside_files_is_refused_until_removed(self):
        self.run_turn({"outside.txt": "outside\n"},
            "Path('outside.txt').unlink(); Path('docs/new.txt').write_text('inside\\n')",
            "outside files: outside.txt", {"files": "docs/"})

    def test_prose_growth_is_refused_with_the_rules_own_sentence(self):
        self.run_turn({"docs/guide.md": "Acme guide.\n"},
            "Path('docs/guide.md').write_text('')",
            "docs/guide.md grows from 1 to 2 words; prose outside the project's `content:` "
            "only shrinks. Move what this adds into a test, a check or a comment at the code "
            "it is about; words that are the product itself need the base's `content:` to "
            "name them first.")


if __name__ == "__main__":
    unittest.main()
