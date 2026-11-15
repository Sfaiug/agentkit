"""A spent Claude login is read by a turn until it serves again.

Anthropic's usage endpoint is asked about a login at most every fifteen minutes, never before the
Retry-After of its last refusal, and a spent login has no turn or seat of its own to read it in
between.  So a usage refresh that may not ask the endpoint yet, where a window Claude's turns
report is spent and not past its reset, runs one turn nobody keeps on that login
(`usage_turn.meters`): what it read is the login's reading, measured as the turn began, and the
tick acts on it at once.  One turn a login a minute, whoever refreshes, none beside one in
flight; a turn that read nothing changes nothing; a login with room, or on a harness whose turns
report no window, runs none.

Black-box: the program `AK_BIN` names ticks from outside through tests/fixtures/akbin.py, on the
adapters of tests/fixtures/fakeadapter.py.  Every endpoint refused an ask two minutes ago with an
hour's Retry-After, so no tick may ask one; the minute is moved by dating the turn's lock.
"""

import fcntl
import json
from pathlib import Path
import re
import shlex
import socket
import sys
import time
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import PANE, Seat

STATE = ".agentkit/state"
PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
REFUSED = {"type": "assistant", "isApiErrorMessage": True, "apiError": "usage_limit_reached",
           "message": {"role": "assistant", "content": [
               {"type": "text", "text": "Back after a little rest"}]}}


def windows(now, session, week):
    """Anthropic's two windows of a login, `session`% and `week`% used."""
    return [{"name": "session", "used": session, "window_secs": 18000, "resets_at": now + 10800},
            {"name": "weekly_all", "used": week, "window_secs": 604800,
             "resets_at": now + 3 * 86400}]


def stream(now, session, week):
    """What a `claude -p` turn streams of those windows."""
    return json.dumps({"type": "rate_limit_event", "rate_limit_info": {
        "status": "allowed" if session < 100 else "rejected", "unifiedWindows": {
            "five_hour": {"utilization": session / 100, "resetsAt": now + 10800},
            "seven_day": {"utilization": week / 100, "resetsAt": now + 3 * 86400}}}}) + "\n"


