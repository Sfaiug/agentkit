"""The live suite opens a seat of every harness and proves it takes ak's line: check 6h.

Block 6h's own lines, cut from tests/smoke.sh with the helpers it calls, run in an answer-key
Home whose adapters are fakes (AGENTKIT_ADAPTER_DIR).  Claude's and Muse's open seats on
tests/fixtures/akpane.py: Claude's shows its prompt and, once a line is entered there, its
working screen until the probe has read it, then its prompt again; Muse's shows only its working
screen, so it never reads at its prompt and the probe waits its whole wait for that.  Every other
harness's manifest names a program at a path nothing is at, whatever this host has installed.
"""

from pathlib import Path
import shlex
import sys
import threading
import unittest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent
FIXTURES = TESTS / "fixtures"
sys.path.insert(0, str(TESTS))
from fixtures.akbin import AK, REAL_TMUX, Home  # noqa: E402
from fixtures.akpane import stamp  # noqa: E402
import suite_shares  # noqa: E402

SMOKE = (TESTS / "smoke.sh").read_text()
# the helpers block 6h calls, and the block itself
SCRIPT = "\n".join(["set -uo pipefail",
                    SMOKE[SMOKE.index("tm()  {"):SMOKE.index('echo "workdir: $WORK"')],
                    SMOKE[SMOKE.index("model_unavailable()"):SMOKE.index("reprobe()")],
                    SMOKE[SMOKE.index("spent_until()"):SMOKE.index("skip_refused()")],
                    SMOKE[SMOKE.index("# --- 6h:"):SMOKE.index("# --- 6e:")]])
PROMPT = "claude-prompt-pane.txt"
WORKING = "claude-working-pane.txt"
SEATS = {"claude": PROMPT, "muse": "muse-working-pane.txt"}    # the screen each seat opens on
ABSENT = ("codex", "grokbuild", "antigravity", "opencode")      # whose program is not there


def show(screen, name):
    """Put fixture `name` in a pane's screen file whole, as its harness's next frame."""
    swap = screen.with_suffix(".swap")
    swap.write_bytes((FIXTURES / name).read_bytes())
    swap.replace(screen)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class EveryHarnesssSeatTakesAksLine(unittest.TestCase):
    def test_each_harness_passes_fails_or_skips_alone_and_leaves_no_seat(self):
        with Home(tmux_log=True) as home:
            adapters = self.adapters(home)
            stop = threading.Event()
            turn = threading.Thread(target=self.turn, args=(home, stop))
            turn.start()
            try:
                done = self.check(home, AGENTKIT_ADAPTER_DIR=str(adapters))
            finally:
                stop.set()
                turn.join(30)
            said = done.out + done.err
            lines = done.out.splitlines()
            self.assertIn("PASS  6h claude: fable's seat took ak's longest line", done.out, said)
            muse = [line for line in lines if line.startswith(("PASS  6h muse", "FAIL  6h muse"))]
            self.assertEqual(len(muse), 1, said)
            self.assertTrue(muse[0].startswith("FAIL  6h muse: step 1: did not read at_prompt "
                                               "with an empty composer"), said)
            for name in ABSENT:
                with self.subTest(harness=name):
                    skipped = [line for line in lines if line.startswith(f"SKIP  6h {name}: ")]
                    self.assertEqual(len(skipped), 1, said)
                    self.assertIn("is not installed", skipped[0])
                    self.assertIn("not on this host", skipped[0])
            self.assertEqual((home.root / "failed").read_text().splitlines(), ["6h muse"])
            for model in ("fable", "spark"):
                with self.subTest(seat=model):
                    self.assertNotEqual(home.tmux("has-session", "-t", f"=smoke-{model}").code, 0)
                    self.assertFalse(
                        (home.path / f".agentkit/state/session-smoke-{model}.json").exists())

    def adapters(self, home):
        """The fake adapters: a seat on akpane.py for each of SEATS, and for each of ABSENT a
        manifest whose program is a path nothing is at."""
        adapters, panes = home.root / "adapters", home.root / "panes"
        adapters.mkdir()
        panes.mkdir()
        for name, screen in SEATS.items():
            show(panes / f"{name}.txt", screen)
            command = shlex.join([sys.executable, str(FIXTURES / "akpane.py"),
                                  str(panes / f"{name}.txt"), str(panes / f"{name}.typed")])
            adapter = adapters / f"{name}.sh"
            adapter.write_text("#!/bin/sh\ncase $1 in\n  auth) echo 'a fake login'; exit 0 ;;\n"
                               f"  interactive) echo {shlex.quote(command)}; exit 0 ;;\n"
                               "esac\nexit 2\n")
            adapter.chmod(0o755)
        for harness in ABSENT:
            (adapters / f"{harness}.toml").write_text(
                f'[update]\nversion = ["{home.root / "absent" / harness}"]\n')
        return adapters

    def turn(self, home, stop):
        """Claude's turn on the line entered in its seat: the working screen until the probe has
        read it there, then the prompt.  Of the captures logged once the pane has drawn it, at
        most one is the send's and the next is step 3's, so a third means step 3 has read it, as
        tests/test_key_a_seat_proves_it_takes_aks_line.py counts."""
        screen, typed = home.root / "panes/claude.txt", home.root / "panes/claude.typed"
        captures = lambda: sum("capture-pane" in call for call in home.calls("tmux"))
        while not typed.with_name("claude.typed.lines").exists():
            if stop.wait(0.05):
                return
        show(screen, WORKING)
        drawn = lambda: stamp((FIXTURES / WORKING).read_bytes(), typed.stat().st_size)
        while home.tmux("display-message", "-p", "-t", "=smoke-fable:",
                        "#{pane_title}").out.rstrip("\n") != drawn():
            if stop.wait(0.05):
                return
        target = captures() + 3
        while captures() < target:
            if stop.wait(0.05):
                return
        show(screen, PROMPT)

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
