"""The main screen answers every key within 100 ms, however slow the reading behind it is.

`menu.loop` on scripted keys, with the seat listing, the run records, the seats' looks and the
estimate each taking two seconds: ↓, ↑ and a wheel step move the highlight, and Esc back from
`c`, `m`, `i` and the stop question shows the list again, each frame out within 100 ms of its
key, drawn from what was last read; the estimate is asked once however often it is drawn.
Offline, in a throwaway HOME: the probe is never started and the sub-screens are stand-ins that
come back the way Esc brings them back.
"""

from contextlib import redirect_stdout
import io
import os
import threading
import time
from unittest.mock import patch
import unittest

from test_v4n import Sandbox
from agentkit import config, menu, orch, terminal

SLOW = 2.0        # what each read takes: a host under load, and then some
FRAME = 0.1       # what a key may take to its frame
Key = terminal.Key


class Keyboard:
    """A terminal the menu has taken, so keys are `terminal.Key`s and the screen is written over."""

    def take(self):
        return True

    def give(self):
        pass

    def close(self):
        pass


class MenuSpeed(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        repo = config.CODE / "acme"
        (repo / ".git").mkdir(parents=True)
        self.seats = [{"name": name, "repo": str(repo), "path": str(repo), "created": 0}
                      for name in ("fix-api", "tidy-docs", "web-portal")]
        self.estimates = []

        def slow(answer):
            def read(*args, **kwargs):
                time.sleep(SLOW)
                return answer()
            return read

        def row_state(cfg, session, look=True, **facts):
            if look:
                time.sleep(SLOW)          # the seat's pane captured and its hooks read
            return {"word": "working", "reason": "", "since": None}

        def estimate(repo):
            self.estimates.append(repo)
            time.sleep(SLOW)
            return 600

        for target, name, fake in (
                (orch, "listing", slow(lambda: [dict(seat) for seat in self.seats])),
                (menu, "run_records", slow(list)),
                (menu, "seat_row_state", row_state),
                (menu.history, "estimate_seconds", estimate),
                (menu, "seat_progress", lambda name: (1, 3)),
                (orch, "job_notices", lambda: []),
                (menu.Live, "probe", lambda self, now=None: False),
                (terminal, "Keyboard", Keyboard),
                (terminal, "sense", lambda: None),     # a taken keyboard's, no real terminal's
                (terminal, "width", lambda *args: 100)):
            self.stack.enter_context(patch.object(target, name, fake))
        self.stack.enter_context(patch.dict(menu._ESTIMATES, clear=True))

    def test_every_key_puts_its_frame_out_within_100_ms(self):
        out, marks, screens = io.StringIO(), [], []
        began = {}                          # when the key the next frame answers was pressed

        def pressed(key):
            began["at"] = time.monotonic()
            return key

        def back(*args, **kwargs):          # a sub-screen, left with Esc
            marks.append(args[:1])
            began["at"] = time.monotonic()

        def choose(choices, default=None, several=False, around=None, wait=None, **_kw):
            around()                        # the question, drawn under its row
            self.assertLess(time.monotonic() - began["at"], FRAME, "the stop question")
            began["at"] = time.monotonic()
            return None                     # Esc: Keep

        script = iter([Key("down"), Key("up"), Key("wheel-down"), Key("char", "c"),
                       Key("char", "m"), Key("char", "i"), Key("char", "x"), Key("esc")])

        def wait_key(prompt, timeout=None, wake=None):
            if began:
                self.assertLess(time.monotonic() - began["at"], FRAME, screens[-1][0])
            text = terminal.ANSI.sub("", out.getvalue())
            out.seek(0)
            out.truncate()
            lit = [line for line in text.splitlines() if line.startswith("›")]
            key = next(script)
            screens.append((key, lit))
            return pressed(key)

        with patch.object(menu, "wait_key", side_effect=wait_key), \
                patch.object(menu, "read", return_value="q"), \
                patch.object(menu, "show_config", side_effect=back), \
                patch.object(terminal, "choose", side_effect=choose), \
                redirect_stdout(out):
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
            # the loop waited for its reads and looks as it closed, so none outlives these fakes
            self.assertEqual([thread for thread in threading.enumerate()
                              if thread.name != "MainThread" and thread.daemon], [])
        # each key's frame is the highlight where it moved it, or where it was left
        highlighted = [(key.name, key.char, [seat.split()[2] for seat in seats])
                       for key, seats in screens]
        self.assertEqual(highlighted, [("down", "", ["fix-api"]), ("up", "", ["tidy-docs"]),
                                       ("wheel-down", "", ["fix-api"]),
                                       ("char", "c", ["tidy-docs"]),
                                       ("char", "m", ["tidy-docs"]),
                                       ("char", "i", ["tidy-docs"]),
                                       ("char", "x", ["tidy-docs"]),
                                       ("esc", "", ["tidy-docs"])], screens)
        self.assertEqual(marks, [(True,)])   # `c`; `m` and `i` are no keys
        self.assertEqual(self.estimates, [str(config.CODE / "acme")])   # once, not once a draw


if __name__ == "__main__":
    unittest.main(verbosity=2)
