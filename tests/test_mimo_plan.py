"""MiMo counts as the token plan it runs on, and a reset a month out reads as a date.

OpenCode's global config names the endpoint MiMo is sent to, and that endpoint is what the
tokens are paid from: a plain token-plan URL there is a subscription whatever config.toml's
`mode` still says, and anything else -- another host, an override, a substitution -- is payg.
The adapter launches OpenCode with project config off, so no workspace can move it.  Offline:
OpenCode's config is a temporary OPENCODE_CONFIG_DIR, HOME is a temporary directory, the
adapter runs a stub `opencode`, and no real ~/.config/opencode or ~/.agentkit is read or written.
"""

from contextlib import ExitStack
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, usage  # noqa: E402

WEEK = 604800
PLAN_RESET = 1792713599      # 23 Oct 2026 01:59:59 CEST, the owner's plan meter
CET = "CET-1CEST,M3.5.0,M10.5.0/3"   # the owner's zone, spelled so no tzdata is needed
PLAN, PAID = "https://token-plan-ams.xiaomimimo.com/v1", "https://api.xiaomimimo.com/v1"


class MimoPlan(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".mimo-plan-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.addCleanup(time.tzset)      # after the environment below is put back
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "OPENCODE_CONFIG_DIR": str(self.root / "opencode"),
            "TZ": CET, "NO_COLOR": "1"}))
        os.environ.pop("XDG_CONFIG_HOME", None)
        for name in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_CONTENT", "MIMO_URL"):
            os.environ.pop(name, None)
        time.tzset()
        stack.enter_context(patch.object(config, "STATE", self.root / "state"))
        config.STATE.mkdir()
        with open(REPO / "config.default.toml", "rb") as fh:
            self.cfg = tomllib.load(fh)
        self.cfg["providers"]["mimo"]["mode"] = "payg"   # what every config written before says

    def write(self, doc):
        (self.root / "opencode").mkdir(exist_ok=True)
        (self.root / "opencode/opencode.json").write_text(json.dumps(doc))

    def endpoint(self, url):
        self.write({"provider": {"mimo": {"npm": "@ai-sdk/openai-compatible", "name": "MiMo",
                                          "options": {"baseURL": url, "apiKey": "tp-dummy"}}}})

    @staticmethod
    def providers(now):
        # Claude behind pace, so a payg MiMo stays out; MiMo reads its plan's own meter.
        return {"anthropic": {"meters": [{"name": "weekly_all", "used": 40, "elapsed": 50,
                                          "pace": -10, "resets_at": now + WEEK / 2,
                                          "window_secs": WEEK, "exhausted": False}],
                              "resets": 0, "error": None, "exhausted": False},
                "mimo": {"meters": [{"name": "plan", "used": 30, "elapsed": 10, "pace": 20,
                                     "resets_at": PLAN_RESET, "window_secs": 2592000,
                                     "exhausted": False}],
                         "resets": 0, "error": None, "exhausted": False}}

    def pick(self):
        return usage.pick_order(self.cfg, self.providers(time.time()), ["opus", "mimo"],
                                orchestrator="opus", quiet=True)

    def mode(self):
        return usage.harness_plugin("opencode").mode(self.cfg["models"]["mimo"])

    def test_a_token_plan_url_is_a_plan_under_a_payg_config(self):
        self.endpoint(PLAN)
        self.assertEqual(self.mode(), "subscription")
        self.assertIn("mimo", self.pick())
        # native `providers` saying the same as legacy `provider` is the same plan
        self.write({"provider": {"mimo": {"options": {"baseURL": PLAN}}},
                    "providers": {"mimo": {"settings": {"baseURL": PLAN}}}})
        self.assertEqual(self.mode(), "subscription")
        # and the shipped default no longer says payg at all
        with open(REPO / "config.default.toml", "rb") as fh:
            self.assertNotIn("mode", tomllib.load(fh)["providers"]["mimo"])

    def test_a_payg_url_is_payg(self):
        self.endpoint(PAID)
        del self.cfg["providers"]["mimo"]["mode"]        # the shipped default, which says none
        self.assertEqual(self.mode(), "payg")
        self.assertEqual(self.pick(), ["opus"])
        # a host that is no token plan, and no config at all, are payg too: never a plan by guess
        self.endpoint("https://example.test/v1")
        self.assertEqual(self.mode(), "payg")
        # nor is a token-plan host behind another scheme, no scheme, or a port that is no number,
        # nor one a JavaScript URL parser reads as another host: this one is api.xiaomimimo.com
        for url in ("ftp://token-plan-ams.xiaomimimo.com/v1", "//token-plan-ams.xiaomimimo.com/v1",
                    "https://token-plan-ams.xiaomimimo.com:invalid/v1",
                    "https://api.xiaomimimo.com\\@token-plan-ams.xiaomimimo.com/../v1",
                    "https://x@token-plan-ams.xiaomimimo.com/v1",
                    "https://token-plan-\u00e4ms.xiaomimimo.com/v1"):
            self.endpoint(url)
            self.assertEqual(self.mode(), "payg", url)
        (self.root / "opencode/opencode.json").unlink()
        self.assertEqual(self.mode(), "payg")
        self.assertEqual(self.pick(), ["opus"])
        # a config folder that cannot be read is payg, and never stops the pick
        (self.root / "opencode").chmod(0)
        self.addCleanup((self.root / "opencode").chmod, 0o755)
        self.assertEqual(self.mode(), "payg")

    def test_opencode_config_set_is_payg(self):
        self.endpoint(PLAN)
        with patch.dict(os.environ, {"OPENCODE_CONFIG": str(self.root / "custom.json")}):
            self.assertEqual(self.mode(), "payg")
            self.assertEqual(self.pick(), ["opus"])
        # an opencode.jsonc beside it is merged over it, whatever it says
        (self.root / "opencode/opencode.jsonc").write_text("{}")
        self.assertEqual(self.mode(), "payg")

    def test_opencode_config_content_set_still_reads_the_global_file(self):
        # an OpenCode seat's shell carries its rulebook document, which the adapter unsets
        # before every launch: `ak run` from there reads MiMo as every other seat does
        self.endpoint(PLAN)
        paid = {"provider": {"mimo": {"options": {"baseURL": PAID}}}}
        with patch.dict(os.environ, {"OPENCODE_CONFIG_CONTENT": json.dumps(paid)}):
            self.assertEqual(self.mode(), "subscription")
            self.assertIn("mimo", self.pick())

    def test_a_substituted_url_is_payg(self):
        os.environ["MIMO_URL"] = PLAN
        self.endpoint("{env:MIMO_URL}")
        self.assertEqual(self.mode(), "payg")
        self.assertEqual(self.pick(), ["opus"])
        self.endpoint(PLAN + "/{file:path.txt}")
        self.assertEqual(self.mode(), "payg")
        # so are a file that is not plain JSON, tables that disagree, and a model of its own
        (self.root / "opencode/opencode.json").write_text(
            '{"provider": {"mimo": {"options": {"baseURL": "%s"}}}} // plan' % PLAN)
        self.assertEqual(self.mode(), "payg")
        self.write({"provider": {"mimo": {"options": {"baseURL": PLAN}}},
                    "providers": {"mimo": {"settings": {"baseURL": PAID}}}})
        self.assertEqual(self.mode(), "payg")
        self.write({"provider": {"mimo": {"options": {"baseURL": PLAN}, "models": {
            "mimo-v2.6-pro": {"options": {"baseURL": PAID}}}}}})
        self.assertEqual(self.mode(), "payg")

    def test_the_adapter_launches_opencode_without_project_config(self):
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "opencode").write_text(
            '#!/usr/bin/env bash\n'
            'printf \'%s %s %s %s\\n\' "$1" "${OPENCODE_DISABLE_PROJECT_CONFIG:-unset}" \\\n'
            '    "${OPENCODE_CONFIG_PROJECT_DISABLE-unset}" "${OPENCODE_CONFIG_CONTENT-unset}" \\\n'
            '    >>"$STUB_LOG"\n')
        (bin_dir / "opencode").chmod(0o755)
        log, prompt, ws = self.root / "stub.log", self.root / "prompt.md", self.root / "ws"
        prompt.write_text("hi\n")
        ws.mkdir()
        env = {"HOME": str(self.root), "PATH": f"{bin_dir}:/usr/bin:/bin",
               "OPENCODE_CONFIG_DIR": str(self.root / "opencode"),
               "AGENTKIT_SESSION": "fakesession", "STUB_LOG": str(log),
               "OPENCODE_CONFIG_CONTENT": "{}",     # a seat's shell, which carries its own
               "OPENCODE_CONFIG_PROJECT_DISABLE": "0"}   # OpenCode reads it over the older name
        adapter = str(REPO / "adapters/opencode.sh")
        subprocess.run([adapter, "run", "mimo/mimo-v2.6-pro", "high", str(ws), str(prompt),
                        str(self.root / "out")], env=env, capture_output=True, timeout=60)
        self.assertEqual(log.read_text(), "run 1 1 unset\n")
        # the seat's command line is run by whoever opens the pane, so it says so itself
        proc = subprocess.run([adapter, "interactive", "mimo/mimo-v2.6-pro", "high"], env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        words = shlex.split(proc.stdout)
        launch = words[words.index("env"):words.index("opencode", words.index("env"))]
        self.assertIn("OPENCODE_DISABLE_PROJECT_CONFIG=1", launch)
        self.assertIn("OPENCODE_CONFIG_PROJECT_DISABLE=1", launch)

    def test_a_reset_thirty_days_out_prints_a_date(self):
        now = PLAN_RESET - 30 * 86400
        meter = {"name": "plan", "used": 30, "resets_at": PLAN_RESET, "window_secs": 2592000}
        self.assertEqual(usage.reset_when(meter, now), "23 Oct")
        # the menu row and `ak usage` both, under headings that name no week
        (config.STATE / "usage.json").write_text(json.dumps(
            {"fetched_at": now, "providers": {"mimo": {"meters": [meter]}}}))
        with patch.object(menu.time, "time", return_value=now):
            lines = menu.usage_lines(self.cfg, 170)
        self.assertEqual(lines[0], "  usage left")
        self.assertRegex(next(line for line in lines if "MiMo" in line),
                         r"MiMo\s+[█░]+\s+70% left · resets 23 Oct$")
        with patch.object(usage.time, "time", return_value=now):
            row = dict(zip(usage.HEADERS, usage.rows(self.cfg, {"mimo": {"meters": [
                {**meter, "elapsed": 0, "pace": 30}]}})[-1]))
        self.assertEqual((row["left"], row["resets"]), ("70%", "23 Oct"))
        self.assertFalse([h for h in usage.HEADERS if "this week" in h], usage.HEADERS)

    def test_a_reset_three_days_out_prints_a_weekday(self):
        plan = {"name": "plan", "used": 30, "resets_at": PLAN_RESET, "window_secs": 2592000}
        week = {**plan, "name": "weekly", "window_secs": WEEK}
        for meter in (plan, week):
            self.assertEqual(usage.reset_when(meter, PLAN_RESET - 3 * 86400), "Fri 01:59")
            self.assertEqual(menu.resets_note(meter, PLAN_RESET - 3 * 86400), "resets Fri 01:59")
            # six days out is still this week's weekday
            self.assertEqual(usage.reset_when(meter, PLAN_RESET - 6 * 86400), "Fri 01:59")
        # a minute past it the plan's is a date, and a weekly window keeps its weekday: a
        # week is as far off as it can ever be
        self.assertEqual(usage.reset_when(plan, PLAN_RESET - 6 * 86400 - 60), "23 Oct")
        self.assertEqual(usage.reset_when(week, PLAN_RESET - 7 * 86400), "Fri 01:59")


if __name__ == "__main__":
    unittest.main()
