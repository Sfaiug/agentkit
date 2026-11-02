"""A resume of a conversation its harness does not hold never starts the harness, so it streams
nothing, and a resume that streams nothing goes to a fresh conversation at once.

A turn on a lost machine leaves its id in what it streamed, with its conversation nowhere on this
host. A real harness answers a resume of it with a closing event a provider's fault ends on too,
and that is retried for ever. What it holds is read where it looks: the adapter's own choice of
home, inherited or an account's, from the workspace. Black-box: the adapter beside the program
`AK_BIN` names, in a Home of tests/fixtures/akbin.py with a stand-in for each harness, then a task
through `ak` with fakeadapter.py's. Fails against `/bin/false`.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig
from fixtures.hookdrive import ROOT

SID = "sid-1"
# harness: (the variable naming its home, its usual home, the conversation under a home)
HARNESSES = {"claude": ("CLAUDE_CONFIG_DIR", ".claude", f"projects/acme/{SID}.jsonl"),
             "codex": ("CODEX_HOME", ".codex", f"sessions/2026/11/02/rollout-{SID}.jsonl")}
WORKSPACE = "code/acme"


class TheAdapterLooksWhereItsHarnessDoes(unittest.TestCase):
    def resumed(self, harness, held, named="", account=""):
        """Whether a `run` resuming SID started the harness, with the conversation at `held`, a
        home under HOME, the harness's variable holding `named`; a refused one left only empty
        files and exit 1."""
        variable, _, conversation = HARNESSES[harness]
        with Home() as home:
            saw = home.root / "saw"
            home.fake(harness, f'#!/bin/sh\ncat >/dev/null\necho "$@" >"{saw}"\n')
            home.write(f"{held}/{conversation}", "{}\n")
            workspace, out = home.path / WORKSPACE, home.path / "turn"
            workspace.mkdir(parents=True, exist_ok=True)
            prompt = home.write("prompt.md", "Go on.\n")
            done = home.run(
                str(ROOT / "adapters" / f"{harness}.sh"), "run", "default", "high", str(workspace),
                str(prompt), str(out), SID, env={"AGENTKIT_ACCOUNT": account, variable: named.format(
                    home=home.path)})
            if saw.is_file():
                self.assertEqual(done.code, 0, done.err)
                self.assertIn(SID, saw.read_text())
                return True
            self.assertEqual(done.code, 1, done.err)
            self.assertFalse((out / "events.jsonl").exists())
            self.assertEqual((out / "final.md").read_text(), "")
            self.assertEqual((out / "session_id").read_text(), "")
            return False

    def test_held_nowhere_the_harness_never_starts(self):
        for harness, (_, usual, _) in HARNESSES.items():
            self.assertFalse(self.resumed(harness, f"{usual}-gone/elsewhere"), harness)

    def test_held_in_its_usual_home_it_resumes(self):
        for harness, (_, usual, _) in HARNESSES.items():
            self.assertTrue(self.resumed(harness, usual), harness)

    def test_held_in_the_home_a_variable_names_it_resumes(self):
        for harness in HARNESSES:
            self.assertTrue(self.resumed(harness, "own[1]", "{home}/own[1]"), harness)

    def test_a_relative_home_is_read_from_the_workspace(self):
        for harness in HARNESSES:
            self.assertTrue(self.resumed(harness, f"{WORKSPACE}/own", "own"), harness)

    def test_an_account_s_home_a_seat_handed_down_is_no_home_of_the_usual_login(self):
        for harness, (_, usual, _) in HARNESSES.items():
            self.assertFalse(self.resumed(harness, f"{usual}-old", f"{{home}}/{usual}-old"), harness)

    def test_an_account_replaces_the_home_a_variable_names(self):
        for harness in HARNESSES:
            self.assertFalse(self.resumed(harness, "own", "{home}/own", account="second"), harness)

    def test_an_account_shares_the_usual_login_s_conversations(self):
        for harness, (_, usual, _) in HARNESSES.items():
            self.assertTrue(self.resumed(harness, usual, account="second"), harness)


class AResumeThatStreamsNothing(unittest.TestCase):
    def test_goes_to_a_fresh_conversation_at_once(self):
        with Home() as home:
            rig = Rig(home, "widgets", files={"AGENTS.md": "---\ntests: true\n---\n# widgets\n"})
            akconfig.write(home, ["opus", "astra"])
            fakes = fakeadapter.install(
                home, claude=[{**fakeadapter.WORK, "session": SID}, {"exit": 1}, fakeadapter.DISPUTE],
                codex=[{**fakeadapter.FAIL, "session": "rev-1"}, {"exit": 1}, fakeadapter.PASS])
            done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            state = json.loads((taskfile.only_run(home) / "run.json").read_text())
            self.assertEqual(state["state"], "pass")
            runs = fakes["claude"].runs(), fakes["codex"].runs()
            self.assertEqual([run[1]["argv"][5:] for run in runs], [[SID], ["rev-1"]])
            self.assertEqual([run[2]["argv"][5:] for run in runs], [[], []])


if __name__ == "__main__":
    unittest.main()
