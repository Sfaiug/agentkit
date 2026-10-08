"""A seat that comes up while a menu is open gets its first look from that menu.

A menu reads again when a record changes, and that read used to look at no seat: a seat started
elsewhere was drawn with a word decided on what there was (`needs you`) that no look had written
to its record or told its bar, and opening it by its number kept the next look away for as long
as its owner stayed in it.  Offline: `Sandbox`'s temporary HOME, a fake listing and a fake
attach; no tmux server and no seat.
"""

import io
import sys
import threading
from contextlib import redirect_stdout
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, menu, orch, watch

SEAT = "fix-api"


class MenuLooksAtASeatFoundOnNews(Sandbox):
    def test_a_seat_opened_as_soon_as_it_is_found_gets_its_word_while_its_owner_is_in_it(self):
        found, frames, holder, seen = [], [], {}, []
        watching = menu.Live.watch

        def start(live, last):
            holder["live"] = live
            watching(live, last)
            live.looker.join()
            holder["first"] = live.looker

        def moving(*_args, **_kw):
            live = holder["live"]
            if not frames:
                # a seat another terminal just started: its record is news to this menu
                config.save_session(self.cfg, SEAT, "astra", ["opus"],
                                    {"cwd": str(self.root), "created": 10000})
                found.append({"name": SEAT, "path": str(self.root), "created": 10000,
                              "attached": False, "exited": False, "legacy": False,
                              "resumable": False})
                live.read()
                frames.append("the new seat is drawn")
                return None
            if len(frames) == 1:
                frames.append("its number is pressed")
                return "1"
            return ""

        attaching = orch.attach

        def attach(name, **kw):
            def ran(argv, **_options):
                if "attach-session" in argv:
                    # its owner is in the seat now, and the menu waits here until they leave
                    live = holder["live"]
                    seen.append(live.looker)
                    live.looker.join()
                    seen.append(watch.seat_read(name).get("word"))
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch.object(sys.stdin, "isatty", return_value=True), \
                    patch.object(sys.stdout, "isatty", return_value=True), \
                    patch.object(orch, "inside", return_value=False), \
                    patch.object(orch, "fix_term", return_value=None), \
                    patch.object(orch, "tmux_out", return_value=(0, "")), \
                    patch.object(orch.subprocess, "run", side_effect=ran):
                return attaching(name, **kw)

        with patch.object(orch, "listing", side_effect=lambda **_kw: list(found)), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu.Live, "watch", start), \
                patch.object(menu.Live, "probe", return_value=False), \
                patch.object(menu, "moving", side_effect=moving), \
                patch.object(menu, "wait_key"), patch.object(menu, "read"), \
                patch.object(menu, "update_first"), \
                patch.object(orch, "attach", side_effect=attach), \
                redirect_stdout(io.StringIO()):
            menu.loop(self.cfg)
        self.assertEqual(len(seen), 2, "the seat was never attached")
        looker, published = seen
        self.assertIsNot(looker, holder["first"], "the read that found the seat began no look")
        self.assertIn(published, ("working", "needs you", "done"))

    def seat(self, name, created=10000):
        config.save_session(self.cfg, name, "astra", ["opus"],
                            {"cwd": str(self.root), "created": created})
        return {"name": name, "path": str(self.root), "created": created, "attached": False,
                "exited": False, "legacy": False, "resumable": False}

    def menu(self, found, look):
        """A menu's reads over `found`, each look it starts handed to `look` in its thread."""
        live = menu.Live(self.cfg)
        self.addCleanup(live.close)
        live.last = [[], None]
        for patched in (patch.object(orch, "listing", side_effect=lambda **_kw: list(found)),
                        patch.object(menu.Live, "_look", side_effect=look)):
            patched.start()
            self.addCleanup(patched.stop)
        return live

    def test_a_seat_is_looked_at_once_and_again_only_after_it_went_and_came_back(self):
        """However many reads follow, and whatever its look recorded: a seat no look can
        record is not read and looked at again without end."""
        found, looked = [self.seat(SEAT)], []
        live = self.menu(found, lambda seats: looked.append([seat["name"] for seat in seats]))

        def read():
            live.read()
            live.looker.join()

        read()
        read()
        self.assertEqual(looked, [[SEAT]])
        found.append(self.seat("acme-docs"))
        read()
        read()
        self.assertEqual(looked, [[SEAT], ["acme-docs"]])
        del found[0]                    # closed ...
        read()
        found.append(self.seat(SEAT))   # ... and one started under its name
        read()
        self.assertEqual(looked, [[SEAT], ["acme-docs"], [SEAT]])

    def test_a_seat_found_while_a_pass_is_going_is_looked_at_by_the_read_after_it(self):
        found, looked, going = [self.seat(SEAT)], [], threading.Event()

        def look(seats):
            looked.append([seat["name"] for seat in seats])
            going.wait(30)

        live = self.menu(found, look)
        live.read(look=True)            # the pass every menu starts with, still going
        found.append(self.seat("acme-docs"))
        live.read()
        self.assertEqual(looked, [[SEAT]])
        going.set()
        live.looker.join()
        live.read()                     # the read a landed pass asks for
        live.looker.join()
        self.assertEqual(looked, [[SEAT], ["acme-docs"]])


if __name__ == "__main__":
    unittest.main()
