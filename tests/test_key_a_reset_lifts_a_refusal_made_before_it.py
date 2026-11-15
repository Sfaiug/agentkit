"""A reset the owner spends lifts a refusal made before it, however late that refusal is written.

A turn refused for usage is written down once ak has read the meters it parks by, and that read
can take a while: the owner may spend a reset meanwhile, and the refilled login be read again
after it.  The credit refilled the week that refused the turn, so the refusal parks nothing once
it is written: Opus is picked again.

Black-box: the program `AK_BIN` names runs a task in a temporary HOME over a Codex login, read
first, and a Claude one, each adapter a fake (tests/fixtures/fakeadapter.py) and Claude read
again a second after its last read.  The Opus turn is refused for usage once the snapshot it
was picked on is five minutes old, so its refusal waits on every login read afresh; Codex's
read is held until the owner has spent Claude's reset on the ak screen in a terminal
(tests/fixtures/akterm.py), and Claude's is read after it.  A build that writes the refusal
before the reset, or reads nothing first, meets the same answer.  No real login or meter is
reached.  This test fails against `/bin/false`.
"""

import json
import re
import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from fixtures.gitrig import Rig
from test_key_claude_reset_in_the_menu import (LIT, MAIN_KEYS, METER, UNLIT, lines, offered,
                                               under_grid)    # its tests run in their own file

WEEK = 604800


def reading(used, **keys):
    """A usage answer: the week at `used`%, a day from rolling over."""
    return {"meters": [{"name": "weekly_all", "used": used, "window_secs": WEEK,
                        "resets_at": int(time.time()) + 86400}], "error": None, **keys}


def until(shown, what, bound=120):
    deadline = time.monotonic() + bound
    while not shown():
        if time.monotonic() > deadline:
            raise AssertionError(f"not {what} after {bound} s")
        time.sleep(0.1)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ResetLiftsAnEarlierRefusal(unittest.TestCase):
    def spend_claudes_reset(self, home):
        """The ak screen opened in a terminal, and Claude's weekly reset spent on its meter."""
        term = Terminal(home, size=(120, 40), env={"NO_COLOR": "1"})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        main = lines(term.wait(lambda screen: MAIN_KEYS in lines(screen)
                               and METER.search(screen)))
        row, found = next((number, found) for number, line in enumerate(main)
                          if (found := re.search(r"Claude", line)))
        row, column = row + 1, found.start() + 3
        term.type(f"\x1b[<35;{column};{row}M")
        term.wait(lambda screen: under_grid(screen).startswith("  Claude  ")
                  and "in hand" in screen)
        term.type(f"\x1b[<0;{column};{row}M\x1b[<0;{column};{row}m")
        term.wait(lambda screen: offered(screen) and UNLIT in lines(screen))
        term.keys("Down")
        term.wait(lambda screen: LIT.format("spend a weekly reset") in lines(screen))
        term.keys("Enter")
        term.wait(lambda screen: "Claude · 100% left" in screen
                  and MAIN_KEYS not in lines(screen))

    def test_a_refusal_made_before_a_reset_parks_nothing_however_late_it_is_written(self):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home)
        akconfig.write(home, {"astra": "codex", "opus": "claude"}, workers=["opus"])
        for harness in ("claude", "codex"):
            home.fake(harness, "#!/bin/sh\nexit 0\n")
        fakes = fakeadapter.install(home, claude="dead", codex="pass")
        claude, codex = fakes["claude"], fakes["codex"]
        started, go, hold, held = (claude.dir / name for name in ("started", "go", "hold", "held"))
        claude.behave({"sh": f": >{shlex.quote(str(started))}; "
                             f"until [ -e {shlex.quote(str(go))} ]; do sleep 0.1; done",
                       "final": "You have hit your usage limit.", "exit": 1})
        # Claude read again a second after its last read, not its shipped fifteen minutes
        manifest, count = re.subn(r"(?m)^probe_every = .*$", "probe_every = 1",
                                  claude.manifest.read_text())
        self.assertEqual(count, 1)
        claude.manifest.write_text(manifest)
        # Codex's read held, while `hold` is there, until the test lets it go
        codex.script.write_text(codex.script.read_text().replace("#!/bin/sh\n", (
            f'#!/bin/sh\nif [ "$1" = usage ] && [ -e {shlex.quote(str(hold))} ]; then'
            f" : >{shlex.quote(str(held))}; while [ -e {shlex.quote(str(hold))} ]; do"
            " sleep 0.1; done; fi\n"), 1))
        week = reading(60, resets=1, reset_kinds=[{"kind": "weekly", "left": 1, "usable": True}])
        claude.answer("usage", json.dumps(week))
        claude.answer("reset", json.dumps({"code": "reset", "available": 0,
                                           "meters": reading(0)["meters"]}))
        codex.answer("usage", json.dumps(reading(10, resets=0)))
        now = time.time()
        cache = home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {
                "openai": {"provider": "openai", **reading(10, resets=0)},
                "anthropic": {"provider": "anthropic", **week}}})

        run = home.spawn("run", str(taskfile.write(home, rig.path)), "--no-merge",
                         "--exec", "opus")
        until(lambda: started.exists() or run.poll() is not None, "turning")
        self.assertTrue(started.exists(), home.log("spawn-1.err").read_text())
        # the reading the turn was picked on is past its five minutes when the turn is refused
        blob = json.loads(cache.read_text())
        cache.write_text(json.dumps({**blob, "fetched_at": blob["fetched_at"] - 600}))
        hold.touch()
        go.touch()
        until(lambda: held.exists() or run.poll() is not None, "refused")
        self.spend_claudes_reset(home)
        time.sleep(1.5)     # past Claude's second: its next read asks again
        hold.unlink()
        run.wait(timeout=300)

        state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.assertEqual((state["state"], state["executor"]), ("exhausted", "opus"))
        read = home.ak("usage", "--json")
        self.assertEqual(read.code, 0, read.out + read.err)
        blob = json.loads(read.out)
        self.assertFalse(blob["providers"]["anthropic"]["exhausted"])
        self.assertIn("opus", blob["pick_order"])


if __name__ == "__main__":
    unittest.main()
