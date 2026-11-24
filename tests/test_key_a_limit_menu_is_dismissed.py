"""ak puts away the menu Claude Code draws at a spent window before it looks at the seat.

Where Claude Code arms no wait of its own it draws a menu in its composer's place (2.1.328,
2.1.329), which read `needs you`: the seat was neither moved to a login with room nor continued
at the reset until the owner answered it.  The owner, 19 Nov 2026: "Should always pick stop and
wait for limit to reset".  That row's own cancel is Esc (2.1.329, 20 Nov 2026), and after it the
composer is back, empty: so a failed turn's look and the tick send Esc first and settle the seat
as it stands, and leave as it was a screen in which that row is not or a row wraps, the trust
dialog among them, and every seat on the owner's own tmux server.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, a seat of
tests/fixtures/akseat.py running HARNESS, its hooks fired as Claude fires them
(tests/fixtures/hookdrive.py), on fake harnesses of fakeadapter.py and the usage readings the
test writes.  The menu, tests/fixtures/claude-limit-menu-pane.txt, holds the rows measured on
2.1.329, drawn into a pane by hand.
"""

from functools import partial
import json
import re
import shlex
import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import FIXTURES, PANE, Seat
from fixtures.hookdrive import Hooks

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
FINE = {"mem_total_mb": 16000, "cpus": 8, "load": 0.1, "free_mb": 12000}
CONVERSATION = "0b9c6f4e-1d2a-4c3b-8e5f-6a7b8c9d0e1f"
MENU = (FIXTURES / "claude-limit-menu-pane.txt").read_text()
STOP = "Stop and wait for limit to reset"
# Its row 1 wrapped over its Stop row 2: a menu of other rows than those read
WRAPPED = MENU.replace(f"  ❯ 1. {STOP}\n    2. Wait here, then continue automatically at Nov 21, 1am",
                       f"  ❯ 1. Wait here, then continue automatically\n       at Nov 21, 1am\n    2. {STOP}")
REFUSED = {"type": "assistant", "isApiErrorMessage": True, "apiError": "usage_limit_reached",
           "message": {"role": "assistant", "content": [{"type": "text", "text":
                       "You've hit your weekly limit · resets Nov 21, 1am (Europe/Berlin)"}]}}
# The seat's harness: it draws SCREEN, again whenever that file changes, keeps each key it gets
# in TYPED, and once one is Esc draws its prompt, empty, as Claude Code does on that menu, until
# SCREEN changes again.  Each frame titles the pane as akpane.py's do, which is how the seat
# knows its screen is drawn.
HARNESS = r"""
import os, re, select, sys, tty
from pathlib import Path
sys.path.insert(0, FIXTURES)
from akpane import stamp
typed, given, screen, drawn = b"", None, None, None
tty.setraw(0)
while True:
    if given != (now := Path(sys.argv[1]).read_bytes()):
        given = screen = now
    if drawn != (screen, len(typed)):
        drawn = screen, len(typed)
        frame = screen.decode().rstrip("\n").replace("\n", "\r\n")
        os.write(1, f"\x1b[H\x1b[2J{frame}\x1b]2;{stamp(screen, len(typed))}\x1b\\".encode())
    if not select.select([0], [], [], 0.05)[0]:
        continue
    got = os.read(0, 4096)
    if not got:
        break
    typed += got
    with open(sys.argv[2], "ab") as keep:
        keep.write(got)
    if re.search(rb"\x1b(?!\[)", got):
        screen = Path(FIXTURES, "claude-prompt-pane.txt").read_bytes()
"""


