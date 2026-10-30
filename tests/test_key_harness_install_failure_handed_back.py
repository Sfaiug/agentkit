"""A harness upgrade that cannot be installed twice in a row is handed back once.

On 27 Oct a codex install failed: npm's Linux build lagged its publish by minutes, which the
next day's retry cures.  But `ak update` reverts a failed install and runs no gate, and the
tick retries that release daily, for ever, telling nobody: a harness whose install something
of ours breaks stays behind for good.  Now a failed install counts a red in that harness's
record, as a red gate does: its second red in a row, gate or install, is handed back once,
naming what could not be installed and the log; a gate pass clears it; a harness that installed
fine in the same update counts none.  Black-box: `ak update` runs the program `AK_BIN` names
through tests/fixtures/akbin.py, with a fake `claude`, a fake `codex` whose `npm` install fails
while `broken` exists, and the gates stood in for by tests/fixtures/akgates.py; each tick runs
the live install tests/fixtures/akinstall.py copies to HOME/agentkit, which types the line into
the seat that merged into agentkit; this test fails against `/bin/false`.
"""

import re
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akgates import Gates
from fixtures.akinstall import Install

CLAUDE = """#!/bin/sh
case "$1 $2" in
  "--version "*) cat {root}/claude ;;
  "install latest") echo "2.2.0 (Claude Code)" >{root}/claude ;;
  "install "*) echo "$2 (Claude Code)" >{root}/claude ;;
  *) echo "claude: not scripted in this test" >&2; exit 1 ;;
esac
"""
CODEX = "#!/bin/sh\ncat {root}/codex\n"
NPM = """#!/bin/sh
case "$1 $2 $3" in
  "i -g @openai/codex@latest") [ -f {root}/broken ] && exit 1
                              echo "codex-cli 0.2.0" >{root}/codex ;;
  "i -g @openai/codex@"*) echo "codex-cli ${{3#@openai/codex@}}" >{root}/codex ;;
  *) echo "npm: not scripted in this test" >&2; exit 1 ;;
esac
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class InstallFailureHandedBack(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus", "astra"])
        self.install = Install(self.home)
        root = self.home.root
        (root / "claude").write_text("2.1.0 (Claude Code)\n")
        (root / "codex").write_text("codex-cli 0.1.0\n")
        for name, script in (("claude", CLAUDE), ("codex", CODEX), ("npm", NPM)):
            self.home.fake(name, script.format(root=shlex.quote(str(root))))
        self.gates = Gates(self.home)
        self.seat = self.install.seat()

    def update(self, broken, code=None):
        """`ak update` with codex's install failing or not; the log it names."""
        flag = self.home.root / "broken"
        flag.touch() if broken else flag.unlink(missing_ok=True)
        done = self.home.ak("update", timeout=120)
        said = done.out + done.err
        self.assertEqual(done.code, int(broken) if code is None else code, said)
        return Path(re.search(r"-- see (\S+)", said)[1]) if broken else None

    def tick(self):
        """One tick of the live install: the lines it typed into the seat."""
        before = len(self.seat.lines())
        done = self.home.run(self.install.ak, "watch")
        self.assertEqual(done.code, 0, done.out + done.err)
        return self.seat.lines()[before:]

    def test_a_second_failed_install_in_a_row_is_handed_back_once(self):
        self.update(broken=True)
        self.assertEqual(self.tick(), [])
        log = self.update(broken=True)
        [line] = self.tick()    # claude installed fine both times: no line of its own
        self.assertEqual(line, "The codex harness upgrade could not be installed twice in a row: "
                               "codex could not be upgraded. "
                               f"Log: ~/{log.relative_to(self.home.path)}. Fix the harness install.")
        self.assertIn("@openai/codex@latest", log.read_text())
        self.update(broken=True)
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.gates.ran(), [])

    def test_a_passing_gate_between_failed_installs_hands_back_nothing(self):
        self.update(broken=True)
        self.update(broken=False)
        self.update(broken=True)
        self.assertEqual(self.tick(), [])

    def test_a_red_gate_then_a_failed_install_is_handed_back(self):
        self.gates.exit("live", 1)
        self.update(broken=False, code=1)
        self.update(broken=True)
        [line] = self.tick()    # claude's gate red was its first
        self.assertIn("codex harness upgrade could not be installed twice in a row", line)


if __name__ == "__main__":
    unittest.main()
