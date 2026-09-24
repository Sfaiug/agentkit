"""`add a model` in `c` is three lists in one frame -- harness, then a model that harness's catalog
offers, then an effort that model takes -- so nothing typed, and nothing the catalog does not
offer, is ever saved.

Each test runs `menu.show_config` with a real `terminal.Keyboard` in a child process on a pty of
its own, through tests/test_config_matrix.py's Screen, in a temporary HOME whose config.toml is
the shipped default plus a Haiku, or one of its own.  The catalogs are faked: Claude's two
Opuses, a Sonnet, and a model whose efforts it does not say; Antigravity's Gemini Pro and the
Flash the shipped default runs, whose label is wider than a phone leaves it.
Nothing here reads or writes the owner's ~/.agentkit, and the only process signalled is the
test's own child.
"""

import re
import unittest

from test_config_matrix import DOWN, ENTER, ESC, UP, Screen, highlighted
from agentkit import terminal

CATALOG = {"claude": [("claude-opus-5-5", "Opus 5.5", ["low", "medium", "high", "xhigh", "max"]),
                      ("claude-opus-5", "Opus 5", ["low", "medium", "high", "xhigh", "max"]),
                      ("claude-sonnet-5", "Sonnet 5", ["low", "medium", "high"]),
                      ("claude-mystery", "Mystery", [])],
           "antigravity": [("gemini-3.1-pro", "Gemini 3.1 Pro", ["low", "high"]),
                           ("gemini-3.8-flash", "Gemini 3.8 Flash with Extended Thinking",
                            ["low", "medium", "high"])]}
CHILD = r"""
import os, sys
sys.path.insert(0, os.environ["MATRIX_REPO"])
from contextlib import closing
from agentkit import config, menu, terminal, update

config.catalog = lambda harness: [{"id": model, "label": label, "efforts": efforts}
                                  for model, label, efforts in %r.get(harness, [])]
update.version = lambda harness: ""
update.agentkit_version = lambda: "abc1234"
update.agentkit_newer = lambda: ""
with closing(terminal.Keyboard()) as keyboard:
    menu.show_config(False, keyboard)
print("<left>", flush=True)
""" % (CATALOG,)
# Google's only model removed, which leaves its provider; OpenAI's model kept, its provider not;
# Acme, a provider of the owner's own, whose one model runs on OpenCode.
TWO = """
[defaults]
orchestrator = "opus"
workers = ["opus"]

[models.opus]
harness = "claude"
model = "claude-opus-5-5"
effort = "xhigh"
provider = "anthropic"

[models.orphan]
harness = "codex"
model = "gpt-6-astra"
effort = "high"
provider = "openai"

[providers.anthropic]
mode = "subscription"

[providers.google]
mode = "subscription"

[models.rocket]
harness = "opencode"
model = "acme/rocket-1"
effort = "high"
provider = "acme"

[providers.acme]
mode = "payg"
"""
ADD = "agentkit · config · add a model"
KEYS = {"choose": "  ↑↓ move   ⏎ choose   esc back",
        "add": "  ↑↓ move   ⏎ add   esc back"}


def title(lines):
    """The screen's name on the header line, the clock off it."""
    return lines[0].rsplit(" ", 1)[0].strip()


def listed(lines):
    """The open step's choices as drawn, each one's columns."""
    return [re.split(r"\s{2,}", line[4:].strip()) for line in lines[2:]
            if re.match(r"[ ›]   \S", line)]


def open_add(screen):
    """Down the matrix to `add a model`, and Enter: its first step, the harnesses."""
    lines = screen.frame()
    for _ in range(20):
        if highlighted(lines).startswith("› + add a model"):
            return screen.press(ENTER, lambda lines: title(lines) == ADD)
        lines = screen.press(DOWN)
    screen.case.fail(f"no `add a model` row: {lines}")


def step(screen, keys, name):
    """`keys`, then the screen once step `name` is the one open."""
    return screen.press(keys, lambda lines: title(lines) == ADD and f"  {name}" in lines)


