"""`ak orch NAME` typed at a terminal opens a seat: a session on ak's tmux server, and its record.

A seat is opened once and lives for weeks.  Its tmux session outlives the harness in it, and ak
finds it again by the marks on it and the names in its environment.  Its record under
~/.agentkit/state is what opens it again once tmux has lost it: the models, the folder and the
project it was filed under, and the conversation ak gave the harness, so a reopened seat resumes
that conversation and not another.  The record is a file other programs read, so each field they
read is pinned; a field added beside them breaks no reader.  With no terminal on stdout there is
nothing to hand the session to, and ak says how to attach.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, with a terminal on its stdin as a
person's, and tmux is read as the test; tests/fixtures/adapters/echo.sh stands for a harness
that takes no conversation id.
"""

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, REPO, Home

ATTACH = (r"\Asession {name} is running; attach it with "
          r"`(\S*/)?tmux -L agentkit-test attach -t {name}`\n\Z")
FIELDS = {"orchestrator", "workers", "cwd", "repo", "created", "account", "home_account",
          "resumable", "rulebook_sha"}
LAUNCHED = {"conversation", "id_source", "session_title"}   # a harness ak can give an id
ECHO = """[defaults]
orchestrator = "echo"
workers = ["echo"]

[models.echo]
harness = "echo"
model = "echo-1"
effort = "low"
provider = "test"

[providers.test]
mode = "subscription"
"""


def open_seat(home, name, model, cwd, env=None):
    """Open a seat as a person would, and what ak said and saved as it did."""
    before = time.time()
    done = home.ak("orch", name, "--model", model, "--workers", model, tty=True, cwd=cwd,
                   env=env)
    after = time.time()
    state = home.path / ".agentkit/state"
    record = json.loads((state / f"session-{name}.json").read_text())
    rulebook = (state / f"rulebook-{name}.md").read_bytes()
    return done, record, rulebook, (before, after)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OpenedFromATerminal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.checkout = home.path / "code/acme"
        (cls.checkout / "src").mkdir(parents=True)
        assert home.run("git", "init", "-q", str(cls.checkout)).code == 0
        cls.acme = open_seat(home, "acme", "opus", cls.checkout / "src")
        cls.beta = open_seat(home, "beta", "opus", home.path / "code")

    def tmux_says(self, target, form):
        return self.home.tmux("display-message", "-p", "-t", target, form).out.strip()

    def test_it_exits_0_and_says_how_to_attach_with_no_terminal_to_hand_over(self):
        for name, (done, *_saved) in (("acme", self.acme), ("beta", self.beta)):
            with self.subTest(name):
                self.assertEqual(done.code, 0, done.err)
                self.assertRegex(done.out, ATTACH.format(name=name))
                self.assertEqual(done.err, "")
        self.assertEqual(self.home.tmux("list-clients").out, "")

    def test_the_session_is_on_ak_s_server_marked_as_a_seat_with_its_names(self):
        panes = self.home.tmux("list-panes", "-s", "-t", "=acme", "-F", "#{pane_id}").out.split()
        self.assertEqual(len(panes), 1, panes)
        options = {name: self.home.tmux("show-options", "-v", "-t", "=acme:", name).out.strip()
                   for name in ("@ak_orch", "@ak_harness_pane")}
        self.assertEqual(options, {"@ak_orch": "1", "@ak_harness_pane": panes[0]})
        for value in ("AGENTKIT_SESSION=acme", "AGENTKIT_TMUX_SOCKET=agentkit-test",
                      f"HOME={self.home.path}"):
            with self.subTest(value):
                name = value.split("=")[0]
                self.assertEqual(self.home.tmux("show-environment", "-t", "=acme", name).out,
                                 value + "\n")

    def test_the_session_outlives_its_harness(self):
        # Nothing in a test's Home can run a harness, so the pane's command ends at once.
        pane = self.home.tmux("list-panes", "-s", "-t", "=beta", "-F", "#{pane_id}").out.strip()
        deadline = time.monotonic() + 30
        while self.tmux_says(pane, "#{pane_dead}") != "1":
            self.assertLess(time.monotonic(), deadline, "the harness never ended")
            time.sleep(0.05)
        self.assertEqual(self.home.tmux("has-session", "-t", "=beta").code, 0)
        self.assertEqual(self.tmux_says(pane, "#{remain-on-exit}"), "on")

    def test_the_record_holds_the_models_and_a_conversation_ak_issued(self):
        for name, (_done, record, rulebook, (before, after)) in (("acme", self.acme),
                                                                 ("beta", self.beta)):
            with self.subTest(name):
                self.assertLessEqual(FIELDS | LAUNCHED, set(record))
                self.assertEqual((record["orchestrator"], record["workers"]), ("opus", ["opus"]))
                self.assertEqual((record["account"], record["home_account"]), (None, None))
                self.assertEqual(str(uuid.UUID(record["conversation"])), record["conversation"])
                self.assertEqual((record["id_source"], record["resumable"]), ("launcher", True))
                self.assertEqual(record["session_title"], name)
                self.assertIsInstance(record["created"], (int, float))
                self.assertTrue(before <= record["created"] <= after, record["created"])
                # the rulebook its orchestrator was started on is kept beside the record
                self.assertEqual(record["rulebook_sha"], hashlib.sha256(rulebook).hexdigest())
        self.assertNotEqual(self.acme[1]["conversation"], self.beta[1]["conversation"])

    def test_opened_inside_a_checkout_it_runs_at_its_top_filed_under_it(self):
        record = self.acme[1]
        self.assertEqual((record["cwd"], record["repo"]), (str(self.checkout),) * 2)
        self.assertEqual(self.tmux_says("=acme:", "#{session_path}"), str(self.checkout))

    def test_opened_outside_any_checkout_it_runs_where_it_was_typed_under_none(self):
        record = self.beta[1]
        self.assertEqual((record["cwd"], record["repo"]), (str(self.home.path / "code"), None))
        self.assertEqual(self.tmux_says("=beta:", "#{session_path}"), str(self.home.path / "code"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OnAHarnessThatTakesNoConversationId(unittest.TestCase):
    def test_the_record_holds_no_conversation_and_cannot_be_resumed(self):
        with Home() as home:
            home.write(".agentkit/config.toml", ECHO)
            adapters = home.root / "adapters"
            shutil.copytree(REPO / "tests/fixtures/adapters", adapters)
            code = home.path / "code"
            code.mkdir()
            done, record, rulebook, _when = open_seat(
                home, "demo", "echo", code, env={"AGENTKIT_ADAPTER_DIR": str(adapters)})
            self.assertEqual(done.code, 0, done.err)
            self.assertRegex(done.out, ATTACH.format(name="demo"))
            self.assertLessEqual(FIELDS, set(record))
            self.assertFalse(LAUNCHED & set(record), record)
            self.assertEqual(record["resumable"], False)
            self.assertEqual((record["orchestrator"], record["workers"]), ("echo", ["echo"]))
            self.assertEqual((record["cwd"], record["repo"]), (str(code), None))
            self.assertEqual(record["rulebook_sha"], hashlib.sha256(rulebook).hexdigest())
            self.assertEqual(home.tmux("show-options", "-v", "-t", "=demo:", "@ak_orch").out,
                             "1\n")


if __name__ == "__main__":
    unittest.main()
