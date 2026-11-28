"""The live suite opens a seat of every harness and proves it takes ak's line: check 6h.

Block 6h's own lines, cut from tests/smoke.sh with the helpers it calls, run in an answer-key
Home whose adapters are fakes (AGENTKIT_ADAPTER_DIR) that open seats on tests/fixtures/akpane.py:
Claude's shows its prompt, works on the line it is given and comes back to it; Muse's shows only
its working screen, so it never reads at its prompt and the probe waits its whole wait for that;
every other harness's program is missing.
"""

from pathlib import Path
import shlex
import sys
import unittest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent
sys.path.insert(0, str(TESTS))
from fixtures.akbin import AK, REAL_TMUX, Home  # noqa: E402
import suite_shares  # noqa: E402

SMOKE = (TESTS / "smoke.sh").read_text()
# the helpers block 6h calls, and the block itself
SCRIPT = "\n".join(["set -uo pipefail",
                    SMOKE[SMOKE.index("tm()  {"):SMOKE.index('echo "workdir: $WORK"')],
                    SMOKE[SMOKE.index("model_unavailable()"):SMOKE.index("reprobe()")],
                    SMOKE[SMOKE.index("spent_until()"):SMOKE.index("skip_refused()")],
                    SMOKE[SMOKE.index("# --- 6h:"):SMOKE.index("# --- 6e:")]])
# A seat's harness: SCREEN shows IDLE; once a line is entered there, WORKING a while, then IDLE.
HARNESS = """import sys, threading, time
from pathlib import Path
sys.path.insert(0, sys.argv[5])
import akpane
screen, typed, idle, working = map(Path, sys.argv[1:5])
def show(shown):
    screen.with_suffix(".swap").write_text(shown.read_text())
    screen.with_suffix(".swap").replace(screen)
def answer():
    while not typed.with_name(typed.name + ".lines").exists():
        time.sleep(0.05)
    show(working)
    time.sleep(5)
    show(idle)
show(idle)
threading.Thread(target=answer, daemon=True).start()
akpane.main(screen, typed)
"""
SEATS = {"claude": ("claude-prompt-pane.txt", "claude-working-pane.txt"),
         "muse": ("muse-working-pane.txt", "muse-working-pane.txt")}
MISSING = ("codex", "grok", "agy", "opencode")    # the programs of the other harnesses


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class EveryHarnesssSeatTakesAksLine(unittest.TestCase):
    def test_each_harness_passes_fails_or_skips_alone_and_leaves_no_seat(self):
        with Home() as home:
            adapters, panes = home.root / "adapters", home.root / "panes"
            adapters.mkdir()
            panes.mkdir()
            harness = home.root / "harness.py"
            harness.write_text(HARNESS)
            for name, (idle, working) in SEATS.items():
                command = shlex.join([sys.executable, str(harness), str(panes / f"{name}.txt"),
                                      str(panes / f"{name}.typed"), str(TESTS / "fixtures" / idle),
                                      str(TESTS / "fixtures" / working), str(TESTS / "fixtures")])
                adapter = adapters / f"{name}.sh"
                adapter.write_text("#!/bin/sh\ncase $1 in\n  auth) echo 'a fake login'; exit 0 ;;\n"
                                   f"  interactive) echo {shlex.quote(command)}; exit 0 ;;\n"
                                   "esac\nexit 2\n")
                adapter.chmod(0o755)
            for program in MISSING:
                (home.bin / program).unlink()
            done = self.check(home, AGENTKIT_ADAPTER_DIR=str(adapters))
            said = done.out + done.err
            lines = done.out.splitlines()
            self.assertIn("PASS  6h claude: fable's seat took ak's longest line", done.out, said)
            muse = [line for line in lines if line.startswith(("PASS  6h muse", "FAIL  6h muse"))]
            self.assertEqual(len(muse), 1, said)
            self.assertTrue(muse[0].startswith("FAIL  6h muse: step 1: did not read at_prompt "
                                               "with an empty composer"), said)
            for name in ("codex", "grokbuild", "antigravity", "opencode"):
                with self.subTest(harness=name):
                    skipped = [line for line in lines if line.startswith(f"SKIP  6h {name}: ")]
                    self.assertEqual(len(skipped), 1, said)
                    self.assertIn("not on this host", skipped[0])
            self.assertEqual((home.root / "failed").read_text().splitlines(), ["6h muse"])
            for model in ("fable", "spark"):
                with self.subTest(seat=model):
                    self.assertNotEqual(home.tmux("has-session", "-t", f"=smoke-{model}").code, 0)
                    self.assertFalse(
                        (home.path / f".agentkit/state/session-smoke-{model}.json").exists())

    def check(self, home, **env):
        """Run block 6h in `home`, the labels it fails written to `home.root / "failed"`."""
        return home.run("/bin/bash", "-c", SCRIPT, timeout=600, env={
            "REPO": str(REPO), "WORK": str(home.root / "work"),
            "SMOKE_CALLER_HOME": str(home.path), "AK_LIVE_FAILED": str(home.root / "failed"),
            "PATH": f"{Path(AK).parent}:{home.env['PATH']}", **env})

    def test_6h_is_a_live_check_that_makes_a_model_call(self):
        self.assertIn("6h", suite_shares.LIVE_CHECKS & suite_shares.MODEL_CALLS)


if __name__ == "__main__":
    unittest.main()