# refused by a worker ten minutes ago, parked until the session resets
MARK = {"exhausted_by": "session", "exhausted_used": {"session": 100, "weekly_all": 30}}


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class SpentClaudeLoginIsReadByATurn(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.now = time.time()
        fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        self.claude, self.codex = fakes["claude"], fakes["codex"]
        self.check = tomllib.loads(self.claude.manifest.read_text())["check"]
        akconfig.write(self.home, ["opus"])

    def held(self, **readings):
        """The snapshot holding each login's reading, `<provider>` or `<provider>.<account>`,
        its endpoint refused two minutes ago for an hour."""
        providers = {}
        for login, reading in readings.items():
            provider, _, account = login.partition(".")
            record = {"provider": provider, "resets": 0, "probed_at": self.now - 120, **reading}
            if account:
                providers.setdefault(provider, {"provider": provider, "accounts": {}})
                providers[provider]["accounts"][account] = record
            else:
                providers[provider] = record
            self.home.write(f"{STATE}/{login}-probe.lock", repr(self.now - 120))
            self.home.write(f"{STATE}/{login}-probe.retry", repr(self.now + 3600))
        self.home.write(f"{STATE}/usage.json", {"fetched_at": self.now - 120,
                                                "providers": providers})

    def lock(self, login="anthropic"):
        return self.home.path / STATE / f"{login}-turn.lock"

    def tick(self):
        began, done = time.time(), self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        for fake in (self.claude, self.codex):
            self.assertNotIn("usage", [call["verb"] for call in fake.calls()],
                             "a tick asked the endpoint before its Retry-After")
        return began, time.time()

    def shown(self, account=None):
        done = self.home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)
        read = json.loads(done.out)
        return read, read["providers"]["anthropic"] if account is None else \
            read["providers"]["anthropic"]["accounts"][account]

    def used(self, account=None):
        """{meter: used%} of that login, and the meters a turn wrote."""
        meters = self.shown(account)[1]["meters"]
        return ({m["name"]: m["used"] for m in meters},
                [m["name"] for m in meters if "measured_at" in m])

    def test_a_tick_reads_a_spent_login_by_one_turn_of_its_check_model_and_frees_it(self):
        self.held(anthropic={"meters": windows(self.now, 100, 30), **MARK,
                             "exhausted_until": self.now + 10800, "exhausted_at": self.now - 600,
                             "exhausted_ends": {"session": self.now + 10800}})
        self.claude.behave({"events": stream(self.now, 10, 30), "final": "Hi."})
        before, after = self.tick()
        [turn] = self.claude.runs()
        self.assertEqual(turn["argv"][:2], [self.check["model"], self.check["effort"]])
        self.assertEqual(turn["env"]["AGENTKIT_ACCOUNT"], "", "not the usual login")
        self.assertNotIn("AGENTKIT_SESSION", turn["env"], "a turn on a seat")
        began = float(self.lock().read_text())
        self.assertTrue(before <= began <= after, "the turn's moment unwritten")
        shown, read = self.shown()
        self.assertEqual({m["name"]: (m["used"], m["measured_at"]) for m in read["meters"]},
                         {"session": (10, began), "weekly_all": (30, began)})
        self.assertFalse(read["exhausted"], "the refusal's mark outlived the turn's reading")
        self.assertEqual(shown["pick_order"], ["opus"])

    def test_one_turn_a_login_a_minute_none_beside_one_in_flight_and_nothing_read_is_nothing(self):
        self.held(anthropic={"meters": windows(self.now, 100, 30)})
        for step in ({"events": stream(self.now, 100, 40), "exit": 1,
                      "final": "You've hit your limit"}, {"final": "Hi."}):
            self.claude.behave(step)
            runs = self.claude.n
            self.lock().write_text(repr(time.time() - 61))
            before, after = self.tick()
            self.assertEqual(self.claude.n, runs + 1, "no turn once the minute had passed")
            self.assertTrue(before <= float(self.lock().read_text()) <= after)
            self.assertEqual(self.used(), ({"session": 100, "weekly_all": 30}, []))
        self.lock().write_text(repr(time.time() - 5))
        self.tick()
        self.assertEqual(self.claude.n, 2, "a second turn inside the minute")
        self.lock().write_text(repr(time.time() - 61))
        with self.lock().open("a") as flight:
            fcntl.flock(flight, fcntl.LOCK_EX)
            self.tick()         # and the tick did not wait for it
        self.assertEqual(self.claude.n, 2, "a turn beside the one in flight")

    def test_each_login_is_read_by_a_turn_of_its_own(self):
        akconfig.write(self.home, ["opus"],
                       providers={"anthropic": {"mode": "subscription",
                                                "accounts": ["default", "acme-second"]}})
        self.held(**{"anthropic.default": {"meters": windows(self.now, 60, 30)},
                     "anthropic.acme-second": {"meters": windows(self.now, 100, 30)}})
        self.claude.behave({"events": stream(self.now, 10, 30), "final": "Hi."})
        self.tick()
        self.assertEqual([turn["env"]["AGENTKIT_ACCOUNT"] for turn in self.claude.runs()],
                         ["acme-second"])
        self.assertEqual(self.used("acme-second"),
                         ({"session": 10, "weekly_all": 30}, ["session", "weekly_all"]))
        self.assertEqual(self.used("default"), ({"session": 60, "weekly_all": 30}, []))

    def test_the_usual_login_is_one_login_whether_accounts_are_listed_or_not(self):
        self.held(anthropic={"meters": windows(self.now, 100, 30)})
        self.claude.behave({"final": "Hi."})
        self.tick()
        akconfig.write(self.home, ["opus"],
                       providers={"anthropic": {"mode": "subscription",
                                                "accounts": ["default", "acme-second"]}})
        self.held(**{"anthropic.default": {"meters": windows(self.now, 100, 30)},
                     "anthropic.acme-second": {"meters": windows(self.now, 60, 30)}})
        self.tick()
        self.assertEqual(self.claude.n, 1, "the usual login read twice inside the minute")

    def test_no_turn_where_the_login_has_room_or_its_harness_reads_no_window(self):
        akconfig.write(self.home, {"opus": {}, "luna": {"harness": "codex", "provider": "openai"}},
                       workers=["opus"])
        past = windows(self.now, 100, 30)
        past[0]["resets_at"] = self.now - 60
        for name, session in (("room", windows(self.now, 80, 30)), ("past its reset", past)):
            with self.subTest(name):
                self.held(anthropic={"meters": session},
                          openai={"meters": windows(self.now, 100, 30)})
                self.tick()
                self.assertEqual((self.claude.n, self.codex.n), (0, 0))


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ATurnReadingRoomRestartsTheWaitingSeatInTheSameTick(unittest.TestCase):
    def test_the_seat_waiting_on_the_spent_login_goes_on_in_the_tick_whose_turn_read_room(self):
        home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"))
        akconfig.write(home, ["opus"])
        claude = fakeadapter.install(home, claude="pass")["claude"]
        now = time.time()
        claude.behave({"events": stream(now, 10, 30), "final": "Hi."})
        seat = Seat(home, "acme", planned=True)
        claude.answer("interactive", shlex.join(
            [sys.executable, str(PANE), str(seat.screen_file), str(seat.typed_file)]))
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        home.write(f".claude/projects/{folder}/conv-acme.jsonl", "".join(
            json.dumps(line) + "\n" for line in
            ({"type": "user", "message": {"role": "user", "content": "go"}}, REFUSED)))
        home.write(f"{STATE}/seat-acme.json", {"session": "acme", "usage_wait": {
            "reason": "anthropic out of usage", "since": now - 600, "until": now + 10800,
            "continue": True}})
        home.write(f"{STATE}/usage.json", {"fetched_at": now - 60, "reset_checked_at": now,
                                           "providers": {
            "anthropic": {"provider": "anthropic", "resets": 0, "probed_at": now - 120,
                          "meters": windows(now, 100, 30)}}})
        home.write(f"{STATE}/anthropic-probe.lock", repr(now - 120))
        home.write(f"{STATE}/anthropic-probe.retry", repr(now + 3600))
        done = home.ak("watch", boxed=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertNotIn("usage", [call["verb"] for call in claude.calls()])
        self.assertEqual(claude.n, 1)
        told = [call["env"].get("AGENTKIT_FIRST_PROMPT") for call in claude.calls("interactive")]
        self.assertEqual(len(told), 1, f"restarted {len(told)} times")
        self.assertTrue(told[0], "restarted, told nothing to go on with")


if __name__ == "__main__":
    unittest.main()
