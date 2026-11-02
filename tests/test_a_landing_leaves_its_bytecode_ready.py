"""A landing leaves bytecode Python will load, in place as the version goes live."""

import importlib.util
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_a_landing_restarts_a_menu_once as landing


def stale(version):
    """The modules of `version` Python would compile again: bytecode names its source's time."""
    for source in (version / "agentkit").rglob("*.py"):
        cached, read = Path(importlib.util.cache_from_source(source)), source.stat()
        stamp = struct.pack("<4sLLL", importlib.util.MAGIC_NUMBER, 0, int(read.st_mtime), read.st_size)
        if not cached.exists() or cached.read_bytes()[:16] != stamp:
            yield source.name


class ALandingLeavesItsBytecodeReady(unittest.TestCase):
    setUp, commit = landing.ALandingRestartsAMenuOnce.setUp, landing.ALandingRestartsAMenuOnce.commit
    change, land = landing.ALandingRestartsAMenuOnce.change, landing.ALandingRestartsAMenuOnce.land

    def ready(self, name):
        told = []
        with patch.object(sys, "pycache_prefix", None):
            self.land(name, after=lambda: told.extend(stale(self.clone)))
        self.assertEqual(told, [])

    def test_a_landing_with_code(self):
        self.ready("agentkit/acme.py")

    def test_a_landing_keeping_the_modules_times(self):
        self.ready("docs/acme.md")

    def test_a_cache_prefix_gets_it_only_once_the_version_is_live(self):
        prefix, early = self.root / "pycache", []
        filed = prefix.joinpath(*self.clone.parts[1:])     # the old source reads what is here
        with patch.object(sys, "pycache_prefix", str(prefix)):
            self.land("agentkit/acme.py", before=lambda: early.append(filed.exists()))
            self.assertEqual(list(stale(self.clone)), [])
        self.assertEqual(early, [False])


if __name__ == "__main__":
    unittest.main()
