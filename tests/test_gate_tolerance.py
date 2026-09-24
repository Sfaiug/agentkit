"""A smoke check that reads a live provider meter tolerates a rate-limited answer.

Checks 1 and 6 stand on live meters: when a probe answers 429, 5xx or nothing at
all, the check asks once more (AK_METER_RETRY_SECS later, 0 here) and then skips
with the provider's own reason, and the gate counts that skip as a pass. A meter
that answers wrong still fails, with no retry. Entirely offline: the `ak usage`
under test runs against fake adapters in a throwaway HOME, and the check bodies
are the suite's own, extracted from tests/smoke.sh.
"""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SMOKE = (REPO / "tests/smoke.sh").read_text()
CHECK_1 = SMOKE[SMOKE.index("# --- 1: usage"):SMOKE.index("# --- 2:")]
# Checks 6 and 6b together: 6b reads the ORCHHOME fixtures and logs check 6 builds, so a
# test that slices 6 off alone proves the skip while proving nothing about its consumers.
CHECK_6 = SMOKE[SMOKE.index("# --- 6: orch"):SMOKE.index("# --- 6c:")]

FAR_FUTURE = 1999999999


def meters(provider, used=8):
    return {"provider": provider, "error": None, "meters": [
        {"name": "weekly_all", "used": used, "resets_at": FAR_FUTURE,
         "window_secs": 604800},
        {"name": "weekly_scoped", "used": used, "resets_at": FAR_FUTURE,
         "window_secs": 604800}]}


def refused(provider, reason):
    return {"provider": provider, "meters": [], "error": reason}


