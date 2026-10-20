"""`Models` on `c` is a row per harness, each ticking the models its catalog offers in and out.

The owner (20 Oct 2026): "in the config instead of having add model and add provider, it should
instead be just provider options and settings and same for models, where models can be removed
and added", and a model opens no screen of its own.  `■` is a model the config runs, `□` one it
does not; Enter takes it in, at its harness's effort as near as it has one, or out, the last
model kept.

Each screen test runs `menu.show_config` with a real `terminal.Keyboard` in a child process on a
pty of its own, through tests/test_config_matrix.py's Screen, in a temporary HOME; the catalogs
are faked.  The one test of config.remove_model and usage.collect runs its child in a temporary
HOME too.  Nothing here reads or writes the owner's ~/.agentkit, and the only process signalled
is the test's own child.
"""

import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest

from test_config_matrix import DOWN, ENTER, ESC, INHERITED, REPO, Screen, highlighted

CATALOGS = {"claude": [("claude-fable-5-1", "Fable 5.1", ["low", "medium", "high", "xhigh", "max"]),
                       ("claude-opus-5-5", "Opus 5.5", ["low", "medium", "high", "xhigh", "max"]),
                       ("claude-sonnet-5-5", "Sonnet 5.5", ["low", "medium", "high"])],
            "opencode": [("opencode/deepseek-v4.1-flash-free", "DeepSeek V4.1 Flash Free",
                          ["low", "high", "max"])]}
CHILD = r"""
import os, sys
sys.path.insert(0, os.environ["MATRIX_REPO"])
from contextlib import closing
from agentkit import config, menu, motion, terminal, update, usage
motion.FADE = 0

config.catalog = lambda harness: [{"id": model, "label": label, "efforts": efforts}
                                  for model, label, efforts in %r.get(harness, [])]
# OpenCode is here, with its own free provider logged in, and nothing of it is run
config.harness_present = lambda harness: True
config.listed_providers = lambda harness: [("opencode", "OpenCode", "free")]
update.version = lambda harness: ""
update.agentkit_version = lambda: "abc1234"
usage.collect = lambda cfg, **kwargs: usage.Readings({})
with closing(terminal.Keyboard()) as keyboard:
    menu.show_config(False, keyboard)
print("<left>", flush=True)
""" % (CATALOGS,)
TWO = """
[defaults]
orchestrator = "opus"
workers = ["opus"]

[models.opus]
harness = "claude"
model = "claude-opus-5-5"
effort = "xhigh"
provider = "anthropic"

[models.flash]
harness = "opencode"
model = "opencode/deepseek-v4.1-flash-free"
effort = "max"
provider = "opencode"

[providers.anthropic]
mode = "subscription"

[providers.opencode]
mode = "free"
name = "OpenCode"
"""
ONE = TWO.split("[models.flash]")[0] + '[providers.anthropic]\nmode = "subscription"\n'
# Google's and OpenAI's only models removed and saved, then a fresh usage cache read back with
# a reset check due: Google's reading has no reset count, OpenAI's a spent week and two credits.
# The adapters are stubbed; what they were asked is printed.
USAGE = r"""
import json, os, sys, time, tomllib
sys.path.insert(0, os.environ["MATRIX_REPO"])
from agentkit import config, usage

cfg = tomllib.loads((config.REPO / "config.default.toml").read_text())
cfg["models"]["spark2"] = dict(cfg["models"]["spark"], model="muse-spark-1.3")
config.remove_model(cfg, "spark")
config.remove_model(cfg, "gemini")
config.save(config.remove_model(cfg, "astra"))
asked = []
usage._adapter_json = lambda harness, verb, *_: asked.append(f"{harness} {verb}") or {}
now = time.time()
week = {"window_secs": 7 * 86400, "used": 95, "resets_at": now + 86400}
(config.STATE / "usage.json").write_text(json.dumps({
    "fetched_at": now, "reset_checked_at": 0, "providers": {
        "google": {"provider": "google", "meters": [], "error": "unknown", "resets": None,
                   "probed_at": now},
        "openai": {"provider": "openai", "harness": "codex", "meters": [week], "resets": 2,
                   "probed_at": now}}}))
read = usage.collect(config.load())
print(json.dumps({"saved": tomllib.loads(config.dump(config.load())),
                  "google": read["google"]["error"], "asked": asked}))
"""


