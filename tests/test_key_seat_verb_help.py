"""Each verb a seat or worker types (`plan`, `notify`, `wait`, `hand-in`) has its own help, in
the one layout every command's help shares, and asking for it changes nothing.

A model learns these verbs from their help, typed inside a live seat or a worker's turn: the
help must print whole, to stdout, exit 0 and leave the seat's plan, questions and waits as they
were, even for `hand-in`, which refuses everything else outside a turn.  The layout is a
purpose line, the usage, the description and one example, each a block of its own.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, and
this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REFUSED, Home

WAIT = ("end this turn waiting on a pull request or run\n"
        "\n"
        "usage: ak wait PR_URL|RUN_ID\n"
        "\n"
        "End this turn waiting on that pull request or run; ak wakes you with one line\n"
        "when it merges, closes or ends. One already over is refused. Never a session.\n"
        "\n"
        "Example: ak wait https://github.com/acme/api/pull/12\n")
USAGE = {
    "plan": "usage: ak plan | ak plan add \"OUTCOME\" --check 'COMMAND' | "
            "ak plan check N 'COMMAND'",
    "notify": 'usage: ak notify needs "QUESTION" [--session NAME] [--dry-run]\n'
              "       ak notify --check",
    "hand-in": 'usage: ak hand-in finding PATH:LINE "WHAT" "WHY IT MATTERS" '
               "(--run COMMAND | --quote LINES)\n"
               '       ak hand-in follow-up PATH:LINE "WHAT" "WHY IT MATTERS" '
               "(--run COMMAND | --quote LINES) [--before PROOF]\n"
               '       ak hand-in dispute PATH:LINE "WHY IT IS WRONG" '
               "(--run COMMAND | --quote LINES)\n"
               "       ak hand-in done\n"
               '       ak hand-in blocked "WHY"\n'
               '       ak hand-in not-needed "WHY"',
    "wait": "usage: ak wait PR_URL|RUN_ID",
}
# Inside a seat, as a model there types them: the seat's name in the environment, its record
# in the state.
SEAT = {"AGENTKIT_SESSION": "acme"}


class SeatVerbHelp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.write(".agentkit/state/session-acme.json",
                       {"orchestrator": "opus", "workers": ["opus"],
                        "cwd": str(cls.home.path / "code" / "acme"), "created": 1})

    def helped(self, verb, flag):
        done = self.home.ak(verb, flag, env=SEAT)
        self.assertEqual(done.code, 0, f"ak {verb} {flag}: {done.err}")
        self.assertEqual(done.err, "", f"ak {verb} {flag}")
        return done.out

    def test_wait_help_is_exactly_its_purpose_usage_description_and_example(self):
        for flag in ("-h", "--help"):
            with self.subTest(flag):
                self.assertEqual(self.helped("wait", flag), WAIT)

    def test_each_verb_prints_purpose_usage_description_and_example_as_blocks(self):
        for verb, usage in USAGE.items():
            for flag in ("-h", "--help"):
                with self.subTest(verb=verb, flag=flag):
                    out = self.helped(verb, flag)
                    self.assertTrue(out.endswith("\n") and not out.endswith("\n\n"), out)
                    blocks = out[:-1].split("\n\n")
                    self.assertEqual(len(blocks), 4, out)
                    purpose, shown, description, example = blocks
                    self.assertNotIn("\n", purpose)
                    self.assertEqual(shown, usage)
                    self.assertTrue(description.strip(), out)
                    self.assertRegex(example, rf"^Example: ak {verb} \S[^\n]*$")

    def test_a_verb_opens_with_the_purpose_the_command_list_gives_it(self):
        listing = self.home.ak("--help").out.splitlines()
        for verb in ("plan", "notify", "wait"):
            with self.subTest(verb):
                purpose = self.helped(verb, "--help").splitlines()[0]
                listed = [line.split(None, 1)[1] for line in listing
                          if line.split(None, 1)[:1] == [verb]]
                self.assertEqual(listed, [purpose])

    def test_hand_in_help_prints_outside_a_turn_where_hand_in_itself_is_refused(self):
        refused = self.home.ak("hand-in", "done", env=SEAT)
        self.assertNotEqual(refused.code, 0, refused.out)
        out = self.helped("hand-in", "-h")
        self.assertEqual(out.split("\n\n")[0], "hand in review evidence or close a worker turn")
        self.assertTrue(out.split("\n\n")[1].startswith(
            "usage: ak hand-in finding PATH:LINE"), out)

    def test_asking_for_help_writes_nothing_under_home_and_calls_no_host_tool(self):
        before = snapshot(self.home.path)
        called = {tool: self.home.calls(tool) for tool in REFUSED}
        for verb in USAGE:
            for flag in ("-h", "--help"):
                with self.subTest(verb=verb, flag=flag):
                    self.helped(verb, flag)
                    self.assertEqual(snapshot(self.home.path), before)
        self.assertEqual({tool: self.home.calls(tool) for tool in REFUSED}, called)


def snapshot(root):
    """Every file under `root` with its bytes, and every directory, by relative path."""
    return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
            for path in sorted(root.rglob("*"))}


if __name__ == "__main__":
    unittest.main()
