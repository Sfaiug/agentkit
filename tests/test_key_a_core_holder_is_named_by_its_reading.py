"""`ak run status` names a seat holding a core (tests/test_key_a_seat_holding_a_core_shows_in_status.py)
as the tick's reading named it, once for all its scopes: the tick asks for each seat's name, and
status for none, so a seat renamed since, or while status reads, shows under one name, its
reading's, until the next tick.  Only a reading saved without a name, by an ak before this, is
asked for (tests/test_key_a_core_holder_renamed_meanwhile.py).

Black-box: the program `AK_BIN` names ticks (`home.tick()`) on a stand-in cgroup tree
(AK_CGROUP_ROOT, AK_CGROUP_FILE) whose CPU counters the test moves, and a clock it steps
(AK_CORES_CLOCK); a seat is renamed by its state files alone.  No wait is real.
"""

import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SOCKET, Home, boxable

SERVICE = f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"
# one seat's two scopes: it launched as fix-api, and again once renamed parser
FIX, PARSER = "agentkit-seat-fix-api-89abcdef.scope", "agentkit-seat-parser-0123abcd.scope"
START = 1_800_000_000
# Each tick's clock past START, and the CPU seconds each scope has used by then: the first holds
# a core from the first interval on, the second from the second.
TICKS = [(0, {FIX: 0, PARSER: 0}), (180, {FIX: 180, PARSER: 0}), (360, {FIX: 360, PARSER: 180}),
         (540, {FIX: 540, PARSER: 360})]


def held(home):
    done = home.ak("run", "status")
    assert done.code == 0, done.out + done.err
    return [line for line in done.out.splitlines() if line.startswith("seats holding a core")]


def renamed(home, new, *old):
    """The state files of a seat now named `new`, each of its `old` names leading there."""
    home.write(f".agentkit/state/session-{new}.json", {})
    for name in old:
        home.write(f".agentkit/state/session-{name}.json", {"renamed": new})


class ACoreHolderIsNamedByItsReading(unittest.TestCase):
    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_the_tick_names_a_seat_once_and_status_keeps_that_name_through_a_rename(self):
        with Home() as home:
            # a collection on record from just now: one due would outlive the tick
            home.write(".agentkit/state/gc.json", {"started_at": time.time()})
            root, membership, clock = (home.root / name
                                       for name in ("cgroup", "membership", "clock"))
            seats = root / SERVICE / "agentkit.slice" / f"{SOCKET}.slice" / f"{SOCKET}.slice"
            membership.write_text(f"0::/{SERVICE}/app.slice/acme.service\n")
            home.env.update(AK_CGROUP_ROOT=str(root), AK_CGROUP_FILE=str(membership),
                            AK_CORES_CLOCK=str(clock))
            renamed(home, "parser", "fix-api")
            after = []
            for at, used in TICKS:
                clock.write_text(str(START + at))
                for scope, seconds in used.items():
                    (seats / scope).mkdir(parents=True, exist_ok=True)
                    (seats / scope / "cpu.stat").write_text(
                        f"usage_usec {seconds * 1_000_000}\nuser_usec 0\nsystem_usec 0\n")
                done = home.tick()
                self.assertEqual(done.code, 0, done.out + done.err)
                after.append(held(home))
                if at == 360:
                    renamed(home, "lexer", "parser", "fix-api")
                    after.append(held(home))
        self.assertEqual(after[2:], [["seats holding a core: parser 6m"],
                                     ["seats holding a core: parser 6m"],
                                     ["seats holding a core: lexer 9m"]])

    def test_a_seat_renamed_while_status_reads_shows_once_under_its_readings_name(self):
        with Home() as home:
            home.write(".agentkit/state/watch.json", {"seat_cores": {
                FIX: {"at": 720, "since": 180, "seat": "parser"},
                PARSER: {"at": 720, "since": 360, "seat": "parser"}}})
            renamed(home, "parser", "fix-api")
            # The seat's file is a pipe, so the test knows when the program reads it, and puts
            # the renamed seat's in its place before that reading gets what it held until then:
            # a program asking for a name, the reading's or a scope's, twice gets both.
            seat = home.path / ".agentkit/state/session-parser.json"
            seat.unlink()
            os.mkfifo(seat)
            pointer = home.root / "pointer"
            pointer.write_text(json.dumps({"renamed": "lexer"}))

            def rename():
                with seat.open("w") as read:    # opens once the program reads the file
                    os.replace(pointer, seat)
                    read.write("{}")

            # a daemon: a program that never reads the file leaves it waiting
            threading.Thread(target=rename, daemon=True).start()
            self.assertEqual(held(home), ["seats holding a core: parser 9m"])

    def test_a_reading_saved_without_a_name_is_asked_for(self):
        with Home() as home:
            home.write(".agentkit/state/watch.json", {"seat_cores": {
                FIX: {"at": 720, "since": 180}, PARSER: {"at": 720, "since": 360}}})
            renamed(home, "parser", "fix-api")
            self.assertEqual(held(home), ["seats holding a core: parser 9m"])


if __name__ == "__main__":
    unittest.main()
