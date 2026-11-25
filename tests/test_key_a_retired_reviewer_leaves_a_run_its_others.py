"""A reviewer removed from the config while a run waits leaves it the others it allowed.

The run launches with astra and nova as its reviewers and astra reviews first.  During that
review astra's entry leaves the config; the review it gave no longer counts, and the delivery's
resume, on today's config, reviews the run again under nova, still in its saved list, and
merges it instead of stopping on `unknown model 'astra'`.

Black-box: the program `AK_BIN` names runs a task in the foreground through
tests/fixtures/akbin.py, against gitrig.py's origin, fakegh.py's GitHub and fakeadapter.py's
harnesses.  The first review waits for a file the test writes once astra is gone.
"""

from pathlib import Path
import json
import shlex
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


class ARetiredReviewerLeavesARunItsOthers(unittest.TestCase):
    def test_the_run_is_reviewed_again_by_the_reviewer_left_and_merges(self):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={"AGENTS.md": "---\nhealth: none\ntests: true\n---\n# widgets\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        nova = {"harness": "claude", "model": "claude-nova-1"}
        akconfig.write(home, {"opus": {}, "astra": {}, "nova": nova}, workers=["opus"],
                       reviewers=["astra", "nova"])
        codex = fakeadapter.install(home, claude="work", codex="pass")["codex"]
        reviewing, go = codex.dir / "reviewing", codex.dir / "go"
        marked, release = shlex.quote(str(reviewing)), shlex.quote(str(go))
        codex.behave({**fakeadapter.PASS,
                      "sh": f"touch {marked}; while [ ! -e {release} ]; do sleep 0.1; done"}, "pass")
        ended = []
        task = taskfile.write(home, rig.path)
        terminal = threading.Thread(target=lambda: ended.append(home.ak("run", str(task), timeout=600)))
        terminal.start()
        while not reviewing.exists() and terminal.is_alive():
            time.sleep(0.1)
        akconfig.write(home, {"opus": {}, "nova": nova}, workers=["opus"], reviewers=["nova"])
        go.touch()
        terminal.join()
        (done,) = ended
        # Without astra's first review, nova's merge proves no replacement.
        self.assertTrue(reviewing.exists(), done.out + done.err)
        (record,) = (home.path / ".agentkit" / "runs").glob("*/run.json")
        state = json.loads(record.read_text())
        self.assertEqual((state["reviewers"], state["reviewer"], state.get("merged")),
                         (["astra", "nova"], "nova", True), done.out + done.err)
        self.assertEqual(done.code, 0, done.out + done.err)


if __name__ == "__main__":
    unittest.main()
