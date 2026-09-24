"""The worker token warns before it expires, not after every turn starts failing.

`claude setup-token` mints a token that lives exactly one year from the day its
file was written.  From fourteen days out every session reads the warning with
the word `needs you` -- one card per episode by the cards rule -- and past the
day the reason says `expired`.  Replacing the file ends the episode.

Offline throughout: a temporary HOME, a fake token file with a chosen mtime, and
no real secrets directory anywhere.
"""

from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, watch, worker

REPLACE = "run claude setup-token and replace ~/.agentkit/secrets/claude_oauth_token"


class TokenExpiry(unittest.TestCase):
    """One HOME the adapter and the poll agree on, and nothing that can reach a network."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".token-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.home = self.root / "home"
        ak = self.home / ".agentkit"
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, ak / name.lower()))
        self.stack.enter_context(patch.object(config, "HOME", ak))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.home), "AGENTKIT_DISCORD_WEBHOOK": "",
            "AGENTKIT_DISCORD_USER_ID": "", "CLAUDE_CODE_OAUTH_TOKEN": "",
            "NO_COLOR": "1", "PYTHONDONTWRITEBYTECODE": "1"}))
        config.ensure_dirs()
        self.token = config.SECRETS / "claude_oauth_token"

    # --- the fixture ---------------------------------------------------------

    def sealed(self):
        """A PATH whose `security` can never reach the account's own Keychain."""
        path = self.root / "sealed-bin"
        if not path.exists():
            path.mkdir()
            (path / "security").write_text(
                '#!/usr/bin/env bash\necho "security: no keychain in this fixture" >&2\nexit 1\n')
            (path / "security").chmod(0o755)
        return {"PATH": f"{path}:{os.environ['PATH']}"}

    def write_token(self, days_ago, content="sk-ant-oat01-fake\n"):
        """A token file written `days_ago` days ago, an hour off the day boundary."""
        self.token.write_text(content)
        self.token.chmod(0o600)
        moment = int(time.time()) - days_ago * 86400 + 3600
        os.utime(self.token, (moment, moment))
        return self.token.stat().st_mtime

    def ask(self, *argv):
        env = {**os.environ, **self.sealed(), "HOME": str(self.home),
               "CLAUDE_CODE_OAUTH_TOKEN": ""}
        done = subprocess.run(["bash", str(REPO / "adapters" / "claude.sh"), "auth", *argv],
                              env=env, capture_output=True, encoding="utf-8", check=False)
        return done.returncode, (done.stdout + done.stderr).strip()

    def poll(self):
        state = {"stalls": {}, "reviewed": {}, "own": {}, "seen_at": {}}
        return state, watch.poll_worker_token(state)

    def state_of(self, name, tokens, session=None, harness="claude", records=()):
        return watch.session_state(name, session={"name": name, **(session or {})},
                                   records=list(records), auth_out={}, gh_out={},
                                   harness=harness, token_out=tokens, previous={})

    # --- 1: the verb dates the token off its file ----------------------------

    def test_auth_reports_the_days_left(self):
        self.write_token(100)
        code, said = self.ask()
        self.assertEqual((code, len(said.splitlines())), (0, 1), said)
        self.assertIn("expires in 265 days", said)
        self.assertEqual(worker.auth_ok("claude"), (True, said))

    # --- 2: from fourteen days out every session reads the warning -----------

    def test_thirteen_days_out_every_session_reads_the_warning(self):
        self.write_token(352)
        _, tokens = self.poll()
        self.assertEqual(tokens["claude"]["days"], 13)
        expected = f"claude worker token expires in 13 days: {REPLACE}"
        running = [(Path("x"), {"launched_session": "w", "state": "running",
                                "started_at": time.time(), "title": "t"})]
        seats = [("a", {}, "claude", ()),            # a live claude seat
                 ("b", {}, "codex", ()),             # another harness entirely
                 ("c", {"exited": True}, "claude", ()),  # nobody in it any more
                 ("w", {}, "claude", running)]       # working, with a run going
        for name, session, harness, records in seats:
            with self.subTest(name=name):
                found = self.state_of(name, tokens, session, harness, records)
                self.assertEqual(found["word"], "needs you")
                self.assertEqual(found["reason"], expected)

    # --- 3: past the day the reason says expired -----------------------------

    def test_past_expiry_the_reason_says_expired(self):
        self.write_token(400)
        code, said = self.ask()
        self.assertEqual((code, len(said.splitlines())), (1, 1), said)
        self.assertIn("worker token expired", said)
        self.assertEqual(worker.auth_ok("claude"), (False, said))
        _, tokens = self.poll()
        self.assertTrue(tokens["claude"]["expired"])
        found = self.state_of("a", tokens)
        self.assertEqual(found["word"], "needs you")
        self.assertIn("expired", found["reason"])
        self.assertEqual(found["reason"], f"claude worker token expired: {REPLACE}")

    # --- 4: a replaced file ends the episode ---------------------------------

    def test_replacing_the_file_ends_the_episode(self):
        self.write_token(352)
        state, tokens = self.poll()
        running = [(Path("x"), {"launched_session": "w", "state": "running",
                                "started_at": time.time(), "title": "t"})]
        found = self.state_of("w", tokens, {}, "claude", running)
        self.assertEqual((found["word"], found["reason"]),
                         ("needs you", f"claude worker token expires in 13 days: {REPLACE}"))
        # replaced: new bytes, today's date.  The new date asks again at once rather
        # than waiting out the day, so the warning is gone on the very next pass.
        self.write_token(0, content="sk-ant-oat01-fresh\n")
        tokens = watch.poll_worker_token(state)
        self.assertIsNone(watch.token_warning(tokens["claude"]))
        found = self.state_of("w", tokens, {}, "claude", running)
        self.assertEqual(found["word"], "working")
        self.assertNotIn("claude worker token", found["reason"])

    def test_replacing_the_file_within_the_window_starts_a_new_episode(self):
        # Any new file date ends the episode, even one that still warns: the word never
        # leaves `needs you`, but the warning's beginning moves to the replacement.
        self.write_token(352)
        state = {"stalls": {}, "reviewed": {}, "own": {}, "seen_at": {}}
        first = watch.poll_worker_token(state, now=1000)["claude"]
        self.assertEqual((first["days"], first["at"]), (13, 1000))
        self.write_token(355, content="sk-ant-oat01-older\n")
        second = watch.poll_worker_token(state, now=2000)
        self.assertEqual((second["claude"]["days"], second["claude"]["at"]), (10, 2000))
        found = watch.session_state(
            "a", now=2000, session={"name": "a"}, records=[], auth_out={}, gh_out={},
            harness="claude", token_out=second,
            previous={"word": "needs you", "word_since": 1000,
                      "reason": f"claude worker token expires in 13 days: {REPLACE}"})
        self.assertEqual(found["word"], "needs you")
        self.assertEqual(found["reason"], f"claude worker token expires in 10 days: {REPLACE}")
        self.assertEqual(found["since"], 2000)

    # --- the rest of the contract --------------------------------------------

    def test_no_token_file_means_no_warning(self):
        self.assertFalse(self.token.exists())
        state, tokens = self.poll()
        self.assertEqual(tokens, {})
        self.assertNotIn("worker_tokens", state)
        found = self.state_of("a", None)
        self.assertNotIn("claude worker token", found["reason"])

    def test_the_tick_asks_the_verb_at_most_once_a_day(self):
        self.write_token(100)
        state = {"stalls": {}, "reviewed": {}, "own": {}, "seen_at": {}}
        start = time.time()
        with patch.object(worker, "auth_ok", wraps=worker.auth_ok) as asked:
            watch.poll_worker_token(state, now=start)
            watch.poll_worker_token(state, now=start + 10)
            self.assertEqual(asked.call_count, 1)
            watch.poll_worker_token(state, now=start + watch.TOKEN_POLL_EVERY)
            self.assertEqual(asked.call_count, 2)

    def test_the_info_screen_shows_the_expiry_date(self):
        # the config screen's Discord row says connected or not, and nothing about the token
        mtime = self.write_token(300)
        when = time.strftime("%Y-%m-%d", time.localtime(mtime + 365 * 86400))
        with redirect_stdout(io.StringIO()) as out:
            menu.show_info(dry_run=True)
        screen = out.getvalue()
        self.assertIn(f"claude worker token expires {when}", screen)


if __name__ == "__main__":
    unittest.main(verbosity=2)
