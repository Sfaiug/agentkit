"""A login that keeps refusing runs reaches the owner once; its card stays up until it answers.

A key with no end date can pass the harness's `auth` verb and still be refused at every turn:
the tick resumes the parked run at once, and it goes straight back into the refusal.  Once a
login has refused twice or more since it last answered, each seat with a run it refused in that
time that has not ended shows its login card, naming the login, and pages the owner once; the
card stays up, and is not sent again, while the run is resumed and refused again, a killed turn
between, and comes down once the login answers a turn or none of those runs is still going.  The
count is the login's, so a later run it refuses before it answers raises the card at once.  A
run refused once whose next turn the login answers raises no card.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, its turns on a fake harness
from fakeadapter.py whose `auth` says yes while its turns say the harness's logout words, from a
seat of akseat.py, paging tests/fixtures/sink.py; each tick runs in the box `home.tick()` builds.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.gitrig import Rig
from fixtures.sink import Sink

OFFLINE = "http://127.0.0.1:9"    # a refused port: the tick's public-board reads stay on loopback
# a turn the key is refused for, while `auth` keeps answering the fake's yes
REFUSED = {"stderr": "Invalid API key · Please run /login\n", "exit": 1}
# a turn killed by signal: resumed at once, and no answer from the login
KILLED = {"sh": "kill -TERM $PPID"}


class Refusals(unittest.TestCase):
    steps = ()

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.env.update(https_proxy=OFFLINE, HTTPS_PROXY=OFFLINE,
                            no_proxy="127.0.0.1,localhost")
        cls.sink = Sink(cls.home)
        cls.addClassCleanup(cls.sink.close)
        Seat(cls.home, "acme", planned=True)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus"])
        cls.claude = fakeadapter.install(cls.home, claude=list(cls.steps))["claude"]
        cls.code = cls.launch("Add retry file")
        cls.run_dir = taskfile.only_run(cls.home)

    @classmethod
    def launch(cls, title):
        """Run a task from the seat until it first parks or ends; its exit code."""
        task = taskfile.write(cls.home, cls.rig.path, title)
        return cls.home.ak("run", str(task), "--no-merge", timeout=300,
                           env={"AGENTKIT_SESSION": "acme"}).code

    @classmethod
    def record(cls):
        return json.loads((cls.run_dir / "run.json").read_text())

    @classmethod
    def tick(cls):
        done = cls.home.tick()
        assert done.code == 0, done.err
        return done

    @classmethod
    def parked(cls, turns, bound=60):
        """Wait until the run has parked on its login after that many turns."""
        deadline = time.monotonic() + bound
        while True:
            state = cls.record()
            if (cls.claude.n >= turns and state["state"] == "waiting_login"
                    and "login_back_at" not in state):
                return state
            if time.monotonic() > deadline:
                raise AssertionError(f"not parked after {turns} turns: {state['state']}")
            time.sleep(0.2)

    @classmethod
    def ended(cls, bound=120):
        deadline = time.monotonic() + bound
        while (state := cls.record())["state"] in ("waiting_login", "queued", "running"):
            if time.monotonic() > deadline:
                raise AssertionError(f"still {state['state']} after {bound} s")
            time.sleep(0.2)
        return state

    @classmethod
    def card(cls):
        """The seat's login card while it is up, else None."""
        try:
            notice = json.loads(
                (cls.home.path / ".agentkit/state/notify-acme.json").read_text())
        except FileNotFoundError:
            return None
        up = (notice.get("kind") == "needs" and not notice.get("seen")
              and str(notice.get("source")).startswith("auth:acme:"))
        return notice if up else None

    @classmethod
    def needs_pages(cls):
        """`needs` pages sent or still owed: the outbox keeps each, delivered or not."""
        return sum(json.loads(path.read_text()).get("kind") == "needs" for path in
                   (cls.home.path / ".agentkit/state/notification-outbox").glob("*.json"))

    def assertNamesTheLogin(self, card):
        self.assertIsNotNone(card)
        self.assertTrue(card["source"].startswith("auth:acme:claude:"), card)
        self.assertIn("Claude Code", card["text"])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class KeepsRefusing(Refusals):
    # the executor refused twice, killed, refused, then answered; the reviewer refused, answered
    steps = (REFUSED, REFUSED, KILLED, REFUSED, "work", REFUSED, "work")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.parked(1)
        cls.tick()                  # refused once: resumed, and nobody hears of it
        cls.after_one = (cls.card(), cls.needs_pages())
        cls.parked(2)
        cls.tick()                  # refused twice in a row: the card goes up
        cls.after_two = (cls.card(), cls.needs_pages())
        cls.parked(4)
        cls.tick()                  # and stays up while the refusals go on, its turn next
        cls.after_three = (cls.card(), cls.needs_pages())
        cls.parked(6)
        cls.tick()                  # answered, then refused once: the run still goes
        cls.after_answer = (cls.card(), cls.needs_pages())
        cls.end = cls.ended()
        cls.tick()
        cls.after_end = (cls.card(), cls.needs_pages())

    def test_one_refusal_raises_no_card(self):
        self.assertEqual(self.code, 1)
        self.assertEqual(self.after_one, (None, 0))

    def test_a_second_refusal_in_a_row_puts_the_card_up_once_naming_the_login(self):
        card, pages = self.after_two
        self.assertNamesTheLogin(card)
        self.assertEqual(pages, 1)

    def test_the_card_stays_up_and_is_not_sent_again_while_the_refusals_go_on(self):
        card, pages = self.after_three
        self.assertEqual(card, self.after_two[0])
        self.assertEqual(pages, 1)

    def test_the_card_comes_down_once_the_login_answers(self):
        self.assertEqual(self.after_answer, (None, 1))
        self.assertEqual(self.claude.n, 7)      # four refused, one killed, executor, reviewer
        self.assertEqual((self.end["state"], self.end["verdict"]), ("pass", "PASS"))
        self.assertEqual(self.after_end, (None, 1))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class RefusedOnce(Refusals):
    steps = (REFUSED, "work")

    def test_a_run_refused_once_whose_next_turn_gets_through_raises_no_card(self):
        self.assertEqual(self.code, 1)
        self.parked(1)
        self.tick()
        cards = [self.card()]
        self.assertEqual(self.ended()["state"], "pass")
        self.tick()
        cards.append(self.card())
        self.assertEqual((cards, self.needs_pages()), ([None, None], 0))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class EndsRefused(Refusals):
    steps = (REFUSED,)              # every turn, of either run

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.parked(1)
        cls.tick()
        cls.parked(2)
        cls.tick()                  # refused twice: the card goes up
        cls.before_end = cls.card()
        cls.parked(3)
        cls.stopped = cls.home.ak("run", "stop", cls.run_dir.name).code
        cls.tick()                  # its one refused run ended
        cls.after_end = (cls.card(), cls.needs_pages())
        cls.later = cls.launch("Add other file")
        cls.tick()                  # refused once more, the login still unanswered
        cls.after_later = (cls.card(), cls.needs_pages())

    def test_a_refused_run_that_ends_takes_its_seats_card_down(self):
        self.assertNamesTheLogin(self.before_end)
        self.assertEqual((self.stopped, self.record()["state"]), (0, "stopped"))
        self.assertEqual(self.after_end, (None, 1))

    def test_a_later_run_the_login_refuses_before_it_answers_raises_the_card_at_once(self):
        self.assertEqual(self.later, 1)
        card, pages = self.after_later
        self.assertNamesTheLogin(card)
        self.assertEqual(pages, 2)


if __name__ == "__main__":
    unittest.main()
