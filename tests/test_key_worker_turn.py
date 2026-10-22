"""`ak worker MODEL TASK` is one headless turn: the adapter's `run` once, its exit code passed back.

A seat or a person uses it to put one question to a model without a run around it.  ak writes
the role's prompt with the task under it, opens the turn's hand-in file, calls the adapter's
`run` verb with the model's id and effort, the workspace, the prompt and the out directory (and
the conversation to resume), prints where the answer is and exits as the adapter did, so a
failed turn fails the command and says where to look.  Black-box: the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py, with a config from akconfig.py and a
scripted harness from fakeadapter.py, whose log shows what each call was given.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home

TASK = "Fix the parser.\nLast line here.\n"
OPENING = {"executor": "You are the executor.", "reviewer": "You are the reviewer.",
           "fixer": "You are the executor, continuing.",
           "reviewer-pr": "You are the reviewer of a pull request by another author.",
           "executor-scratch": "You are the executor.",
           "fixer-scratch": "You are the executor, continuing.",
           "reviewer-scratch": "You are the reviewer."}


class WorkerTurn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, {"beta": {"harness": "acme", "model": "beta-1",
                                           "effort": "low"}})
        cls.fake = fakeadapter.install(cls.home, acme="work")["acme"]
        cls.ws = cls.home.path / "code" / "widgets"
        cls.ws.mkdir(parents=True)
        cls.task = cls.home.write("fix-api.md", TASK)

    def turn(self, *args, step="work", **kwargs):
        """One `ak worker beta` on the task; what it printed and the adapter call it made."""
        self.fake.behave(step)
        before = len(self.fake.runs())
        done = self.home.ak("worker", "beta", str(self.task), *args, **kwargs)
        runs = self.fake.runs()
        self.assertEqual(len(runs), before + 1, done.err)
        return done, runs[-1]

    def rows(self, out):
        return [json.loads(line) for line in (out / "hand-in.jsonl").read_text().splitlines()]

    def test_a_turn_calls_the_adapter_once_and_prints_where_the_answer_is(self):
        out = self.home.path / "out"
        done, call = self.turn("--workspace", str(self.ws), "--out", str(out),
                               "--session", "prev-1")
        self.assertEqual((done.code, done.out), (0, f"{out}/final.md\n"), done.err)
        self.assertEqual(call["argv"], ["beta-1", "low", str(self.ws), str(out / "prompt.md"),
                                        str(out), "prev-1"])
        self.assertTrue((out / "final.md").is_file())

    def test_the_prompt_is_the_role_s_opening_with_the_task_under_it(self):
        out = self.home.path / "prompted"
        done, _ = self.turn("--workspace", str(self.ws), "--out", str(out))
        self.assertEqual(done.code, 0, done.err)
        prompt = (out / "prompt.md").read_text()
        self.assertTrue(prompt.startswith("You are the executor.\n"), prompt)
        self.assertIn(f"Work only inside {self.ws}", prompt.splitlines()[1])
        self.assertTrue(prompt.endswith(f"\n\n{TASK}"), prompt)

    def test_the_turn_hands_in_to_its_out_directory_as_nobody_s_seat(self):
        out = self.home.path / "handed"
        done, call = self.turn("--workspace", str(self.ws), "--out", str(out),
                               env={"AGENTKIT_SESSION": "acme"})
        self.assertEqual(done.code, 0, done.err)
        env = call["env"]
        self.assertEqual(env.get("AK_HAND_IN"), str(out / "hand-in.jsonl"))
        self.assertEqual(env.get("AGENTKIT_UNATTENDED"), "1")
        self.assertNotIn("AGENTKIT_SESSION", env)
        self.assertTrue(env.get("AGENTKIT_RUN", "").startswith(
            f"{self.home.path}/.agentkit/runs/worker/turn-"), env)
        rows = self.rows(out)
        self.assertEqual(rows[0], {"kind": "turn", "workspace": str(self.ws), "role": "executor",
                                   "findings": []})
        self.assertEqual(rows[-1], {"kind": "done"})    # the adapter's own `ak hand-in done`

    def test_a_failed_turn_exits_as_the_adapter_did_and_points_at_its_log(self):
        for step, code in (({"final": "Half done.", "exit": 7}, 7), ("flaky", 1)):
            with self.subTest(code=code):
                out = self.home.path / f"failed-{code}"
                done, _ = self.turn("--workspace", str(self.ws), "--out", str(out), step=step)
                self.assertEqual((done.code, done.out), (code, f"{out}/final.md\n"))
                self.assertIn(f"ak worker: beta exited {code}; see {out}/stderr.log", done.err)

    def test_the_role_picks_the_prompt_s_opening_and_the_turn_s_role(self):
        for role, opening in OPENING.items():
            with self.subTest(role=role):
                out = self.home.path / "roles" / role
                done, _ = self.turn("--workspace", str(self.ws), "--out", str(out),
                                    "--role", role)
                self.assertEqual(done.code, 0, done.err)
                prompt = (out / "prompt.md").read_text()
                self.assertEqual(prompt.split("\n", 1)[0], opening)
                self.assertTrue(prompt.endswith(f"\n\n{TASK}"), prompt)
                self.assertEqual(self.rows(out)[0]["role"], role)

    def test_alone_it_works_where_it_was_started_into_a_folder_named_for_model_and_task(self):
        out = self.home.path / ".agentkit" / "tmp" / "worker-beta-fix-api"
        done, call = self.turn(cwd=self.ws)
        self.assertEqual((done.code, done.out), (0, f"{out}/final.md\n"), done.err)
        # No --session: a new conversation, so the adapter is given none to resume.
        self.assertEqual(call["argv"], ["beta-1", "low", str(self.ws), str(out / "prompt.md"),
                                        str(out)])
        self.assertTrue((out / "prompt.md").read_text().endswith(f"\n\n{TASK}"))
        self.assertEqual(self.rows(out)[0]["workspace"], str(self.ws))


if __name__ == "__main__":
    unittest.main()
