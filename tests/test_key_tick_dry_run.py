"""`ak watch --dry-run` says what a tick would do and does none of it: it writes nothing at all.

A person or a model runs the dry tick to see what the next real one will do to the seats, the
owner's pages and other people's pull requests, on the live host, while the real tick runs
from cron beside it.  So it reads and reports, and leaves every file under HOME as it was, to
the byte and the modification time, every seat's tmux session as it was with nothing typed
into it, the webhook unpaged and GitHub unchanged.  The HOME here holds what a real tick acts
on: a seat at its prompt with a question asked 5 minutes ago and no card for it yet, a page to
another seat whose retry is due, and an open pull request by somebody else on a repository this
account owns, which a real tick would review.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, beside seats of akseat.py, the webhook of sink.py and
the GitHub of fakegh.py.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from fixtures.sink import Sink

SEATS = ("acme", "beta")
QUESTION = "Which branch should the fix land on?"
# what a call that changes GitHub starts with
WRITES = {("pr", verb) for verb in ("create", "merge", "comment", "review", "edit", "close",
                                    "ready", "reopen")} | {("repo", "fork"), ("issue", "create")}


def files(root):
    """Every directory under `root`, and every file with what it holds and when it changed."""
    return {str(path.relative_to(root)):
            (path.read_bytes(), path.stat().st_mtime_ns) if path.is_file() else None
            for path in root.rglob("*")}


def writes_github(call):
    if tuple(call[:2]) in WRITES:
        return True
    if call[:1] != ["api"]:
        return False
    method = next((call[i + 1] for i, arg in enumerate(call[:-1]) if arg in ("-X", "--method")),
                  "GET")
    return method.upper() != "GET" or any("mutation" in arg for arg in call)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class DryRunTick(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        cls.sink = Sink(home)
        cls.addClassCleanup(cls.sink.close)
        rig = Rig(home, "widgets")
        cls.github = GitHub(home)
        rig.branch("fix-api", {"api.py": "x = 2\n"})
        cls.url = cls.github.open_pr(rig, "fix-api", title="Fix api", author="beta")
        cls.seats = [Seat(home, name) for name in SEATS]
        asked = time.time() - 300
        home.write(".agentkit/state/notify-acme.json", {
            "session": "acme", "kind": "needs", "text": QUESTION, "time": asked,
            "source": None, "watcher": False, "asked_at": {QUESTION.lower(): asked}}, ago=300)
        # beta's page met an outage and waits in the outbox; its retry fell due a minute ago
        cls.sink.script(500)
        done = home.ak("notify", "needs", "Which schema?", "--session", "beta")
        assert done.code == 0, done.err
        cls.sink.wait(1)
        outbox = home.path / ".agentkit/state/notification-outbox"
        event, = outbox.glob("*.json")
        cls.event = {**json.loads(event.read_text()), "next_attempt": time.time() - 60}
        cls.page = home.write(str(event.relative_to(home.path)), cls.event, ago=60)
        cls.before = files(home.path)
        cls.tmux_before = cls.tmux_state()
        cls.prs = cls.github.prs()
        cls.called = len(home.calls("gh"))
        cls.done = home.ak("watch", "--dry-run")

    @classmethod
    def tmux_state(cls):
        """The sessions on ak's server, and every option each seat and the server hold."""
        ask = cls.home.tmux
        return (ask("list-sessions", "-F", "#{session_name}").out,
                ask("show-options", "-g").out, ask("show-options", "-gw").out,
                *(ask("show-options", *scope, "-t", f"={name}:").out
                  for name in SEATS for scope in ((), ("-w",))))

    def test_the_dry_tick_exits_0_and_says_it_would_review_the_pull_request(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertIn(self.url, self.done.out)

    def test_no_file_under_home_is_added_removed_or_touched(self):
        after = files(self.home.path)
        self.assertEqual(sorted(set(after) ^ set(self.before)), [])
        self.assertEqual([path for path in after if after[path] != self.before[path]], [])
        self.assertFalse((self.home.path / ".agentkit/state/card-acme.json").exists())
        self.assertEqual(json.loads(self.page.read_text()), self.event)

    def test_no_seat_is_typed_into_or_restyled_and_no_session_is_opened(self):
        self.assertEqual(self.tmux_state(), self.tmux_before)
        for seat in self.seats:
            with self.subTest(seat.name):
                self.assertEqual(seat.typed(), "")

    def test_the_webhook_hears_nothing_and_github_is_left_as_it_was(self):
        self.assertEqual(len(self.sink.requests), 1)    # beta's own page, before the tick
        self.assertEqual(self.github.prs(), self.prs)
        calls = self.home.calls("gh")[self.called:]
        self.assertEqual([call for call in calls if writes_github(call)], [])


if __name__ == "__main__":
    unittest.main()
