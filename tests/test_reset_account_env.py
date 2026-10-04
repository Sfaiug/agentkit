"""A reset count and a reset spend name their account to the adapter, the empty one included.

A turn on a named subscription carries `AGENTKIT_ACCOUNT=<name>` in its environment, and
anything it runs inherits it.  `reset-status` and `reset` are asked about the login the
reading they belong to was taken on: the usual one for a provider or a record that names none,
else its own account -- never the caller's.  A fake adapter in a temporary HOME records the
name each verb was told; nothing real is asked or spent.
"""

import os
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, usage  # noqa: E402

# `unset` only when the variable is absent altogether, so an empty name reads as itself.
ADAPTER = """#!/usr/bin/env bash
printf '%s' "${AGENTKIT_ACCOUNT-unset}" >"$FAKE/told-$1"
case $1 in
  usage) printf '{"meters":[{"name":"weekly","used":10}]}\\n' ;;
  reset-status) printf '{"available":1}\\n' ;;
  *) printf '{"error":"no reset was applied"}\\n' ;;
esac
"""

CFG = {"models": {"one": {"harness": "fake", "model": "m-one", "effort": "high",
                          "provider": "alpha"}},
       "providers": {"alpha": {}}}


class ResetAccountEnv(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-reset-account-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.fake = root / "fake"
        self.fake.mkdir()
        adapter = self.fake / "fake.sh"
        adapter.write_text(ADAPTER)
        adapter.chmod(0o755)
        (self.fake / "fake.toml").write_text("[usage]\nreset = true\n")
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            stack.enter_context(patch.object(config, name, root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), config.ADAPTER_DIR_ENV: str(self.fake), "FAKE": str(self.fake),
            config.ACCOUNT_ENV: "second"}))

    def told(self, verb):
        return (self.fake / f"told-{verb}").read_text()

    def test_a_probe_counts_the_resets_of_its_own_account(self):
        for account, name in ((None, ""), ("default", ""), ("third", "third")):
            prov = usage._probe(CFG, "alpha", time.time(), account)
            self.assertEqual(prov["resets"], 1.0, prov)
            self.assertEqual(self.told("reset-status"), name, account)

    def test_a_reset_is_spent_on_the_account_its_count_was_read_for(self):
        week = {"window_secs": 7 * 86400, "used": 95}
        for account, name in ((None, ""), ("default", ""), ("third", "third")):
            prov = {"provider": "alpha", "harness": "fake", "meters": [week], "resets": 1}
            with patch.object(usage, "_probe_gently", return_value=prov):
                self.assertEqual(usage.replenish(CFG, "alpha", account=account), (False, 1.0))
            self.assertEqual(self.told("reset"), name, account)


if __name__ == "__main__":
    unittest.main()
