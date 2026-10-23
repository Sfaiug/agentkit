"""A worker whose harness login has expired stops at once with exit 2 and says which login.

One expired token used to cost a run its twenty-minute silence window and three retries, so
`ak worker` treats a login that cannot authenticate as its own failure: the adapter's `auth`
verb saying no in one line before the launch, the harness's own logout words (its manifest's
`[auth] signatures`) anywhere in a turn's stderr.log, or a turn over quickly having streamed
nothing whose `auth` then says no.  Each ends in `ak worker: <harness> login expired: <line>`
and exit 2, nothing on stdout; any other answer is no answer and the turn runs.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, its harness the
scripted adapter of fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home

EXPIRED = "ak worker: codex login expired: "


class WorkerLoginExpired(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        # The model's name differs from its harness's: the message names the login's harness.
        akconfig.write(cls.home, {"beta": "codex"})
        cls.fake = fakeadapter.install(cls.home, codex="pass")["codex"]
        cls.workspace = cls.home.path / "code" / "fix-api"
        cls.workspace.mkdir(parents=True)
        cls.task = cls.home.write("tasks/fix-api.md", "Fix the api.\n")
        cls.signature = tomllib.loads(cls.fake.manifest.read_text())["auth"]["signatures"][0]

    def setUp(self):
        self.fake.answer("auth", fakeadapter.ANSWERS["auth"], 0)

    def worker(self, name, step="pass", timeout=120):
        out = self.home.root / "out" / name
        self.fake.behave(step)
        done = self.home.ak("worker", "beta", str(self.task), "--workspace",
                            str(self.workspace), "--out", str(out), timeout=timeout)
        return out, done

    def assertExpired(self, done, line):
        self.assertEqual((done.code, done.out, done.err), (2, "", EXPIRED + line + "\n"))

    def answers_after_the_turn(self, line):
        # The fake's answers file, as Adapter.answer writes it: the turn changes what `auth`
        # says only after the launch was let through.
        return {str(self.fake.dir / "codex.answers"): json.dumps({"auth": [line, 1]})}

    def test_an_auth_verb_saying_no_stops_the_worker_before_any_turn(self):
        self.fake.answer("auth", "token expired; run login", 1)
        runs = self.fake.n
        out, done = self.worker("before")
        self.assertExpired(done, "token expired; run login")
        self.assertFalse(out.exists())
        self.assertEqual(self.fake.n, runs)

    def test_logout_words_anywhere_in_a_turn_stop_it_whatever_its_exit_code(self):
        # Another case, then a page of the harness unwinding: the whole log is read.
        out = self.home.root / "out" / "words"
        said = self.signature.upper() + "\n" + "unwinding\n" * 3000
        _, done = self.worker("words", {"write": {str(out / "stderr.log"): said}, "exit": 1})
        self.assertExpired(done, self.signature)

    def test_a_turn_that_says_it_is_logged_out_and_then_hangs_ends_at_once(self):
        out = self.home.root / "out" / "hangs"
        step = {"write": {str(out / "stderr.log"): self.signature + "\n"}, "sh": "sleep 600"}
        _, done = self.worker("hangs", step, timeout=60)
        # Whether the stopped turn's `sleep` is still there to be named first is a race.
        self.assertEqual((done.code, done.out, done.err.splitlines()[-1:]),
                         (2, "", [EXPIRED + self.signature]), done.err)
        self.assertNotIn("Traceback", done.err)

    def test_a_quick_silent_turn_asks_the_auth_verb_again_and_believes_its_no(self):
        step = {"write": self.answers_after_the_turn("session ended; log in again")}
        _, done = self.worker("silent", step)
        self.assertExpired(done, "session ended; log in again")

    def test_a_turn_that_streamed_events_is_its_own_result_whatever_auth_says_after(self):
        out = self.home.root / "out" / "streamed"
        step = {"write": {str(out / "events.jsonl"): '{"type": "turn.completed"}\n',
                          **self.answers_after_the_turn("session ended; log in again")},
                "final": "Handed in."}
        _, done = self.worker("streamed", step)
        self.assertEqual((done.code, done.out, done.err), (0, f"{out / 'final.md'}\n", ""))

    def test_an_auth_answer_that_is_not_one_line_is_no_answer_and_the_turn_runs(self):
        for name, answer in (("two-lines", ("no token\nrun login", 1)), ("silent", ("", 1)),
                             ("crashed", ("no token", 3))):
            with self.subTest(name):
                self.fake.answer("auth", *answer)
                runs = self.fake.n
                out, done = self.worker(name)
                self.assertEqual((done.code, done.out), (0, f"{out / 'final.md'}\n"), done.err)
                self.assertEqual(self.fake.n, runs + 1)


if __name__ == "__main__":
    unittest.main()
