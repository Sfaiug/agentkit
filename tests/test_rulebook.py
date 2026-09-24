"""The orchestrator rulebook reaches agentkit's own sessions and nothing else.

Offline: the real adapters and the real install.sh block, run against a sandbox HOME with a
fake `codex` on PATH; no harness, no network, and nothing outside that HOME is touched.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, run, worker

RULEBOOK = (REPO / "orchestrator.md").read_text()
MINIMUM = "Minimum change that solves the task completely; the best part is no part."
# The owner's own words, and the standing rules each in the section of the rulebook it belongs to.
PHRASES = ("the best part is no part", "Less is more", "brutal elimination", "the least possible steps")
RULES = (("Understand first", "unknown knowns, "),
         ("Understand first", "show options or a small prototype and let them react"),
         ("Decide and delegate", "Three rounds is the budget: a task never sets `rounds`."),
         ("Decide and delegate", "only when a default is wrong (`repo`, `from`, `after`)"),
         ("Decide and delegate", "never `done_when_minutes`"),
         ("Decide and delegate", "Runs already going are never stopped for a process change"),
         ("Decide and delegate", "`ak run stop <id> --keep` and a relaunch with `from: <branch>`, "
                                 "never steering"))
# The config this sandbox HOME answers with, so that what the owner has configured -- which
# models exist, which adapters are theirs -- decides nothing here and cannot fail the gate.
CONFIG = """[tiers]
A = ["fixture"]
B = ["fixture"]

[models.fixture]
harness = "claude"
model = "test-model"
effort = "high"
provider = "anthropic"

