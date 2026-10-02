"""A smoke check that reads a live provider meter tolerates a rate-limited answer.

Checks 1 and 6 stand on live meters: when a probe answers 429, 5xx or nothing at
all, the check asks once more where the host's cadence and Retry-After allow
(AK_METER_RETRY_SECS later, 0 here, so an immediate retry asks nothing) and then
skips with the provider's own reason, and the gate counts that skip as a pass. A
gate run never sends a request the host would hold back; where it therefore cannot
get a fresh answer it skips with that hold reason, as a 429 skips. A meter that
answers wrong still fails, with no retry. Check 3's skip stands on the same
account's spent-knowledge twice over: its own read, and where the shared cadence
holds that read empty, the host's own cache. Entirely offline: the `ak usage` under
test runs against fake adapters in a throwaway HOME, and the check bodies are the
suite's own, extracted from tests/smoke.sh.
"""

import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SMOKE = (REPO / "tests/smoke.sh").read_text()
CHECK_1 = SMOKE[SMOKE.index("# --- 1: usage"):SMOKE.index("# --- 2:")]
# Checks 6 and 6b together: 6b reads the ORCHHOME fixtures and logs check 6 builds, so a
# test that slices 6 off alone proves the skip while proving nothing about its consumers.
# The helpers live in check 1's section, so check 6 runs with them prepended: without that
# the slice calls `host_held`, `reprobe` and `skip_unavailable` as missing commands.
CHECK_1_PREAMBLE = CHECK_1[:CHECK_1.index('U="$WORK/usage.json"')]
CHECK_6 = CHECK_1_PREAMBLE + SMOKE[SMOKE.index("# --- 6: orch"):SMOKE.index("\nfi\n\n# --- 6c:")]
# The suite's own sandbox setup for the shared cadence: smoke_share_probes is defined just
# above smoke_home, so the slice between the two is the whole function.
SHARE = SMOKE[SMOKE.index("smoke_share_probes() {"):SMOKE.index("smoke_home() {")]
# Check 3's skip: the `ak usage` snapshot plus spent_until/skip_spent, up to the first
# live call. The helpers live in check 1's section, so the skip runs with them
# prepended, as check 6 does.
CHECK_3_SKIP = SMOKE[SMOKE.index('ak usage --json >"$WORK/usage-real.json"'):
                     SMOKE.index("printf 'Create a file hello.txt")]

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
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-gate-tolerance-", dir=REPO)
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

    def share(self, caller):
        """The suite's own setup: link this sandbox at a caller HOME standing in for
        the host. The caller HOME is set the way smoke.sh sets it, as a plain shell
        variable inside the block, never exported."""
        (self.home / ".agentkit/state").mkdir(parents=True, exist_ok=True)
        return (SHARE + f"SMOKE_CALLER_HOME={shlex.quote(str(caller))}\n"
                "smoke_share_probes\n")

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
        # The retry is inside every cadence, so it asks nothing: one ask, then the skip.
        self.assertEqual(self.probes("claude"), ["usage"])
        self.assertEqual(self.probes("codex"), ["usage"])

    def test_429_skip_passes_under_an_outer_suites_diversion(self):
        # Sourced inside a running suite, the check inherits that suite's diversion log; its
        # own `finish` reads only what this check diverted.
        outer = self.root / "outer-diversions.log"
        outer.write_text("an outer suite's diversion\n")
        self.env["AK_NOTIFY_SINK_LOG"] = str(outer)
        self.test_429_skips_with_reason_after_one_retry()

    def test_5xx_skips_with_reason_after_one_retry(self):
        self.adapter("claude", meters("anthropic"))
        self.adapter("codex", refused("openai", "unknown: HTTP 503 from "
                                      "chatgpt.com/backend-api/wham/usage"))
        self.adapter("muse", meters("meta", 40))
        result = self.shell(CHECK_1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIP  1: provider meter unavailable (", result.stdout)
        self.assertIn("HTTP 503", result.stdout)
        self.assertEqual(self.probes("claude"), ["usage"])

    def test_timeout_skips_with_reason_after_one_retry(self):
        self.adapter("claude", refused("anthropic", "unknown: claude.sh usage "
                                                    "timed out after 30s"))
        self.adapter("codex", meters("openai", 45))
        self.adapter("muse", meters("meta", 40))
        result = self.shell(CHECK_1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIP  1: provider meter unavailable (", result.stdout)
        self.assertIn("timed out", result.stdout)
        self.assertEqual(self.probes("claude"), ["usage"])

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

    # A spent window, and a refusal for quota, as check 3 and skip_refused word them.
    SPENT = {"spent window": "astra (codex): the openai subscription window is spent until "
                             "2026-10-06 09:00:00 UTC, so every call would be a 429",
             "quota refusal": "required model astra was refused: You've hit your usage limit"}

    def test_a_spent_window_skip_passes_beside_a_real_call_that_passed(self):
        # One real call that passed shows the checkout can still make one; a window that
        # resets in weeks is the provider's state, and holds no host on old code.
        for kind, why in self.SPENT.items():
            with self.subTest(kind):
                result = self.shell('ok_call "3c grok (grokbuild): replied PONG"\n'
                                    f'skip_spent_checks 3a/3b "{why}"\n',
                                    AGENTKIT_ACCEPTANCE_REQUIRED="1")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"SKIP  3a: {why}\nSKIP  3b: {why}\n", result.stdout)
                self.assertIn("3 passed, 0 failed, 0 skipped", result.stdout)
                last = result.stdout.strip().splitlines()[-1]
                self.assertIn("all checks exercised and passed; "
                              "2 spent-window skips counted as passed", last)
        # Beside it, every other skip counts as it did.
        result = self.shell('ok_call "3c grok (grokbuild): replied PONG"\n'
                            f'skip_spent_checks 3a "{self.SPENT["spent window"]}"\n'
                            'skip "4: prerequisite run did not happen"\n',
                            AGENTKIT_ACCEPTANCE_REQUIRED="1")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("2 passed, 0 failed, 1 skipped", result.stdout)
        self.assertIn("1 spent-window skip counted as passed", result.stdout)

    def test_a_spent_window_skip_holds_the_gate_with_no_real_call_passed(self):
        # Every window spent, or every call refused: nothing shows a real call can pass.
        for kind, why in self.SPENT.items():
            with self.subTest(kind):
                result = self.shell('ok "2 offline: an ak command answered"\n'
                                    f'skip_spent_checks 3a/3b "{why}"\n',
                                    AGENTKIT_ACCEPTANCE_REQUIRED="1")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("1 passed, 0 failed, 2 skipped", result.stdout)
                self.assertIn("acceptance: INCOMPLETE", result.stdout)
                self.assertNotIn("counted as passed", result.stdout)

    def test_retry_held_by_cadence_skips_without_asking(self):
        # The second answer would pass, but the retry is inside Claude's fifteen minutes,
        # so it is never asked for: one ask, then the skip with the first answer's reason.
        self.adapter("claude", refused("anthropic", "unknown: HTTP 429 from "
                                                  "api.anthropic.com/api/oauth/usage"),
                     then=meters("anthropic"))
        self.adapter("codex", meters("openai", 45))
        self.adapter("muse", meters("meta", 40))
        result = self.shell(CHECK_1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIP  1: provider meter unavailable (", result.stdout)
        self.assertIn("HTTP 429", result.stdout)
        self.assertNotIn("FAIL", result.stdout)
        self.assertEqual(self.probes("claude"), ["usage"])

    def test_host_cadence_holds_the_gate_without_asking(self):
        # The host asked Claude seconds ago: check 1 skips with that hold reason without
        # sending any request.
        caller = self.root / "caller"
        (caller / ".agentkit/state").mkdir(parents=True)
        (caller / ".agentkit/state/anthropic-probe.lock").write_text(repr(time.time()))
        self.healthy()
        result = self.shell(self.share(caller) + CHECK_1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIP  1: provider meter unavailable (", result.stdout)
        self.assertIn("next ask in", result.stdout)
        self.assertNotIn("FAIL", result.stdout)
        self.assertEqual(self.probes("claude"), [])
        self.assertEqual(self.probes("codex"), [])

    def test_held_check_1_leaves_no_ask_for_a_later_sandbox_read(self):
        # smoke_home links the sandbox at the host's own probe ages, so a later sandbox
        # ask (check 3's `ak usage`, an `ak run`, an `ak orch` seat) obeys the same hold
        # through _cooling.
        caller = self.root / "caller"
        (caller / ".agentkit/state").mkdir(parents=True)
        (caller / ".agentkit/state/anthropic-probe.lock").write_text(repr(time.time()))
        self.healthy()
        result = self.shell(self.share(caller) + CHECK_1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIP  1: provider meter unavailable (", result.stdout)
        self.assertEqual(self.probes("claude"), [])
        # Check 3's line, seconds later in the same sandbox HOME: Claude still held and
        # silent, while a provider the host never asked answers normally.
        later = subprocess.run([str(REPO / "bin/ak"), "usage", "--json"], cwd=self.root,
                               env={**self.env, "REPO": str(REPO)},
                               text=True, capture_output=True, timeout=120)
        self.assertEqual(later.returncode, 0, later.stdout + later.stderr)
        self.assertEqual(self.probes("claude"), [])
        self.assertEqual(self.probes("codex"), ["usage"])

    def test_host_ask_after_setup_holds_a_later_sandbox_ask(self):
        # The links are the host's own files, not copies of them: a host ask after the
        # sandbox is set up still holds a later sandbox ask, which then sends no request.
        caller = self.root / "caller"
        (caller / ".agentkit/state").mkdir(parents=True)
        self.healthy()
        setup = self.shell(self.share(caller))
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        link = self.home / ".agentkit/state/anthropic-probe.lock"
        self.assertTrue(link.is_symlink())
        self.assertEqual(Path(os.readlink(link)),
                         caller / ".agentkit/state/anthropic-probe.lock")
        # The host asks Claude, and is told by OpenAI to wait, seconds after setup.
        (caller / ".agentkit/state/anthropic-probe.lock").write_text(repr(time.time()))
        (caller / ".agentkit/state/openai-probe.retry").write_text(
            repr(time.time() + 600))
        later = subprocess.run([str(REPO / "bin/ak"), "usage", "--json"], cwd=self.root,
                               env={**self.env, "REPO": str(REPO)},
                               text=True, capture_output=True, timeout=120)
        self.assertEqual(later.returncode, 0, later.stdout + later.stderr)
        self.assertEqual(self.probes("claude"), [])
        self.assertEqual(self.probes("codex"), [])
        self.assertEqual(self.probes("muse"), ["usage"])

    def test_share_creates_a_missing_host_state_and_holds(self):
        # A host that has never run agentkit has no ~/.agentkit/state: the setup
        # creates it (0700) so the links resolve, and repeated asks are then held
        # to one request by the suite's own cadence mark.
        caller = self.root / "caller"
        caller.mkdir()  # no .agentkit at all
        self.healthy()
        setup = self.shell(self.share(caller))
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        self.assertEqual(stat.S_IMODE((caller / ".agentkit").stat().st_mode), 0o700)
        self.assertEqual(
            stat.S_IMODE((caller / ".agentkit/state").stat().st_mode), 0o700)
        ask = subprocess.run(
            [sys.executable, "-c",
             "from agentkit import config, usage\n"
             "cfg = config.load()\n"
             "[usage._probe_gently(cfg, 'anthropic') for _ in range(3)]\n"],
            cwd=self.root,
            env={**self.env, "REPO": str(REPO), "PYTHONPATH": str(REPO)},
            text=True, capture_output=True, timeout=120)
        self.assertEqual(ask.returncode, 0, ask.stdout + ask.stderr)
        self.assertEqual(self.probes("claude"), ["usage"])

    def test_host_ask_after_setup_holds_through_an_accounts_host(self):
        # Where the host lists accounts for a provider, its default login's cadence is
        # that provider's .default file: the sandbox link tracks it, so a host ask after
        # setup holds a later sandbox ask there too.
        caller = self.root / "caller"
        (caller / ".agentkit/state").mkdir(parents=True)
        (caller / ".agentkit/config.toml").write_text(
            '[providers.anthropic]\naccounts = ["default", "second"]\n')
        self.healthy()
        setup = self.shell(self.share(caller))
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        link = self.home / ".agentkit/state/anthropic-probe.lock"
        self.assertTrue(link.is_symlink())
        self.assertEqual(Path(os.readlink(link)),
                         caller / ".agentkit/state/anthropic.default-probe.lock")
        (caller / ".agentkit/state/anthropic.default-probe.lock").write_text(
            repr(time.time()))
        later = subprocess.run([str(REPO / "bin/ak"), "usage", "--json"], cwd=self.root,
                               env={**self.env, "REPO": str(REPO)},
                               text=True, capture_output=True, timeout=120)
        self.assertEqual(later.returncode, 0, later.stdout + later.stderr)
        self.assertEqual(self.probes("claude"), [])
        self.assertEqual(self.probes("codex"), ["usage"])

    def test_retry_past_cadence_that_gets_an_answer_passes(self):
        # Codex's minute with the default 60 s sleep: the retry is past the cadence, so it
        # asks again and the new answer passes. Claude's fifteen still holds its own retry.
        self.adapter("claude", meters("anthropic"))
        self.adapter("codex", refused("openai", "unknown: HTTP 503 from "
                                      "chatgpt.com/backend-api/wham/usage"),
                     then=meters("openai", 45))
        self.adapter("muse", meters("meta", 40))
        result = self.shell(CHECK_1, AK_METER_RETRY_SECS="60")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS  1 ak usage --json", result.stdout)
        self.assertEqual(self.probes("codex"), ["usage", "usage"])
        self.assertEqual(self.probes("claude"), ["usage"])

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

    def test_held_check_1_picks_once_the_hold_lifts(self):
        # Check 1 skipped on the host's hold; by check 6 the hold has lifted and the
        # suite has asked since (checks 3 and 4), so check 6 refreshes $U from that
        # fresh reading and runs the pick instead of skipping on the suite's own ask.
        caller = self.root / "caller"
        (caller / ".agentkit/state").mkdir(parents=True)
        lock = caller / ".agentkit/state/anthropic-probe.lock"
        lock.write_text(repr(time.time()))
        self.healthy()
        aged = ("python3 -c 'import sys, time; "
                "open(sys.argv[1], \"w\").write(repr(time.time() - 901))' "
                + shlex.quote(str(lock)))
        block = (self.share(caller) + CHECK_1 + "\n" + aged + "\n"
                 "ak usage --json >/dev/null\n" + CHECK_6)
        result = self.shell(block)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIP  1: provider meter unavailable (", result.stdout)
        self.assertIn("PASS  6 ak orch --dry-run", result.stdout)
        self.assertIn("PASS  6b ak orch", result.stdout)
        self.assertNotIn("SKIP  6:", result.stdout)
        self.assertNotIn("FAIL", result.stdout)
        # Check 1 asked nothing; the one suite ask served check 6 from the cache.
        self.assertEqual(self.probes("claude"), ["usage"])

    def test_held_check_1_picks_once_the_hold_lifts_after_a_held_read(self):
        # Check 3's `ak usage` ran while the hold lasted and cached Claude with no meters;
        # the hold lifts minutes later, inside that snapshot's five.  Check 6's refresh asks
        # now that it may, rather than picking on the empty reading the hold left behind.
        caller = self.root / "caller"
        (caller / ".agentkit/state").mkdir(parents=True)
        state = caller / ".agentkit/state"
        (state / "anthropic-probe.lock").write_text(repr(time.time()))
        self.healthy()
        # Minutes pass between checks 3 and 6: both cadences run out.
        aged = ("python3 -c 'import sys, time; [open(p, \"w\").write(repr(time.time() - 901)) "
                "for p in sys.argv[1:]]' "
                + shlex.quote(str(state / "anthropic-probe.lock")) + " "
                + shlex.quote(str(state / "openai-probe.lock")))
        block = (self.share(caller) + CHECK_1 + "\n"
                 "ak usage --json >/dev/null\n" + aged + "\n" + CHECK_6)
        result = self.shell(block)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIP  1: provider meter unavailable (", result.stdout)
        self.assertIn("PASS  6 ak orch --dry-run", result.stdout)
        self.assertNotIn("FAIL", result.stdout)
        self.assertEqual(self.probes("claude"), ["usage"])

    def test_held_check_1_skips_check_6_while_the_hold_lasts(self):
        # The hold that skipped check 1 still lasts at check 6 and the suite asked
        # nothing since: the refresh has neither meters nor a throttled error, so
        # check 6 skips with the hold's own reason while 6b still passes.
        caller = self.root / "caller"
        (caller / ".agentkit/state").mkdir(parents=True)
        (caller / ".agentkit/state/anthropic-probe.lock").write_text(repr(time.time()))
        self.healthy()
        result = self.shell(self.share(caller) + CHECK_1 + "\n" + CHECK_6)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SKIP  1: provider meter unavailable (", result.stdout)
        self.assertIn("SKIP  6: provider meter unavailable (", result.stdout)
        self.assertIn("next ask in", result.stdout)
        self.assertIn("PASS  6b ak orch", result.stdout)
        self.assertNotIn("FAIL", result.stdout)
        self.assertEqual(self.probes("claude"), [])
        self.assertEqual(self.probes("codex"), ["usage"])

    def skip_astra(self):
        """Check 3's own skip for astra, deciding without making any live call."""
        return (CHECK_1_PREAMBLE + CHECK_3_SKIP +
                'if skip_spent 3a/3b astra; then echo "DECISION: skip"; '
                'else echo "DECISION: attempt"; fi\n')

    def test_held_sandbox_read_skips_off_the_host_spent_week(self):
        # The host asked openai seconds ago, so the sandbox read is held and empty;
        # the host's own cache parks the week until its reset. The skip stands on
        # that spent-knowledge instead of spending real calls on the 429s the week
        # would answer with.
        caller = self.root / "caller"
        (caller / ".agentkit/state").mkdir(parents=True)
        (caller / ".agentkit/state/openai-probe.lock").write_text(repr(time.time()))
        reset = int(time.time()) + 4 * 86400
        (caller / ".agentkit/state/usage.json").write_text(json.dumps({
            "fetched_at": time.time(), "providers": {
                "openai": {
                    "provider": "openai", "exhausted": True,
                    "exhausted_until": float(reset), "exhausted_at": time.time() - 3600,
                    "exhausted_ends": {"primary_window": float(reset)},
                    "meters": [{"name": "primary_window", "used": 100,
                                "resets_at": float(reset), "window_secs": 604800,
                                "exhausted": True}]}}}))
        self.healthy()
        result = self.shell(self.share(caller) + self.skip_astra())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        when = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(reset))
        self.assertIn(f"SKIP  3a: required model astra has a spent openai window "
                      f"until {when}", result.stdout)
        self.assertIn("DECISION: skip", result.stdout)
        self.assertNotIn("FAIL", result.stdout)
        self.assertEqual(self.probes("codex"), [])

    def test_held_sandbox_read_with_no_host_cache_still_attempts(self):
        # Unknown usage cannot justify skipping a real call: with no host cache to
        # stand on either, the skip stays quiet and the call goes out as before.
        caller = self.root / "caller"
        (caller / ".agentkit/state").mkdir(parents=True)
        (caller / ".agentkit/state/openai-probe.lock").write_text(repr(time.time()))
        self.healthy()
        result = self.shell(self.share(caller) + self.skip_astra())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DECISION: attempt", result.stdout)
        self.assertNotIn("SKIP  3a", result.stdout)
        self.assertNotIn("FAIL", result.stdout)
        self.assertEqual(self.probes("codex"), [])

    def stale_host_week(self, caller, reset):
        """The host's cache with openai at 100% in a window that ended at `reset`."""
        (caller / ".agentkit/state/usage.json").write_text(json.dumps({
            "fetched_at": reset - 7200, "providers": {
                "openai": {
                    "provider": "openai", "exhausted": True,
                    "meters": [{"name": "primary_window", "used": 100,
                                "resets_at": float(reset), "window_secs": 604800,
                                "exhausted": True}]}}}))

    def test_live_sandbox_room_overrules_the_host_stale_week(self):
        # The sandbox measured openai itself at 45%; the host cache still says 100%
        # in a window that reset an hour ago. A stale week never parks a call the
        # sandbox read live.
        caller = self.root / "caller"
        (caller / ".agentkit/state").mkdir(parents=True)
        (caller / ".agentkit/state/openai-probe.lock").write_text(
            repr(time.time() - 3600))
        self.stale_host_week(caller, int(time.time()) - 3600)
        self.healthy()
        result = self.shell(self.share(caller) + self.skip_astra())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DECISION: attempt", result.stdout)
        self.assertNotIn("SKIP  3a", result.stdout)
        self.assertNotIn("FAIL", result.stdout)
        self.assertEqual(self.probes("codex"), ["usage"])

    def test_held_sandbox_read_ignores_the_host_reset_week(self):
        # Held and empty, and the host's 100% sits in a window that already reset:
        # past meters are dropped as a live read drops them, leaving nothing spent,
        # so the call goes out instead of skipping to a time already past.
        caller = self.root / "caller"
        (caller / ".agentkit/state").mkdir(parents=True)
        (caller / ".agentkit/state/openai-probe.lock").write_text(repr(time.time()))
        self.stale_host_week(caller, int(time.time()) - 3600)
        self.healthy()
        result = self.shell(self.share(caller) + self.skip_astra())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DECISION: attempt", result.stdout)
        self.assertNotIn("SKIP  3a", result.stdout)
        self.assertNotIn("FAIL", result.stdout)
        self.assertEqual(self.probes("codex"), [])


if __name__ == "__main__":
    unittest.main()
