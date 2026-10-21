"""A model's effort bar on `c` and a step along it read one list, the model's own: its harness's
listing where that says its efforts, else its adapter's `[catalog]` row, else the adapter's
`[effort] levels`, else config.EFFORTS (config.efforts).

OpenCode lists its free DeepSeek without saying its efforts; the bar counts, and a step walks,
the low, high and max its `[catalog]` row gives, never the generic list's six.  A Muse Wonder
model at `max` stands at the end of its own list: its bar is full and a step goes no further.

Offline: a temporary HOME, the OpenCode listing put in config's cache as if just asked, so
nothing asks a harness; the screen is menu.config_body, drawn without UTF-8 so a full cell is
`#` and an open one `-`, and nothing is saved past the temporary HOME.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, terminal

DEEPSEEK, WONDER = "opencode/deepseek-v4.1-flash-free", "muse-wonder-1.0"
CONFIG = f"""[defaults]
orchestrator = "deepseek"
workers = ["deepseek"]

[models.deepseek]
harness = "opencode"
model = "{DEEPSEEK}"
effort = "low"
provider = "opencode"

[models.wonder]
harness = "muse"
model = "{WONDER}"
effort = "max"
provider = "meta"

[providers.opencode]
mode = "payg"
[providers.meta]
mode = "subscription"
"""
# OpenCode's own listing, in hand: the free DeepSeek with no efforts said
LISTING = [{"id": DEEPSEEK, "label": "DeepSeek V4.1 Flash Free", "efforts": []}]


class OneList(unittest.TestCase):
    def setUp(self):
        home = Path(tempfile.mkdtemp(prefix="effort-one-list-"))
        self.addCleanup(shutil.rmtree, home)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(home), "NO_COLOR": "1", "LANG": "C", "LC_ALL": "C"}))
        os.environ.pop(config.ADAPTER_DIR_ENV, None)
        stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, home / name.lower()))
        stack.enter_context(patch.dict(config._CATALOGS, clear=True))
        stack.enter_context(patch.dict(config._ANSWERED, clear=True))
        stack.enter_context(patch.object(terminal, "width", return_value=100))
        config._CATALOGS["opencode"] = (time.monotonic(), LISTING)
        config._CATALOGS["muse"] = (time.monotonic(), [{"id": WONDER, "label": WONDER,
                                                        "efforts": []}])
        config.ensure_dirs()
        (home / config.CONFIG_NAME).write_text(CONFIG)
        self.cfg = config.load()

    def bar(self, name):
        """`name`'s effort as `c` draws it, on the row its full name leads: its cells, then its
        word."""
        lines, _places = menu.config_body(self.cfg)
        line = next(line for line in (terminal.ANSI.sub("", line) for line in lines)
                    if line.lstrip().startswith(config.model_name(self.cfg, name) + " "))
        return line.split()[-2:]

    def step(self, name, step=1):
        self.assertEqual(menu.config_effort(self.cfg, name, step), "")
        return self.cfg["models"][name]["effort"]

    def test_deepseek_counts_and_walks_its_catalog_row(self):
        self.assertEqual(self.bar("deepseek"), ["#--", "low"])
        self.assertEqual(self.step("deepseek"), "high")
        self.assertEqual(self.bar("deepseek"), ["##-", "high"])
        self.assertEqual(self.step("deepseek"), "max")
        self.assertEqual(self.bar("deepseek"), ["###", "max"])
        self.assertEqual(self.step("deepseek"), "max")      # its last: no `ultra` past it
        self.assertEqual(config.load()["models"]["deepseek"]["effort"], "max")

    def test_wonder_at_max_is_full_and_steps_no_further(self):
        self.assertEqual(self.bar("wonder"), ["######", "max"])
        self.assertEqual(self.step("wonder"), "max")
        self.assertEqual(self.step("wonder", -1), "xhigh")


if __name__ == "__main__":
    unittest.main()