[providers.anthropic]
mode = "subscription"
"""


class Rulebook(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".rulebook-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / ".claude").mkdir()
        (self.home / ".codex").mkdir()
        self.state = self.home / ".agentkit/state"
        self.state.mkdir(parents=True)
        (self.home / ".agentkit/config.toml").write_text(CONFIG)
        # This HOME is the whole host, for what runs in this process as much as for what it
        # starts.  config.HOME was bound to the owner's at import, so $HOME -- all a subprocess
        # needs -- would leave every call made here reading the owner's config and the owner's
        # adapters, and a host configuring no model this test names would fail the gate.
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(config, "HOME", self.home / ".agentkit"))
        stack.enter_context(patch.object(config, "STATE", self.state))
        stack.enter_context(patch.dict(os.environ, {"HOME": str(self.home)}))
        os.environ.pop(config.ADAPTER_DIR_ENV, None)   # the checkout's adapters, never a copy

    def adapter(self, harness, *args, seat=""):
        """One `interactive` line, as `ak orch` asks for it: the seat's name in the env."""
        proc = subprocess.run([str(REPO / f"adapters/{harness}.sh"), "interactive", *args],
                              capture_output=True, text=True,
                              env={**os.environ, "HOME": str(self.home), "AGENTKIT_SESSION": seat})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return shlex.split(proc.stdout)

    def named(self, words, flag):
        """The value the command line gives that flag, asserted to be this HOME's rulebook."""
        self.assertIn(flag, words, words)
        path = Path(words[words.index(flag) + 1])
        self.assertEqual(path.parent, self.state, path)
        self.assertTrue(path.is_file(), path)
        return path

    # --- one per harness: the mechanism, and the file under ~/.agentkit/state -----

    def test_claude_is_launched_with_the_rulebook_as_a_system_prompt_file(self):
        words = self.adapter("claude", "claude-opus-5", "high",
                             "00000000-0000-0000-0000-000000000000", "new", seat="atoll")
        path = self.named(words, "--append-system-prompt-file")
        self.assertEqual(path.name, "rulebook-atoll.md")
        self.assertEqual(path.read_text(), RULEBOOK)

    def test_codex_is_launched_with_the_rulebook_as_its_own_developer_instructions(self):
        words = self.adapter("codex", "default", "xhigh", seat="atoll")
        path = self.named(words, "--rulebook")
        # the seat wrapper is where the rulebook becomes Codex's own per-launch config value
        wrapper = next(i for i, w in enumerate(words) if w.endswith("tools/codex-seat.py"))
        fake = self.home / "bin"
        fake.mkdir()
        (fake / "codex").write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        (fake / "codex").chmod(0o755)
        proc = subprocess.run(words[wrapper - 1:], capture_output=True, text=True,
                              env={**os.environ, "HOME": str(self.home),
                                   "PATH": f"{fake}:{os.environ['PATH']}"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(f"developer_instructions={RULEBOOK}", proc.stdout)
        self.assertEqual(path.read_text(), RULEBOOK)

    def test_muse_is_launched_with_the_rulebook_named_in_its_environment(self):
        words = self.adapter("muse", "muse-spark-1.3-contributor", "xhigh", seat="atoll")
        pin = next(w for w in words if w.startswith("TBH_EVAL_APPEND_SYSTEM_PROMPT_FILE="))
        path = Path(pin.split("=", 1)[1])
        self.assertEqual(path.parent, self.state, path)
        self.assertEqual(path.read_text(), RULEBOOK)
        # in the environment `muse` is launched with, never in the command muse itself parses
        self.assertEqual(words[words.index(pin) + 1], "muse")
        self.assertIn("env", words[:words.index(pin)])

    # --- what the file says, and whose session it is for -------------------------

    def test_this_host_s_own_rules_ride_along_after_the_repo_s(self):
        words = self.adapter("claude", "claude-opus-5", "high", seat="atoll")
        path = self.named(words, "--append-system-prompt-file")
        self.assertEqual(path.read_text(), RULEBOOK)
        (self.home / ".agentkit/rules.md").write_text("# This host\n\nThe printer is upstairs.\n")
        self.adapter("claude", "claude-opus-5", "high", seat="atoll")
        self.assertEqual(path.read_text(),
                         RULEBOOK.rstrip() + "\n\n# This host\n\nThe printer is upstairs.\n")

    def test_the_rulebook_is_written_for_the_seat_being_launched(self):
        # the launch is often made from another seat, whose name this process carries
        with patch.dict(os.environ, {"HOME": str(self.home), "AGENTKIT_SESSION": "somebody-else"}):
            words, _ = orch.fresh_command(config.load(), "fixture", seat="atoll")
            self.assertEqual(os.environ["AGENTKIT_SESSION"], "somebody-else")
        self.assertEqual(Path(words[words.index("--append-system-prompt-file") + 1]),
                         self.state / "rulebook-atoll.md")

    def test_the_executor_and_the_fixer_are_asked_for_the_minimum_change(self):
        self.assertIn(MINIMUM, worker.PREAMBLES["executor"])
        self.assertIn(MINIMUM, worker.PREAMBLES["fixer"])

    def test_every_executor_and_fixer_carries_the_owner_s_four_phrases(self):
        for role in ("executor", "fixer", "executor-scratch", "fixer-scratch"):
            for words in PHRASES:
                with self.subTest(role=role, words=words):
                    self.assertIn(words, worker.PREAMBLES[role])

    def test_the_rulebook_carries_every_standing_rule_and_stays_one_page(self):
        sections = dict(re.findall(r"^## (.+?)\n(.*?)(?=^## |\Z)", RULEBOOK, re.S | re.M))
        for heading, words in RULES:
            with self.subTest(words=words):
                self.assertIn(words, sections[heading])
        # 43 lines before these rules came in, and a page has room for twelve more at most
        self.assertLessEqual(len(RULEBOOK.splitlines()), 55)

    # --- and the user's own harness files are theirs again -----------------------

    def test_install_unlinks_its_old_doctrine_symlink_and_puts_the_backup_back(self):
        self.assertNotIn("ln -sfn", self.cleanup_block())
        claude = self.home / ".claude/CLAUDE.md"
        claude.symlink_to(REPO / "AGENTS.md")
        (self.home / ".claude/CLAUDE.md.bak-20240101").write_text("older\n")
        (self.home / ".claude/CLAUDE.md.bak-20250601").write_text("the user's own memory\n")
        codex = self.home / ".codex/AGENTS.md"
        codex.write_text("a file nobody linked\n")            # not ours: never touched
        proc = subprocess.run(["bash", "-c", self.cleanup_block()], capture_output=True, text=True,
                              env={**os.environ, "HOME": str(self.home)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(claude.is_symlink(), proc.stdout)
        self.assertEqual(claude.read_text(), "the user's own memory\n")
        self.assertEqual(codex.read_text(), "a file nobody linked\n")
        self.assertFalse(codex.is_symlink())

    def test_install_cleanup_needs_no_backup_and_follows_a_relative_link(self):
        # An old install left no backup where the user had no file of their own, and the link it
        # wrote may be relative: neither may end the install with the second target untouched.
        claude = self.home / ".claude/CLAUDE.md"
        claude.symlink_to(REPO / "AGENTS.md")
        codex = self.home / ".codex/AGENTS.md"
        codex.symlink_to(os.path.relpath(REPO / "AGENTS.md", codex.parent))
        proc = subprocess.run(["bash", "-c", self.cleanup_block()], capture_output=True, text=True,
                              env={**os.environ, "HOME": str(self.home)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(claude.exists() or claude.is_symlink(), proc.stdout)
        self.assertFalse(codex.exists() or codex.is_symlink(), proc.stdout)

    def cleanup_block(self):
        """Section (4) of install.sh, under the flags the installer itself runs it with."""
        source = (REPO / "install.sh").read_text()
        start = source.index("# --- (4) ")
        block = source[start:source.index("\n# --- ", start + 1)]
        self.assertNotIn("AGENTS.md", block.split("\n# ")[0])   # nothing links it any more
        return f"set -euo pipefail\nREPO={shlex.quote(str(REPO))}\n{block}"

    # --- and no session is opened missing the rules it was launched with ---------

    def test_a_rulebook_that_cannot_be_written_stops_the_launch(self):
        blocked = self.home / "blocked"                  # ~/.agentkit/state cannot be made here
        (blocked / ".claude").mkdir(parents=True)
        (blocked / ".agentkit").write_text("not a directory\n")
        for harness, args in (("claude", ("claude-opus-5", "high")),
                              ("codex", ("default", "xhigh")),
                              ("muse", ("muse-spark-1.3-contributor", "xhigh")),
                              ("opencode", ("mimo/mimo-v2.6-pro", "high"))):
            proc = subprocess.run([str(REPO / f"adapters/{harness}.sh"), "interactive", *args],
                                  capture_output=True, text=True,
                                  env={**os.environ, "HOME": str(blocked), "AGENTKIT_SESSION": "atoll"})
            self.assertNotEqual(proc.returncode, 0, harness)
            self.assertEqual(proc.stdout.strip(), "", harness)   # nothing for `ak orch` to launch
            self.assertIn("rulebook", proc.stderr, harness)

    def test_no_child_of_a_seat_inherits_the_rulebook_its_harness_was_given(self):
        # Muse and OpenCode take their rules from the environment, and a seat's environment
        # is inherited by everything it starts -- its workers of every harness, its done-when
        # commands, and whatever those start in turn.  Each manifest names its variable; the
        # core drops all of them.
        names = config.seat_env_names()
        self.assertIn("TBH_EVAL_APPEND_SYSTEM_PROMPT_FILE", names)
        self.assertIn("OPENCODE_CONFIG_CONTENT", names)
        with patch.dict(os.environ, {"TBH_EVAL_APPEND_SYSTEM_PROMPT_FILE": str(self.state / "r.md"),
                                     "OPENCODE_CONFIG_CONTENT": "{}",
                                     "AGENTKIT_SESSION": "atoll"}):
            self.assertIn("TBH_EVAL_APPEND_SYSTEM_PROMPT_FILE", os.environ)   # the seat has them
            self.assertIn("OPENCODE_CONFIG_CONTENT", os.environ)
            for built in (config.child_env(), config.seatless_env(), run.run_child_env()):
                self.assertNotIn("TBH_EVAL_APPEND_SYSTEM_PROMPT_FILE", built)
                self.assertNotIn("OPENCODE_CONFIG_CONTENT", built)

    def test_a_muse_worker_does_not_inherit_the_seat_s_rulebook(self):
        # And the adapter drops an inherited one itself, for the calls that do not come through
        # an environment agentkit built: `ak usage` from a seat's own shell, say.
        fake = self.home / "bin"
        fake.mkdir()
        (fake / "muse").write_text('#!/bin/sh\nprintf "%s\\n" "${TBH_EVAL_APPEND_SYSTEM_PROMPT_FILE-<unset>}"'
                                   ' >>"$MUSE_SEEN"\nprintf \'{"payload":{"kind":"run_terminal","text":"x"}}\\n\'\n')
        (fake / "muse").chmod(0o755)
        (self.home / "prompt.md").write_text("You are the executor.\n")
        seen = self.home / "seen"
        subprocess.run([str(REPO / "adapters/muse.sh"), "run", "muse-spark", "xhigh",
                        str(self.home), str(self.home / "prompt.md"), str(self.home / "out")],
                       capture_output=True, text=True,
                       env={**os.environ, "HOME": str(self.home), "MUSE_SEEN": str(seen),
                            "PATH": f"{fake}:{os.environ['PATH']}",
                            "AGENTKIT_MUSE_PROVIDER": "echo",
                            "TBH_EVAL_APPEND_SYSTEM_PROMPT_FILE": str(self.state / "rulebook-atoll.md")})
        self.assertEqual(seen.read_text().strip(), "<unset>")


if __name__ == "__main__":
    unittest.main(verbosity=2)
