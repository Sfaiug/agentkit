"""A move of ak is final only once a tick started from the version it put live completes.

A move leaves `~/.agentkit/tmp/keep/ak`, a link to the bin/ak of the version it replaced, and
while that is there the version stays and nothing else moves.  A tick is of the folder at
~/agentkit its bin/ak began in: one of the version live removes the link as it completes; one
that began before the move, the tick that made it among them, leaves it however it ends.
Black-box, the Home built as tests/test_key_update_ff.py builds it: ~/agentkit's first version
has a bin/ak of its own, `HOLDING`, which runs the program from the folder it began in, at
first waiting there while `HOLD` names a file that is there, so a tick begins before a move and
runs on after it; the commits after it hold the program as it is.
"""

from collections import namedtuple
import json
import os
import sys
import threading
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.akinstall import Install

# the first version's bin/ak: the program beside it, run in the folder this began in, whatever
# is at its path by then
HOLDING = """#!/bin/sh
cd "$(dirname "$0")/.." || exit 1
if [ -n "${HOLD-}" ]; then
  : >"$HOLD.waiting"
  while [ -e "$HOLD" ]; do sleep 0.05; done
fi
exec bin/program "$@"
"""

Tick = namedtuple("Tick", "code err head kept completed")


class AMoveIsFinalOnceItsVersionTicks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        cls.install = install = Install(home)
        program, ak = install.seed / "bin" / "program", install.seed / "bin" / "ak"
        ak.rename(program)
        ak.write_text(HOLDING)
        ak.chmod(0o755)
        first = install.advance()
        install.git("fetch", "-q", "origin")
        install.git("reset", "-q", "--hard", first)
        program.rename(ak)
        cls.second = install.advance()
        hold = home.root / "hold"
        hold.touch()
        held = []
        old = threading.Thread(target=lambda: held.append(home.run(
            install.ak, "watch", env={"HOLD": str(hold)}, timeout=300)))
        old.start()
        until = time.monotonic() + 120
        while not Path(f"{hold}.waiting").exists() and time.monotonic() < until:
            time.sleep(0.05)
        cls.moved = cls.tick()
        cls.replaced, cls.released = cls.moved.kept, time.time()
        hold.unlink()
        old.join()
        done, = held
        cls.old = Tick(done.code, done.err, *cls.after())
        cls.third = install.advance()
        cls.final = cls.tick()
        cls.stayed = bool(cls.replaced) and (cls.replaced / "bin" / "ak").is_file()
        cls.next = cls.tick()

    @classmethod
    def after(cls):
        """Where ~/agentkit stands, the folder the link names, and when a tick last completed."""
        link = cls.home.path / ".agentkit" / "tmp" / "keep" / "ak"
        watch = cls.home.path / ".agentkit" / "state" / "watch.json"
        try:
            completed = json.loads(watch.read_text()).get("tick_completed_at") or 0
        except (OSError, ValueError):
            completed = 0
        kept = Path(os.readlink(link)).parents[1] if link.is_symlink() else None
        return cls.install.head(), kept, completed

    @classmethod
    def tick(cls):
        """One `ak watch` of the live copy, and where it left things."""
        done = cls.home.run(cls.install.ak, "watch", timeout=300)
        return Tick(done.code, done.err, *cls.after())

    def test_a_tick_of_the_new_version_makes_the_move_final(self):
        self.assertIsNotNone(self.replaced)
        self.assertEqual(self.final.code, 0, self.final.err)
        self.assertIsNone(self.final.kept)
        self.assertEqual(self.next.code, 0, self.next.err)
        self.assertEqual(self.next.head, self.third)

    def test_a_tick_of_the_version_replaced_proves_nothing(self):
        self.assertEqual(self.moved.code, 0, self.moved.err)
        self.assertEqual(self.moved.head, self.second)
        self.assertIsNotNone(self.replaced)
        self.assertEqual(self.old.code, 0, self.old.err)
        self.assertGreaterEqual(self.old.completed, self.released)
        self.assertEqual(self.old.kept, self.replaced)

    def test_no_move_starts_while_the_move_is_kept(self):
        self.assertEqual(self.final.code, 0, self.final.err)
        self.assertEqual(self.install.origin(), self.third)
        self.assertEqual(self.final.head, self.second)
        self.assertTrue(self.stayed)


if __name__ == "__main__":
    unittest.main()