class AddModel(unittest.TestCase):
    def test_the_three_steps_add_a_valid_model(self):
        screen = Screen(self, child=CHILD)
        lines = open_add(screen)
        self.assertEqual(lines[2], "  harness")
        self.assertEqual(listed(lines)[:2], [["claude", "Claude"], ["codex", "ChatGPT"]])
        self.assertEqual(highlighted(lines).split(), ["›", "claude", "Claude"])
        self.assertEqual(lines[-1], KEYS["choose"])
        lines = step(screen, ENTER, "model")
        self.assertEqual(lines[2:4], ["  harness  claude · Claude", "  model"])
        # the model whose efforts the catalog does not say is no choice; the one run is marked
        self.assertEqual(listed(lines), [["Opus 5.5", "claude-opus-5-5", "✓ opus"],
                                         ["Opus 5", "claude-opus-5"],
                                         ["Sonnet 5", "claude-sonnet-5"]])
        lines = step(screen, DOWN + DOWN + ENTER, "effort")
        self.assertEqual(lines[2:5], ["  harness  claude · Claude",
                                      "  model    Sonnet 5 · claude-sonnet-5", "  effort"])
        self.assertEqual(listed(lines), [["low"], ["medium"], ["high"]])
        self.assertEqual(lines[-1], KEYS["add"])
        lines = screen.press(DOWN + ENTER, lambda lines: title(lines) == "agentkit · config")
        self.assertEqual(highlighted(lines).split()[:3], ["›", "sonnet", "claude"])
        saved = screen.saved()
        self.assertEqual(saved["models"]["sonnet"],
                         {"harness": "claude", "model": "claude-sonnet-5", "effort": "medium",
                          "provider": "anthropic"})
        # offered both ways at once, and in neither default until it is chosen there
        self.assertEqual(saved["defaults"], {"orchestrator": "opus", "workers": ["opus", "astra"]})
        screen.leave()

    def test_esc_steps_back_one_level(self):
        screen = Screen(self, child=CHILD)
        open_add(screen)
        before = screen.path.read_bytes()
        step(screen, ENTER, "model")
        lines = step(screen, DOWN + ENTER, "effort")
        self.assertIn("  model    Opus 5 · claude-opus-5", lines)
        lines = step(screen, ESC, "model")
        self.assertEqual(highlighted(lines).split()[:3], ["›", "Opus", "5"])
        self.assertEqual(lines[-1], KEYS["choose"])
        lines = step(screen, ESC, "harness")
        self.assertEqual(highlighted(lines).split(), ["›", "claude", "Claude"])
        self.assertNotIn("  model", lines)
        lines = screen.press(ESC, lambda lines: title(lines) == "agentkit · config")
        self.assertTrue(highlighted(lines).startswith("› + add a model"))
        self.assertEqual(screen.path.read_bytes(), before)
        screen.leave()
        self.assertEqual(screen.path.read_bytes(), before)

    def test_a_taken_name_gets_a_suffix(self):
        screen = Screen(self, child=CHILD)
        open_add(screen)
        step(screen, ENTER, "model")
        step(screen, DOWN + ENTER, "effort")
        lines = screen.press(DOWN + DOWN + ENTER,
                             lambda lines: title(lines) == "agentkit · config")
        self.assertEqual(highlighted(lines).split()[1], "opus-2")    # `opus` is Opus 5.5's
        self.assertEqual(screen.saved()["models"]["opus-2"],
                         {"harness": "claude", "model": "claude-opus-5", "effort": "high",
                          "provider": "anthropic"})
        open_add(screen)
        lines = step(screen, ENTER, "model")
        self.assertEqual(listed(lines)[1], ["Opus 5", "claude-opus-5", "✓ opus-2"])
        step(screen, DOWN + ENTER, "effort")
        lines = screen.press(ENTER, lambda lines: title(lines) == "agentkit · config")
        self.assertEqual(highlighted(lines).split()[1], "opus-3")
        self.assertEqual(screen.saved()["models"]["opus-3"]["effort"], "low")
        screen.leave()

    def test_a_configured_model_can_be_added_again_at_another_effort(self):
        screen = Screen(self, child=CHILD)
        open_add(screen)
        lines = step(screen, ENTER, "model")
        self.assertEqual(listed(lines)[0], ["Opus 5.5", "claude-opus-5-5", "✓ opus"])
        lines = step(screen, ENTER, "effort")
        self.assertEqual(listed(lines), [["low"], ["medium"], ["high"], ["xhigh", "✓ opus"],
                                         ["max"]])
        before = screen.path.read_bytes()
        lines = screen.press(DOWN * 3 + ENTER, lambda lines: "opus runs claude-opus-5-5 at "
                                                             "xhigh already" in lines[-3])
        self.assertEqual(title(lines), ADD)                   # nothing added, still choosing
        self.assertEqual(screen.path.read_bytes(), before)
        lines = screen.press(UP + ENTER, lambda lines: title(lines) == "agentkit · config")
        self.assertEqual(highlighted(lines).split()[1], "opus-2")
        models = screen.saved()["models"]
        self.assertEqual(models["opus-2"], {"harness": "claude", "model": "claude-opus-5-5",
                                            "effort": "high", "provider": "anthropic"})
        self.assertEqual(models["opus"]["effort"], "xhigh")
        screen.leave()

    def test_a_removed_providers_harness_is_not_offered(self):
        screen = Screen(self, child=CHILD, text=TWO)
        lines = open_add(screen)
        # codex's provider has no table, so no provider offers it; Google's has one and no
        # model, the shipped default's harness standing in for it; Acme's is its model's
        self.assertEqual(listed(lines), [["claude", "Claude"], ["antigravity", "Gemini"],
                                         ["opencode", "Acme"]])
        # a catalog with nothing to offer says so, and Esc goes back
        lines = screen.press(DOWN * 2 + ENTER, lambda lines: "the opencode catalog names no "
                                                             "model with its efforts" in lines[-3])
        self.assertEqual(lines[2:4], ["  harness  opencode · Acme", "  model"])
        self.assertEqual(listed(lines), [])
        lines = step(screen, ESC, "harness")
        self.assertEqual(highlighted(lines).split(), ["›", "opencode", "Acme"])
        number = next(number for number, line in enumerate(lines, 1) if "antigravity" in line)
        lines = screen.click(6, number, lambda lines: "  model" in lines)
        self.assertEqual(lines[2], "  harness  antigravity · Gemini")
        self.assertEqual(listed(lines), [["Gemini 3.1 Pro", "gemini-3.1-pro"],
                                         ["Gemini 3.8 Flash with Extended Thinking",
                                          "gemini-3.8-flash"]])
        lines = step(screen, ENTER, "effort")
        self.assertEqual(listed(lines), [["low"], ["high"]])
        lines = screen.press(DOWN + ENTER, lambda lines: title(lines) == "agentkit · config")
        self.assertIn("Gemini", lines)
        self.assertEqual(highlighted(lines).split()[1], "gemini-pro")
        saved = screen.saved()
        self.assertEqual(saved["models"]["gemini-pro"],
                         {"harness": "antigravity", "model": "gemini-3.1-pro", "effort": "high",
                          "provider": "google"})
        self.assertNotIn("openai", saved["providers"])
        screen.leave()

    def test_a_phone_draws_each_step_in_forty_columns(self):
        screen = Screen(self, child=CHILD, rows=24, cols=40)
        drawn = [open_add(screen), step(screen, ENTER, "model"), step(screen, ENTER, "effort")]
        for lines in drawn:
            self.assertLessEqual(len(lines), 23)
            for line in lines:
                self.assertLessEqual(terminal.cells(line), 40, line)
        self.assertEqual(listed(drawn[1])[0], ["Opus 5.5", "claude-opus-5-5", "✓ opus"])
        # a label and an id too wide for the row: the id gives way, then the label, not the mark
        step(screen, ESC + ESC, "harness")
        lines = step(screen, DOWN * 4 + ENTER, "model")
        self.assertEqual(lines[2], "  harness  antigravity · Gemini")
        self.assertEqual(listed(lines)[1], ["Gemini 3.8 Flash with…", "✓ gemini"])
        for line in lines:
            self.assertLessEqual(terminal.cells(line), 40, line)
        screen.press(ESC + ESC, lambda lines: title(lines) == "agentkit · config")
        screen.leave()


if __name__ == "__main__":
    unittest.main()
