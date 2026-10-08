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
                live._wake()    # the wait ends on that news, not on the clock, which looks again
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

    def seat(self, name, **facts):
        config.save_session(self.cfg, name, "astra", ["opus"],
                            {"cwd": str(self.root), "created": 10000})
        return {"name": name, "path": str(self.root), "repo": None, "created": 10000,
                "attached": False, "exited": False, "legacy": False, "resumable": False, **facts}

    def menu(self, found, **patches):
        """A menu over `found`, its reads and looks its own but for `patches` of `menu`."""
        live = menu.Live(self.cfg)
        self.addCleanup(live.close)
        live.last = [[], None]
        for patched in (patch.object(orch, "listing", side_effect=lambda **_kw: list(found)),
                        patch.object(orch, "tmux_out", return_value=(0, "")),
                        *(patch.object(menu, name, side_effect=fake)
                          for name, fake in patches.items())):
            patched.start()
            self.addCleanup(patched.stop)
        return live

    def test_a_pass_is_started_once_for_a_seat_and_again_only_after_it_went_and_came_back(self):
        """However many reads follow, and whatever its look recorded: a seat no look can
        record is not read and looked at again without end."""
        found, looked = [self.seat(SEAT)], []

        def groups(_cfg, seats, *_args, look=True, **_kw):
            if look:
                looked.append([seat["name"] for seat in seats])     # ... and records nothing
            return [], [], 0, {}

        live = self.menu(found, v5o_groups=groups)

        def read():
            live.read()
            live.looker.join()

        read()
        read()
        self.assertEqual(looked, [[SEAT]])
        found.append(self.seat("acme-docs"))
        read()
        read()
        self.assertEqual(looked, [[SEAT], [SEAT, "acme-docs"]])
        del found[0]                    # closed ...
        read()
        found.append(self.seat(SEAT))   # ... and one started under its name
        read()
        self.assertEqual(looked, [[SEAT], [SEAT, "acme-docs"], ["acme-docs", SEAT]])

    def test_a_closed_seat_found_on_news_keeps_the_number_it_is_listed_by(self):
        """The pass is over every seat, so each is looked at under its own number."""
        found = [self.seat("acme-docs", exited=True, resumable=True)]
        live = self.menu(found)
        live.read(look=True)
        live.looker.join()
        found.append(self.seat(SEAT, exited=True, resumable=True))
        live.read()
        live.looker.join()
        live.read()
        self.assertEqual(watch.seat_read(SEAT)["reason"], "session closed: press 2 to reopen")
        row = {row["name"]: row for row in live.last[1][1]}[SEAT]
        self.assertEqual((row["number"], row["sentence"]),
                         ("2", "session closed: press 2 to reopen"))

    def test_a_seat_found_while_a_pass_is_going_is_looked_at_once_that_pass_is_over(self):
        """Even when the watcher reads on the pass's own ask before the pass's thread has ended:
        the pass is over before it asks, so that read is the one that starts the next."""
        found, looked = [{"name": "acme-docs"}], []
        started, release, second = (threading.Event() for _ in range(3))
        discovered, ended = threading.Event(), threading.Event()
        live = menu.Live(self.cfg)
        self.addCleanup(live.close)
        reading, asks = live.read, live.ask

        def groups(_cfg, seats, *_args, look=True, **_kw):
            if look:
                looked.append([seat["name"] for seat in seats])
                if SEAT in looked[-1]:
                    second.set()
                started.set()
                release.wait(30)
            return [], [], 0, {}

        def read(look=False):
            reading(look)
            if threading.current_thread() is live.watcher:
                discovered.set()

        def ask(look=False):
            asks(look)
            if threading.current_thread() not in (threading.main_thread(), live.watcher):
                ended.wait(30)      # the pass's own ask: the watcher reads on it first

        with patch.object(orch, "listing", side_effect=lambda **_kw: list(found)), \
                patch.object(orch, "file_projectless"), \
                patch.object(menu, "v5o_groups", side_effect=groups), \
                patch.object(live, "recorded", return_value=[]), \
                patch.object(live, "read", side_effect=read), \
                patch.object(live, "ask", side_effect=ask):
            try:
                live.watch([[], None])
                self.assertTrue(started.wait(30))
                found.append({"name": SEAT})
                live.ask()
                self.assertTrue(discovered.wait(30))    # read while the first pass is going
                release.set()
                self.assertTrue(second.wait(30), f"{SEAT} was never looked at: {looked}")
                self.assertEqual(looked, [["acme-docs"], ["acme-docs", SEAT]])
            finally:
                release.set()
                ended.set()
                live.close()
                live.watcher.join(30)


if __name__ == "__main__":
    unittest.main()
