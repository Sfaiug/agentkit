"""`ak usage` says how much of what a login has left is kept for a cap's model.

A login whose reading holds a part of its shared week for a cap (`held` > 0 on the cap's meter,
its window not ended) gains one row under `left`, in the points of the week as `left` is, naming
whose it is by the cap's `scope` (`kept for Fable  3%`); `left` stays the week as read.  A login
holding nothing, and one whose cap's window has ended, show today's rows; `ak usage --json` is
unchanged by the row.

Black-box: AK_BIN in a temporary HOME with invented readings in state/usage.json and a standing
usage clock (`AK_USAGE_CLOCK`, tests/fixtures/clock.py), run at card and table widths.  Fails
against /bin/false.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, clock, meters
from fixtures.akbin import Home

MODELS = {"anvil-main": {"harness": "echo", "provider": "acme"},
          "anvil-fable": {"harness": "echo", "provider": "acme"}}
CARD = {"COLUMNS": "40"}
WIDE = {"COLUMNS": "200"}
STANDARD_LABELS = ("left", "holds", "a month", "resets", "week elapsed", "session",
                   "resets held", "headroom", "budget", "outlook")


def card_rows(out, heading):
    """(label, value) pairs of `heading`'s card on `ak usage` at card width."""
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(heading))
    end = next((i for i in range(start + 1, len(lines)) if not lines[i]), len(lines))
    rows = []
    for line in lines[start + 1:end]:
        if line.startswith("  ") and not line.startswith("   "):
            label, value = line.strip().rsplit("  ", 1)
            rows.append((label.strip(), value.strip()))
    return rows


class UsageSaysThePartKeptForACap(unittest.TestCase):
    def usage(self, logins, *, clock_offset=0, now=None):
        """(card text, wide text, `--json` payload) for `logins`, {account: (week_used, cap_held,
        cap_resets_offset)} where `cap_resets_offset` is seconds from `now`; `AK_USAGE_CLOCK`
        stands at `now + clock_offset`."""
        with Home() as home:
            meters.install(home)
            now = int(time.time()) if now is None else now
            clock.standing(home, "AK_USAGE_CLOCK", now + clock_offset)
            accounts_cfg = {"accounts": list(logins)} if len(logins) > 1 else {}
            akconfig.write(home, MODELS, providers={"acme": {"mode": "subscription",
                                                             **accounts_cfg}})

            def reading(week_used, held, resets_offset):
                week = {"name": "weekly_all", "used": week_used, "window_secs": meters.WEEK,
                        "resets_at": now + 3 * 86400, "elapsed": 57}
                cap = {"name": "weekly_scoped", "scope": "Fable", "used": 20,
                       "window_secs": meters.WEEK, "resets_at": now + resets_offset, "elapsed": 57}
                if held is not None:
                    cap["held"] = held
                return {"provider": "acme", "resets": 0, "meters": [week, cap]}

            built = {account: reading(*spec) for account, spec in logins.items()}
            prov = ({**built["default"], "accounts": built}
                    if len(logins) > 1 else built["default"])
            home.write(".agentkit/state/usage.json", {
                "fetched_at": now, "reset_checked_at": now, "providers": {"acme": prov}})
            card, wide, data = (home.ak("usage", env=CARD), home.ak("usage", env=WIDE),
                                home.ak("usage", "--json"))
            for done in (card, wide, data):
                self.assertEqual(done.code, 0, done.out + done.err)
            return card.out, wide.out, json.loads(data.out)

    def test_a_login_whose_cap_holds_three_shows_the_row_under_left(self):
        card, wide, _ = self.usage({"default": (58, 3, 3 * 86400),
                                    "second": (40, None, 3 * 86400)})
        rows = card_rows(card, "Acme I ")
        self.assertEqual(rows[:2], [("left", "42%"), ("kept for Fable", "3%")])
        self.assertEqual(tuple(label for label, _ in rows),
                         ("left", "kept for Fable", *STANDARD_LABELS[1:]))
        second_rows = card_rows(card, "Acme II ")
        self.assertEqual(tuple(label for label, _ in second_rows), STANDARD_LABELS)
        self.assertEqual(second_rows[0], ("left", "60%"))
        card_lines = card.splitlines()
        left_line = next(line for line in card_lines if line.startswith("  left "))
        kept_line = next(line for line in card_lines if line.startswith("  kept for Fable "))
        self.assertEqual(left_line.index("42%"), kept_line.index("3%"))
        for line in card_lines:
            self.assertLessEqual(len(line), 40, line)
            self.assertEqual(line, line.rstrip(), repr(line))
        self.assertEqual(meters.cell(wide, "Acme I", "left"), "42%")
        self.assertEqual(meters.cell(wide, "Acme II", "left"), "60%")
        wide_lines = wide.splitlines()
        first_at = next(i for i, line in enumerate(wide_lines) if line.startswith("Acme I "))
        second_at = next(i for i, line in enumerate(wide_lines) if line.startswith("Acme II "))
        self.assertTrue(wide_lines[first_at + 1].startswith("  kept for Fable  "))
        self.assertEqual(wide_lines[first_at].index("42%"), wide_lines[first_at + 1].index("3%"))
        self.assertEqual(second_at, first_at + 2)
        self.assertFalse(wide_lines[second_at + 1].startswith("  kept for"))

    def test_holding_nothing_and_an_ended_cap_window_show_todays_rows(self):
        # Cap window ends at +50s (still future to collect's real clock, past AK_USAGE_CLOCK at +100s)
        card, wide, _ = self.usage({"default": (58, None, 3 * 86400),
                                    "second": (40, 0, 3 * 86400),
                                    "third": (70, 3, 50)}, clock_offset=100)
        for label, left in (("Acme I ", "42%"), ("Acme II ", "60%"), ("Acme III ", "30%")):
            rows = card_rows(card, label)
            self.assertEqual(tuple(name for name, _ in rows), STANDARD_LABELS, label)
            self.assertEqual(rows[0], ("left", left), label)
        self.assertNotIn("kept for", card)
        self.assertNotIn("kept for", wide)

    def test_ak_usage_json_is_unchanged_by_the_row(self):
        now = int(time.time())
        _, _, held = self.usage({"default": (58, 3, 3 * 86400)}, now=now)
        _, _, plain = self.usage({"default": (58, None, 3 * 86400)}, now=now)

        def steady(data):
            prov = {k: v for k, v in data["providers"]["acme"].items() if k != "budget"}
            prov["meters"] = [{k: v for k, v in m.items() if k != "held"} for m in prov["meters"]]
            return {**data, "providers": {"acme": prov}}

        self.assertEqual(steady(held), steady(plain))
        scoped = next(m for m in held["providers"]["acme"]["meters"]
                      if m["name"] == "weekly_scoped")
        self.assertEqual(scoped["held"], 3)


if __name__ == "__main__":
    unittest.main()
