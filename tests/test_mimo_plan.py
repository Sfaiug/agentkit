"""MiMo counts as the token plan it runs on, and a reset a month out reads as a date.

OpenCode's global config names the endpoint MiMo is sent to, and that endpoint is what the
tokens are paid from: a plain token-plan URL there is a subscription whatever config.toml's
`mode` still says, and anything else -- another host, an override, a substitution -- is payg.
The adapter launches OpenCode with project config off, so no workspace can move it.  Offline:
OpenCode's config is a temporary OPENCODE_CONFIG_DIR, HOME is a temporary directory, the
adapter runs a stub `opencode`, and no real ~/.config/opencode or ~/.agentkit is read or written.
The plan's meter is read through the shared browser, whose lapsed console session one page load
renews: that browser is a fake bridge under the temporary HOME, beside a fake `curl`.
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
HOST, CONSOLE = "platform.xiaomimimo.com", "https://platform.xiaomimimo.com/console/plan-manage"
REFUSED = {"ok": False, "stage": "usage", "http": 401, "code": 401, "host": HOST}

# The fake bridge's venv python: the tab's fetch rounds answer `fetch-1`, `fetch-2`, ... in
# turn, its page polls the lines of `pages` in turn, the last one standing, and every argv
# lands in `asked-bridge`.  The fake curl refuses whatever it is asked, logged in `asked-curl`.
FAKE_VENV = """#!/bin/sh
dir="$HOME/fake"
printf '%s\\n' "$*" >>"$dir/asked-bridge"
case "$*" in
  *tokenPlan*) kind=fetch ;;
  *location.href*) exit 0 ;;
  *) kind=page ;;
esac
n=$(( $(cat "$dir/n-$kind" 2>/dev/null || echo 0) + 1 )); echo "$n" >"$dir/n-$kind"
case $kind in
  fetch) cat "$dir/fetch-$n" ;;
  page) awk -v n="$n" 'NR <= n { l = $0 } END { print l }' "$dir/pages" ;;
esac
"""
FAKE_CURL = """#!/bin/sh
printf '%s\\n' "$*" >>"$HOME/fake/asked-curl"
printf '{"code":401,"message":"unauthorized"}\\n401\\n'
"""


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

    def probe(self, fetches, pages, **env):
        """The adapter's `usage` over the fake bridge, whose tab's fetch rounds say `fetches`
        in turn and whose page polls say `pages`: its answer, and what the bridge was asked."""
        self.endpoint(PLAN)
        fake, bridge, bin_dir = (self.root / "fake", self.root / ".local/share/browser-bridge",
                                 self.root / "bin")
        for folder in (fake, bridge / "venv/bin", bin_dir):
            folder.mkdir(parents=True, exist_ok=True)
        (bridge / "bridge.py").write_text("# fake bridge for tests/test_mimo_plan.py\n")
        for path, text in ((bridge / "venv/bin/python", FAKE_VENV), (bin_dir / "curl", FAKE_CURL)):
            path.write_text(text)
            path.chmod(0o755)
        for n, payload in enumerate(fetches, 1):
            (fake / f"fetch-{n}").write_text(json.dumps(json.dumps(payload)) + "\n")
        (fake / "pages").write_text("".join(json.dumps(page) + "\n" for page in pages))
        # the caller gives the probe 30s, and bash counts SECONDS on from its environment's
        proc = subprocess.run(
            [str(REPO / "adapters/opencode.sh"), "usage"], capture_output=True, text=True,
            timeout=30 - int(env.get("SECONDS", 0)),
            env={"HOME": str(self.root), "PATH": f"{bin_dir}:/usr/bin:/bin",
                 "OPENCODE_CONFIG_DIR": str(self.root / "opencode"), **env})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout), (fake / "asked-bridge").read_text().splitlines()

    @staticmethod
    def fetches(asked):
        return [argv for argv in asked if "tokenPlan" in argv]

    def test_a_refused_session_renews_and_reads_the_plan(self):
        plan = json.loads((REPO / "tests/fixtures/mimo-tokenplan-usage.json").read_text())
        detail = json.loads((REPO / "tests/fixtures/mimo-tokenplan-detail.json").read_text())
        answer, asked = self.probe(
            [REFUSED, {"ok": True, "usage": plan["data"], "detail": detail["data"], "host": HOST}],
            ["", "account.xiaomi.com loading", f"{HOST} complete"])
        self.assertEqual([(m["name"], m["used"]) for m in answer["meters"]],
                         [("plan", 6.0), ("compensation", 5.0), ("month", 34.8)])
        self.assertIsNone(answer["error"])
        self.assertNotIn("none", answer)
        # fetch, the tab sent to the console with its old page marked, three polls through
        # the sign-in and back, and the fetch that reads the meters
        self.assertEqual(len(asked), 6, asked)
        self.assertEqual(self.fetches(asked), [asked[0], asked[5]])
        self.assertIn(f"location.href = '{CONSOLE}'", asked[1])
        self.assertIn("akRenew", asked[1])
        self.assertFalse((self.root / "fake/asked-curl").exists())

    def test_a_session_refused_twice_notes_the_login_missing(self):
        answer, asked = self.probe([REFUSED, REFUSED], [f"{HOST} complete"])
        self.assertEqual((answer["meters"], answer["error"]), ([], None))
        for words in ("browser session refused (HTTP 401)", "provider key refused (HTTP 401)",
                      f"log into {CONSOLE} in the shared browser", "ak browser login"):
            self.assertIn(words, answer["none"])
        self.assertEqual(len(self.fetches(asked)), 2)

    def test_a_renewal_landing_on_another_host_notes_no_xiaomi_login(self):
        # the sign-in page never goes back: the probe polls it out, 8s, and fetches once more
        start = time.monotonic()
        answer, asked = self.probe(
            [REFUSED, {"ok": False, "stage": "usage", "http": 404, "host": "account.xiaomi.com"}],
            ["", "account.xiaomi.com complete"])
        self.assertLess(time.monotonic() - start, 15)
        self.assertEqual((answer["meters"], answer["error"]), ([], None))
        self.assertIn("browser has no Xiaomi login", answer["none"])
        self.assertIn(f"log into {CONSOLE}", answer["none"])
        self.assertNotIn("browser session refused", answer["none"])
        self.assertEqual(len(self.fetches(asked)), 2)
        self.assertGreater(len(asked) - len(self.fetches(asked)), 3)   # polled, not slept

    def test_a_renewal_settling_past_the_budget_stays_inside_it(self):
        # four seconds short of the budget: the renewal is cut off, it is never fetched
        # again, and the sources behind it are noted untested, never tried
        answer, asked = self.probe([REFUSED], ["", "account.xiaomi.com loading"], SECONDS="16")
        self.assertEqual((answer["meters"], answer["error"]), ([], None))
        for words in ("browser session expired, renewal unfinished (probe budget)",
                      "mimo CLI untested (probe budget)", "provider key untested (probe budget)"):
            self.assertIn(words, answer["none"])
        self.assertNotIn("log into", answer["none"])
        self.assertEqual(len(self.fetches(asked)), 1)
        self.assertIn("location.href", asked[1])
        self.assertFalse((self.root / "fake/asked-curl").exists())


if __name__ == "__main__":
    unittest.main()
