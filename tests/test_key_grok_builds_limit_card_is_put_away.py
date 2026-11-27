"""ak puts away Grok Build's allowance limit card before it looks at the seat.

At a spent allowance, Grok Build 1.0.92 draws a card of choices in its composer's place, sharing
its bottom hint with `ask_user_question` (`Tab:next answer │ Esc:scrollback │ Shift+x:dismiss`).
The owner, 19 Nov 2026: "Should always pick stop and wait for limit to reset"; 26 Nov 2026:
"I want you to also apply to every other harness. All should work the same way with ak."
`Shift+x` (`X`) dismisses the card without picking a choice and brings back the empty composer;
the tick (`ak watch`) and a look a seat's wrapper starts (`agentkit/looker.py`) send `X` and
nothing else, while a question card under a conversation quoting a title before the unframed
`Waiting on answers…` row, or a card with a wrapped row, gets no key.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, a Grok
Build seat of tests/fixtures/akseat.py running HARNESS in an 80-column pane on fake adapters of
fakeadapter.py.
"""

import json
import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import FIXTURES, Seat, _cells
from fixtures.hookdrive import ROOT, _env

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
FINE = {"mem_total_mb": 16000, "cpus": 8, "load": 0.1, "free_mb": 12000}
CONVERSATION = "5b2d4e81-7c3a-4f9b-8d1e-6a2c4f8b1d3e"
FREE = (FIXTURES / "grokbuild-limit-free-pane.txt").read_text(encoding="utf-8")
WEEKLY = (FIXTURES / "grokbuild-limit-weekly-pane.txt").read_text(encoding="utf-8")
FREE_EXTRA_ROW = FREE.replace(
    "  ┃  2 (○) Upgrade to SuperGrok Plus",
    "  ┃\n  ┃  2 (○) Upgrade to SuperGrok Plus",
)
# An 80-column empty Grok Build composer drawn once `Shift+x` removes the limit card.
PROMPT = (
    "  ~/proj                                             1.3k / 500k │ [Dashboard]\n"
    "     ❯ say hi                                                        9:51 PM\n"
    "\n"
    "  ╭──────────────────────────────────────────────────────────────────────────╮\n"
    "  │ ❯                                                                        │\n"
    "  ╰────────────────────────────────────── Grok 4.7 (xhigh) · always-approve ─╯\n"
    "\n"
    "  Shift+Tab:mode  │  Ctrl+x:shortcuts\n"
)
# A question card (the same hint, none of the limit titles) under a conversation whose last row
# before the unframed `Waiting on answers…` row is the frame and `You hit your free usage limit.`.
QUESTION_UNDER_QUOTED_TITLE = (
    "  ~/proj                                             1.3k / 500k │ [Dashboard]\n"
    "  ┃  You hit your free usage limit.\n"
    "   ◆ Waiting on answers for Which colour do you want?       9.6s ⇣18.0k [stop]\n"
    "\n"
    "  ┃\n"
    "  ┃  Which colour do you want?\n"
    "  ┃\n"
    "  ┃\n"
    "  ┃  1 (○) Red   Pick red\n"
    "  ┃  2 (○) Blue  Pick blue\n"
    "  ┃  z (○) Type your answer here\n"
    "  ┃\n"
    "  ┃  ↑/↓ navigate · y copy                                    Enter:submit\n"
    "  ┃\n"
    "  Tab:next answer  │  Esc:scrollback  │  Shift+x:dismiss\n"
)

