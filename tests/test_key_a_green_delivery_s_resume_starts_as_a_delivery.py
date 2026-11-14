"""A member parked in a line with a green verdict, resumed as the line resumes it, is a delivery
from its resume's first step: the first weight it asks of its unit is the line check's, it asks
for the idle class nowhere before its merge, and it starts no harness, as the saved pair it
delivers runs no model.

Idle, a delivery beside a line's check took 82 s from its wake to the line naming its models, read
every provider's usage and asked each harness if it could run, for picks it never made (14 Nov
2026).  Black-box, on the fixture of tests/test_key_a_delivering_run_has_the_landing_weight.py,
whose systemd-run notes, as a resume's scope starts, how many calls the manager and each harness
have had.
"""

import json
import unittest

from test_key_a_delivering_run_has_the_landing_weight import Delivery

RESUMED = '''if args[-2] == "resume":
    import json
    root = pathlib.Path({root})
    logs = [root / "logs" / "systemctl.log", *root.glob("adapters/*.calls")]
    (root / "resumed").write_text(json.dumps(dict(
        (log.name, len(log.read_text().splitlines())) for log in logs)))
'''


class AGreenDeliverySResumeStartsAsADelivery(Delivery, unittest.TestCase):
    starts = RESUMED

    def test_its_first_weight_is_the_checks_and_it_starts_no_harness(self):
        unit = self.deliver()["scope"]
        before = json.loads((self.home.root / "resumed").read_text())
        weights = [argv[-1] for argv in self.home.calls("systemctl")[before["systemctl.log"]:]
                   if argv[:4] == ["--user", "set-property", "--runtime", f"{unit}.scope"]]
        self.assertEqual(weights[:1], ["CPUWeight=10000"], weights)
        self.assertNotIn("CPUWeight=idle", weights)
        started = [call for log in (self.home.root / "adapters").glob("*.calls")
                   for call in log.read_text().splitlines()[before.get(log.name, 0):]]
        self.assertEqual(started, [])


if __name__ == "__main__":
    unittest.main()
