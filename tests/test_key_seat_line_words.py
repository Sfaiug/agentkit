"""A seat's launch line hands Claude Code and Grok Build the same words, whichever tree prints it.

`ak orch` opens a seat on the line its harness's adapter prints for `interactive <model> <effort>
[<id> [new]]`, told the seat's name, the rulebook it wrote, the first prompt (empty when there is
none), the account where there is one, and what the harness's plugin checked before asking.  The
line opens with `env` words, then runs a wrapper of the tree's own, which ends in a `--` before
the harness: its conversation (resumed, or a new one opened under the given id), its rulebook,
model, effort and standing permissions, then the first prompt as one word, byte for byte.  Only
the env words and the harness's words are pinned here.  A seat on an account runs on that
account's login, which Grok's env words name; no rulebook to hand over prints no line.

Black-box: the adapters beside the program `AK_BIN` names (or `AK_ROOT`'s) print the line in a
throwaway HOME, split as `ak orch` splits it; this test fails against `/bin/false`.
"""

import re
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import ROOT

SEAT, MODEL, EFFORT, ACCOUNT = "acme", "acme-7", "high", "work"
ID = "0b7e3c1a-5d2f-4e8a-9c6b-1f2a3b4c5d6e"
RULES = 'Answer in "plain" words: it\'s the owner\'s call.\n'
PROMPT = '-fix it\'s "$HOME"\nthen ship'
CLAUDE_PINS = ('{"permissions":{"defaultMode":"bypassPermissions"},'
               '"crossSessionInbound":"refuse","switchModelsOnFlag":true}')


def parts(line, program):
    """The env words a line opens with, and its harness's: `program` after a `--`, on."""
    words, head = shlex.split(line.strip()), 0
    if words[:1] == ["env"]:
        head = 1
        while head < len(words) and (words[head] == "-u" or
                                     re.match(r"[A-Za-z_][A-Za-z0-9_]*=", words[head])):
            head += 2 if words[head] == "-u" else 1
    return words[:head], words[words.index(program, words.index("--", head)):]


class Line:
    """The cases every harness's line answers; a subclass names the harness and its words."""
    harness = program = None
    checked = {}    # what the harness's plugin tells its adapter it checked

    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rulebook = self.home.write("acme-rules.md", RULES)

    def launch(self, *conversation, account=None, first="", rulebook=True):
        env = {"AGENTKIT_SESSION": SEAT, "AGENTKIT_FIRST_PROMPT": first, **self.checked,
               **({"AGENTKIT_RULEBOOK": str(self.rulebook)} if rulebook else {}),
               **({"AGENTKIT_ACCOUNT": account} if account else {})}
        return self.home.run(str(ROOT / "adapters" / f"{self.harness}.sh"), "interactive",
                             MODEL, EFFORT, *conversation, env=env)

    def assertWords(self, done, env, conversation=(), first=()):
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(parts(done.out, self.program),
                         (env, [self.program, *conversation, *self.words(), *first]))

    def test_a_fresh_seat(self):
        self.assertWords(self.launch(), self.env(None))

    def test_a_resumed_conversation(self):
        self.assertWords(self.launch(ID), self.env(None), ["--resume", ID])

    def test_a_new_conversation_under_a_given_id(self):
        self.assertWords(self.launch(ID, "new"), self.env(None), ["--session-id", ID])

    def test_a_first_prompt_reaches_the_harness_as_one_word(self):
        self.assertWords(self.launch(first=PROMPT), self.env(None), first=["--", PROMPT])

    def test_a_seat_on_an_account(self):
        self.assertWords(self.launch(account=ACCOUNT), self.env(ACCOUNT))

    def test_no_rulebook_to_hand_over_prints_no_line(self):
        # none named, and none to be made: the host's own rules cannot be read
        (self.home.path / ".agentkit" / "rules.md").mkdir()
        done = self.launch(rulebook=False)
        self.assertEqual((done.code, done.out), (2, ""), done.err)


class ClaudeCode(Line, unittest.TestCase):
    harness, program = "claude", "claude"
    checked = {"AGENTKIT_CLAUDE_CHECKED": "1"}

    def env(self, account):
        # an account's login is the wrapper's to pick, from AGENTKIT_ACCOUNT
        return ["env", "-u", "CLAUDE_CODE_OAUTH_TOKEN", "-u", "CLAUDE_CONFIG_DIR",
                "CLAUDE_CODE_DISABLE_AGENT_VIEW=1", "CLAUDE_CODE_DISABLE_CLAUDE_MDS=1",
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY=1"]

    def words(self):
        return ["--append-system-prompt-file", str(self.rulebook), "--model", MODEL,
                "--effort", EFFORT, "--dangerously-skip-permissions", "--settings", CLAUDE_PINS,
                "--remote-control", SEAT]


class GrokBuild(Line, unittest.TestCase):
    harness, program = "grokbuild", "grok"

    def env(self, account):
        return ["env", "-u", "XAI_API_KEY",
                f"GROK_HOME={self.home.path}/.grok-{account}"] if account else []

    def words(self):
        return ["--rules", RULES, "--trust", "--always-approve", "--model", MODEL,
                "--reasoning-effort", EFFORT]


if __name__ == "__main__":
    unittest.main()
