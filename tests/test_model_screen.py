"""Enter on a model's label in `c` opens that model's own screen: its id picked from the catalog,
its effort following the new model's own list, its review rule, and `Remove`, all without typing.

Each screen test runs `menu.show_config` with a real `terminal.Keyboard` in a child process on a
pty of its own, through tests/test_config_matrix.py's Screen, in a temporary HOME whose
config.toml is the shipped default plus a Haiku, or a single model.  The Claude catalog is
faked: two Opuses and two Sonnets that take low to max, low to high, and nothing the catalog
says -- as OpenCode's catalog says none -- and a Haiku that takes only `none`.  The one test of
config.remove_model and usage.collect runs its child in a temporary HOME too.  Nothing here
reads or writes the owner's ~/.agentkit, and the only process signalled is the test's own child.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest

from test_config_matrix import (DOWN, ENTER, ESC, INHERITED, LEFT, REPO, RIGHT, UP, Screen,
                                highlighted, row)
from agentkit import terminal

CATALOG = [("claude-opus-5", ["low", "medium", "high", "xhigh", "max"]),
           ("claude-opus-5-5", ["low", "medium", "high", "xhigh", "max"]),
           ("claude-sonnet-4-6", ["low", "medium", "high"]),
           ("claude-sonnet-5", []),
           ("claude-haiku-4-5", ["none"])]
CHILD = r"""
import os, sys
sys.path.insert(0, os.environ["MATRIX_REPO"])
from contextlib import closing
from agentkit import config, menu, terminal, update

config.catalog = lambda harness: [{"id": model, "label": model, "efforts": efforts}
                                  for model, efforts in %r if harness == "claude"]
update.version = lambda harness: ""
update.agentkit_version = lambda: "abc1234"
update.agentkit_newer = lambda: ""
with closing(terminal.Keyboard()) as keyboard:
    menu.show_config(False, keyboard)
print("<left>", flush=True)
""" % (CATALOG,)
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
usage._adapter_json = lambda harness, verb, timeout: asked.append(f"{harness} {verb}") or {}
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
ONE = """
[defaults]
orchestrator = "opus"
workers = ["opus"]

[models.opus]
harness = "claude"
model = "claude-opus-5-5"
effort = "xhigh"
provider = "anthropic"

[providers.anthropic]
mode = "subscription"
"""
KEYS = {"label": "  ↑↓←→ move   ⏎ open   esc back",
        "step": "  ↑↓ move   ←→ choose   esc back",
        "remove": "  ↑↓ move   ⏎ remove   esc back"}


def title(lines):
    """The screen's name on the header line, the clock off it."""
    return lines[0].rsplit(" ", 1)[0].strip()


def value(lines, label):
    """What the model screen shows after `label` on its line."""
    line = next(line for line in lines if line[2:].startswith(label))
    return line[2 + len(label):].strip()


def open_model(screen, keys, name):
    """`keys` in the matrix to reach `name`'s row, ← onto its label and Enter: its own screen."""
    screen.frame()
    lines = screen.press(keys + LEFT, lambda lines: lines[-1] == KEYS["label"])
    screen.case.assertIn(name, highlighted(lines))
    return screen.press(ENTER, lambda lines: title(lines) == f"agentkit · config · {name}")


def choices(screen, after):
    """The two answers the selector drew under the question, as shown."""
    def ready(text):
        found = re.search(r"\x1b\[\d+;1H\r(.*?)\x1b\[K\r?\n\r(.*?)\x1b\[K", text[after:])
        return found and [terminal.ANSI.sub("", found.group(n)) for n in (1, 2)]
    return screen.until(ready, "the remove question's answers")


