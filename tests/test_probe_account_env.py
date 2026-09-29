"""A usage probe names its account to the adapter, the empty one included.

A turn on a named subscription carries `AGENTKIT_ACCOUNT=<name>` in its environment, and
anything it runs inherits it.  A provider that lists no `accounts` has one login, the usual one,
so its probe must name the empty account rather than pass the caller's on: otherwise a seat on
a second Claude subscription asks every other company's adapter about a login it never had.
A fake adapter in a temporary directory records the name it was told; nothing real is asked.
"""

import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import usage  # noqa: E402

# `unset` only when the variable is absent altogether, so an empty name reads as itself.
ADAPTER = """#!/usr/bin/env bash
printf '%s' "${AGENTKIT_ACCOUNT-unset}" >"$FAKE/told"
printf '{"meters":[{"name":"weekly","used":10}]}\\n'
"""

CFG = {"models": {"one": {"harness": "fake", "model": "m-one", "effort": "high",
                          "provider": "alpha"}},
       "providers": {"alpha": {}}}


class ProbeAccountEnv(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-probe-account-")
        self.addCleanup(tmp.cleanup)
        self.fake = Path(tmp.name)
        adapter = self.fake / "fake.sh"
        adapter.write_text(ADAPTER)
        adapter.chmod(0o755)
        env = patch.dict(os.environ, {"AGENTKIT_ADAPTER_DIR": str(self.fake),
                                      "FAKE": str(self.fake), "AGENTKIT_ACCOUNT": "second"})
        env.start()
        self.addCleanup(env.stop)

    def told(self, account=None):
        prov = usage._probe(CFG, "alpha", time.time(), account)
        self.assertEqual([m["name"] for m in prov["meters"]], ["weekly"], prov)
        return (self.fake / "told").read_text()

    def test_a_provider_without_accounts_is_asked_about_the_usual_login(self):
        self.assertEqual(self.told(), "")

    def test_a_named_account_is_asked_about_itself(self):
        self.assertEqual(self.told("third"), "third")
        self.assertEqual(self.told("default"), "")


if __name__ == "__main__":
    unittest.main()
