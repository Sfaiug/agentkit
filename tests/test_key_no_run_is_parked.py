"""Colliding builds keep going; the younger meets the older before its review.

Black-box through AK_BIN, akbin, gitrig, fakeadapter and fakegh. Both executors edit
the same line and hold. A tick must leave both running. The older then lands while
the younger still builds, whose conflict fixer preserves both changes before review.
"""

import json
from pathlib import Path
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, rerun_boxed
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

BASE = "".join(f"line {n}\n" for n in range(1, 31))


class NoRunIsParked(unittest.TestCase):
    def test_both_build_and_the_younger_rebases_resolves_reviews_and_lands(self):
        with Home() as home:
            home.env.update(https_proxy="http://127.0.0.1:9", http_proxy="http://127.0.0.1:9",
                            GIT_ALLOW_PROTOCOL="file")
            home.write(".agentkit/state/gc.json", {"started_at": time.time()})
            rig = Rig(home, "widgets", files={"api.py": BASE})
            GitHub(home).grant(rig.slug, "WRITE")
            akconfig.write(home, ["opus", "astra"])
            fakes = fakeadapter.install(home, claude="pass", codex="pass")
            marks = fakes["claude"].dir
            runs = []

            def state(directory):
                saved = json.loads((directory / "run.json").read_text())
                self.assertNotIn("lease_wait", saved)
                self.assertNotEqual(saved["state"], "stopped")
                return saved

            def wait(ready, what):
                deadline = time.monotonic() + 120
                while not ready():
                    for directory in runs:
                        state(directory)
                    self.assertLess(time.monotonic(), deadline, f"never {what}")
                    time.sleep(0.1)

            def held(name):
                return {"write": {"api.py": BASE.replace("line 5\n", f"{name}\n")},
                        "sh": f"touch '{marks}/{name}.held'; "
                              f"while [ -d '{marks}' ] && [ ! -e '{marks}/{name}.go' ]; "
                              "do sleep 0.1; done",
                        "commit": f"{name} line five", "hand_in": [["done"]],
                        "final": "## Summary\nEdited line five."}

            resolved = BASE.replace("line 5\n", "older and younger\n")
            fakes["claude"].behave(held("older"), held("younger"), {
                "sh": f"printf %s {shlex.quote(resolved)} > api.py && git add api.py && "
                      "GIT_EDITOR=true git rebase --continue",
                "hand_in": [["done"]], "final": "## Summary\nPreserved both changes."})
            # Record the commit and contents from the reviewer's own checkout.
            fakes["codex"].behave("pass", {
                "sh": f"git rev-parse HEAD > '{marks}/reviewed'; "
                      f"git show HEAD:api.py > '{marks}/reviewed-api'",
                "hand_in": [["done"]], "final": "## Summary\nBoth changes pass."})

            loops = []
            for name, title in (("older", "Change line five"), ("younger", "Reword line five")):
                task = taskfile.write(home, rig.path, title, done_when=("true",), front={"rounds": 1})
                loop = home.spawn("run", str(task))
                loops.append(loop)
                wait(lambda: (marks / f"{name}.held").exists() or loop.poll() is not None,
                     f"{name} building")
                self.assertIsNone(loop.poll(), home.log(f"spawn-{len(loops)}.err").read_text())
                runs.append(next(directory for directory in taskfile.runs(home) if directory not in runs))

            tick = home.ak("watch")
            self.assertEqual(tick.code, 0, tick.out + tick.err)
            self.assertEqual([state(directory)["state"] for directory in runs], ["running"] * 2)
            self.assertIsNone(loops[1].poll())
            (marks / "older.go").touch()
            wait(lambda: loops[0].poll() is not None, "the older landing")
            self.assertEqual(loops[0].returncode, 0, (runs[0] / "log.txt").read_text())
            self.assertTrue(state(runs[0])["merged"])
            older = rig.head()
            self.assertEqual(rig.origin("show", "main:api.py"), BASE.replace("line 5\n", "older\n").strip())
            self.assertEqual(state(runs[1])["state"], "running")
            self.assertIsNone(loops[1].poll())

            (marks / "younger.go").touch()
            wait(lambda: loops[1].poll() is not None, "the younger landing")
            self.assertEqual(loops[1].returncode, 0, (runs[1] / "log.txt").read_text())
            younger = state(runs[1])
            self.assertEqual((younger["state"], younger["merged"], younger["rounds"]), ("pass", True, 1))
            self.assertEqual(younger["rebases"], [{"round": 1, "onto": older, "method": "rebase"}])
            self.assertEqual([turn["role"] for turn in fakes["claude"].runs()],
                             ["executor", "executor", "fixer"])
            self.assertEqual(fakes["codex"].n, 2)
            self.assertEqual((marks / "reviewed").read_text().strip(),
                             younger["round_summaries"][0]["head_sha"])
            reviewed = (marks / "reviewed").read_text().strip()
            self.assertEqual(rig.git("rev-parse", f"{reviewed}^"), older)
            self.assertEqual((marks / "reviewed-api").read_text(), resolved)
            self.assertEqual(rig.origin("show", "main:api.py"), resolved.strip())
            self.assertEqual(taskfile.runs(home), runs)


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
