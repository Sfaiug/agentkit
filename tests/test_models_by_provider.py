"""Every list of models sits under its providers, a model added last included."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["HOME"] = tempfile.mkdtemp()

from agentkit import config, menu, orch, terminal  # noqa: E402


def cfg():
    """Claude's second model added after every other provider's, as `+ add a model` leaves it."""
    return {
        "providers": {"anthropic": {}, "openai": {}, "meta": {}},
        "models": {
            "fable": {"harness": "claude", "model": "claude-fable-5-1", "effort": "xhigh",
                      "provider": "anthropic"},
            "astra": {"harness": "codex", "model": "default", "effort": "xhigh",
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


ORDER = ["fable", "sonnet", "astra", "spark"]


class ModelsByProvider(unittest.TestCase):
    def test_offered_sits_each_model_under_its_provider(self):
        self.assertEqual(config.offered(cfg()), ORDER)

    def test_the_config_screen_lists_the_same_order(self):
        self.assertEqual(menu.config_models(cfg()), ORDER)

    def test_the_new_session_and_config_screens_list_the_same_order(self):
        config_ = cfg()
        notes = {name: "" for name in config.offered(config_)}   # as `n` builds them
        selected = {"orchestrator": "fable", "workers": ["fable"], "reviewers": ["astra"]}
        lines, rows, _ = orch.picker_lines(config_, notes, selected, None, 0, 40)
        body, places = menu.config_body(config_, "fixture", selected=selected)
        for drawn, positions in ((lines, [row.start for row in rows]),
                                 (body, [line for line, (hit, _) in places.items()
                                         if hit[0] == "model"])):
            self.assertEqual([terminal.plain(drawn[line]).split()[0] for line in positions], ORDER)


if __name__ == "__main__":
    unittest.main()
