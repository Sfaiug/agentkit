"""The answer key's harness does in each turn what the test scripted, and hands it in through ak.

A run test scripts its executor, reviewer and fixer turns and judges what ak made of them; that
holds only if tests/fixtures/fakeadapter.py reads each turn's role off the prompt ak wrote, acts
as told inside ak's worker box, and keeps a log of every call.
"""

from datetime import datetime, timezone
import sys
from pathlib import Path
import time
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import fakeadapter
from fixtures.akbin import REPO, Home
from fixtures.gitrig import Rig


class FakeAdapter(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home)
        self.prompt = self.home.write("prompt.md", "Add the retry file.\n")

    def test_each_role_does_what_its_word_says_and_hands_it_in_from_ak_s_box(self):
        fakes = fakeadapter.install(self.home, claude=["work", "pass"], codex="fail")
        for model, role in (("opus", "executor"), ("astra", "reviewer"), ("opus", "fixer")):
            self.home.ak("worker", model, str(self.prompt), "--workspace", str(self.rig.path),
                         "--out", str(self.home.root / role), "--role", role)
        claude, codex = fakes["claude"].runs(), fakes["codex"].runs()
        self.assertEqual([(run["n"], run["role"], run["step"]) for run in claude + codex],
                         [(1, "executor", "work"), (2, "fixer", "pass"),
                          (1, "reviewer", "fail")])
        self.assertEqual([[(h["argv"][0], h["code"]) for h in run["hand_ins"]]
                          for run in claude + codex],
                         [[("done", 0)], [("done", 0)], [("finding", 0), ("done", 0)]])
        self.assertEqual(self.rig.files(remote=False, ref="HEAD"), [".keep", "retry.txt"])
        self.assertEqual((self.home.root / "executor/session_id").read_text(), "sid-claude-1")

    def test_a_step_written_out_is_done_as_written_and_the_last_step_repeats(self):
        fake = fakeadapter.install(self.home, claude=[{
            "write": {"notes/a.txt": "x\n"}, "sh": "touch by-sh", "final": "Custom.",
            "session": "sid-acme", "exit": 3}, "silent"])["claude"]
        codes = []
        for n in range(1, 5):
            if n == 4:
                fake.behave("pass")
            out = self.home.root / f"out-{n}"
            codes.append(self.home.run(str(fake.script), "run", "m", "low", str(self.rig.path),
                                       str(self.prompt), str(out)).code)
            if n == 1:
                self.assertEqual([(out / name).read_text() for name in
                                  ("final.md", "session_id")], ["Custom.\n", "sid-acme"])
        self.assertEqual(codes, [3, 0, 0, 0])
        self.assertEqual(self.rig.git("status", "--porcelain"), "?? by-sh\n?? notes/")
        self.assertEqual((self.home.root / "out-3/final.md").read_text(), "")
        self.assertEqual([run["step"] for run in fake.runs()][1:], ["silent", "silent", "pass"])
        self.assertEqual(fake.n, 4)

    def test_a_final_names_a_moment_counted_from_its_own_turn(self):
        fake = fakeadapter.install(self.home, claude={"final": "Try again at {in 60}."})["claude"]
        before = time.time()
        self.home.run(str(fake.script), "run", "m", "low", str(self.rig.path), str(self.prompt),
                      str(self.home.root / "out"))
        named = (self.home.root / "out/final.md").read_text()
        at = datetime.strptime(named, "Try again at %Y-%m-%dT%H:%M:%SZ.\n")
        self.assertGreaterEqual(at.replace(tzinfo=timezone.utc).timestamp(), int(before) + 60)

    def test_other_verbs_answer_as_set_and_a_fresh_install_forgets_its_calls(self):
        fake = fakeadapter.install(self.home, codex="pass")["codex"]
        self.assertEqual(self.home.run(str(fake.script), "auth")[:2],
                         (0, "the fake needs no login\n"))
        fake.answer("usage", '{"meters": [], "error": null}', 1)
        self.assertEqual(self.home.run(str(fake.script), "usage")[:2],
                         (1, '{"meters": [], "error": null}\n'))
        self.assertEqual([call["verb"] for call in fake.calls()], ["auth", "usage"])
        self.assertEqual(fake.calls("usage")[0]["env"]["AGENTKIT_ADAPTER_DIR"], str(fake.dir))
        manifest = tomllib.loads(fake.manifest.read_text())
        shipped = tomllib.loads((REPO / "adapters/codex.toml").read_text())
        self.assertEqual((manifest["worker"], manifest["stall"]),
                         ({"state": [str(fake.dir)], "sessions": shipped["worker"]["sessions"]},
                          shipped["stall"]))
        self.assertEqual(fakeadapter.install(self.home, codex="pass")["codex"].calls(), [])


if __name__ == "__main__":
    unittest.main()
