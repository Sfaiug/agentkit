"""`Models` on `c` is a row per harness, each ticking the models its catalog offers in and out.

The owner (20 Oct 2026): "in the config instead of having add model and add provider, it should
instead be just provider options and settings and same for models, where models can be removed
and added".  `■` is a model the config runs, `□` one it does not; Enter takes it in, at its
harness's effort as near as it has one, or out, the last model kept; one taken out comes back as
it was.  OpenCode lists only the models the config runs on it.  `c` runs on a pty
(tests/test_config_matrix.py's Screen) in a temporary HOME, the catalogs faked.
"""

import tomllib
import unittest

from test_config_matrix import DOWN, ENTER, ESC, UP, Screen, highlighted

TO_MAX = ["low", "medium", "high", "xhigh", "max"]
CATALOGS = {"claude": [("claude-opus-5-5", "Opus 5.5", TO_MAX),
                       ("claude-sonnet-5-5", "Sonnet 5.5", TO_MAX[:3])],
            "opencode": [("opencode/deepseek-v4.1-flash-free", "DeepSeek V4.1 Flash Free",
                          ["low", "high", "max"]), ("anthropic/lyra-1", "Lyra 1", ["low", "high"]),
                         ("zeta/comet-2", "Comet 2", ["high"])]}
CHILD = r"""
import os, sys
sys.path.insert(0, os.environ["MATRIX_REPO"])
from contextlib import closing
from agentkit import config, menu, terminal, update, usage

config.catalog = lambda harness: [{"id": model, "label": label, "efforts": efforts}
                                  for model, label, efforts in %r.get(harness, [])]
update.version = lambda harness: ""
update.agentkit_version = lambda: "abc1234"
usage.collect = lambda cfg, **kwargs: usage.Readings({})
with closing(terminal.Keyboard()) as keyboard:
    menu.show_config(False, keyboard)
print("<left>", flush=True)
""" % (CATALOGS,)
TWO = """[defaults]
orchestrator = "opus"
workers = ["opus"]
[models]
opus = {harness = "claude", model = "claude-opus-5-5", effort = "xhigh", provider = "acme"}
[models.flash]
harness = "opencode"
model = "opencode/deepseek-v4.1-flash-free"
effort = "max"
provider = "opencode"
[providers]
anthropic = {mode = "subscription"}   # listed first, but Claude Code runs acme here
acme = {mode = "subscription"}
opencode = {mode = "free", name = "OpenCode", colour = "#123456"}
"""
ONE = TWO.split("[models.flash]")[0] + '[providers]\nacme = {mode = "subscription"}\n'


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
                          "provider": "acme"})
        # opus out and back: its entry as it was, under its own name
        self.assertEqual(opened(screen, UP + ENTER, "□ Opus 5.5"), "□ Opus 5.5")
        self.assertNotIn("opus", screen.saved()["models"])
        self.assertEqual(opened(screen, ENTER, "■ Opus 5.5"), "■ Opus 5.5")
        self.assertEqual(screen.saved()["models"]["opus"], {
            "harness": "claude", "model": "claude-opus-5-5", "effort": "xhigh", "provider": "acme"})
        self.assertEqual(opened(screen, DOWN + ENTER, "□ Sonnet 5.5"), "□ Sonnet 5.5")
        self.assertNotIn("sonnet", screen.saved()["models"])
        # OpenCode lists only its own: out, its free provider with it, and back as both were
        lines = screen.press(ESC + DOWN + ENTER, lambda lines: any("■ DeepSeek" in line
                                                                   for line in lines))
        self.assertFalse(any("Lyra" in line or "Comet" in line for line in lines), lines)
        self.assertEqual(opened(screen, ENTER, "□ DeepSeek"), "□ DeepSeek V4.1 Flash Free")
        self.assertNotIn("opencode", screen.saved()["providers"])
        self.assertEqual(opened(screen, ENTER, "■ DeepSeek"), "■ DeepSeek V4.1 Flash Free")
        self.assertEqual(screen.saved(), tomllib.loads(TWO))
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


if __name__ == "__main__":
    unittest.main()
