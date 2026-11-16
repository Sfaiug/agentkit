"""A reset of one model's own cap lifts only the refusals that can have come from that cap.

A Claude login's Fable reset refills Fable's own cap (`weekly_scoped` of scope `Fable`) alone,
and that cap never gated Opus: an Opus turn refused beside the shared week at 60% keeps both
models parked once one is spent.  A Fable turn's refusal can have come from that cap, and a
weekly reset refills the whole login, so each of those is lifted.

Black-box: the program `AK_BIN` names runs a task in a temporary HOME over one Claude login
whose injected reading holds the shared week at 60% and Fable's cap at 90%, two workers naming
no `meter`, and a scripted harness refusing the turn for usage, as
tests/test_key_a_refusal_parks_the_models_it_was_meant_for.py does; the reset is then spent on
Claude's meter on the ak screen in a terminal (tests/fixtures/akterm.py), as
tests/test_key_claude_reset_in_the_menu.py does, its adapter a fake
(tests/fixtures/fakeadapter.py).  No real login or meter is reached.  This test fails against
`/bin/false`.
"""

import json
from pathlib import Path
import re
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from fixtures.gitrig import Rig
from test_key_claude_reset_in_the_menu import (LIT, MAIN_KEYS, METER, UNLIT, lines, offered,
                                               under_grid)    # its tests run in their own file

OPUS, FABLE = "claude-opus-5-5", "claude-fable-5-2"
WEEK = 604800
REFILLS = {"weekly": "weekly_all", "Fable": "weekly_scoped"}    # the cap each kind refills


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AResetOfOneCap(unittest.TestCase):
    def picked(self, model, kind):
        """`ak usage --json`'s pick_order once a turn of `model` is refused for usage and a
        `kind` reset is then spent on Claude's meter."""
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home)
        akconfig.write(home, {OPUS: "claude", FABLE: "claude"})
        assert not any("meter" in entry for entry in akconfig.read(home)["models"].values())
        home.fake("claude", "#!/bin/sh\nexit 0\n")
        fake = fakeadapter.install(home, claude="dead")["claude"]
        now = time.time()
        week = {"used": 60, "window_secs": WEEK, "resets_at": now + 3 * 86400}
        meters = [{"name": "weekly_all", **week},
                  {"name": "weekly_scoped", **week, "used": 90, "scope": "Fable"}]
        reading = {"provider": "anthropic", "meters": meters, "error": None, "resets": 2,
                   "reset_kinds": [{"kind": "weekly", "left": 1, "usable": True},
                                   {"kind": "Fable", "left": 1, "usable": True}]}
        fake.answer("usage", json.dumps(reading))      # a probe reads the same
        # what the spend reads back: the cap `kind` refills empty, the rest as they were
        fake.answer("reset", json.dumps({
            "code": "reset", "available": 1,
            "reset_kinds": [{**held, "left": 0, "usable": False} if held["kind"] == kind
                            else held for held in reading["reset_kinds"]],
            "meters": [{**m, "used": 0} if m["name"] == REFILLS[kind] else m for m in meters]}),
            given=(kind,))
        home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"anthropic": reading}})
        done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", "--exec", model,
                       timeout=300)
        self.assertEqual(done.code, 1, done.out + done.err)
        state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.assertEqual((state["state"], state["executor"]), ("exhausted", model))

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
        listed = term.wait(lambda screen: offered(screen) and UNLIT in lines(screen))
        term.keys(*["Down"] * (offered(listed).index(f"  → spend a {kind} reset") + 1))
        term.wait(lambda screen: LIT.format(f"spend a {kind} reset") in lines(screen))
        term.keys("Enter")
        term.wait(lambda screen: re.search(r"Claude · \d+% left", screen)
                  and MAIN_KEYS not in lines(screen))
        self.assertEqual([call["argv"] for call in fake.calls("reset")], [[kind]])

        read = home.ak("usage", "--json")
        self.assertEqual(read.code, 0, read.out + read.err)
        return sorted(json.loads(read.out)["pick_order"])

    def test_a_fable_reset_leaves_an_opus_refusal_parking_both(self):
        self.assertEqual(self.picked(OPUS, "Fable"), [])

    def test_a_fable_reset_lifts_a_fable_refusal(self):
        self.assertEqual(self.picked(FABLE, "Fable"), sorted([OPUS, FABLE]))

    def test_a_weekly_reset_lifts_an_opus_refusal(self):
        self.assertEqual(self.picked(OPUS, "weekly"), sorted([OPUS, FABLE]))


if __name__ == "__main__":
    unittest.main()