class LimitSeat:
    """A unittest.TestCase's seat whose turn the limit refused, its hooks and its word."""

    def seat(self, screen, second=False, legacy=False, heard=True):
        """Seat acme on its login `default`, spent, and with `second` on a second with room too,
        in its turn the transcript records as refused, HARNESS drawing `screen` in its pane; with
        `legacy` on the owner's own tmux server; that turn's prompt heard by its hook, unless not
        `heard`."""
        self.home = home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"))
        logins = ["default", "second"] if second else ["default"]
        akconfig.write(home, ["opus"], providers={"anthropic": {"accounts": logins}})
        self.fake = fakeadapter.install(home, claude="pass")["claude"]
        if legacy:
            home.tmux = partial(home.tmux, server="default")
        seat = Seat(home, "acme", screen=screen, alive=False,
                    record={"conversation": CONVERSATION, "account": "default"})
        seat.program = home.root / "panes" / "limit.py"
        seat.program.write_text(f"FIXTURES = {str(FIXTURES)!r}\n{HARNESS}")
        seat.start()
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl", "".join(
            json.dumps(line) + "\n" for line in
            ({"type": "user", "message": {"role": "user", "content": "go"}}, REFUSED)))
        now = time.time()

        def reading(used):
            return {"provider": "anthropic", "resets": 0, "meters": [
                {"name": "weekly_all", "used": used, "window_secs": 604800,
                 "resets_at": now + 3 * 86400}]}
        readings = {"default": reading(100), "second": reading(10)}
        home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"anthropic": {
                **reading(100), "accounts": {login: readings[login] for login in logins}}}})
        # reopened, it draws its prompt and keeps its keys apart from the menu's
        self.fake.answer("interactive", shlex.join(
            [sys.executable, str(PANE), str(FIXTURES / "claude-prompt-pane.txt"),
             f"{seat.typed_file}.reopened"]))
        self.hooks = Hooks(home)
        if heard:
            self.fire("UserPromptSubmit", {"prompt": "go"})
        return seat

    def fire(self, event, payload, pane=None):
        """Its hook for that event, in its pane where `pane` is the seat, which has it look."""
        fired = self.hooks.fire(event, payload, seat="acme", pane=pane, finished=True)
        self.assertEqual(fired.code, 0, fired)

    def tick(self):
        if not boxable():
            self.skipTest("no bwrap able to box a tick here")
        done = self.home.ak("watch", boxed=True, env={"AK_HOST_READINGS": json.dumps(FINE)})
        self.assertEqual(done.code, 0, done.out + done.err)

    def word(self):
        """The word ak last published for the seat, as its record holds it: no look again."""
        return json.loads((self.home.path / ".agentkit/state/seat-acme.json").read_text())["word"]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ALimitMenuIsDismissed(LimitSeat, unittest.TestCase):
    def test_a_failed_turns_hook_dismisses_it_and_a_login_with_room_takes_the_seat(self):
        seat = self.seat(MENU, second=True)
        self.fire("StopFailure", {"error": "rate_limit"}, pane=seat)
        self.assertEqual(seat.typed(), "\x1b")
        record = json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())
        self.assertEqual(record.get("account"), "second")
        (opened,) = self.fake.calls("interactive")
        self.assertIn("Continue that turn", opened["env"].get("AGENTKIT_FIRST_PROMPT") or "")
        self.assertNotEqual(self.word(), "needs you")

    def test_a_tick_dismisses_it_and_with_no_login_with_room_the_seat_is_out_of_usage(self):
        seat = self.seat(MENU)
        self.fire("StopFailure", {"error": "rate_limit"})
        self.tick()
        self.assertEqual(seat.typed(), "\x1b")
        self.assertEqual(self.word(), "out of usage")

    def test_a_menu_without_that_row_and_the_trust_dialog_are_left_needing_the_owner(self):
        for screen in (MENU.replace(STOP, "Stop"), WRAPPED, "claude-dialog-pane.txt"):
            with self.subTest(screen=screen[-40:]):
                seat = self.seat(screen)
                self.fire("StopFailure", {"error": "rate_limit"})
                self.tick()
                self.assertEqual(self.word(), "needs you")
                self.assertEqual(seat.typed(), "")

    def test_the_trust_dialog_gets_no_key_where_its_rule_shares_the_menus_id(self):
        # a rule's id is optional, its state's where none is written: both are then `asking`
        seat = self.seat("claude-dialog-pane.txt")
        manifest = self.fake.manifest
        manifest.write_text(re.sub(r'(?m)^id = "asking\.(?:limit|trust)"\n', "",
                                   manifest.read_text()))
        self.fire("StopFailure", {"error": "rate_limit"})
        self.tick()
        self.assertEqual(seat.typed(), "")

    def test_a_seat_on_the_owners_own_tmux_server_gets_no_key(self):
        seat = self.seat(MENU, legacy=True)
        self.fire("StopFailure", {"error": "rate_limit"})
        self.tick()
        self.assertEqual(seat.typed(), "")


if __name__ == "__main__":
    unittest.main()
