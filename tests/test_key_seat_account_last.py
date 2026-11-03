"""Workers spend the launching seat's subscription last.

Black-box: AK_BIN runs in a temporary HOME with an invented provider, injected usage
readings, scripted adapters and a seat record; no real login, meter or seat is reached.
"""

import json
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
               second_ready=True, seat_provider="acme", scoped_spent=False,
               resume=False, launching_account=None):
        with Home() as home:
            rig = Rig(home)
            # Claude's scripted quota refusal parks a run for the resume cases.
            harness = "claude" if resume else "acme"
            akconfig.write(home, {"beta": {"harness": harness, "provider": "acme"},
                                  "alpha": {"harness": harness, "provider": seat_provider,
                                            **({"meter": "weekly_scoped"} if scoped_spent else {})}},
                           orchestrator="alpha", workers=["beta"],
                           providers={"acme": {"accounts": list(accounts)}})
            home.fake(harness, "#!/bin/sh\nexit 0\n")
            fake = fakeadapter.install(home, **{harness: "work"})[harness]
            if not second_ready:
                fake.script.write_text(fake.script.read_text().replace("#!/bin/sh\n",
                    '#!/bin/sh\nif [ "$1" = auth ] && [ "$AGENTKIT_ACCOUNT" = second ]; then\n'
                    '  echo "acme: login expired"; exit 1\nfi\n'))
            def record(name, account):
                home.write(f".agentkit/state/session-{name}.json", {
                    "orchestrator": "alpha", "workers": ["beta"], "account": account,
                    "cwd": str(rig.path), "created": 1})
                home.write(f".agentkit/state/plan-{name}.md", PLAN_LINE + "\n")

            if seat is not None:
                record("fix-api", seat)
                home.env["AGENTKIT_SESSION"] = "fix-api"
            now = time.time()

            def reading(used):
                read = {"provider": "acme", "resets": 0, "meters": [
                    {"name": "weekly_all", "used": used, "window_secs": 604800,
                     "resets_at": now + 3 * 86400}]}
                if scoped_spent:
                    read["meters"].append({**read["meters"][0], "name": "weekly_scoped", "used": 100})
                return read

            readings = {
                "fetched_at": now, "reset_checked_at": now, "providers": {"acme": {
                    **reading(10), "accounts": dict(zip(accounts, (reading(10),
                                                                 reading(second_used))))}}}
            home.write(".agentkit/state/usage.json", readings)
            task = taskfile.write(home, rig.path)
            before = 0
            if resume:
                original = "old-api" if launching_account is not None else None
                if original:
                    record(original, launching_account)
                fake.behave("dead")
                stopped = home.ak("run", str(task), "--no-merge",
                                  env={"AGENTKIT_SESSION": original}, timeout=300)
                self.assertEqual(stopped.code, 1, stopped.out + stopped.err)
                directory = taskfile.only_run(home)
                state = json.loads((directory / "run.json").read_text())
                self.assertEqual((state["state"], state["launched_session"]), ("exhausted", original))
                fake.behave("work")
                home.write(".agentkit/state/usage.json", readings)
                before = len(fake.runs())
                done = home.ak("run", "resume", directory.name, timeout=300)
            else:
                done = home.ak("run", str(task), "--no-merge", timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            turns = [call for call in fake.runs()[before:] if call["role"] == "executor"]
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

    def test_another_models_spent_cap_leaves_the_workers_other_account_available(self):
        self.assertEqual(self.launch(seat="second", accounts=("default", "second"),
                                     scoped_spent=True), "")

    def test_a_seatless_run_resumed_inside_a_seat_keeps_its_account_order(self):
        self.assertEqual(self.launch(resume=True), "first")

    def test_a_resumed_run_uses_its_launching_seat_inside_another_seat_or_outside_one(self):
        self.assertEqual(self.launch(resume=True, launching_account="second"), "first")
        self.assertEqual(self.launch(seat=None, resume=True, launching_account="first"), "second")


if __name__ == "__main__":
    unittest.main()
