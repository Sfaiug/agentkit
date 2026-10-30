"""Every help entry has one shape, and a nested entry is chosen by the word right after the verb.

Each of the 39 entries (the 16 verbs and the sub-verbs of hand-in, run, orch, notify and
browser) prints its purpose, a blank line, its usage, any more it has to say, and an `Example:`
of its own form last, each block once and apart, for `-h` and `--help` alike.  A model reads
the usage to learn which flags exist, so the flags each command takes are pinned, and the lines
the spec quotes are pinned exactly.  `ak run status -h` is the status entry, but a sub-verb's name
anywhere else, or a word that names none, gets the verb's own entry.  Printing any entry runs
nothing and writes nothing: `ak update -h` upgrades nothing and `ak models -h` asks no board.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, and
this test fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REFUSED, Home

NESTED = {"hand-in": ("finding", "follow-up", "dispute", "done", "blocked", "not-needed"),
          "run": ("status", "resume", "merge", "stop", "clean", "gc"),
          "orch": ("rules", "list", "why", "stop", "rename", "project"),
          "notify": ("needs",),
          "browser": ("status", "login", "mcp-register", "install")}
VERBS = ("models", "usage", "worker", "hand-in", "run", "orch", "notify", "wait", "plan",
         "update", "watch", "browser", "doctor", "attach", "fetch", "macbridge")
ENTRIES = tuple(entry for verb in VERBS
                for entry in (verb, *(f"{verb} {sub}" for sub in NESTED.get(verb, ()))))
PUBLIC = ("run", "plan", "notify", "wait", "usage", "models", "browser", "fetch")
INTERNAL_PURPOSE = {
    "orch": "open a seat",
    "worker": "run one headless model turn from a task or prompt file",
    "hand-in": "hand in review evidence or close a worker turn",
    "watch": "check PRs and stalled sessions",
    "update": "upgrade harnesses and verify with acceptance gates",
    "macbridge": "macOS only: forward requested files to the server over SSH",
    "attach": "the menu",
    "doctor": "show the slice, the tick, the machines, and any model set to an effort it does not take",
}
FLAGS = {
    "usage": ("[--json]",),
    "models": ("[--json]", "[--refresh]"),
    "worker": ("--workspace", "--out", "--session", "--role"),
    "run": ("--rounds", "--exec", "--review", "--anyway", "--first", "--no-worktree",
            "--no-merge", "--bg", "--parallel", "--review-pr", "--history", "--why", "--plain",
            "--json", "--dry-run", "--keep"),
}
USAGE = {
    "browser": "usage: ak browser <status|login|mcp-register|install>",
    "fetch": "usage: ak fetch PATH [PATH ...] | ak fetch --serve",
    "macbridge": "usage: ak macbridge [--reader]",
    "attach": "usage: ak attach [--client] [--overlay] [--dry-run]",
    "doctor": "usage: ak doctor",
    "run status": "usage: ak run status [ID] [--history] [--why] [--plain] [--json]",
    "orch rules": "usage: ak orch rules CODE",
    "hand-in done": "usage: ak hand-in done",
    "notify needs": 'usage: ak notify needs "QUESTION" [--session NAME] [--dry-run]',
}


def blocks(out):
    """The help's blocks, as the blank lines between them part them."""
    return out.removesuffix("\n").split("\n\n")


