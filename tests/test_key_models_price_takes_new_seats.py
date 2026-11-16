"""Each time `r recommended` on `c` in a window of its own makes its answer (it opens, the boards
land), each of new seats' roles whose kept price holds (tests/test_key_models_price_said.py), the
orchestrator too, takes the best of its choices that costs no more than its limit where that is
not the row it uses, the owner's design of 5 Nov 2026: into [defaults] as ← and → take it, no
open seat's record changing, its entry in ak's state then naming the new model and effort, its
limit and unit as they were, saying `executor took Acme Mid 1 medium, the best up to $0.30 a
build` under the rows.  Where every choice costs more than its limit the role stays.

Black-box: `AK_BIN` in a terminal (tests/fixtures/akterm.py) in a window of its own, a seat open
beside it, a fake harness running five invented releases, the boards held as asked
(tests/test_key_role_choices.py); judged by the screen, config.toml and ak's state.  Fails
against /bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV
from test_key_models_price_takes import CHEAP, DEAR, MID, NAMES, ROWS, SEAT, price, under
from test_key_role_choices import hold

# new seats' roles, Step orchestrating and building at `high`, under the limit of 0.3 Mid drops to
CREW = {"orchestrator": "step", "workers": ["step"], "reviewers": ["fine"]}
ROLES = ("orchestrator", "executor", "reviewer")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NewSeatsPriceTakes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakeadapter.install(home, claude="pass")["claude"].answer("models", "".join(
            f"acme-{name}-1\tAcme {name.title()} 1\tmedium high\n" for name in NAMES))
        Seat(home, SEAT, model="top", record={**CREW, "orchestrator": "top"})     # open: it stays
        cls.state = home.path / ".agentkit/state"

    def fresh(self, mid, **kept):
        """The config with new seats on CREW, the boards with Mid at cost `mid`, and new seats
        keeping the prices `kept` by role, as a test starts."""
        akconfig.write(self.home, {name: {"harness": "claude", "model": f"acme-{name}-1"}
                                   for name in NAMES}, **CREW)
        self.boards(mid)
        for role in ROLES:
            self.path(role).unlink(missing_ok=True)
        for role, entry in kept.items():
            self.home.write(f".agentkit/state/models-{role}-price", entry)

    def boards(self, mid):
        """The boards holding Mid at cost `mid`, the answer made anew from them as they land."""
        hold(self.home, [(release, name, effort, quality / 100 - 0.1, mid if cost is None else cost)
                         for release, name, effort, quality, cost in ROWS])
        (self.state / "matrix.json").unlink(missing_ok=True)

    def path(self, role):
        return self.state / f"models-{role}-price"

    def kept(self):
        """{role: price} new seats keep in ak's state."""
        return {role: json.loads(self.path(role).read_text()) for role in ROLES
                if self.path(role).exists()}

    def held(self):
        """What a take writes: config.toml and new seats' prices; and the open seat's roles and
        prices, which a take there would write."""
        record = json.loads((self.state / f"session-{SEAT}.json").read_text())
        return akconfig.read(self.home), self.kept(), {
            key: value for key, value in record.items()
            if key in ("orchestrator", "workers", "reviewers") or key.endswith("_price")}

    def recommended(self):
        """`r` on `c` in a window of its own, once the boards landed: its answer made of them."""
        term = Terminal(self.home, size=(100, 60), env=ENV)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait("boards read")
        return term

    def said(self, term, text):
        term.wait(lambda screen: text in " ".join(screen.split()))

    def test_a_better_model_as_cheap_as_the_limit_is_taken_by_the_next_screen_and_said(self):
        self.fresh(DEAR, executor=price("step"))
        before = self.held()
        self.recommended()
        self.assertEqual(self.held(), before)
        self.boards(CHEAP)
        self.said(self.recommended(), MID)
        cfg, kept, seat = self.held()
        self.assertEqual(tuple(cfg["defaults"][key] for key in CREW), ("step", ["mid"], ["fine"]))
        self.assertEqual((kept, seat), ({"executor": price("mid", "medium")}, before[2]))
        self.assertEqual(cfg["models"]["mid"]["exec_effort"], "medium")

    def test_new_seats_orchestrator_takes_it_too(self):
        self.fresh(CHEAP, orchestrator=price("step"))
        before = self.held()
        self.said(self.recommended(),
                  "orchestrator took Acme Mid 1 medium, the best up to $0.30 a task")
        cfg, kept, seat = self.held()
        self.assertEqual(tuple(cfg["defaults"][key] for key in CREW), ("mid", ["step"], ["fine"]))
        self.assertEqual((kept, seat), ({"orchestrator": price("mid", "medium")}, before[2]))
        self.assertEqual(cfg["models"]["mid"]["effort"], "medium")

    def test_a_role_whose_every_choice_costs_more_than_its_limit_stays(self):
        self.fresh(CHEAP, orchestrator=price("step", limit=0.1),
                   executor=price("step", limit=0.1), reviewer=price("fine", limit=0.1))
        before = self.held()
        self.recommended().wait(lambda screen: "comparing" in screen and "u unit" in screen
                                and under(screen) == "")
        self.assertEqual(self.held(), before)


if __name__ == "__main__":
    unittest.main()
