"""A seat's creation rewrites config.toml and keeps every value in it; one it cannot write back
leaves the file as it was.

Creating a seat records the models it started with as `[defaults]`, what the next `n` starts
from, and that write is of the whole file.  config.toml is the owner's, and other programs read
and write it too: a key ak does not know must come back with the same value, whatever its TOML
shape (a quoted key, a date, a float, infinity, a nan and its sign, an empty array, a nested
table, an array of tables, one mixing tables and values, a DEL in a string), or one seat's
creation silently loses a setting.  A value ak cannot write back must cost only the remembered
defaults, never the file or the seat.  Black-box: `ak orch NAME --model --workers` runs from a
terminal through tests/fixtures/akbin.py on a fake harness, and the file is judged by what it
parses to, not by how ak spelled it.
"""

import stat
import struct
import sys
from pathlib import Path
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures import akconfig, fakeadapter

CONFIG = ".agentkit/config.toml"
DEFAULTS = '''
[defaults]
orchestrator = "one"
workers = ["one"]
'''
TABLES = '''
[models.one]
harness = "claude"
model = "one"
effort = "high"
provider = "anthropic"
{one}
[models.two]
harness = "claude"
model = "two"
effort = "high"
provider = "anthropic"

[providers.anthropic]
mode = "subscription"
{provider}
[audit]
on = false
'''
UNKNOWN = ('"odd key" = 1\nmystery = [1, 2]\nwhen = 2026-10-01\n' + DEFAULTS +
           TABLES.format(one='live_host = "acme.example"\ncolour = "teal"\ncustom_flag = true\n',
                         provider="price = 20.5\naccounts = []\n") + '''
[[hooks_list]]
x = 1

[[hooks_list]]
x = 2

[extra]
a = 1

[extra.inner]
b = 2
''')
# A provider that is no table: the one value a test can put in the file that ak reads and
# cannot write back, as the writer orders each provider's keys.
UNWRITABLE = DEFAULTS + TABLES.format(one="", provider="") + "\n[providers]\nweird = 1\n"
# What tomllib reads that repr, json.dumps or [[tables]] alone would not write back as read.
ODD = DEFAULTS + TABLES.format(one="", provider="") + '''
[extra]
far = -inf
lost = -nan
mixed = [{"\\u007f" = "\\u007f"}, 1]
'''


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SaveKeeps(unittest.TestCase):
    def setUp(self):
        # Each case creates the same seat: a second creation would find the first one's.
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")

    def create(self):
        done = self.home.ak("orch", "demo", "--model", "two", "--workers", "one", tty=True)
        self.assertEqual(done.code, 0, done.err)

    def test_every_key_ak_does_not_know_comes_back_with_its_value(self):
        self.home.write(CONFIG, UNKNOWN)
        self.create()
        saved, given = akconfig.read(self.home), tomllib.loads(UNKNOWN)
        # The file was rewritten: it records the seat just created.
        self.assertEqual(saved.pop("defaults"), {"orchestrator": "two", "workers": ["one"]})
        given.pop("defaults")
        self.assertEqual(saved, given)

    def test_infinity_nan_del_and_a_mixed_array_come_back(self):
        self.home.write(CONFIG, ODD)
        self.create()
        bits = lambda token: struct.pack("<d", float(token))     # a nan equals itself, signed
        saved = tomllib.loads((self.home.path / CONFIG).read_text(), parse_float=bits)
        self.assertEqual(saved["defaults"], {"orchestrator": "two", "workers": ["one"]})
        self.assertEqual(saved["extra"], tomllib.loads(ODD, parse_float=bits)["extra"])

    def test_a_value_ak_cannot_write_back_leaves_the_file_and_the_seat_still_opens(self):
        path = self.home.write(CONFIG, UNWRITABLE)
        path.chmod(0o644)
        before = path.read_bytes()
        self.create()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        self.assertTrue((self.home.path / ".agentkit/state/session-demo.json").is_file())
        self.assertEqual(self.home.tmux("has-session", "-t", "=demo").code, 0)


if __name__ == "__main__":
    unittest.main()