class Entries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        before = cls.home.tree()
        cls.helped = {entry: [cls.home.ak(*entry.split(), flag) for flag in ("--help", "-h")]
                      for entry in ENTRIES}
        cls.written = before != cls.home.tree()
        cls.listing = cls.home.ak("--help").out

    def help(self, entry):
        return self.helped[entry][0].out

    def test_every_entry_prints_the_same_help_for_both_flags_on_stdout_alone(self):
        self.assertEqual(len(ENTRIES), 39)
        for entry, (long, short) in self.helped.items():
            with self.subTest(entry):
                self.assertEqual((long.code, long.err), (0, ""))
                self.assertEqual((short.code, short.err), (0, ""))
                self.assertEqual(short.out, long.out)

    def test_every_entry_is_purpose_usage_then_its_own_example_each_a_block_apart(self):
        for entry in ENTRIES:
            with self.subTest(entry):
                out = self.help(entry)
                self.assertTrue(out.endswith("\n") and not out.endswith("\n\n"), repr(out[-20:]))
                parts = blocks(out)
                self.assertIn(len(parts), (3, 4), out)
                self.assertNotIn("\n\n\n", out)
                purpose, usage, example = parts[0], parts[1].split("\n"), parts[-1]
                self.assertNotIn("\n", purpose)
                self.assertRegex(usage[0], rf"^usage: ak {re.escape(entry)}( |$)")
                for more in usage[1:]:
                    self.assertRegex(more, r"^ +\S")    # the usage goes on, indented
                self.assertRegex(example, rf"^Example: ak {re.escape(entry)}( |$)")
                self.assertNotIn("\n", example)

    def test_a_usage_names_only_its_own_verb(self):
        for entry in ENTRIES:
            with self.subTest(entry):
                usage = blocks(self.help(entry))[1]
                verbs = re.findall(r"(?<![\w-])ak ([\w-]+)", usage)
                self.assertEqual(set(verbs), {entry.split()[0]}, usage)

    def test_a_verb_opens_with_the_purpose_the_listing_gives_it(self):
        rows = dict(line.split(None, 1) for line in self.listing.splitlines()
                    if line.startswith("  "))
        for verb in VERBS:
            with self.subTest(verb):
                want = rows[verb] if verb in PUBLIC else INTERNAL_PURPOSE[verb]
                self.assertEqual(self.help(verb).split("\n")[0], want)
        self.assertEqual(rows["ak"], INTERNAL_PURPOSE["attach"])   # attach is the menu

    def test_the_purpose_is_never_said_twice(self):
        def sentence(line):
            return line.strip().rstrip(".").lower()
        for entry in ENTRIES:
            with self.subTest(entry):
                purpose, *rest = self.help(entry).split("\n")
                self.assertNotIn(sentence(purpose), [sentence(line) for line in rest])

    def test_a_usage_carries_the_flags_its_command_takes(self):
        for entry, flags in FLAGS.items():
            usage = blocks(self.help(entry))[1]
            for flag in flags:
                with self.subTest(entry=entry, flag=flag):
                    self.assertRegex(usage, rf"(?<![\w-]){re.escape(flag)}(?![\w-])")
        for entry, line in USAGE.items():
            with self.subTest(entry):
                self.assertEqual(blocks(self.help(entry))[1], line)

    def test_printing_help_writes_nothing_and_calls_nothing(self):
        self.assertFalse(self.written)
        self.assertEqual({name: self.home.calls(name) for name in REFUSED
                          if self.home.calls(name)}, {})
        self.assertNotEqual(self.home.tmux("list-sessions").code, 0)

    def test_a_sub_verb_right_after_its_verb_gets_its_own_entry_whatever_follows(self):
        for args, entry in ((("run", "status", "MISSING", "--help"), "run status"),
                            (("orch", "list", "acme", "-h"), "orch list")):
            with self.subTest(args=args):
                done = self.home.ak(*args)
                self.assertEqual((done.code, done.err, done.out), (0, "", self.help(entry)))

    def test_any_other_word_or_place_gets_the_verbs_own_entry(self):
        for args in (("run", "bogus", "-h"), ("run", "--rounds", "9", "status", "-h"),
                     ("run", "-h", "status"), ("browser", "bogus", "--help")):
            with self.subTest(args=args):
                done = self.home.ak(*args)
                self.assertEqual((done.code, done.err, done.out), (0, "", self.help(args[0])))


if __name__ == "__main__":
    unittest.main()