class ModelScreen(unittest.TestCase):
    def test_an_id_picked_from_the_catalog_is_saved_and_esc_goes_back_to_its_row(self):
        screen = Screen(self, child=CHILD)
        lines = open_model(screen, DOWN, "opus")
        self.assertEqual(highlighted(lines).split(),
                         ["›", "model", "id", "‹", "claude-opus-5-5", "›"])
        self.assertEqual(lines[-1], KEYS["step"])
        lines = screen.press(LEFT,
                             lambda lines: value(lines, "model id") == "‹ claude-opus-5 ›")
        opus = screen.saved()["models"]["opus"]
        self.assertEqual((opus["model"], opus["effort"]), ("claude-opus-5", "xhigh"))  # taken
        before = screen.path.read_bytes()
        screen.press(LEFT)                                # the catalog's first: nothing before it
        self.assertEqual(screen.path.read_bytes(), before)
        ids = [model for model, efforts in CATALOG if efforts]    # the Sonnet 5 says none
        for model in ids[1:]:
            screen.press(RIGHT, lambda lines: value(lines, "model id") == f"‹ {model} ›")
            self.assertEqual(screen.saved()["models"]["opus"]["model"], model)
        before = screen.path.read_bytes()
        screen.press(RIGHT)                               # and nothing after its last
        self.assertEqual(screen.path.read_bytes(), before)
        lines = screen.press(ESC, lambda lines: title(lines) == "agentkit · config")
        self.assertIn("opus", highlighted(lines))
        self.assertEqual(lines[-1], KEYS["label"])
        screen.leave()
        self.assertEqual(screen.saved()["models"]["opus"]["model"], "claude-haiku-4-5")

    def test_the_effort_follows_the_new_model_s_own_list(self):
        screen = Screen(self, child=CHILD)
        open_model(screen, DOWN, "opus")
        effort = lambda: screen.saved()["models"]["opus"]["effort"]
        # xhigh is not the Sonnet's: high is nearest; past the Sonnet 5, whose efforts the
        # catalog does not say, the Haiku's only is none; back, low
        for key, model, wanted in ((RIGHT, "claude-sonnet-4-6", "high"),
                                   (RIGHT, "claude-haiku-4-5", "none"),
                                   (LEFT, "claude-sonnet-4-6", "low")):
            lines = screen.press(key, lambda lines: value(lines, "model id") == f"‹ {model} ›")
            self.assertEqual(value(lines, "effort"), f"‹ {wanted} ›")
            self.assertEqual(effort(), wanted)
        # the effort row steps that model's own list, and stops at its end
        lines = screen.press(DOWN + RIGHT + RIGHT,
                             lambda lines: value(lines, "effort") == "‹ high ›")
        self.assertTrue(highlighted(lines).startswith("› effort"))
        self.assertEqual(effort(), "high")
        before = screen.path.read_bytes()
        screen.press(RIGHT)
        self.assertEqual(screen.path.read_bytes(), before)
        # fable's id is none the catalog lists: no effort is offered for it, and none saved
        screen.press(ESC, lambda lines: title(lines) == "agentkit · config")
        screen.press(UP + ENTER, lambda lines: title(lines) == "agentkit · config · fable")
        lines = screen.press(DOWN + RIGHT, lambda lines: "the catalog names no efforts for "
                                                         "claude-fable-5-1" in lines[-3])
        self.assertEqual(value(lines, "effort"), "‹ xhigh ›")
        self.assertEqual(screen.path.read_bytes(), before)
        screen.press(ESC, lambda lines: title(lines) == "agentkit · config")
        screen.leave()

    def test_the_review_toggle_writes_the_key_and_a_missing_key_reads_yes(self):
        screen = Screen(self, child=CHILD)
        rule = "Reviews its own company's work"
        self.assertNotIn("reviews_own_provider", screen.saved()["models"]["opus"])
        lines = open_model(screen, DOWN, "opus")
        self.assertEqual(value(lines, rule), "‹ yes ›")
        lines = screen.press(DOWN + DOWN + ENTER, lambda lines: value(lines, rule) == "‹ no ›")
        self.assertTrue(highlighted(lines).startswith(f"› {rule}"))
        self.assertIs(screen.saved()["models"]["opus"]["reviews_own_provider"], False)
        screen.press(RIGHT, lambda lines: value(lines, rule) == "‹ yes ›")
        self.assertIs(screen.saved()["models"]["opus"]["reviews_own_provider"], True)
        # fable ships with `false`, and says no
        screen.press(ESC, lambda lines: title(lines) == "agentkit · config")
        lines = screen.press(UP + ENTER,
                             lambda lines: title(lines) == "agentkit · config · fable")
        self.assertEqual(value(lines, rule), "‹ no ›")
        screen.press(ESC, lambda lines: title(lines) == "agentkit · config")
        screen.leave()

    def test_remove_asks_with_keep_preselected_and_removes(self):
        screen = Screen(self, child=CHILD)
        open_model(screen, DOWN, "opus")
        lines = screen.press(DOWN * 3, lambda lines: lines[-1] == KEYS["remove"])
        self.assertEqual(highlighted(lines), "› Remove")
        before = screen.path.read_bytes()
        mark = len(screen.text())
        asked = screen.press(ENTER, lambda lines: lines[-1].strip() == "esc keep")
        self.assertIn("  Remove opus from the config?", asked)
        self.assertFalse(any(line.startswith("›") for line in asked), asked)
        self.assertEqual(choices(screen, mark), ["› Keep", "  Remove"])
        lines = screen.press(ENTER, lambda lines: lines[-1] == KEYS["remove"])   # Enter keeps
        self.assertEqual(screen.path.read_bytes(), before)
        screen.press(ENTER, lambda lines: lines[-1].strip() == "esc keep")
        lines = screen.press(ESC, lambda lines: lines[-1] == KEYS["remove"])     # so does Esc
        self.assertEqual(screen.path.read_bytes(), before)
        screen.press(ENTER, lambda lines: lines[-1].strip() == "esc keep")
        lines = screen.press(DOWN + ENTER, lambda lines: title(lines) == "agentkit · config")
        self.assertNotIn(" opus ", "\n".join(lines))
        self.assertIn("haiku", highlighted(lines))        # the row under it
        saved = screen.saved()
        self.assertNotIn("opus", saved["models"])
        # a default it leaves empty falls back the way config.remove_provider's does
        self.assertEqual(saved["defaults"], {"orchestrator": "fable", "workers": ["astra"]})
        self.assertEqual("\n".join(lines).count("●"), 1)
        self.assertIn("●", row(lines, "fable")[1])
        screen.leave()

    def test_the_last_model_cannot_be_removed(self):
        screen = Screen(self, child=CHILD, text=ONE)
        open_model(screen, b"", "opus")
        before = screen.path.read_bytes()
        mark = len(screen.text())
        lines = screen.press(DOWN * 3 + ENTER,
                             lambda lines: "the config needs one model" in lines[-3])
        self.assertEqual(highlighted(lines), "› Remove")
        self.assertNotIn("Remove opus", screen.text()[mark:])     # nothing asked
        self.assertEqual(screen.path.read_bytes(), before)
        screen.press(ESC, lambda lines: title(lines) == "agentkit · config")
        screen.leave()
        self.assertEqual(list(screen.saved()["models"]), ["opus"])

    def test_a_company_s_last_model_leaves_its_provider_its_usage_read_and_its_credits(self):
        home = tempfile.TemporaryDirectory(prefix="model-screen-")
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

    def test_a_click_on_a_label_opens_it_and_a_phone_draws_it_in_forty_columns(self):
        screen = Screen(self, child=CHILD, rows=24, cols=40)
        lines = screen.frame()
        number, line = row(lines, "haiku")
        lines = screen.click(line.index("haiku") + 1, number,
                             lambda lines: title(lines) == "agentkit · config · haiku")
        for line in lines:
            self.assertLessEqual(terminal.cells(line), 40, line)
        self.assertEqual(lines[2:4], ["› model id", "    ‹ claude-haiku-4-5 ›"])
        self.assertIn("  Reviews its own company's work", lines)
        # a click on the id's left arrow steps it back, past the Sonnet 5
        number = lines.index("    ‹ claude-haiku-4-5 ›") + 1
        lines = screen.click(5, number,
                             lambda lines: "    ‹ claude-sonnet-4-6 ›" in lines)
        self.assertEqual(screen.saved()["models"]["haiku"]["model"], "claude-sonnet-4-6")
        self.assertEqual(screen.saved()["models"]["haiku"]["effort"], "high")   # was xhigh
        screen.press(ESC, lambda lines: title(lines) == "agentkit · config")
        screen.leave()


if __name__ == "__main__":
    unittest.main()