def models_page(screen):
    """`c`, the highlight walked down onto `Models`, and Enter: the page it opens."""
    lines = screen.frame()
    for _ in range(20):
        if highlighted(lines).startswith("› Models"):
            return screen.press(ENTER,
                                lambda lines: lines[0].startswith("agentkit · config · models"))
        lines = screen.press(DOWN)
    screen.case.fail(f"no `Models` row: {lines}")


def opened(screen, keys, label):
    """`keys` on the Models page, then the line of `label` in the list it opened."""
    lines = screen.press(keys, lambda lines: any(label in line for line in lines))
    return next(line.strip(" ›") for line in lines if label in line)


class ModelsPage(unittest.TestCase):
    def test_a_harness_ticks_its_models_in_and_out(self):
        screen = Screen(self, child=CHILD, text=TWO, session=None)
        lines = models_page(screen)
        self.assertEqual([line[2:].split("  ")[0] for line in lines[2:4]],
                         ["Claude Code", "OpenCode"])
        self.assertIn("Opus 5.5", lines[2])
        self.assertEqual(opened(screen, ENTER, "Sonnet 5.5"), "□ Sonnet 5.5")
        self.assertEqual(highlighted(screen.frame()).split(), ["›", "■", "Opus", "5.5"])
        # in: named from its label, at the effort of its harness's first model as near as it goes
        self.assertEqual(opened(screen, DOWN + ENTER, "■ Sonnet 5.5"), "■ Sonnet 5.5")
        self.assertEqual(screen.saved()["models"]["sonnet"],
                         {"harness": "claude", "model": "claude-sonnet-5-5", "effort": "high",
                          "provider": "anthropic"})
        # out again, and the free provider its last model takes goes and comes back with it
        self.assertEqual(opened(screen, ENTER, "□ Sonnet 5.5"), "□ Sonnet 5.5")
        self.assertNotIn("sonnet", screen.saved()["models"])
        self.assertEqual(opened(screen, ESC + DOWN + ENTER + ENTER, "□ DeepSeek"),
                         "□ DeepSeek V4.1 Flash Free OpenCode")
        self.assertNotIn("opencode", screen.saved()["providers"])
        self.assertEqual(opened(screen, ENTER, "■ DeepSeek"),
                         "■ DeepSeek V4.1 Flash Free OpenCode")
        saved = screen.saved()
        self.assertEqual(saved["providers"]["opencode"], {"mode": "free", "name": "OpenCode"})
        self.assertEqual(saved["models"]["deepseek-flash-free"]["effort"], "high")
        screen.press(ESC + ESC, lambda lines: lines[0].startswith("agentkit · config  "))
        screen.leave()

    def test_the_last_model_stays(self):
        screen = Screen(self, child=CHILD, text=ONE, session=None)
        models_page(screen)
        before = screen.path.read_bytes()
        lines = screen.press(ENTER + ENTER,
                             lambda lines: any("the config needs one model" in line
                                               for line in lines))
        self.assertEqual(highlighted(lines).split(), ["›", "■", "Opus", "5.5"])
        self.assertEqual(screen.path.read_bytes(), before)
        screen.press(ESC + ESC, lambda lines: lines[0].startswith("agentkit · config  "))
        screen.leave()

    def test_a_company_s_last_model_leaves_its_provider_its_usage_read_and_its_credits(self):
        home = tempfile.TemporaryDirectory(prefix="models-page-")
        self.addCleanup(home.cleanup)
        env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        env.update({"HOME": home.name, "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
                    "MATRIX_REPO": str(REPO)})
        done = subprocess.run([sys.executable, "-c", USAGE], env=env, capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        answer = json.loads(done.stdout)
        shipped = tomllib.loads((REPO / "config.default.toml").read_text())
        saved = answer["saved"]
        self.assertNotIn("gemini", saved["models"])
        self.assertNotIn("astra", saved["models"])
        self.assertEqual(saved["providers"]["google"], shipped["providers"]["google"])
        self.assertEqual(saved["providers"]["openai"], shipped["providers"]["openai"])
        self.assertNotIn("usage_model", saved["providers"]["meta"])     # it named spark
        self.assertEqual(saved["providers"]["meta"]["usage_effort"], "minimal")
        self.assertEqual(saved["defaults"], {"orchestrator": "opus", "workers": ["opus"]})
        self.assertEqual(answer["google"], "unknown")     # read from the cache, never raised
        self.assertEqual(answer["asked"], [])             # no credit spent with no model to use it


if __name__ == "__main__":
    unittest.main()
