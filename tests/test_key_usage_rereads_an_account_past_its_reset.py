"""A fresh usage snapshot holding a meter past its reset on an account the provider is not on now
is read again, as one on the account it is on is: `ak usage` shows that account's new week, and a
new seat's preview runs on the account with room.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, its one harness the meter fixture (tests/fixtures/meters.py).
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home


class UsageRereadsAnAccountPastItsReset(unittest.TestCase):
    def test_an_account_past_its_reset_is_read_again(self):
        home = Home()
        self.addCleanup(home.close)
        fixture = meters.install(home)
        fixture.week("test", "shoal", used=100)
        fixture.week("test", "reef", used=20)
        akconfig.write(home, {"acme": {"harness": "echo", "model": "echo-1", "provider": "test"}},
                       providers={"test": {"mode": "subscription", "accounts": ["shoal", "reef"]}})
        first = home.ak("usage", "--json")
        self.assertEqual(first.code, 0, first)
        snapshot = home.path / ".agentkit/state/usage.json"
        blob = json.loads(snapshot.read_text())
        self.assertEqual(blob["providers"]["test"]["account"], "reef")
        # shoal's week ends inside the snapshot's five minutes, and its probe is due again
        blob["providers"]["test"]["accounts"]["shoal"]["meters"][0]["resets_at"] = time.time() - 60
        snapshot.write_text(json.dumps(blob))
        (home.path / ".agentkit/state/test.shoal-probe.lock").write_text("0")
        shown = home.ak("usage", "--json")
        self.assertEqual(shown.code, 0, shown)
        shoal = json.loads(shown.out)["providers"]["test"]["accounts"]["shoal"]["meters"]
        self.assertEqual([meter["resets_at"] for meter in shoal], [fixture.resets_at])
        preview = home.ak("orch", "crew", "--model", "acme", "--workers", "acme", "--dry-run",
                          timeout=30)
        self.assertEqual(preview.code, 0, preview)


if __name__ == "__main__":
    unittest.main()
