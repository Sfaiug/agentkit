"""A quota refusal spends the reset credit of the subscription that was refused, not the usual one.

A provider listing `accounts` runs a worker turn on the one with room; when that account is
refused for quota and no other has room, the reset policy is asked at once.  The credit it
spends is the refused account's: the usual login's week is not the one that ran out.  A fake
adapter in a temporary HOME records the account each verb was told, and a fake worker call
refuses the first turn; nothing real is asked or spent.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run  # noqa: E402

# The usual login's week is spent, the second's half; each holds one reset credit.
ADAPTER = """#!/usr/bin/env bash
printf '%s %s\\n' "$1" "${AGENTKIT_ACCOUNT:-default}" >>"$FAKE/told"
case $1 in
  usage) used=$([ -n "${AGENTKIT_ACCOUNT:-}" ] && echo 50 || echo 100)
         printf '{"meters":[{"name":"weekly","used":%s,"resets_at":%s,"window_secs":604800}]}\\n' \\
             "$used" "$(( $(date +%s) + 86400 ))" ;;
  reset-status) printf '{"available":1}\\n' ;;
  reset) printf '{"code":"reset","available":0}\\n' ;;
  *) exit 2 ;;
esac
"""

MANIFEST = """[usage]
reset = true

[stall]
quotas = ["usage limit reached"]
"""

CONFIG = """[defaults]
orchestrator = "one"
workers = ["one"]

[models.one]
harness = "fake"
model = "m-one"
effort = "high"
provider = "alpha"

[providers.alpha]
accounts = ["default", "second"]
"""


class RefusedSubscription(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-named-subscription-")
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name)
        self.fake = root / "fake"
        self.fake.mkdir()
        adapter = self.fake / "fake.sh"
        adapter.write_text(ADAPTER)
        adapter.chmod(0o755)
        (self.fake / "fake.toml").write_text(MANIFEST)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, key, root / key.lower()))
        env = {k: v for k, v in os.environ.items()
               if k not in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_ACCOUNT")}
        env.update(HOME=str(root), FAKE=str(self.fake), AK_RUN_DEPTH="0", AK_MAX_RUNS="0",
                   AGENTKIT_DISCORD_WEBHOOK="off", **{config.ADAPTER_DIR_ENV: str(self.fake)})
        stack.enter_context(patch.dict(os.environ, env, clear=True))
        config.ensure_dirs()
        (config.HOME / "config.toml").write_text(CONFIG)
        self.cfg = config.load()
        self.ran_on = []

    def call(self, cfg, name, text, workspace, out, role, session, env=None, **_kw):
        """The first turn is refused for quota, as a spent window is; the next one answers."""
        self.ran_on.append(env.get(config.ACCOUNT_ENV) or "default")
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        if len(self.ran_on) == 1:
            return 1, "Claude AI usage limit reached", "s1", False
        return 0, "## Summary\nDone.\n", "s1", False

    def test_a_refusal_on_the_second_spends_the_second_s_credit(self):
        out = self.root / "run" / "round-1" / "executor"
        out.parent.mkdir(parents=True)
        lines = []
        with patch.object(run.worker, "call", side_effect=self.call):
            code, _, _, _ = run.call_retrying(self.cfg, "one", "Do the task.", self.root, out,
                                              "executor", None, lines.append, limit=120)
        self.assertEqual((code, self.ran_on[0]), (0, "second"), lines)
        told = (self.fake / "told").read_text().splitlines()
        self.assertEqual([line for line in told if line.startswith("reset ")],
                         ["reset second"], lines)


if __name__ == "__main__":
    unittest.main()
