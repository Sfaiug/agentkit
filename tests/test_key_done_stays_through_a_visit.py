"""A done seat stays done through the owner's visits: only new work ends it.

Black-box: AK_BIN reads a fake tmux's attachment fields and a plan in a temporary HOME.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, REPO, SYSTEM

FINISHED, BEGAN = 2000, 1000
TMUX = r"""#!PYTHON
import json, os, re, sys
from pathlib import Path

args = sys.argv[1:]
if args[:2] != ["-L", "agentkit-test"]:
    sys.exit(1)       # no legacy server
args = args[2:]
home = Path(os.environ["HOME"])
visit = json.loads((home / "tmux.json").read_text())
fields = {
    "session_id": "$0", "session_name": "acme", "session_path": str(home), "session_created": "100",
    "session_attached": str(visit["attached"]), "session_last_attached": str(visit["last"]),
    "@ak_orch": "1", "@ak_harness_pane": "%1", "pane_id": "%1", "pane_dead": "0",
}
if args[0] in ("list-sessions", "list-panes", "display-message"):
    form = args[args.index("-F") + 1] if "-F" in args else args[-1]
    print(re.sub(r"#\{([^{}]+)\}", lambda m: fields.get(m[1], ""), form))
elif args[0] == "capture-pane":
    print((home / "pane.txt").read_text())
elif args[0] == "show-options" and args[-1] == "@ak_harness_pane":
    print("%1")
"""


# `done`: its whole job is finished and live, until the owner gives it new work.  A seat that
# rested after a visit read `done` again whenever the owner was in it: "It should have never
# switched to idle, as it was done and there was no new conversation going on."  [13 Nov 2026]
class DoneStaysThroughAVisit(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-done-visit-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.state = self.home / ".agentkit" / "state"
        self.state.mkdir(parents=True)
        shutil.copy(REPO / "config.default.toml", self.state.parent / "config.toml")
        self.write(self.state / "session-acme.json", {
            "orchestrator": "opus", "workers": ["opus"], "created": 100,
            "cwd": str(self.home), "conversation": "conv-acme", "id_source": "launcher"})
        self.write(self.state / "seat-acme.json", {"state": "at_prompt", "began": BEGAN})
        self.plan = self.state / "plan-acme.md"
        self.plan.write_text("- [x] The API is live\n")
        os.utime(self.plan, (FINISHED, FINISHED))
        shutil.copy(REPO / "tests/fixtures/claude-prompt-pane.txt", self.home / "pane.txt")
        bins = self.home / "bin"
        bins.mkdir()
        for name, script in {"tmux": TMUX.replace("PYTHON", sys.executable),
                             "ps": "#!/bin/sh\nexit 0\n",
                             "systemctl": "#!/bin/sh\nexit 1\n"}.items():
            program = bins / name
            program.write_text(script)
            program.chmod(0o755)
        self.env = {"HOME": str(self.home), "PATH": os.pathsep.join([str(bins), *SYSTEM]),
                    "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TERM": "dumb",
                    "NO_COLOR": "1", "LANG": "C.UTF-8", "AK_NOTIFY_SINK": "dry-run"}

    def write(self, path, data):
        path.write_text(json.dumps(data))

    def word(self, last, attached=0):
        self.write(self.home / "tmux.json", {"last": last, "attached": attached})
        done = subprocess.run([AK, "orch", "why", "acme"], env=self.env, cwd=self.home,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.splitlines()[0]

    def test_a_visit_after_the_plan_finished_stays_done(self):
        self.assertEqual(self.word(FINISHED + 1), "acme  done")

    def test_a_client_attached_reads_the_same_word(self):
        self.assertEqual(self.word(FINISHED + 1, attached=1), "acme  done")

    def test_a_prompt_starts_work(self):
        self.assertEqual(self.word(""), "acme  done")
        self.write(self.state / "hook-acme.json", {
            "session": "acme", "event": "UserPromptSubmit", "at": FINISHED + 1})
        self.assertEqual(self.word(""), "acme  working")


if __name__ == "__main__":
    unittest.main()
