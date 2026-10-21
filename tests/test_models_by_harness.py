"""Every list of models sits under its harnesses, in each harness's colour, a model added last
included."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["HOME"] = tempfile.mkdtemp()

from agentkit import config, menu, orch, terminal  # noqa: E402


def cfg():
    """Claude Code's second model added after every other harness's, and a ChatGPT model run
    on OpenCode beside the one Codex runs, as `Models` leaves them."""
    return {
        "providers": {"anthropic": {}, "openai": {}, "meta": {}},
        "models": {
            "fable": {"harness": "claude", "model": "claude-fable-5-1", "effort": "xhigh",
                      "provider": "anthropic"},
            "astra": {"harness": "codex", "model": "default", "effort": "xhigh",
                      "provider": "openai"},
            "sol": {"harness": "opencode", "model": "openai/gpt-6.1-sol", "effort": "high",
                    "provider": "openai"},
            "spark": {"harness": "muse", "model": "muse-spark-1.3-contributor", "effort": "max",
                      "provider": "meta"},
            "orphan": {"harness": "grokbuild", "model": "grok-4.7", "effort": "xhigh",
                       "provider": "xai"},
            "sonnet": {"harness": "claude", "model": "claude-sonnet-5-5", "effort": "xhigh",
                       "provider": "anthropic"},
        },
        "defaults": {"orchestrator": "fable", "workers": ["fable", "astra"]},
    }


ORDER = ["fable", "sonnet", "astra", "sol", "spark"]
HEADINGS = [("Claude Code", "#D97757"), ("Codex", "#FFFFFF"), ("OpenCode", "#5B98F1"),
            ("Muse Code", "#3E9EFB")]


class ModelsByHarness(unittest.TestCase):
    def setUp(self):
        colour = patch.object(terminal, "colour_depth", return_value=24)   # each heading's own
        colour.start()
        self.addCleanup(colour.stop)

    def test_offered_sits_each_model_under_its_harness(self):
        self.assertEqual(config.offered(cfg()), ORDER)

    def test_the_new_session_and_config_screens_list_the_same_order_under_the_same_headings(self):
        config_ = cfg()
        notes = {name: "" for name in config.offered(config_)}   # as `n` builds them
        selected = {"orchestrator": "fable", "workers": ["fable"], "reviewers": ["astra"]}
        lines, rows, _ = orch.picker_lines(config_, notes, selected, None, 0, 40)
        body, places = menu.config_body(config_, selected=selected)
        headings = [terminal.styled(name, colour) for name, colour in HEADINGS]
        self.assertEqual(len(set(headings)), len(HEADINGS))       # four colours, none the same
        for drawn, positions in ((lines, [row.start for row in rows]),
                                 (body, [line for line, (hit, _) in places.items()
                                         if hit[0] == "model"])):
            # each by its full name (config.model_name), cut where the screen is narrow
            shown = [terminal.plain(drawn[line]).split()[0].rstrip("…") for line in positions]
            self.assertEqual(len(shown), len(ORDER))
            for text, name in zip(shown, ORDER):
                self.assertTrue(config.model_name(config_, name).startswith(text), (text, name))
            self.assertEqual([line for line in drawn if line in headings], headings)

    def test_a_harness_its_manifest_gives_no_colour_is_headed_in_the_accent(self):
        self.assertEqual(menu.model_heading("acme"), terminal.styled("acme", "accent"))


if __name__ == "__main__":
    unittest.main()
