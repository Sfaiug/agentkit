"""A foreground run whose reviewer's mark is renamed while it runs exits 0 once it merges.

The terminal following the run loaded its config at launch, where `nova` was another model, on
another provider.  During the first review astra's entry is renamed `nova`, on a provider of its
own, and astra's provider leaves the config, so the run cannot go on under astra
(config.as_launched); the run joins its line under astra, and its delivery's resume, on today's
config, reviews it again under nova and merges it.  The merge stands, whatever the config loaded
before the rename says of nova.

Black-box: the program `AK_BIN` names runs a task in the foreground through
tests/fixtures/akbin.py, against gitrig.py's origin, fakegh.py's GitHub and fakeadapter.py's
harnesses.  The first review waits for a file the test writes once the config is renamed.
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


class AForegroundRunMergedUnderARenamedReviewerExits0(unittest.TestCase):
    def test_the_terminal_exits_0_for_a_merge_reviewed_under_the_new_mark(self):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={"AGENTS.md": "---\nhealth: none\ntests: true\n---\n# widgets\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, {"opus": {}, "astra": {},
                              "nova": {"harness": "claude", "model": "claude-nova-1"}})
        codex = fakeadapter.install(home, claude="work", codex="pass")["codex"]
        reviewing, go = codex.dir / "reviewing", codex.dir / "go"
        codex.behave({**fakeadapter.PASS, "sh": f"touch {shlex.quote(str(reviewing))}; "
                                                f"while [ ! -e {shlex.quote(str(go))} ]; do sleep 0.1; done"},
                     "pass")
        ended = []
        task = taskfile.write(home, rig.path)
        terminal = threading.Thread(target=lambda: ended.append(home.ak("run", str(task), timeout=600)))
        terminal.start()
        while not reviewing.exists() and terminal.is_alive():
            time.sleep(0.1)
        akconfig.write(home, {"opus": {}, "nova": {**akconfig.SHIPPED["astra"], "provider": "acme"}})
        go.touch()
        terminal.join()
        (done,) = ended
        (record,) = (home.path / ".agentkit" / "runs").glob("*/run.json")
        state = json.loads(record.read_text())
        self.assertEqual((state["reviewer"], state["review"]["reviewer_provider"], state.get("merged")),
                         ("nova", "acme", True), done.out + done.err)
        self.assertEqual(done.code, 0, done.out + done.err)


if __name__ == "__main__":
    unittest.main()
