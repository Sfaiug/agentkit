"""A Muse login costs what its last usage frame's plan lists.  Muse's `login-end` names no plan,
so the plan is the one its usage answer last named (`plan` in what adapters/muse-usage.sh
prints): an answer holding `plan` read a frame and sets it, null included, its meters there or
not, and nothing else changes it: a failed probe, which read none, has no key.  `ak usage
--json` gives the login's `plan` and `price` by it, and `ak usage` its price under `a month`:
High Usage is $15.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, the
`muse` harness being tests/fixtures/meters.py's script beside its shipped manifest, its login
written into the Home as `login-end` answers it, on a terminal wide enough for the whole table.
Each answer is read afresh: the provider's probe lock and the snapshot are dated back past their
cadence, as tests/test_key_a_refilled_login_is_used_again.py does.  Fails against /bin/false.
"""

import json
from pathlib import Path
import shutil
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home

STATE = ".agentkit/state"
UNSAID = object()   # an answer without the key `plan`
FAILED = "unknown: responses probe returned HTTP 503"   # a probe that read no frame
PASSED = "unknown: no current subscription meters"      # a frame whose meters have all reset


class MusePlan(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.meter = meters.install(self.home)
        shutil.copy2(self.meter.dir / "echo.sh", self.meter.dir / "muse.sh")
        akconfig.write(self.home, {"spark": "muse"},
                       providers={"meta": {"mode": "subscription"}})
        self.home.write(f"{STATE}/logins.json", {"meta": {"default": {
            "email": "owner@meta.test", "ends": None, "plan": None,
            "checked_at": time.time()}}})

    def answer(self, plan=UNSAID, *, error=None):
        """(`plan` and `price` on `ak usage --json`, `a month` on `ak usage`) once the login's
        usage is read afresh, answering a week with `plan` (none without it), or for an `error`
        no meters."""
        said = {} if plan is UNSAID else {"plan": plan}
        if error:
            (self.meter.dir / "meta.default.usage.json").write_text(json.dumps(
                {"meters": [], "error": error, **said}))
        else:
            self.meter.week("meta", used=40, **said)
        snapshot = self.home.path / STATE / "usage.json"
        if snapshot.exists():
            self.home.write(f"{STATE}/usage.json",
                            {**json.loads(snapshot.read_text()), "fetched_at": 0})
        self.home.write(f"{STATE}/meta-probe.lock", "0")
        data = self.home.ak("usage", "--json")
        self.assertEqual(data.code, 0, data.out + data.err)
        text = self.home.ak("usage", env={"COLUMNS": "200"})
        self.assertEqual(text.code, 0, text.out + text.err)
        login = json.loads(data.out)["providers"]["meta"]
        return login["plan"], login["price"], meters.cell(text.out, "Muse", "a month")

    def test_a_frame_naming_its_plan_prices_the_login_until_another_names_one(self):
        self.assertEqual(self.answer("High Usage"), ("High Usage", 15, "$15"))
        self.assertEqual(self.answer(), ("High Usage", 15, "$15"))
        self.assertEqual(self.answer(error=FAILED), ("High Usage", 15, "$15"))
        self.assertEqual(self.answer(None), (None, None, "-"))

    def test_a_frame_naming_no_plan_leaves_the_login_unpriced(self):
        self.assertEqual(self.answer("High Usage"), ("High Usage", 15, "$15"))
        self.assertEqual(self.answer(None), (None, None, "-"))
        self.assertEqual(self.answer(), (None, None, "-"))
        self.assertEqual(self.answer(error=FAILED), (None, None, "-"))
        self.assertEqual(self.answer("High Usage", error=PASSED), ("High Usage", 15, "$15"))


if __name__ == "__main__":
    unittest.main()
