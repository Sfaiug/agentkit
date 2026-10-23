"""A config.toml ak saves is rewritten whole: its header, mode 0600, no comments, a fixed order.

Opening a seat remembers its models as the next seat's [defaults], and that is a save of the
whole config.toml, the file the owner also edits by hand and the `c` screen writes: it starts
with two lines saying a comment will not survive, it is the owner's alone (0600, whatever mode
it had), and nothing of it is lost but comments: every unknown key and table is kept with its
value.  Its layout is fixed, so two saves of one config read the same: the known top-level keys
in their order, then unknown ones as the file had them; [defaults]; [models.*] and
[providers.*] in file order, each with its known keys first in their order; then every other
table as the file had it.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py on the echo fixture's harness; this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home

ADAPTERS = Path(__file__).resolve().parent / "fixtures" / "adapters"
HEADER = ["# agentkit's config, written by the menu's `c` screen. It is rewritten whole on every "
          "change,",
          "# so a comment left here would not survive it; unknown keys are kept as they are."]
# Out of order on purpose: an unknown top-level key first, known keys reversed, [defaults]
# after the models, [providers.*] before them, model `two` before `one`, unknown keys first.
CONFIG = """# keep me
acme_knob = "on"   # and me
within = 5
pace_margin = 0.25
run_memory_max_mb = 4096
max_load = 64.0
min_free_mb = 512
max_gates = 2
max_runs = 3

[audit]
on = false

[providers.test]
acme_note = "kept"
mode = "subscription"

[models.two]
custom_flag = true
provider = "test"
review_effort = "low"
exec_effort = "medium"
effort = "high"
model = "echo-2"
harness = "echo"

[models.one]
harness = "echo"
model = "echo-1"
effort = "high"
provider = "test"

[defaults]
orchestrator = "one"
workers = ["one", "two"]

[zeta]
knob = 1

[zeta.inner]
deep = ["a", "b"]
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ConfigSave(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.env["AGENTKIT_ADAPTER_DIR"] = str(ADAPTERS)
        cls.path = cls.home.write(".agentkit/config.toml", CONFIG)
        cls.path.chmod(0o644)
        cls.home.path.joinpath("code").mkdir()
        cls.done = cls.home.ak("orch", "demo", "--model", "two", "--workers", "one", tty=True,
                               cwd=cls.home.path / "code")
        cls.text = cls.path.read_text()
        cls.lines = cls.text.splitlines()

    def setUp(self):
        self.assertEqual(self.done.code, 0, self.done.err)

    def section(self, header):
        """The `key =` lines of one table, or of the top level before any table."""
        at = self.lines.index(header) + 1 if header else 0
        keys = []
        for line in self.lines[at:]:
            if line.startswith("["):
                break
            if " = " in line:
                keys.append(line.split(" = ", 1)[0])
        return keys

    def test_it_starts_with_the_header_and_keeps_no_comment(self):
        self.assertEqual(self.lines[:2], HEADER)
        self.assertEqual([line for line in self.lines if line.lstrip().startswith("#")], HEADER)
        self.assertNotIn("keep me", self.text)
        self.assertNotIn("and me", self.text)

    def test_it_is_the_owner_s_alone_and_leaves_no_temporary_file(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(sorted(p.name for p in self.path.parent.glob("config*")),
                         ["config.toml"])

    def test_every_value_is_kept_and_defaults_are_the_new_seat_s(self):
        saved, given = tomllib.loads(self.text), tomllib.loads(CONFIG)
        self.assertEqual(saved.pop("defaults"), {"orchestrator": "two", "workers": ["one"]})
        given.pop("defaults")
        self.assertEqual(saved, given)

    def test_known_top_level_keys_lead_in_their_order_and_unknown_ones_follow(self):
        self.assertEqual(self.section(None), ["max_runs", "max_gates", "min_free_mb", "max_load",
                                              "run_memory_max_mb", "pace_margin", "within",
                                              "acme_knob"])

    def test_tables_go_defaults_models_providers_then_the_rest_as_the_file_had_them(self):
        self.assertEqual([line for line in self.lines if line.startswith("[")],
                         ["[defaults]", "[models.two]", "[models.one]", "[providers.test]",
                          "[audit]", "[zeta]", "[zeta.inner]"])

    def test_a_model_s_and_a_provider_s_known_keys_lead_and_unknown_ones_follow(self):
        self.assertEqual(self.section("[models.two]"),
                         ["harness", "model", "effort", "exec_effort", "review_effort",
                          "provider", "custom_flag"])
        self.assertEqual(self.section("[models.one]"), ["harness", "model", "effort", "provider"])
        self.assertEqual(self.section("[providers.test]"), ["mode", "acme_note"])
        self.assertEqual(self.section("[defaults]"), ["orchestrator", "workers"])


if __name__ == "__main__":
    unittest.main()
