"""A seat holding a core is one row of `ak run status` while both its names hold its record."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home


class ACoreHolderIsOneSeatByItsRecord(unittest.TestCase):
    def test_a_seat_whose_rename_is_half_written_is_one_row(self):
        with Home() as home:
            for name, made in (("fix-api", 1800000000.5), ("parser", 1800000000.5), ("acme", 9.5)):
                home.write(f".agentkit/state/session-{name}.json", {"created": made})
            home.write(".agentkit/state/watch.json", {"seat_cores": {
                "agentkit-seat-fix-api-89abcdef.scope": {"at": 720, "since": 180},
                "agentkit-seat-parser-0123abcd.scope": {"at": 720, "since": 360},
                "agentkit-seat-acme-4567abcd.scope": {"at": 720, "since": 540}}})
            done = home.ak("run", "status")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual([line.split(": ")[1] for line in done.out.splitlines()
                          if line.startswith("seats holding")], ["fix-api 9m · acme 3m"])


if __name__ == "__main__":
    unittest.main()
