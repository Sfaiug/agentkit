"""ak shows what its rented machines cost this month and gives back any past its time or the cap.

Black-box: `AK_BIN` runs `ak watch` in `home.tick()`'s box and `ak doctor` on a fake Google's clock.
"""

from datetime import UTC, datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, REPO, Home, boxable
from fixtures.google import ADDRESS, NL, SPOT, Google, kind, sku

# Every `bin/ak` gives `google_cloud` the test clock, at the time in the file it names.
CLOCK = """
import sys, time
if sys.argv[:1] == [{ak!r}]:
    sys.path[:0] = [{repo!r}, {tests!r}]
    from fixtures.clock import Clock
    from agentkit import google_cloud
    del sys.path[:2]
    google_cloud.time = Clock(time.sleep)
    google_cloud.time.time = lambda: float(open({now!r}).read())
"""
# c4a-standard-8 costs €6.0045 an hour: €5.60 its cores, €0.40 memory, €0.0045 disk and address
P, HOUR = 6.0045, 3600
SKUS = [sku(f"{SPOT} C4A Arm Instance Core running in Netherlands", NL, 700_000_000),
        sku(f"{SPOT} C4A Arm Instance Ram running in Netherlands", NL, 12_500_000),
        sku("Hyperdisk Balanced Capacity in Netherlands", NL, 73_000_000, "GiBy.mo"), ADDRESS]
T, DECEMBER = (datetime(2026, *at, tzinfo=UTC).timestamp() for at in ((11, 1, 2), (12, 1, 0, 30)))


def machine(id, created, hours, labels={"ak": "rented"}):
    return {"id": id, "name": f"acme-{id}", "creationTimestamp": created, "labels": labels,
            "machineType": "zones/europe-west4-a/machineTypes/c4a-standard-8",
            "scheduling": {"maxRunDuration": {"seconds": str(hours * HOUR)}}}


# acme-1 from 23:00 UTC until 05:00, acme-2 from 00:30, acme-3 from 02:00; acme-9 never ak's
ONE, TWO, THREE, FOUR, OWN = (machine(*row) for row in (
    ("1", "2026-10-31T16:00:00.000-07:00", 6), ("2", "2026-11-01T00:30:00Z", 1),
    ("3", "2026-11-01T02:00:00Z", 0), ("4", "2026-12-01T00:00:00Z", 6),
    ("9", "2026-10-01T00:00:00Z", 0, {"team": "acme"})))


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class WatchesTheBill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.google = google = Google(home, [SKUS], [{"zones/europe-west4-a": {
            "machineTypes": [kind("c4a-standard-8", 8, 32)]}}])
        cls.addClassCleanup(google.close)
        google.key()
        home.write("clock/sitecustomize.py", CLOCK.format(
            ak=AK, repo=str(Path(AK).resolve().parents[1]), tests=str(REPO / "tests"),
            now=str(home.path / "clock" / "now")))
        google.env["PYTHONPATH"] = str(home.path / "clock")
        google.machines = [ONE, OWN]
        cls.off = cls.at(T)
        config = home.path / ".agentkit/config.toml"
        config.write_text(config.read_text() + "\n[google_cloud]\nactive = true\nmax_month = 30\n")
        cls.unpriced = cls.at(T)
        # renamed, acme-1 keeps its meter; acme-3 is read again as another machine of its name
        google.machines = [{**ONE, "name": "acme-1b"}, TWO, OWN, THREE]
        google.again, google.refused = {"acme-3": FOUR}, {"acme-2"}
        cls.refused, google.silent = cls.at(T + 180), True
        cls.unanswered = cls.at(T + HOUR)
        google.silent, google.refused, google.machines = False, set(), google.machines[:3]
        cls.over = cls.at(T + 2 * HOUR)
        google.machines = [FOUR, OWN]
        cls.december = cls.at(DECEMBER)
        google.refused, cls.unreadable = {"acme-4"}, []
        for text in ("{", "null", '{"answered": 1, "spent": NaN, "machines": {}}'):
            ledger = home.write(".agentkit/state/google-cloud-ledger.json", text)
            cls.unreadable += [(text, cls.at(DECEMBER + 180), ledger.read_text())]

    @classmethod
    def at(cls, when):
        """At `when`, what a tick asked Google, whom it deleted, and `ak doctor`'s lines then."""
        cls.home.write("clock/now", str(when))
        start, done = len(cls.google.asked), cls.home.tick(env=cls.google.env)
        assert done.code == 0, done.out + done.err
        asked = cls.google.asked[start:]
        return asked, [one[7:] for one in asked if one.startswith("DELETE ")], [
            line.removeprefix("rented machines: ") for line in cls.google.rented()]

    def test_off_asks_nothing_on_one_past_its_end_or_unpriced_goes_back_and_prices_follow(self):
        self.assertEqual((*self.off[:2], self.off[2][0][:23]), ([], [], "best now c4a-standard-8"))
        self.assertEqual(self.unpriced[1:], (["acme-1"], [
            "1 running · €0.00 of €30.00 this month",
            "acme-1 listed with no price kept, given back"]))
        # acme-1b 3 minutes, acme-2 from 00:30 and acme-3 from 02:00
        self.assertEqual(self.refused[1:], (["acme-2"], [
            f"3 running · €{1.65 * P:.2f} of €30.00 this month",
            "acme-2 listed past its end, not given back: Google refused: Forbidden",
            "acme-3 listed past its end, given back"]))
        self.assertEqual([sum("/skus?" in one for one in step[0]) for step in (
            self.unpriced, self.refused, self.over, self.december)], [1, 0, 0, 1])
        self.assertNotIn("Partial", str([one for one in self.google.asked if "/instances?" in one]))
        # a Google that does not answer is asked once and moves nothing
        self.assertEqual(self.unanswered, (["/token"], [], [
            f"3 running · €{1.65 * P:.2f} of €30.00 this month as of 1 Nov 02:03",
            *self.refused[2][1:]]))

    def test_past_the_cap_each_goes_back_and_a_month_counts_its_own_time(self):
        # acme-1b and acme-2 1.95 hours more, acme-3 nothing past its end
        self.assertEqual(self.over[1:], (["acme-1b", "acme-2"], [
            f"2 running · €{5.55 * P:.2f} of €30.00 this month",
            "acme-1b listed past the cap, given back", "acme-2 listed past its end, given back"]))
        # acme-4 half an hour, acme-1b's last hour in November
        self.assertEqual(self.december[1:], ([], ["1 running · €3.00 of €30.00 this month"]))
        # a ledger that cannot be read is past the cap, and kept; a refusal is still said
        for text, step, kept in self.unreadable:
            self.assertEqual((step[1:], kept), ((["acme-4"], [
                "cannot read ~/.agentkit/state/google-cloud-ledger.json: all machines go back",
                "acme-4 listed past the cap, not given back: Google refused: Forbidden"]), text))


if __name__ == "__main__":
    unittest.main()
