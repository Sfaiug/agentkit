"""A seat whose usage ran out reads `out of usage` in red, says when it comes back, and under the
pointer opens what any row opens: it offers nothing.

The owner's pick of 20 Oct 2026: a spent window is no question for him -- ak resumes the seat
when the usage comes back, or on another account sooner -- but no word for work going on, as
nothing moves until then; so `○ out of usage  back 19:20` in red.  Under the pointer it read
`✓ Wait for 19:20` and `→ Go on now with gpt-6.1-sol` until he had both removed, 12 Nov 2026.
A run waiting for usage is a red square.  A harness upgrade does not wait for such a seat: no turn of it is in
flight.  A move to another account that failed is no wait that ends by itself, and stays his.
Offline: a temporary HOME, no tmux.
"""

from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_close_and_info as pty  # noqa: E402
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, orch, terminal, transitions, update, watch  # noqa: E402

SEAT = "acme-api"
SPENT = "anthropic out of usage until 2026-10-15 20:00"
RED = "be222a"
# The real menu on a pty (test_close_and_info's), its one seat out of usage until 19:20 today.
CHILD = pty.CHILD.replace("sys.exit(menu.loop(", """
import time
back = time.mktime(time.localtime()[:3] + (19, 20, 0, 0, 0, -1))
cfg = config.load()
config.save_session(cfg, "acme-api", "opus", ["opus"], {"cwd": "/"})
menu.seat_row_state = lambda cfg, session, **facts: {
    "word": "out of usage", "reason": "anthropic out of usage", "since": None,
    "resumes_at": back}
sys.exit(menu.loop(""")


class Login:
    """A harness whose seat login passes on `ok` accounts alone."""
    def __init__(self, ok):
        self.ok = ok

    def seat_auth(self, account):
        return account in self.ok, "" if account in self.ok else "expired login"


def today_at(hour, minute):
    """`hour:minute` of the sandbox's today (`time.time()` reads 10000), in the reader's own
    time, as a moment."""
    return time.mktime(time.localtime(10000)[:3] + (hour, minute, 0, 0, 0, -1))


