"""ak puts away Codex's rate-limit model chooser before it looks at the seat.

Once a login nears or reaches its limit, Codex draws a chooser in its composer's place offering
to switch to another model (0.153.4, 28 Sep 2026; 0.172.0, 26 Nov 2026).  The owner, 19 Nov 2026:
"Should always pick stop and wait for limit to reset"; 26 Nov 2026: "I want you to also apply to
every other harness. All should work the same way with ak."  Esc closes it without picking a row,
leaving the model unchanged and typing nothing if it has gone meanwhile; the tick (`ak watch`)
and a look a seat's wrapper starts (`agentkit/looker.py`) send Esc and nothing else, while other
choosers (the directory-trust prompt, the model picker) and wrapped chooser rows get no key.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, a Codex
seat of tests/fixtures/akseat.py running HARNESS on fake adapters of fakeadapter.py.
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
from fixtures.akseat import FIXTURES, Seat
from fixtures.hookdrive import ROOT, _env

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
FINE = {"mem_total_mb": 16000, "cpus": 8, "load": 0.1, "free_mb": 12000}
CONVERSATION = "3a1c5e70-9b2d-4f6a-8c1e-2d4f6a8b0c1d"
CHOOSER = (FIXTURES / "codex-limit-chooser-pane.txt").read_text()
REFUSAL = (FIXTURES / "codex-limit-refusal-pane.txt").read_text()
LEGACY = (FIXTURES / "codex-seat-server-turn-pane.txt").read_text()

# The seat's harness: it draws SCREEN, again whenever that file is written, keeps each key it
# gets in TYPED, and once one is Esc draws Codex's prompt, empty, as Codex does when Esc puts the
# rate-limit chooser away.  Each frame titles the pane as akpane.py's do, which is how the seat
# knows its screen is drawn.
HARNESS = r"""
import os, re, select, sys, tty
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
    if re.search(rb"\x1b(?!\[)", got):
        screen = Path(FIXTURES, "codex-prompt-pane.txt").read_bytes()
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CodexsRateLimitChooserIsPutAway(unittest.TestCase):
    def seat(self, screen):
        self.home = home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"))
        akconfig.write(home, ["astra"], providers={"openai": {"accounts": ["default"]}})
        fakeadapter.install(home, codex="pass")
        seat = Seat(home, "acme", model="astra", screen=screen, alive=False, composer="›",
                    record={"conversation": CONVERSATION, "account": "default"})
        seat.program = home.root / "panes" / "limit.py"
        seat.program.write_text(f"FIXTURES = {str(FIXTURES)!r}\n{HARNESS}")
        seat.start()
        now = time.time()
        reading = {"provider": "openai", "resets": 0, "meters": [
            {"name": "weekly_all", "used": 92, "window_secs": 604800,
             "resets_at": now + 3 * 86400}]}
        home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"openai": {
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

    def test_a_tick_puts_away_each_captured_rate_limit_chooser(self):
        for name, screen in (("0.172.0-near-limit", CHOOSER),
                             ("0.172.0-refusal", REFUSAL),
                             ("0.153.4", LEGACY)):
            with self.subTest(capture=name):
                seat = self.seat(screen)
                self.tick()
                self.assertEqual(seat.typed(), "\x1b")
                self.assertNotEqual(self.word(), "needs you")

    def test_the_look_a_seats_wrapper_starts_puts_it_away_without_a_tick(self):
        seat = self.seat(CHOOSER)
        done = self.home.run("python3", str(ROOT / "agentkit" / "looker.py"), "acme",
                             env=_env(self.home, "acme", seat, None))
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(seat.typed(), "\x1b")
        self.assertNotEqual(self.published(), "needs you")

    def test_the_directory_trust_prompt_gets_no_key_and_reads_needs_you(self):
        seat = self.seat("codex-dialog-pane.txt")
        self.tick()
        self.assertEqual(seat.typed(), "")
        self.assertEqual(self.word(), "needs you")

    def test_wrapped_rows_and_other_pickers_get_no_key(self):
        cases = (
            ("wrapped-heading", CHOOSER.replace("  Approaching rate limits",
                                                "  Approaching rate\n  limits")),
            ("wrapped-keep", CHOOSER.replace("  2. Keep current model",
                                             "  2. Keep current\n     model")),
            ("wrapped-never-show", CHOOSER.replace("  2. Keep current model\n",
                                                   "  2. Decide later\n").replace(
                                                       "  3. Keep current model (never show again)",
                                                       "  3. Keep current model\n     (never show again)")),
            ("wrapped-hint", CHOOSER.replace("  enter select · esc back",
                                             "  enter select ·\n  esc back")),
            ("model-picker", "codex-model-picker-pane.txt"),
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
