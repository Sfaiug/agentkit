"""A resume of a conversation held nowhere goes to a fresh one at once, whatever the harness streamed;
one held where the harness's environment keeps it stays on its id.

A turn on a lost machine leaves its id in what it streamed, with its conversation nowhere on this
host, and Claude Code answers a resume of it with one closing event and exit 1. Black-box: the
program `AK_BIN` names runs a task through tests/fixtures/akbin.py with stand-ins of both harnesses,
each holding the shipped `[worker] sessions`: round 1 fails review, and each resumes in round 2.
A held conversation's turn exits 0, so going on with it is asked at once, not after a transient wait.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

CLAUDE = "projects/acme/sid-1.jsonl"
CODEX = "sessions/2026/11/02/rollout-rev-1.jsonl"
STREAMED = """echo '{"type":"result","is_error":true}' >"${AK_HAND_IN%/*}/events.jsonl\""""


class AResumeOfALostConversation(unittest.TestCase):
    def resumes(self, code, held=(), **env):
        """The session each harness's third turn was given, after its second, a resume of what it
        reported in round 1, streamed one closing event, answered nothing and exited `code`; with
        `held`, files under the Home, and `env` set."""
        with Home() as home:
            rig = Rig(home, "widgets", files={"AGENTS.md": "---\ntests: true\n---\n# widgets\n"})
            akconfig.write(home, ["opus", "astra"])
            home.env.update({name: str(home.path / place) for name, place in env.items()})
            for path in held:
                home.write(path, "{}\n")
            closing = {"sh": STREAMED, "exit": code}
            fakes = fakeadapter.install(
                home, claude=[{**fakeadapter.WORK, "session": "sid-1"}, closing, fakeadapter.DISPUTE],
                codex=[{**fakeadapter.FAIL, "session": "rev-1"}, closing, fakeadapter.PASS])
            done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            state = json.loads((taskfile.only_run(home) / "run.json").read_text())
            self.assertEqual(state["state"], "pass")
            runs = fakes["claude"].runs(), fakes["codex"].runs()
            self.assertEqual([run[1]["argv"][5:] for run in runs], [["sid-1"], ["rev-1"]])
            return [run[2]["argv"][5:] for run in runs]

    def test_held_nowhere_it_starts_afresh(self):
        self.assertEqual(self.resumes(1), [[], []])

    def test_held_in_the_usual_place_it_stays_on_its_id(self):
        self.assertEqual(self.resumes(0, [f".claude/{CLAUDE}", f".codex/{CODEX}"]),
                         [["sid-1"], ["rev-1"]])

    def test_held_where_the_environment_names_it_stays_on_its_id(self):
        self.assertEqual(
            self.resumes(0, [f"own-claude/{CLAUDE}", f"own-codex/{CODEX}"],
                         CLAUDE_CONFIG_DIR="own-claude", CODEX_HOME="own-codex"),
            [["sid-1"], ["rev-1"]])


if __name__ == "__main__":
    unittest.main()
