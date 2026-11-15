"""`ak usage` says what a login's shared week has left.

The owner (11 Nov 2026), of `ak usage` giving a Claude login `0%` left, headroom `0.0` and
`exhausted` while its week read 75% used beside Fable's full cap, and the ak screen and Claude's
own page both read `25% left`: "This is not right."  A row's `left`, `headroom` and `outlook`
read the week every model draws on, the one its `resets` names; a model's own cap that is spent
leaves its outlook the shared week's.  A spent shared week is still `exhausted`.

Black-box: the program `AK_BIN` names runs `ak usage` from outside through
tests/fixtures/akbin.py, on a terminal wide enough for the whole table, its Claude adapter over
a fake `curl` answering each login's shared week and Fable's own cap, both resetting in three
days, as the endpoint did on 11 Nov 2026.  This test fails against `/bin/false`.
"""

from pathlib import Path
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home

OPUS, FABLE = "claude-opus-5-5", "claude-fable-5-2"
WIDE = {"COLUMNS": "200"}


def table(case, **logins):
    """`ak usage`'s cell under each heading for each row, the logins given (`default`, `second`)
    each answering its shared week and Fable's cap at (week, cap)% used."""
    made = Home()
    case.addCleanup(made.close)
    accounts = {"accounts": list(logins)} if len(logins) > 1 else {}
    akconfig.write(made, {OPUS: "claude", FABLE: "claude"},
                   providers={"anthropic": {"mode": "subscription", **accounts}})
    assert not any("meter" in entry for entry in akconfig.read(made)["models"].values())
    resets = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 3 * 86400))
    for login, (week, cap) in logins.items():
        token = f"tok-{login}"
        made.write(".agentkit/secrets/claude_oauth_token"
                   + ("" if login == "default" else f".{login}"), token)
        made.write(f"{token}.json", {"limits": [
            {"kind": "weekly_all", "group": "weekly", "percent": week, "resets_at": resets,
             "scope": None},
            {"kind": "weekly_scoped", "group": "weekly", "percent": cap, "resets_at": resets,
             "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None}}]})
    # the answer of the login whose token the adapter's header file (`-H @file`) carries
    made.fake("curl", "#!/bin/sh\nfor arg; do case $arg in @*) "
                      "tok=$(sed -n 's/^Authorization: Bearer //p' \"${arg#@}\");; esac; done\n"
                      f"cat {shlex.quote(str(made.path))}/\"$tok.json\"\nprintf '\\n200'\n")
    made.fake("security", "#!/bin/sh\nexit 1\n")     # no Keychain login on any host
    done = made.ak("usage", env=WIDE)
    case.assertEqual(done.code, 0, done.out + done.err)
    labels = ["Claude"] if len(logins) == 1 else ["Claude I", "Claude II"]
    return {label: {heading: meters.cell(done.out, label, heading)
                    for heading in ("left", "headroom", "outlook")} for label in labels}


class SharedWeek(unittest.TestCase):
    def test_a_full_fable_cap_leaves_the_row_the_shared_week(self):
        row = table(self, default=(82, 100))["Claude"]
        self.assertEqual((row["left"], row["headroom"]), ("18%", "0.2"))
        self.assertNotEqual(row["outlook"], "exhausted")

    def test_a_full_shared_week_is_exhausted(self):
        row = table(self, default=(100, 10))["Claude"]
        self.assertEqual((row["left"], row["outlook"]), ("0%", "exhausted"))

    def test_each_login_reads_its_own_shared_week(self):
        rows = table(self, default=(100, 57), second=(82, 100))
        self.assertEqual(rows["Claude II"]["left"], "18%")
        self.assertEqual(rows["Claude I"]["left"], "0%")


if __name__ == "__main__":
    unittest.main()