# The seat's harness: it draws SCREEN, again whenever that file is written, keeps each key it
# gets in TYPED, and once one is `X` (`Shift+x`) draws Grok Build's empty composer, as Grok Build
# does when `Shift+x` puts the allowance card away.
HARNESS = r"""
import os, select, sys, tty
from pathlib import Path
sys.path.insert(0, FIXTURES)
from akpane import stamp
typed, given, screen, drawn = b"", None, None, None
tty.setraw(0)
while True:
    written = os.stat(sys.argv[1])
    if given != (written.st_ino, written.st_mtime_ns):
        given, screen = (written.st_ino, written.st_mtime_ns), Path(sys.argv[1]).read_bytes()
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
    if b"X" in got:
        screen = PROMPT.encode()
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class GrokBuildsLimitCardIsPutAway(unittest.TestCase):
    def seat(self, screen):
        self.home = home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"))
        akconfig.write(home, ["grok"], providers={"xai": {"accounts": ["default"]}})
        fakeadapter.install(home, grokbuild="pass")
        seat = Seat(home, "acme", model="grok", screen=screen, alive=False,
                    record={"conversation": CONVERSATION, "account": "default"})
        seat.program = home.root / "panes" / "limit.py"
        seat.program.write_text(f"FIXTURES = {str(FIXTURES)!r}\nPROMPT = {PROMPT!r}\n{HARNESS}")
        seat.start()
        height = max(len(seat.screen.splitlines()), 16)
        resized = home.tmux("resize-window", "-t", f"={seat.name}:", "-x", "80", "-y", str(height))
        self.assertEqual(resized.code, 0, resized.err)
        width = home.tmux("display-message", "-p", "-t", seat.pane, "#{pane_width}").out.strip()
        self.assertEqual(width, "80")
        now = time.time()
        reading = {"provider": "xai", "meters": [], "none": True, "none_reason": "no meter",
                   "resets": 0}
        home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"xai": {
                **reading, "accounts": {"default": reading}}}})
        return seat

    def tick(self):
        if not boxable():
            self.skipTest("no bwrap able to box a tick here")
        done = self.home.ak("watch", boxed=True, env={"AK_HOST_READINGS": json.dumps(FINE)})
        self.assertEqual(done.code, 0, done.out + done.err)

    def word(self):
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.err)
        return why.out.splitlines()[0].split(None, 1)[1]

    def published(self):
        return json.loads((self.home.path / ".agentkit/state/seat-acme.json").read_text())["word"]

    def test_the_captured_fixtures_are_no_wider_than_80_columns(self):
        for name, screen in (("free", FREE), ("weekly", WEEKLY)):
            with self.subTest(capture=name):
                self.assertLessEqual(max(_cells(row) for row in screen.splitlines()), 80)

    def test_a_tick_puts_away_each_captured_limit_card_and_a_taller_framed_card(self):
        for name, screen in (("free", FREE),
                             ("weekly", WEEKLY),
                             ("free-extra-empty-framed-row", FREE_EXTRA_ROW)):
            with self.subTest(capture=name):
                seat = self.seat(screen)
                self.tick()
                self.assertEqual(seat.typed(), "X")
                self.assertNotEqual(self.word(), "needs you")

    def test_a_question_card_under_a_quoted_limit_title_gets_no_key_and_reads_needs_you(self):
        seat = self.seat(QUESTION_UNDER_QUOTED_TITLE)
        self.tick()
        self.assertEqual(seat.typed(), "")
        self.assertEqual(self.word(), "needs you")

    def test_the_look_a_seats_wrapper_starts_puts_away_all_four_titles(self):
        other_titles = (
            ("credit-limit", WEEKLY.replace(
                "You hit your weekly limit.", "You've hit the credit limit for your plan.")),
            ("spending-cap", WEEKLY.replace(
                "You hit your weekly limit.", "You've hit your spending cap.")),
            ("interior-trust-words", FREE.replace(
                "  ┃                                    tasks",
                "  ┃  Do you trust the contents of this directory? Yes, proceed. No, quit")),
        )
        for name, screen in (("free", FREE), ("weekly", WEEKLY), *other_titles):
            with self.subTest(title=name):
                seat = self.seat(screen)
                done = self.home.run("python3", str(ROOT / "agentkit" / "looker.py"), "acme",
                                     env=_env(self.home, "acme", seat, None))
                self.assertEqual(done.code, 0, done.err)
                self.assertEqual(seat.typed(), "X")
                self.assertNotEqual(self.published(), "needs you")

    def test_wrapped_rows_and_partial_titles_get_no_key(self):
        cases = (
            ("wrapped-choice", FREE.replace(
                "  ┃                                    tasks",
                "tasks")),
            ("wrapped-title", FREE.replace(
                "  ┃  You hit your free usage limit.",
                "  ┃  You hit your free\nusage limit.")),
            ("wrapped-hint", FREE.replace(
                "  Tab:next answer  │  Esc:scrollback  │  Shift+x:dismiss",
                "  Tab:next answer  │  Esc:scrollback  │\n  Shift+x:dismiss")),
            ("title-not-whole", FREE.replace(
                "  ┃  You hit your free usage limit.",
                "  ┃  You hit your free usage limit. (example)")),
        )
        for name, screen in cases:
            with self.subTest(case=name):
                seat = self.seat(screen)
                done = self.home.run("python3", str(ROOT / "agentkit" / "looker.py"), "acme",
                                     env=_env(self.home, "acme", seat, None))
                self.assertEqual(done.code, 0, done.err)
                self.assertEqual(seat.typed(), "")


if __name__ == "__main__":
    unittest.main()
