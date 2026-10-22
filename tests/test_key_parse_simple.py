"""A simple verb refuses an argument it does not take: exit 2, its usage line, nothing done.

A model that guesses a flag or adds a stray word learns the command's shape from the refusal
alone, so the refusal must name the verb's usage, and it must come before the verb starts what
it is for: an upgrade, a tick, a probe of every provider, a wait, the menu.  Each case here
exits 2, prints nothing on stdout and that one line on stderr, calls no host tool, starts no
tmux server and writes nothing under HOME.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, REFUSE, REFUSED, Home

MENU = ("ak attach: usage: ak [--client] [--overlay] [--dry-run]   "
        "(the menu; `ak attach` is the same)")
FETCH = "ak fetch: usage: ak fetch PATH [PATH ...] | ak fetch --serve"
WAIT = "ak wait: usage: ak wait PR_URL|RUN_ID"
# git is no refused host tool, but an upgrade or a tick reaches for it first.
TOOLS = (*REFUSED, "git")


class SimpleVerbsRefuseBadArguments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.fake("git", REFUSE.format(python=shlex.quote(sys.executable), name="git",
                                           log=shlex.quote(str(cls.home.log("git")))))

    def tree(self):
        return {str(path.relative_to(self.home.path)): (path.stat().st_mtime_ns,
                                                        path.stat().st_size)
                for path in self.home.path.rglob("*")}

    def refused(self, *args):
        """Run `ak ARGS`, check it refused and did nothing, and return its stderr."""
        before = self.tree()
        done = self.home.ak(*args, timeout=60)
        self.assertEqual(done.code, 2, f"ak {shlex.join(args)}: {done.out}{done.err}")
        self.assertEqual(done.out, "")
        self.assertEqual(self.tree(), before, "a refusal wrote under HOME")
        for tool in TOOLS:
            self.assertEqual(self.home.calls(tool), [], f"a refusal called {tool}")
        if REAL_TMUX:
            self.assertNotEqual(self.home.tmux("list-sessions").code, 0,
                                "a refusal started ak's tmux server")
        return done.err

    def assert_refusals(self, cases):
        for args, line in cases.items():
            with self.subTest(args=shlex.join(args)):
                self.assertEqual(self.refused(*args), line + "\n")

    def test_a_flag_verb_names_the_argument_it_does_not_take(self):
        usage = "ak usage: usage: ak usage [--json]"
        update = "ak update: usage: ak update [--dry-run]"
        watch = "ak watch: usage: ak watch [--dry-run]"
        self.assert_refusals({
            ("usage", "--bogus"): f"{usage}  (got '--bogus')",
            ("usage", "extra"): f"{usage}  (got 'extra')",
            ("usage", "--json", "--bogus"): f"{usage}  (got '--bogus')",
            ("update", "--bogus"): f"{update}  (got '--bogus')",
            ("update", "x", "--dry-run"): f"{update}  (got 'x')",
            ("update", "--dry-run", "--dry-run"): f"{update}  (got '--dry-run')",
            ("watch", "--bogus"): f"{watch}  (got '--bogus')",
            ("watch", "x"): f"{watch}  (got 'x')",
            ("watch", "--dry-run", "--dry-run"): f"{watch}  (got '--dry-run')",
            ("doctor", "x"): "ak doctor: usage: ak doctor  (got 'x')",
            ("doctor", "--bogus"): "ak doctor: usage: ak doctor  (got '--bogus')",
        })

    def test_models_names_every_argument_it_was_given(self):
        models = "ak models: usage: ak models [--json] [--refresh]"
        self.assert_refusals({
            ("models", "--bogus"): f"{models}  (got ['--bogus'])",
            ("models", "--json", "x"): f"{models}  (got ['--json', 'x'])",
        })

    def test_fetch_and_wait_answer_a_wrong_shape_with_their_usage_alone(self):
        self.assert_refusals({
            ("fetch",): FETCH,
            ("fetch", "--"): FETCH,
            ("fetch", "--serve", "extra"): FETCH,
            ("fetch", "a", "--serve"): FETCH,
            ("wait",): WAIT,
            ("wait", "a", "b"): WAIT,
            ("wait", "--bogus"): WAIT,
        })

    def test_the_menu_refuses_an_unknown_word_as_attach_however_it_was_called(self):
        self.assert_refusals({
            ("attach", "--bogus"): f"{MENU}  (got '--bogus')",
            ("attach", "x"): f"{MENU}  (got 'x')",
            ("attach", "--dry-run", "--bogus"): f"{MENU}  (got '--bogus')",
            ("--bogus",): f"{MENU}  (got '--bogus')",
            ("--dry-run", "x"): f"{MENU}  (got 'x')",
        })

    def test_a_stray_word_after_dry_run_still_gets_the_usage_line(self):
        # What the parenthesis names here is left out: it names `--dry-run`, not the word.
        for verb in ("update", "watch"):
            with self.subTest(verb=verb):
                err = self.refused(verb, "--dry-run", "x")
                self.assertTrue(err.startswith(f"ak {verb}: usage: ak {verb} [--dry-run]  "),
                                err)
                self.assertEqual(err.count("\n"), 1, err)

    @unittest.skipIf(sys.platform == "darwin", "the bridge runs on macOS")
    def test_off_macos_macbridge_refuses_whatever_it_is_given_and_points_to_fetch(self):
        line = "ak macbridge: ak macbridge runs on macOS; use ak fetch on this host"
        self.assert_refusals({("macbridge",): line, ("macbridge", "--bogus"): line,
                              ("macbridge", "--reader"): line})


if __name__ == "__main__":
    unittest.main()
