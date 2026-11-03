"""Workers spend the launching seat's subscription last.

Black-box: AK_BIN runs in a temporary HOME with an invented provider, injected usage
readings, scripted adapters and a seat record; no real login, meter or seat is reached.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import PLAN_LINE
from fixtures.gitrig import Rig


class SeatAccountLast(unittest.TestCase):
    def launch(self, second_used=20, *, seat="first", accounts=("first", "second"),
               second_ready=True, seat_provider="acme"):
        with Home() as home:
            rig = Rig(home)
            akconfig.write(home, {"beta": {"harness": "acme", "provider": "acme"},
                                  "alpha": {"harness": "acme", "provider": seat_provider}},
                           orchestrator="alpha", workers=["beta"],
                           providers={"acme": {"accounts": list(accounts)}})
            home.fake("acme", "#!/bin/sh\nexit 0\n")
            fake = fakeadapter.install(home, acme="work")["acme"]
            if not second_ready:
                fake.script.write_text(fake.script.read_text().replace("#!/bin/sh\n",
                    '#!/bin/sh\nif [ "$1" = auth ] && [ "$AGENTKIT_ACCOUNT" = second ]; then\n'
                    '  echo "acme: login expired"; exit 1\nfi\n'))
            if seat is not None:
                home.write(".agentkit/state/session-fix-api.json", {
                    "orchestrator": "alpha", "workers": ["beta"], "account": seat,
                    "cwd": str(rig.path), "created": 1})
                home.write(".agentkit/state/plan-fix-api.md", PLAN_LINE + "\n")
                home.env["AGENTKIT_SESSION"] = "fix-api"
            now = time.time()

            def reading(used):
                return {"provider": "acme", "resets": 0, "meters": [
                    {"name": "weekly_all", "used": used, "window_secs": 604800,
                     "resets_at": now + 3 * 86400}]}

            home.write(".agentkit/state/usage.json", {
                "fetched_at": now, "reset_checked_at": now, "providers": {"acme": {
                    **reading(10), "accounts": dict(zip(accounts, (reading(10),
                                                                 reading(second_used))))}}})
            task = taskfile.write(home, rig.path)
            done = home.ak("run", str(task), "--no-merge", timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            turns = [call for call in fake.runs() if call["role"] == "executor"]
            self.assertEqual(len(turns), 1, turns)
            return turns[0]["env"].get("AGENTKIT_ACCOUNT")

    # "Among the marks ak picks in that order, across its provider's accounts, the seat's
    # own last, the next once it is spent or cannot run." [18 Sep - 26 Oct 2026]
    def test_a_worker_spends_the_other_account_before_its_launching_seats(self):
        self.assertEqual(self.launch(), "second")

    def test_a_worker_uses_the_seats_account_once_the_other_is_spent(self):
        self.assertEqual(self.launch(100), "first")

    def test_a_worker_uses_the_seats_account_when_the_other_cannot_run(self):
        self.assertEqual(self.launch(second_ready=False), "first")

    def test_the_seats_account_is_last_even_beside_the_usual_login(self):
        self.assertEqual(self.launch(accounts=("first", "default")), "")

    def test_a_seat_on_the_second_account_leaves_workers_the_first(self):
        self.assertEqual(self.launch(seat="second"), "first")

    def test_without_a_launching_seat_the_account_order_stays_the_same(self):
        self.assertEqual(self.launch(seat=None), "first")
        self.assertEqual(self.launch(seat=None, accounts=("default", "second")), "second")

    def test_a_seat_on_another_provider_leaves_the_account_order_alone(self):
        self.assertEqual(self.launch(seat_provider="other"), "first")


if __name__ == "__main__":
    unittest.main()