class GateTolerance(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".gate-tolerance-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.adapters = self.root / "adapters"
        self.adapters.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        # A check that escapes its skip must still never reach a real tmux server.
        tmux = bin_dir / "tmux"
        tmux.write_text("#!/bin/sh\nexit 1\n")
        tmux.chmod(0o755)
        # Installed as far as the checks ask, whatever this host has, and never run: the
        # meters are the fake adapters', and so is the login each check asks about first.
        for name in ("claude", "codex", "muse"):
            harness = bin_dir / name
            harness.write_text('#!/bin/sh\necho "unexpected harness call: $0" >&2\nexit 97\n')
            harness.chmod(0o755)
        self.env = {**os.environ, "HOME": str(self.home), "WORK": str(self.root),
                    "PATH": f"{bin_dir}:{REPO / 'bin'}:{os.environ['PATH']}",
                    "PYTHONDONTWRITEBYTECODE": "1", "TMUX": "",
                    "AGENTKIT_SESSION": "", "AK_RUN_ROLE": "",
                    "AGENTKIT_DISCORD_WEBHOOK": "off",
                    "AGENTKIT_ADAPTER_DIR": str(self.adapters),
                    "AK_METER_RETRY_SECS": "0"}

    def adapter(self, harness, first, then=None, login=True):
        """A usage adapter answering `first`, then `then` from its second probe on.

        `login=False` is a host with the harness but none of its login: `auth` says the
        credential file is not there, which is what a check skips as not on this host.
        """
        if login:
            auth, code = "fixture: logged in", 0
        else:
            auth, code = f"{harness}: no {self.home}/.{harness}/auth.json; run {harness} login", 1
        first_path = self.root / f"{harness}-first.json"
        first_path.write_text(json.dumps(first))
        if then is None:
            then_path = first_path
        else:
            then_path = self.root / f"{harness}-then.json"
            then_path.write_text(json.dumps(then))
        count = self.root / f"{harness}.count"
        script = self.adapters / f"{harness}.sh"
        script.write_text(
            "#!/bin/bash\n"
            f"COUNT={shlex.quote(str(count))}\n"
            f"FIRST={shlex.quote(str(first_path))}\n"
            f"THEN={shlex.quote(str(then_path))}\n"
            'if [ "${1:-}" = usage ]; then\n'
            '  if [ -f "$COUNT" ]; then cat "$THEN"; else cat "$FIRST"; fi\n'
            '  echo usage >>"$COUNT"\n'
            "  exit 0\n"
            "fi\n"
            'if [ "${1:-}" = reset-status ]; then printf \'{\"available\": 0}\\n\'; exit 0; fi\n'
            f'if [ "${{1:-}}" = auth ]; then echo {shlex.quote(auth)}; exit {code}; fi\n'
            # Every other verb is the real adapter's offline half (`interactive` prints a
            # command line for `ak orch`); `reset` stays refused so no fixture can spend one.
            'if [ "${1:-}" = reset ]; then exit 2; fi\n'
            f'exec {shlex.quote(str(REPO / "adapters" / f"{harness}.sh"))} "$@"\n')
        script.chmod(0o755)
        return count

    def healthy(self):
        return {"claude": self.adapter("claude", meters("anthropic")),
                "codex": self.adapter("codex", meters("openai", 45)),
                "muse": self.adapter("muse", meters("meta", 40))}

    def shell(self, block, **env):
        script = 'set -uo pipefail\n. "$REPO/tests/acceptance.sh"\n' + block + '\nfinish\n'
        return subprocess.run(["/bin/bash", "-c", script], cwd=self.root,
                              env={**self.env, "REPO": str(REPO), **env},
                              text=True, capture_output=True, timeout=120)

    def probes(self, harness):
        count = self.root / f"{harness}.count"
        return count.read_text().split() if count.exists() else []

    def test_429_skips_with_reason_after_one_retry(self):
        counts = self.healthy()
        counts["claude"] = self.adapter(
            "claude", refused("anthropic", "unknown: HTTP 429 from "
                             "api.anthropic.com/api/oauth/usage; token may be expired"))
        result = self.shell(CHECK_1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIP  1: provider meter unavailable (", result.stdout)
        self.assertIn("HTTP 429", result.stdout)
        self.assertNotIn("FAIL", result.stdout)
        self.assertEqual(self.probes("claude"), ["usage", "usage"])
        self.assertEqual(self.probes("codex"), ["usage", "usage"])

    def test_5xx_skips_with_reason_after_one_retry(self):
        self.adapter("claude", meters("anthropic"))
        self.adapter("codex", refused("openai", "unknown: HTTP 503 from "
                                      "chatgpt.com/backend-api/wham/usage"))
        self.adapter("muse", meters("meta", 40))
        result = self.shell(CHECK_1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIP  1: provider meter unavailable (", result.stdout)
        self.assertIn("HTTP 503", result.stdout)
        self.assertEqual(self.probes("claude"), ["usage", "usage"])

    def test_timeout_skips_with_reason_after_one_retry(self):
        self.adapter("claude", refused("anthropic", "unknown: claude.sh usage "
                                                    "timed out after 30s"))
        self.adapter("codex", meters("openai", 45))
        self.adapter("muse", meters("meta", 40))
        result = self.shell(CHECK_1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIP  1: provider meter unavailable (", result.stdout)
        self.assertIn("timed out", result.stdout)
        self.assertEqual(self.probes("claude"), ["usage", "usage"])

    def test_wrong_value_with_healthy_meter_still_fails_without_retry(self):
        self.adapter("claude", {"provider": "anthropic", "meters": [], "error": None})
        self.adapter("codex", meters("openai", 45))
        self.adapter("muse", meters("meta", 40))
        result = self.shell(CHECK_1)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("FAIL  1 ak usage --json", result.stdout)
        self.assertNotIn("provider meter unavailable", result.stdout)
        self.assertIn("0 passed, 1 failed, 0 skipped", result.stdout)
        self.assertEqual(self.probes("claude"), ["usage"])

    def test_acceptance_summary_counts_meter_skip_as_passed(self):
        self.adapter("claude", refused("anthropic", "unknown: HTTP 429 from "
                                                   "api.anthropic.com/api/oauth/usage"))
        self.adapter("codex", meters("openai", 45))
        self.adapter("muse", meters("meta", 40))
        result = self.shell(CHECK_1, AGENTKIT_ACCEPTANCE_REQUIRED="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 passed, 0 failed, 0 skipped", result.stdout)
        last = result.stdout.strip().splitlines()[-1]
        self.assertIn("1 provider-meter skip counted as passed", last)

    def test_a_harness_with_no_login_here_skips_by_name_and_the_gate_passes(self):
        # A Claude-only host: Codex's and Muse's meters have no login to read, and nothing
        # to retry.
        self.adapter("claude", meters("anthropic"))
        self.adapter("codex", refused("openai", "unknown: no ChatGPT login"), login=False)
        self.adapter("muse", refused("meta", "unknown: no Muse login"), login=False)
        result = self.shell(CHECK_1, AGENTKIT_ACCEPTANCE_REQUIRED="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIP  1: required model astra is not on this host: codex: no ",
                      result.stdout)
        self.assertNotIn("FAIL", result.stdout)
        self.assertIn("1 passed, 0 failed, 0 skipped", result.stdout)
        last = result.stdout.strip().splitlines()[-1]
        self.assertIn("1 skip for what this host lacks counted as passed", last)
        self.assertEqual(self.probes("codex"), ["usage"])

    def test_retry_that_gets_an_answer_passes(self):
        self.adapter("claude", refused("anthropic", "unknown: HTTP 429 from "
                                                  "api.anthropic.com/api/oauth/usage"),
                     then=meters("anthropic"))
        self.adapter("codex", meters("openai", 45))
        self.adapter("muse", meters("meta", 40))
        result = self.shell(CHECK_1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS  1 ak usage --json", result.stdout)
        self.assertEqual(self.probes("claude"), ["usage", "usage"])

    def usage_json(self):
        """A real `ak usage --json` against the fake adapters, saved as this run's $U."""
        result = subprocess.run([str(REPO / "bin/ak"), "usage", "--json"], cwd=self.root,
                                env={**self.env, "REPO": str(REPO)},
                                text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (self.root / "usage.json").write_text(result.stdout)
        return result.stdout

    def test_orch_pick_skips_when_the_meter_it_stands_on_is_down(self):
        (self.root / "usage.json").write_text(json.dumps({
            "pick_order": [], "providers": {
                "anthropic": refused("anthropic", "unknown: HTTP 429 from "
                                                  "api.anthropic.com/api/oauth/usage"),
                "openai": {"meters": [], "error": None, "exhausted": False},
                "meta": {"meters": [], "error": None, "exhausted": False}}}))
        self.adapter("claude", refused("anthropic", "unknown: HTTP 429 from "
                                                  "api.anthropic.com/api/oauth/usage"))
        self.adapter("codex", meters("openai", 45))
        self.adapter("muse", meters("meta", 40))
        result = self.shell(CHECK_6, U=str(self.root / "usage.json"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIP  6: provider meter unavailable (", result.stdout)
        self.assertIn("HTTP 429", result.stdout)
        # 6b names its models explicitly and asserts command shape, not the pick, so its
        # prerequisites run above the gate and it still passes on a throttled meter.
        self.assertIn("PASS  6b ak orch", result.stdout)
        self.assertNotIn("FAIL", result.stdout)
        self.assertIn("2 passed, 0 failed, 0 skipped", result.stdout)
        last = result.stdout.strip().splitlines()[-1]
        self.assertIn("1 provider-meter skip counted as passed", last)
        self.assertEqual(self.probes("claude"), ["usage"])

    def test_other_provider_timeout_does_not_mask_a_wrong_value(self):
        # Anthropic answered and its value is wrong; meta's local probe timing out beside
        # it is not a throttled meter and must not turn this failure into a skip.
        self.adapter("claude", {"provider": "anthropic", "meters": [], "error": None})
        self.adapter("codex", meters("openai", 45))
        self.adapter("muse", refused("meta", "unknown: Muse usage probe timed out"))
        result = self.shell(CHECK_1)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("FAIL  1 ak usage --json", result.stdout)
        self.assertNotIn("provider meter unavailable", result.stdout)
        self.assertEqual(self.probes("claude"), ["usage"])

    def test_meter_skip_names_the_down_provider_not_a_bystander(self):
        self.adapter("claude", refused("anthropic", "unknown: HTTP 429 from "
                                                  "api.anthropic.com/api/oauth/usage"))
        self.adapter("codex", meters("openai", 45))
        self.adapter("muse", refused("meta", "unknown: Muse usage probe timed out"))
        result = self.shell(CHECK_1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIP  1: provider meter unavailable (", result.stdout)
        self.assertIn("HTTP 429", result.stdout)
        self.assertNotIn("Muse usage probe", result.stdout)

    def test_healthy_pick_runs_despite_a_bystander_timeout(self):
        # Only anthropic and openai feed check 6's pick; a timed-out meta probe beside
        # healthy meters must not skip the coverage the check exists to prove.
        self.adapter("claude", meters("anthropic"))
        self.adapter("codex", meters("openai", 45))
        self.adapter("muse", refused("meta", "unknown: Muse usage probe timed out"))
        self.usage_json()
        result = self.shell(CHECK_6, U=str(self.root / "usage.json"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS  6 ak orch --dry-run", result.stdout)
        self.assertIn("PASS  6b ak orch", result.stdout)
        self.assertNotIn("SKIP", result.stdout)


if __name__ == "__main__":
    unittest.main()
