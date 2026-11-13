"""`ak orch`, `ak notify` and `ak plan` refuse arguments they cannot read, and do nothing.

A model learns these verbs by calling them, and often calls them wrongly: a flag without its
value, one name too many or too few, the removed `done` kind or `--file` flag, a question with
no seat to ask it for.  Each such call exits 2 before it touches anything -- no seat opened or
typed into, no question kept, no card made, no page sent -- and says on stderr, in the words
below, the verb's usage or the one thing missing, because the model reads that line and calls
again.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
beside a live seat of tests/fixtures/akseat.py, with its pages pointed at tests/fixtures/sink.py,
and this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.sink import Sink

NOTIFY_USAGE = ('ak notify: usage: ak notify needs "QUESTION" [--session NAME] [--dry-run]\n'
                "       ak notify --check\n")
PLAN_USAGE = ("ak plan: usage: ak plan | ak plan add \"OUTCOME\" --check 'COMMAND' | "
              "ak plan check N 'COMMAND'\n")
NO_SEAT = "ak notify: notify needs a session: use --session NAME\n"
INSIDE = {"AGENTKIT_SESSION": "fix-api"}
QUESTION = "Which branch?"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Refusals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.sink = Sink(cls.home)
        cls.addClassCleanup(cls.sink.close)
        cls.seat = Seat(cls.home, "fix-api")

    def standing(self):
        """Every file under HOME, every session tmux holds, what the seat was typed and every
        page the sink took."""
        files = {str(path.relative_to(self.home.path)): path.read_bytes()
                 for path in self.home.path.rglob("*") if path.is_file()}
        held = self.home.tmux("list-sessions", "-F", "#{session_name}").out.split()
        return files, held, self.seat.typed(), self.sink.requests

    def refused(self, cases, env=None):
        """Each argv exits 2 with exactly its line on stderr, nothing on stdout, and leaves
        everything as it was."""
        for args, error in cases:
            with self.subTest(args=args, env=env):
                before = self.standing()
                done = self.home.ak(*args, env=env)
                self.assertEqual((done.code, done.out), (2, ""), done.err)
                if callable(error):
                    error(done.err)
                else:
                    self.assertEqual(done.err, error)
                self.assertEqual(self.standing(), before)

    def test_orch_wants_each_flag_s_value_and_each_verb_s_count_of_names(self):
        def stray(word):
            def check(err):
                self.assertTrue(err.startswith("ak orch: usage: ak orch [name] "), err)
                self.assertTrue(err.endswith(f"  (got {word!r})\n"), err)
            return check
        lists = "ak orch: usage: ak orch list [--why]\n"
        why = "ak orch: usage: ak orch why NAME\n"
        stop = "ak orch: usage: ak orch stop <name>\n"
        rename = "ak orch: usage: ak orch rename [--auto] [OLD] NEW\n"
        self.refused([
            (("orch", "--model"), "ak orch: --model needs a model name\n"),
            (("orch", "--workers"),
             "ak orch: --workers needs a comma-separated list of model names\n"),
            (("orch", "acme", "beta"), stray("beta")),
            (("orch", "--bogus"), stray("--bogus")),
            (("orch", "list", "extra"), lists), (("orch", "list", "--why", "--why"), lists),
            (("orch", "why"), why), (("orch", "why", "fix-api", "beta"), why),
            (("orch", "stop"), stop), (("orch", "stop", "fix-api", "beta"), stop),
            (("orch", "rename"), rename), (("orch", "rename", "--auto"), rename),
        ])

    def test_notify_reads_only_needs_and_one_question_and_shows_its_usage_otherwise(self):
        # `done` was a kind once: a seat that still says it is told the one call there is
        cases = [(args, NOTIFY_USAGE) for args in (
            ("notify",), ("notify", "bogus"), ("notify", "done", "Summary"),
            ("notify", "--check", "extra"), ("notify", "--dry-run"),
            ("notify", "needs"), ("notify", "needs", "  "), ("notify", "needs", "-x"),
            ("notify", "needs", "Which branch?", "Or main?"),
            ("notify", "needs", QUESTION, "--bogus"))]
        self.refused(cases)
        self.refused(cases, env=INSIDE)

    def test_notify_needs_names_the_missing_seat_the_session_s_name_or_the_removed_file(self):
        removed = "ak notify: --file was removed: notification cards carry no attachments\n"
        self.refused([
            (("notify", "needs", QUESTION), NO_SEAT),
            (("notify", "needs", QUESTION, "--session"),
             "ak notify: --session needs a session name\n"),
            # wherever it stands, even with the seat named after it or only a dry run asked
            (("notify", "needs", QUESTION, "--session", "fix-api", "--file", "a.png"), removed),
            (("notify", "needs", QUESTION, "--file", "a.png", "--session", "fix-api"), removed),
            (("notify", "needs", QUESTION, "--dry-run", "--file", "a.png"), removed),
        ])
        # an empty seat variable is no seat either
        self.refused([(("notify", "needs", QUESTION), NO_SEAT)], env={"AGENTKIT_SESSION": ""})

    def test_plan_outside_a_seat_is_refused_before_its_arguments_are_read(self):
        outside = "ak plan: ak plan belongs to a session; run it inside one\n"
        self.refused([(args, outside) for args in (
            ("plan", "unexpected"), ("plan", "add", "x"), ("plan", "check", "x", "true"))])

    def test_plan_in_a_seat_wants_a_check_for_each_line_and_a_line_number_for_each_check(self):
        self.refused([(args, PLAN_USAGE) for args in (
            ("plan", "unexpected"), ("plan", "add", "the parser works"),
            ("plan", "add", "the parser works", "--check"),
            ("plan", "add", "the parser works", "--chek", "true"),
            ("plan", "add", "the parser works", "--check", "true", "extra"),
            ("plan", "check", "x", "true"), ("plan", "check", "1"),
            ("plan", "check", "-1", "true"))], env=INSIDE)


if __name__ == "__main__":
    unittest.main()
