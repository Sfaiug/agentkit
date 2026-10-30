"""Several suites share the suite helper, each VM placed by the VMs running there: ak's together
get at most half of what would be free without them. Offline: test_suite_helper.py's fake Mac,
8 GiB free and 9 spare CPUs, where each VM holds half the memory it was given.
"""

import subprocess
import time
import unittest

import test_suite_helper as fixture
from agentkit import helper


class SeveralSuites(unittest.TestCase):
    setUp, git = fixture.HelperMac.setUp, fixture.HelperMac.git

    def piece(self, key, name, memory):
        """`run` of a piece of suite `key` in a VM `name` of `memory` MiB, started."""
        for path in (key, "mirrors/acme"):
            (self.root / path).mkdir(parents=True, exist_ok=True)
        return subprocess.Popen(helper._remote("acme-mac", "run", key, "ak-helper:new", name, 1,
                                               memory, "acme"), stdout=subprocess.DEVNULL)

    def up(self, name):
        deadline = time.monotonic() + 30
        while not (self.fake / f"vm-{name}").exists():
            self.assertLess(time.monotonic(), deadline, f"{name} never came up")
            time.sleep(0.1)
        return self.fake / f"vm-{name}"

    def test_a_second_suite_is_placed_with_what_the_first_left(self):
        first = self.piece("first", "ak-first-1-1", 2048)
        running = self.up("ak-first-1-1")
        # half of 8 GiB free and the 1 GiB the first's VM holds, less the 2 GiB it was given
        self.assertEqual(helper.room("acme-mac", 1.0, 500), ((2, 4, 1000, 5, 9), ""))
        second = self.piece("second", "ak-second-1-2", 1000)
        self.up("ak-second-1-2").unlink()
        running.unlink()
        self.assertEqual((first.wait(30), second.wait(30)), (0, 0))

    def test_pieces_admitted_at_once_never_get_more_than_the_budget_together(self):
        # 4 GiB is left: each of two 3000 MiB VMs fits alone, both together do not
        pieces = {name: self.piece("first", name, 3000) for name in ("ak-first-1-2",
                                                                     "ak-first-2-2")}
        deadline = time.monotonic() + 30
        while all(piece.poll() is None for piece in pieces.values()):
            self.assertLess(time.monotonic(), deadline, "neither piece was turned away")
            time.sleep(0.1)
        full, = [name for name, piece in pieces.items() if piece.poll() is not None]
        self.assertEqual(pieces.pop(full).returncode, helper.FULL)
        (name, admitted), = pieces.items()
        self.up(name).unlink()
        self.assertEqual(admitted.wait(30), 0)

    def test_a_vm_that_ended_no_longer_counts(self):
        for name in ("ak-first-1-1", "ak-second-1-1"):
            piece = self.piece(name.split("-")[1], name, 3000)
            self.up(name).unlink()
            self.assertEqual(piece.wait(30), 0)
        self.assertEqual(helper.room("acme-mac", 1.0, 1500), ((1, 9, 3000, 5, 9), ""))


if __name__ == "__main__":
    unittest.main()
