"""The worker token warns before it expires, not after every turn starts failing.

`claude setup-token` mints a token that lives exactly one year from the day its
file was written.  From fourteen days out the ak screen says when, on the line under
its subscriptions' usage, and no session's word changes for it; past the day every
session reads it with the word `needs you` -- one card per episode by the cards rule,
the reason saying `expired` -- and the line turns amber.  Replacing the file ends the
episode.

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
from agentkit import config, menu, terminal, watch, worker

REPLACE = "run claude setup-token and replace ~/.agentkit/secrets/claude_oauth_token"


class TokenExpiry(unittest.TestCase):
    """One HOME the adapter and the poll agree on, and nothing that can reach a network."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-token-", dir=REPO)
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
        # a worker on another subscription names its account; these ask the usual login
        os.environ.pop(config.ACCOUNT_ENV, None)
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

    # --- 2: from fourteen days out the ak screen says it, and no word changes --

    def test_thirteen_days_out_the_ak_screen_says_it_and_no_session_reads_it(self):
        self.write_token(352)
        _, tokens = self.poll()
        self.assertEqual(tokens["claude"]["days"], 13)
        running = [(Path("x"), {"launched_session": "w", "state": "running",
                                "started_at": time.time(), "title": "t"})]
        for name, session, harness, records in (("a", {}, "claude", ()),
                                                 ("w", {}, "claude", running)):
            with self.subTest(name=name):
                found = self.state_of(name, tokens, session, harness, records)
                self.assertNotIn("worker token", found["reason"])
        self.assertEqual(self.state_of("w", tokens, {}, "claude", running)["word"], "working")
        self.assertRegex(watch.token_standing(), r"^claude worker token expires \S+ \(in 13 days\)$")
        self.write_token(300)        # 65 days out it says nothing yet
        self.assertIsNone(watch.token_standing())

    def test_the_line_under_the_grid_says_it_dim_then_amber_once_dead(self):
        cfg = config.load()
        (config.STATE / "usage.json").write_text('{"providers": {}}')
        self.stack.enter_context(patch.object(terminal, "colour_depth", return_value=8))

        def under(height=30, owned=True):
            with patch.object(terminal, "width", return_value=100), \
                    patch.object(terminal, "height", return_value=height), \
                    redirect_stdout(io.StringIO()) as out:
                menu.draw(cfg, [], drawn={} if owned else None, look=False, records=[])
            lines = out.getvalue().split("\033[J")[0].replace("\033[K", "").split("\n")
            return next(line for line in lines if "worker token" in line)
        self.write_token(352)
        self.assertEqual(under(), "  " + terminal.styled(watch.token_standing(), "dim"))
        # the grid folded to its readings, a screen too short for its frame, and a pipe with no
        # keyboard say it the same
        for height, owned in ((10, True), (9, True), (30, False)):
            with self.subTest(height=height, owned=owned):
                self.assertEqual(under(height, owned),
                                 "  " + terminal.styled(watch.token_standing(), "dim"))
        self.write_token(400)
        self.assertEqual(under(), "  " + terminal.styled(watch.token_standing(), "amber"))

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

    def test_a_token_dying_between_the_daily_asks_is_dead_at_the_next_pass(self):
        # its file's date passing asks the verb again at once, so no seat waits out the day
        ends = watch.token_ends(self.write_token(365))
        answers = [(True, "claude: long-lived worker token (expires in 0 days)"),
                   (False, "claude: worker token expired")]
        state = {}
        with patch.object(worker, "auth_ok", side_effect=lambda *_: answers.pop(0)):
            watch.poll_worker_token(state, now=ends - 3600)
            tokens = watch.poll_worker_token(state, now=ends + 3600)
            self.assertEqual(watch.poll_worker_token(state, now=ends + 7200), tokens)
        # the episode begins with the death, not the day the line first said it
        self.assertEqual((tokens["claude"]["expired"], tokens["claude"]["at"]), (True, ends + 3600))
        found = self.state_of("a", tokens)
        self.assertEqual((found["word"], found["reason"]),
                         ("needs you", f"claude worker token expired: {REPLACE}"))

    # --- 4: a replaced file ends the episode ---------------------------------

    def test_replacing_the_file_ends_the_episode(self):
        self.write_token(400)
        state, tokens = self.poll()
        running = [(Path("x"), {"launched_session": "w", "state": "running",
                                "started_at": time.time(), "title": "t"})]
        found = self.state_of("w", tokens, {}, "claude", running)
        self.assertEqual((found["word"], found["reason"]),
                         ("needs you", f"claude worker token expired: {REPLACE}"))
        # replaced: new bytes, today's date.  The new date asks again at once rather
        # than waiting out the day, so the warning is gone on the very next pass.
        self.write_token(0, content="sk-ant-oat01-fresh\n")
        tokens = watch.poll_worker_token(state)
        self.assertIsNone(watch.token_warning(tokens["claude"]))
        found = self.state_of("w", tokens, {}, "claude", running)
        self.assertEqual(found["word"], "working")
        self.assertNotIn("claude worker token", found["reason"])

    def test_a_draft_keeps_the_new_episodes_beginning(self):
        # the draft stands beside the reason, and the episode keeps its beginning
        tokens = {"claude": {"harness": "claude", "expired": True, "remedy": REPLACE,
                             "at": 2000}}
        found = watch.session_state(
            "a", now=3000, session={"name": "a", "attached": False}, records=[],
            auth_out={}, gh_out={}, harness="claude", token_out=tokens,
            live={"state": "draft", "evidence": "Fix the login redirect", "began": 1000},
            previous={"word": "needs you", "word_since": 1000})
        self.assertEqual((found["reason"], found["unsent"]),
                         (f"claude worker token expired: {REPLACE}", "Fix the login redirect"))
        self.assertEqual(found["since"], 2000)

    # --- the rest of the contract --------------------------------------------

    def test_within_a_logins_window_the_owner_is_paged_once_a_day(self):
        # nearer than the line under the usage alone says; a dead one is every seat's word.  The
        # verb's days are whole, so 84 hours out reads `3 days` and is still outside the window
        pages, now = [], 400 * 86400 + 12 * 3600   # noon UTC: a minute on is the same day anywhere
        with patch.object(watch.notify, "page", lambda *page: pages.append(page)):
            for hours, at in ((96, now), (84, now), (72, now), (72, now + 60),
                              (48, now + 86400), (-1, now)):
                record = {"harness": "claude", "remedy": REPLACE, "expired": hours < 0,
                          "days": None if hours < 0 else hours // 24,
                          "mtime": at + hours * 3600 - watch.TOKEN_LIFE_DAYS * 86400}
                watch.remind_worker_tokens({"claude": record}, now=at)
        self.assertEqual([text for _, _, text in pages],
                         [f"claude worker token expires in {days} days: {REPLACE}"
                          for days in (3, 3, 2)])
        # one key a day: the outbox sends a key once, however often it is asked
        keys = [key for key, _, _ in pages]
        self.assertEqual(keys[0], keys[1])
        self.assertNotEqual(keys[1], keys[2])

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

if __name__ == "__main__":
    unittest.main(verbosity=2)
