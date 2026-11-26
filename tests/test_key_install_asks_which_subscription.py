"""A newcomer's install asks which subscription they have, by the name every screen gives it.

On a machine with no model program, a terminal run of a server install asks "Which subscription
do you have (Claude, ChatGPT, Muse, Grok, Gemini, MiMo, or all)? [all]", the names every screen
gives these subscriptions.  An answer is one of those names in any case, or a program's name, and only the program that runs that subscription's models is
installed and logged in: `chatgpt` and `codex` alike install codex and log it in, and no other.
An answer that is neither, `gpt`, is refused with the same names, and nothing is installed.
Black-box: install.sh of the checkout `AK_BIN` names runs from outside in a Home made the
account's own by tests/fixtures/installer.py, with no model program on its PATH, and with a
terminal on its input and output, as only then does it ask; the answer is typed in, and the
Discord secrets it asks for next are on disk.  Its `npm` logs each call and makes `i` install a
fake codex that logs each of its own; every other program installs by `curl`, which the Home
refuses and logs, and a `node` new enough leaves curl nothing else to fetch.
"""

from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import LOG, Home

PROGRAMS = ("claude", "codex", "muse", "grok", "opencode", "agy")
NAMES = "Claude, ChatGPT, Muse, Grok, Gemini, MiMo"
# a terminal on the install's input and output alike, what is sent to this typed into it
TERMINAL = "import os, pty, sys; sys.exit(os.waitstatus_to_exitcode(pty.spawn(sys.argv[1:])))"


def install(answer):
    """A terminal install answering `answer`, and its Home."""
    home = Home()
    installer.prepare(home)
    installer.own_home(home)
    for secret in ("discord_webhook", "discord_user_id"):    # asked for next, unless written
        home.write(f".agentkit/secrets/{secret}", "acme\n")
    installer.without(home, *PROGRAMS)
    home.fake("node", "#!/bin/sh\necho v22.0.0\n")
    codex = home.refuse("codex", LOG)
    home.refuse("npm", LOG + '[ "$1" != i ] || exec cp {codex} {bin}/codex\n',
                codex=shlex.quote(str(codex.rename(home.root / "codex"))),
                bin=shlex.quote(str(home.bin)))
    return home, home.run(sys.executable, "-c", TERMINAL, "bash", str(installer.INSTALL),
                          "--server", input=f"{answer}\n", timeout=300)


@unittest.skipUnless(sys.platform.startswith("linux"), "a Linux host's install")
class AsksWhichSubscription(unittest.TestCase):
    def installs(self, answer):
        home, done = install(answer)
        self.addCleanup(home.close)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(home.calls("curl"), [], done.out)
        return home, done.out

    def test_the_question_names_the_subscriptions_and_chatgpt_installs_codex(self):
        for answer in ("chatgpt", "codex"):
            with self.subTest(answer=answer):
                home, out = self.installs(answer)
                self.assertIn(f"Which subscription do you have ({NAMES}, or all)? [all] ", out)
                self.assertEqual([call for call in home.calls("npm") if call[0] == "i"],
                                 [["i", "-g", "@openai/codex"]], out)
                self.assertIn(["login", "--device-auth"], home.calls("codex"), out)

    def test_an_answer_naming_none_is_refused_with_the_names(self):
        home, out = self.installs("gpt")
        self.assertIn(f"'gpt' is not one of: {NAMES}, or all; installing nothing", out)
        self.assertEqual([call for call in home.calls("npm") if call[0] == "i"], [], out)
        self.assertFalse((home.bin / "codex").exists())


if __name__ == "__main__":
    unittest.main()