# `out of usage`: red, until it comes back or the owner moves it. [14, 20 Oct 2026]
class OutOfUsageRow(Sandbox):
    def decide(self, live=None, records=()):
        found = watch.session_state(SEAT, now=10000, session={"name": SEAT}, records=list(records),
                                    live=live or {"state": "at_prompt", "began": 9000},
                                    harness="claude", auth_out={}, gh_out={}, token_out=None,
                                    previous={})
        return found

    def test_a_spent_window_reads_out_of_usage_until_it_comes_back(self):
        watch.seat_write(SEAT, usage_wait={"reason": SPENT, "until": 90000, "since": 9500})
        found = self.decide()
        self.assertEqual((found["word"], found["reason"]), ("out of usage", SPENT))
        self.assertEqual(found["resumes_at"], 90000)
        # its screen cannot say a turn is in flight: the harness's refusal leaves a screen a
        # turn could have drawn, and the wait is the fact
        self.assertEqual(self.decide({"state": "working", "began": 9000})["word"], "out of usage")

    def test_a_spent_window_reads_out_of_usage_while_runs_or_wait_are_going(self):
        watch.seat_write(SEAT, usage_wait={"reason": SPENT, "until": 90000, "since": 9500},
                         wait={"on": "https://github.com/acme/api/pull/2", "kind": "pr", "at": 9940})
        run = (config.RUNS / "going", {"state": "running", "launched_session": SEAT, "started_at": 9940})
        self.assertEqual(self.decide(records=[run])["word"], "out of usage")

    def test_an_unsent_draft_under_the_refused_turn_is_marked_beside_it(self):
        # the refused turn's UserPromptSubmit has no Stop: its hook still says working
        watch.seat_write(SEAT, usage_wait={"reason": SPENT, "until": 90000, "since": 9500})
        found = self.decide({"state": "draft", "evidence": "Fix the login redirect",
                             "began": 9000, "hooked": "working", "hooked_at": 9000})
        self.assertEqual((found["word"], found["reason"], found["unsent"]),
                         ("out of usage", SPENT, "Fix the login redirect"))
        row = terminal.plain(menu.last_column("out of usage", 0, 0, 40, unsent=found["unsent"],
                                              back=found["resumes_at"]))
        self.assertRegex(row, r"^back .*\d\d:\d\d . unsent$")

    def test_a_failed_move_to_another_account_needs_the_owner(self):
        failed = "anthropic account reopen failed: no such file"
        watch.seat_write(SEAT, usage_wait={"reason": failed, "since": 9500})
        found = self.decide()
        self.assertEqual((found["word"], found["reason"]), ("needs you", failed))
        run = (config.RUNS / "acme-run", {"state": "running", "title": "Build endpoint",
                                          "launched_session": SEAT, "started_at": 9940})
        found = self.decide(records=[run])
        self.assertEqual((found["word"], found["reason"]), ("needs you", failed))
        watch.seat_write(SEAT, wait={"on": "https://github.com/acme/api/pull/1", "kind": "pr",
                                     "at": 9940})
        found = self.decide()
        self.assertEqual((found["word"], found["reason"]), ("needs you", failed))

    def test_an_upgrade_waits_for_turns_but_not_for_a_seat_out_of_usage(self):
        answers = {"waits": {"word": "out of usage", "reason": SPENT, "resumes_at": 90000},
                   "busy": {"word": "working", "reason": "turn running"}}
        with patch.object(orch, "listing", return_value=[{"name": "waits"}, {"name": "busy"}]), \
                patch.object(watch, "session_state",
                             side_effect=lambda name, **_kw: answers[name]):
            self.assertEqual(update.working_sessions({"providers": {}}), ["busy"])

    def test_its_row_and_its_bar_say_when_it_comes_back_in_red(self):
        self.assertEqual(terminal.state_text("out of usage"), "○ out of usage")
        self.assertEqual(terminal.colour("out of usage").rgb, RED)
        back = today_at(19, 20)
        self.assertEqual(terminal.plain(menu.last_column("out of usage", 3, 8, back=back)),
                         "back 19:20")
        bar = menu.last_column("out of usage", 3, 8, narrow=True, tmux=True, back=back)
        self.assertEqual(bar, f"#[fg=#{RED}]back 19:20#[default]")
        tomorrow = back + 86400
        self.assertEqual(menu.back_at(tomorrow, now=back),
                         time.strftime("%a 19:20", time.localtime(tomorrow)))
        # it outranks work going on, as it is what stops it
        self.assertEqual(menu.rollup(["working", "out of usage", "done"]), "out of usage")

    def test_a_move_by_hand_takes_a_model_that_is_spent(self):
        # fable full with no reset known
        self.cfg["models"] = {k: self.cfg["models"][k] for k in ("opus", "fable", "astra")}
        full = {"meters": [{"name": "weekly_all", "used": 100, "exhausted": True,
                            "tier_a_exhausted": False}]}
        providers = {"anthropic": full, "openai": {"meters": [
            {"name": "weekly", "used": 20, "exhausted": False, "tier_a_exhausted": False}]}}
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        with patch.object(config, "harness_present", return_value=True), \
                patch.object(orch, "harness_plugin", return_value=Login({None})):
            self.assertEqual(orch.spent_note(self.cfg, "fable", providers), "spent")
            self.assertEqual(orch._switch_plan(self.cfg, SEAT, "fable", providers),
                             ("", None))      # the owner's switch asks nothing of usage

    def test_a_move_by_hand_lands_on_a_login_on_credits(self):
        # astra's login with a window has expired; the one left holds only credits
        self.cfg["models"] = {k: self.cfg["models"][k] for k in ("opus", "astra")}
        self.cfg["providers"]["openai"]["accounts"] = ["default", "second"]
        free = {"meters": [{"name": "weekly", "used": 20, "exhausted": False,
                            "tier_a_exhausted": False}]}
        paid = {"credits": 10, "meters": [{"name": "weekly", "used": 100, "exhausted": True,
                                           "tier_a_exhausted": True}]}
        providers = {"anthropic": {"meters": [{"name": "weekly_all", "used": 100,
                                               "exhausted": True, "tier_a_exhausted": True}]},
                     "openai": {**free, "accounts": {"default": free, "second": paid}}}
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        with patch.object(config, "harness_present", return_value=True), \
                patch.object(orch, "harness_plugin", return_value=Login({"second"})):
            self.assertEqual(orch._switch_plan(self.cfg, SEAT, "astra", providers),
                             ("", "second"))      # asked by hand, the owner may spend them

    # red without usage. [2, 14, 19, 23, 26 Oct 2026]
    def test_a_run_waiting_for_usage_is_a_red_square(self):
        run = (config.RUNS / "acme-run", {"state": "exhausted", "quota_dry": True,
                                          "step": "reviewer", "launched_session": SEAT})
        with patch.object(transitions, "runs_by_seat", return_value={SEAT: [run]}), \
                patch.object(transitions, "going", return_value=True), \
                patch.object(terminal, "colour_depth", return_value=24):
            tasks = menu.seat_tasks(SEAT, records=[run], now=10000)
            self.assertEqual([tuple(task) for task in tasks], [(1, "spent")])
            self.assertIn("38;2;190;34;42m■■", menu.squares(tasks))


class OutOfUsageOnScreen(unittest.TestCase):
    def test_pointed_at_it_opens_its_line_and_offers_nothing(self):
        with patch.object(pty, "CHILD", CHILD):
            screen = pty.Menu(self, {"acme-api": "out of usage"})
        lines = screen.frame()
        [row] = [line for line in lines if "acme-api" in line]
        self.assertRegex(row, r"○ out of usage +back \d\d:\d\d")
        screen.send(b"j")      # the highlight on its row opens its lines
        lines = screen.frame(lambda lines: any("orchestrates" in line for line in lines))
        at = next(n for n, line in enumerate(lines) if "orchestrates" in line)
        # its line, the crew alone
        self.assertRegex(lines[at], r"^ +Opus \S+ \S+ orchestrates, builds, reviews$")
        self.assertEqual(lines[at + 1], "")     # and nothing to choose under it
        screen.leave()


if __name__ == "__main__":
    unittest.main()
