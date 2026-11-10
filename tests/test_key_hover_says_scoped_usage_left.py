"""The line under the usage grid says what a model's own cap has left, as its provider names it.

The owner (10 Nov 2026), the pointer on a Claude subscription: "it only shows the normal reset
time, but not the fable usage I have remaining."  Anthropic's usage endpoint says whose cap a
limit is; `adapters/claude.sh usage` keeps that name as the meter's `scope`, the line under the
grid says `<scope> NN% left` right after the reset time, and a scoped meter is never the
subscription's own figure in its cell -- all with no model in config.toml claiming the meter.
A reading whose meters name no scope draws the line it drew before.

Black-box: the adapters beside the program `AK_BIN` names (or `AK_ROOT`'s), over a fake `curl`
answering the endpoint's own two weekly limits of 10 Nov 2026; then `AK_BIN`'s ak screen in a
terminal (tests/fixtures/akterm.py) over a reading in a temporary HOME (TZ=UTC), its harness
faked (tests/fixtures/fakeadapter.py), the pointer typed as the SGR sequence a terminal sends.
This test fails against `/bin/false`.
"""

import json
import os
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

ADAPTERS = Path(os.environ.get("AK_ROOT") or Path(AK).resolve().parents[1]) / "adapters"
MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"
WEEK = 604800
# The endpoint's `limits[]` on 10 Nov 2026: the shared week, then Fable's own cap.
LIMITS = [{"kind": "weekly_all", "group": "weekly", "percent": 70, "severity": "normal",
           "resets_at": "2026-11-13T11:59:59.674206+00:00", "scope": None, "is_active": True},
          {"kind": "weekly_scoped", "group": "weekly", "percent": 8, "severity": "normal",
           "resets_at": "2026-11-13T11:59:59.674345+00:00",
           "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None},
           "is_active": False}]


def home(cleanup):
    """A Home whose only model, on Claude, names no `meter`."""
    made = Home()
    cleanup(made.close)
    akconfig.write(made, {"opus": "claude"})
    assert not any("meter" in entry for entry in akconfig.read(made)["models"].values())
    return made


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def under_grid(screen):
    """The ak screen's line under the usage grid: what the meter under the pointer says."""
    shown = lines(screen)
    return shown[max(number for number, line in enumerate(shown) if "▰" in line) + 1]


class AdapterNamesTheCap(unittest.TestCase):
    def test_the_scoped_limit_s_meter_carries_its_model_s_name(self):
        made = home(self.addCleanup)
        made.write(".agentkit/secrets/claude_oauth_token", "tok-acme")
        answer = made.write("answer.json", {"limits": LIMITS})
        made.fake("curl", f"#!/bin/sh\ncat '{answer}'\nprintf '\\n200'\n")
        made.fake("security", "#!/bin/sh\nexit 1\n")     # no Keychain login on any host
        done = made.run("bash", str(ADAPTERS / "claude.sh"), "usage")
        self.assertEqual(done.code, 0, done.err)
        meters = json.loads(done.out)["meters"]
        self.assertEqual([meter["name"] for meter in meters], ["weekly_all", "weekly_scoped"])
        self.assertNotIn("scope", meters[0])
        self.assertEqual(meters[1].get("scope"), "Fable")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class LineUnderTheGrid(unittest.TestCase):
    def open(self, *meters):
        """The ak screen over Claude reading these weekly meters, each (used, scope or None),
        all resetting in three days: its main screen and when they reset, as the line says."""
        made = home(self.addCleanup)
        now = time.time()
        resets = now + 3 * 86400
        reading = {"meters": [{"name": name, "used": used, "resets_at": resets,
                               "window_secs": WEEK, **({"scope": scope} if scope else {})}
                              for name, (used, scope) in zip(("weekly_all", "weekly_scoped"),
                                                             meters)], "error": None}
        made.write(".agentkit/state/usage.json", {"fetched_at": now,
                                                  "providers": {"anthropic": reading}})
        # a probe the screen makes on its own reads the same
        fakeadapter.install(made, claude="pass")["claude"].answer("usage", json.dumps(reading))
        self.term = Terminal(made, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(made.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        main = lines(self.term.wait(lambda screen: MAIN_KEYS in lines(screen) and "▰" in screen))
        return main, time.strftime("%a %H:%M", time.gmtime(resets))

    def pointed(self, main):
        """The line under the grid once the pointer is on Claude's meter, and its cell."""
        row = next(number for number, line in enumerate(main) if "Claude" in line and "▰" in line)
        self.term.type(f"\x1b[<35;{main[row].index('Claude') + 3};{row + 1}M")
        screen = self.term.wait(lambda screen: MAIN_KEYS in lines(screen)
                                and under_grid(screen).startswith("  Claude  "))
        return under_grid(screen), main[row]

    def test_the_line_says_what_the_cap_has_left_after_the_reset_time(self):
        main, when = self.open((22, None), (0, "Fable"))
        line, cell = self.pointed(main)
        self.assertEqual(line, f"  Claude  resets {when} · Fable 100% left")
        self.assertIn("78% left", cell)

    def test_the_cell_is_the_shared_week_however_far_along_the_cap_is(self):
        main, when = self.open((60, None), (95, "Fable"))
        line, cell = self.pointed(main)
        self.assertIn("40% left", cell)
        self.assertEqual(line, f"  Claude  resets {when} · Fable 5% left")

    def test_meters_naming_no_scope_draw_the_line_they_drew(self):
        main, when = self.open((22, None), (0, None))
        line, cell = self.pointed(main)
        self.assertEqual(line, f"  Claude  resets {when}")
        self.assertIn("78% left", cell)


if __name__ == "__main__":
    unittest.main()
