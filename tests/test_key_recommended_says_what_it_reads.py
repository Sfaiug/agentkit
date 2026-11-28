"""`r recommended` on `c` names what its first answer reads before making it: while the home's
run history is held back, `c` stands as last drawn, its header reading `config · recommended ·
reading what your runs cost`; let go, the page ends on the roles a home that never held its
history ends on.

Black-box: the program `AK_BIN` names in a terminal (tests/fixtures/akterm.py) at 100 columns,
over the invented boards and harnesses of tests/test_key_models_company_list.py, with an
unfinished run in history.db whose turn's `harness` receipt is a FIFO the test answers when it
lets the history go; judged by the screen while held and once settled.  Fails against /bin/false.
"""

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV, lines
from test_key_models_company_list import boards
from test_key_models_on import MODELS

NOW = int(time.time())
DAY = 86400
DOING = "config · recommended · reading what your runs cost"
ROLES = ("orchestrator", "executor", "reviewer")


def role_lines(screen):
    """The recommended screen's three role lines, not its bars' heading."""
    return [line for line in lines(screen)
            if line.lstrip("› ").startswith(ROLES) and " · " not in line]


def settled(screen):
    """The recommended screen drawn whole, its three roles over its boards read."""
    return "comparing all 3 models" in screen and "boards read" in screen \
        and len(role_lines(screen)) == 3


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RecommendedSaysWhatItReads(unittest.TestCase):
    def home(self, held):
        """A home whose one unfinished run's turn receipt only the runs-cost read opens, its
        lineup already read (`ak models`); `held`, that receipt a FIFO nothing answers yet."""
        home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\ncrux-2\tCrux 2\tlow\n"
                                        "crux-flash-1\tCrux Flash 1\thigh\n")
        meter = {"name": "weekly", "used": 20, "resets_at": NOW + DAY, "window_secs": 7 * DAY}
        fakes["claude"].answer("usage", json.dumps({"meters": [meter], "error": None}))
        akconfig.write(home, {name: MODELS[name] for name in ("mid", "bolt", "flash")},
                       orchestrator="mid", workers=["flash"])
        home.write(".agentkit/state/boards.json", boards())
        home.write(".agentkit/state/usage.json", {
            "providers": {"anthropic": {"provider": "anthropic", "harness": "claude",
                                        "meters": [meter], "error": None, "probed_at": NOW}}})
        turn = home.root / "turn"
        turn.mkdir()
        receipt = turn / "harness"
        receipt.write_text("claude\n")
        with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db, db:
            db.execute("CREATE TABLE runs (run_id TEXT, executor TEXT, executor_effort TEXT, "
                       "reviewer TEXT, kind TEXT, finished_at REAL, counted_turns TEXT, "
                       "orchestrator TEXT, orchestrator_effort TEXT, started_at REAL)")
            db.execute("CREATE TABLE reviews (run_id TEXT, review_id TEXT, effort TEXT)")
            db.execute("CREATE TABLE turn_usage (turn TEXT, run_id TEXT, role TEXT, account TEXT, "
                       "model TEXT, began REAL, at REAL, input INTEGER, cache_write INTEGER, "
                       "cache_read INTEGER, output INTEGER)")
            db.execute("CREATE TABLE seat_usage (event TEXT, orchestrator TEXT, effort TEXT, "
                       "account TEXT, model TEXT, tokens INTEGER, at REAL, input INTEGER, "
                       "cache_write INTEGER, cache_read INTEGER, output INTEGER)")
            db.execute("CREATE TABLE meter_readings (provider TEXT, account TEXT, meter TEXT, "
                       "source TEXT, used REAL, resets_at REAL, at REAL, plan TEXT)")
            db.execute("INSERT INTO runs (run_id, kind, finished_at, counted_turns) "
                       "VALUES (?, ?, ?, ?)",
                       ("fix-api-open", "task", None, json.dumps([str(turn)])))
        seeded = home.ak("models", "--json", env=ENV)
        self.assertEqual(seeded.code, 0, seeded.out + seeded.err)
        if held:
            receipt.unlink()
            os.mkfifo(receipt)
        return home, receipt

    def let_go(self, receipt):
        """The held receipt answered once its reader has it open, a plain file in its place for
        every read after."""
        until = time.monotonic() + 30
        while True:
            try:
                fd = os.open(receipt, os.O_WRONLY | os.O_NONBLOCK)
                break
            except OSError:           # no reader has it open yet
                self.assertLess(time.monotonic(), until, "nothing read the runs' history")
                time.sleep(0.05)
        try:
            receipt.with_suffix(".tmp").write_text("claude\n")
            os.replace(receipt.with_suffix(".tmp"), receipt)
            os.write(fd, b"claude\n")
        finally:
            os.close(fd)

    def config(self, home):
        """`c` up in a terminal, and its screen once read alike twice running: drawn whole."""
        term = Terminal(home, size=(100, 40), env=ENV)
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        before = [None]

        def whole(screen):
            alike, before[0] = screen == before[0] and "r recommended" in screen, screen
            return alike
        return term, lines(term.wait(whole))

    def test_c_names_the_read_until_the_page_is_drawn_as_unheld(self):
        unheld, _ = self.home(held=False)
        plain, _ = self.config(unheld)
        plain.keys("r")
        expected = role_lines(plain.wait(settled))

        home, receipt = self.home(held=True)
        term, config = self.config(home)
        term.keys("r")
        # `c` as last drawn under the header naming the read
        term.wait(lambda screen: DOING in lines(screen)[0] and lines(screen)[1:] == config[1:])
        self.let_go(receipt)
        self.assertEqual(role_lines(term.wait(settled)), expected)


if __name__ == "__main__":
    unittest.main()
