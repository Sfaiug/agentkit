"""`ak notify needs --dry-run` prints the page it would send and its terminal notice, no more.

A person or a model trying the command, or ak's own wording, sees exactly what the owner would
be paged with: the page's JSON on stdout, its word and the seat and, when an owner id is set,
the mention that is the only one it may ping, never the question; and the terminal notice, which
alone carries the question, on stderr.  Nothing is posted, kept or queued, so a dry run never
opens a card or an episode that a real ask would then find already out.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, beside the record of
a seat of tests/fixtures/akseat.py, with tests/fixtures/sink.py ready to catch any page.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.sink import Sink


def page(seat, owner=None):
    """The page as a webhook would be sent it."""
    return {"username": "agentkit",
            "content": f"🙋 Needs you · {seat}" + (f" <@{owner}>" if owner else ""),
            "allowed_mentions": {"users": [owner]} if owner else {"parse": []}}


class DryRun(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.sink = Sink(self.home)
        self.addCleanup(self.sink.close)

    def kept(self):
        """Every file under ak's own directory, with what it holds."""
        root = self.home.path / ".agentkit"
        return {str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*") if path.is_file()}

    def dry_run(self, question, *args, env=None):
        done = self.home.ak("notify", "needs", question, *args, "--dry-run", env=env)
        self.assertEqual(done.code, 0, done.err)
        return json.loads(done.out), done.err.splitlines()

    def test_it_prints_the_page_and_the_terminal_notice_and_keeps_nothing(self):
        Seat(self.home, "fix-api", alive=False)
        before = self.kept()
        shown, said = self.dry_run("Which branch?", "--session", "fix-api")
        self.assertEqual(shown, page("fix-api"))
        self.assertEqual(said, ["terminal notice: Needs you · fix-api: Which branch?"])
        self.assertEqual(self.kept(), before)
        self.assertEqual(self.sink.requests, [])

    def test_the_page_mentions_the_owner_only_when_an_id_is_set(self):
        Seat(self.home, "acme-api", alive=False)
        ask = ("Which schema?", "--session", "acme-api")
        self.assertEqual(self.dry_run(*ask)[0], page("acme-api"))
        self.home.write(".agentkit/secrets/discord_user_id", "42\n")
        self.assertEqual(self.dry_run(*ask)[0], page("acme-api", "42"))
        # the environment's id outranks the secrets file's
        self.assertEqual(self.dry_run(*ask, env={"AGENTKIT_DISCORD_USER_ID": "77"})[0],
                         page("acme-api", "77"))
        self.assertEqual(self.sink.requests, [])

    def test_outside_a_seat_the_page_names_agentkit(self):
        before = self.kept()
        shown, said = self.dry_run("Which branch?")
        self.assertEqual(shown, page("agentkit"))
        self.assertEqual(said, ["terminal notice: Needs you · agentkit: Which branch?"])
        self.assertEqual(self.kept(), before)
        self.assertEqual(self.sink.requests, [])


if __name__ == "__main__":
    unittest.main()
