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
    def run_turn(self, write, repair, refusal, front=None, *, committed=False, fixer=False):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={"widget.py": "VALUE = 1\n",
                  "tests/test_key_widget.py": "# the base's answer key\n",
                  "docs/guide.md": "Acme.\n"})
        akconfig.write(home, ["opus", "astra"])
        script = f"AK = {AK!r}\nREPAIR = {repair!r}\n" + WORK
        command = ("git add -A && git commit -qm work && " if committed else "")
        worker = {"write": write, "sh": command + "python3 -c " + shlex.quote(script),
                  "final": "## Summary\nFixed the work."}
        fakes = fakeadapter.install(home, claude=["work", worker] if fixer else worker,
                                   codex=["fail", "pass"] if fixer else "pass")
        task = taskfile.write(home, rig.path, front=front, done_when=("true",))
        done = home.ak("run", str(task), "--no-merge", timeout=300)
        run_dir = taskfile.only_run(home)
        turn = Path(fakes["claude"].runs()[-1]["argv"][4])
        evidence = json.loads((turn / "attempts.json").read_text())
        self.assertEqual([item[0] for item in evidence["attempts"]], [2, 0], evidence)
        self.assertIn(refusal, evidence["attempts"][0][1])
        for name in ("unchanged", "head", "index"):
            self.assertTrue(evidence[name], evidence)
        self.assertTrue(evidence["dirty"], evidence)
        rows = [json.loads(line) for line in (turn / "hand-in.jsonl").read_text().splitlines()]
        self.assertEqual(rows[1:], [{"kind": "done"}])
        self.assertEqual(rows[0]["checks"]["base"], rig.head())
        self.assertEqual(rows[0]["checks"]["upstream"], "origin/main")
        self.assertEqual(rows[0]["checks"]["files"], [front["files"]] if front else [])
        self.assertFalse(rows[0]["checks"]["scratch"])
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual([call["role"] for call in fakes["claude"].runs()],
                         ["executor", "fixer"] if fixer else ["executor"])
        state = json.loads((run_dir / "run.json").read_text())
        self.assertEqual(state["state"], "pass")
        self.assertEqual(state["round_summaries"][0]["done_when"], True)

    def test_uncommitted_python_needs_a_key_and_an_untracked_key_closes_the_turn(self):
        self.run_turn({"widget.py": "VALUE = 2\n", "new.py": "VALUE = 3\n",
                       "venv/ignored.py": "VALUE = 4\n"},
            "Path('tests/test_key_turns.py').write_text('# checks the change\\n')",
            "Python changed with no answer key: new.py, widget.py. A change to a .py file "
            "outside tests/ adds, edits or moves in a tests/test_key_*.py in the same change: "
            "a black-box test of what it does.")

    def test_committed_python_still_needs_a_key_against_the_runs_base(self):
        self.run_turn({"widget.py": "VALUE = 2\n"},
            "Path('tests/test_key_turns.py').write_text('# checks the change\\n')",
            "Python changed with no answer key: widget.py.", committed=True)

    def test_a_fixer_is_held_to_the_same_rules(self):
        self.run_turn({"widget.py": "VALUE = 2\n"},
            "Path('retry.txt').unlink(); "
            "Path('tests/test_key_turns.py').write_text('# checks the fix\\n')",
            "Python changed with no answer key: widget.py.", fixer=True)

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

    def workspace_done(self, home, rig, base, files=(), **extra):
        turn = home.root / "hand-in.jsonl"
        checks = {"base": base, "files": files, "scratch": False, "commands": [], **extra}
        turn.write_text(json.dumps({"kind": "turn", "workspace": str(rig.path),
                                   "role": "executor", "checks": checks}) + "\n")
        before = rig.git("rev-parse", "HEAD"), rig.git("ls-files", "--stage")
        result = home.ak("hand-in", "done", cwd=rig.path, env={"AK_HAND_IN": str(turn)})
        self.assertEqual((rig.git("rev-parse", "HEAD"), rig.git("ls-files", "--stage")), before)
        return result

    def test_integrated_target_changes_are_not_the_workers_change(self):
        for integration in ("rebase", "merge"):
            with self.subTest(integration=integration), Home() as home:
                rig = Rig(home, files={"docs/change.txt": "before\n"})
                base = rig.head()
                rig.branch("fix-api", {"docs/change.txt": "after\n"}, push=False)
                rig.commit({"notes.md": "upstream prose\n"})
                rig.git("checkout", "-q", "fix-api")
                rig.git(integration, "-q", "origin/main")
                for extra in ({}, {"upstream": "origin/main"}):
                    result = self.workspace_done(home, rig, base, ["docs/"], **extra)
                    self.assertEqual(result.code, 0, result.out + result.err)

    def test_an_unstaged_attributes_deletion_removes_the_filter(self):
        with Home() as home:
            rig = Rig(home, files={".gitattributes": "AGENTS.md filter=old\n",
                                  "AGENTS.md": "Acme.\n"})
            base = rig.head()
            (rig.path / ".gitattributes").unlink()
            (rig.path / "AGENTS.md").write_text("Acme rules.\n")
            result = self.workspace_done(home, rig, base)
            self.assertEqual(result.code, 0, result.out + result.err)


if __name__ == "__main__":
    unittest.main()
