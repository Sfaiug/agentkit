"""Done refuses a failing task check inside the turn; an uncommitted fix can close it.

Black-box through AK_BIN and fakeadapter: after an interruption gives the run a short silence
window, its executor checks, fixes and checks again in one turn, silent throughout. The check
prints once a second for longer than that window. The loop still checks the commit afterwards.
"""

import json
from pathlib import Path
import shlex
import signal
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import AK, Home
from fixtures.gitrig import Rig

CHECK = "python3 check.py"
KILLED = {"exit": -signal.SIGTERM, "session": ""}
CHECKER = """\
import time
from pathlib import Path
if not Path('retry.txt').exists():
    print('retry.txt is missing')
    raise SystemExit(7)
for n in range(5):
    print(n, flush=True)
    time.sleep(1)
"""
WORK = """\
import json, os, subprocess
from pathlib import Path
out = Path(os.environ['AK_HAND_IN']).parent
before = Path(os.environ['AK_HAND_IN']).read_bytes()
heads, attempts = [], []
for n in range(2):
    heads.append(subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True))
    result = subprocess.run([AK, 'hand-in', 'done'], capture_output=True, text=True)
    attempts.append([result.returncode, result.stdout + result.stderr])
    if n == 0:
        (out / 'unchanged').write_text(str(before == Path(os.environ['AK_HAND_IN']).read_bytes()))
        Path('retry.txt').write_text('fixed, uncommitted\\n')
heads.append(subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True))
dirty = subprocess.check_output(['git', 'status', '--porcelain'], text=True)
(out / 'attempts.json').write_text(json.dumps([attempts, heads, dirty]))
"""


class DoneWaitsForTheChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets", files={"check.py": CHECKER})
        akconfig.write(cls.home, ["opus", "astra"])
        script = "AK = " + repr(AK) + "\n" + WORK
        cls.fakes = fakeadapter.install(cls.home, claude=[KILLED, KILLED, {
            "sh": "python3 -c " + shlex.quote(script), "final": "## Summary\nFixed retry.txt."}],
            codex="pass")
        task = taskfile.write(cls.home, rig.path, done_when=(CHECK, 'export AK_SHARD; true'))
        cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        state = json.loads((cls.run_dir / "run.json").read_text())
        assert state["state"] == "interrupted", state
        (cls.run_dir / "run.json").write_text(json.dumps({**state, "silence_minutes": 0.05}))
        cls.done = cls.home.ak("run", "resume", cls.run_dir.name, timeout=300)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.turn = Path(cls.fakes["claude"].runs()[-1]["argv"][4])

    def test_done_refuses_the_failure_and_accepts_the_uncommitted_fix_in_the_same_turn(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        attempts, heads, dirty = json.loads((self.turn / "attempts.json").read_text())
        self.assertEqual([attempt[0] for attempt in attempts], [2, 0], attempts)
        for text in (CHECK, "exit 7", "retry.txt is missing", "Fix", "blocked"):
            self.assertIn(text, attempts[0][1])
        self.assertEqual((self.turn / "unchanged").read_text(), "True")
        self.assertEqual(len(set(heads)), 1)
        self.assertIn("?? retry.txt", dirty)
        rows = [json.loads(line) for line in (self.turn / "hand-in.jsonl").read_text().splitlines()]
        self.assertEqual(rows[0]["checks"]["commands"], [CHECK])
        self.assertEqual(rows[0]["checks"]["silence"], 3)
        self.assertEqual(rows[1:], [{"kind": "done"}])

    def test_the_silent_turn_reaches_review_without_a_fixer_and_the_loop_checks_its_commit(self):
        self.assertEqual(self.state["state"], "pass", self.done.out + self.done.err)
        self.assertEqual([run["role"] for run in self.fakes["claude"].runs()], ["executor"] * 3)
        self.assertEqual([run["role"] for run in self.fakes["codex"].runs()], ["reviewer"])
        self.assertFalse((self.turn / "events.jsonl").exists())
        self.assertIn(f"$ {CHECK}\n[exit 0]", (self.run_dir / "round-1/donewhen.log").read_text())
        self.assertEqual(len(self.state["round_summaries"]), 1)
        self.assertEqual((Path(self.state["worktree"]) / "retry.txt").read_text(), "fixed, uncommitted\n")


if __name__ == "__main__":
    unittest.main()
