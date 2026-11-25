"""Enter or a click on a subscription's meter opens its row on `c` → Subscriptions.

The owner (10 Nov 2026), of the meters on the ak screen: "when hoverign here, it looks and feels
like you can press it, but you cant", and: "Make sure every screen feels and is operated in the
same sort of way."  Every meter opens that page on its own row, the row found by its company
and account in config.toml as the page reads it, so a subscription another process added
meanwhile moves no highlight onto another's row, its usual login the same whether listed as
`default` or not, and a config.toml removed meanwhile is read as ak's shipped one; Esc comes
back to the screen it was opened from, the highlight on that meter.  Its acts are that row's,
lit as the page lights them: `log in again` where its login ends within the week, Enter
signing that one in, and nothing where it holds a reset, so Enter spends none.  With no seat
the meters are the screen's rows: the pointer off them lights none.  A menu started again on
new code comes up on the subscription it left, whatever row a save the old program never read
gave it, new code waiting on its way to the terminal for the lock held meanwhile
(test_key_a_restart_keeps_the_last_frame_up.py).
Black-box: `AK_BIN`'s menu in a terminal (tests/fixtures/akterm.py) over Claude's and ChatGPT's
subscriptions in a temporary HOME (TZ=UTC), with no seat, their harnesses faked, each logging
every verb (tests/fixtures/fakeadapter.py), NO_COLOR, so the lit act is bracketed.  This test
fails against `/bin/false`.
"""

import fcntl
import itertools
import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_log_in_again_only_when_needed import DAY, LIT, MAIN_KEYS, METER, PAGE, UNLIT, lines

GRID = re.compile(METER.pattern + r"|  — ")     # a meter, or the dash of one with no reading


def under_grid(screen):
    """The line under the usage grid, on the ak screen and `c`: what the meter lit says.  A
    login added meanwhile has no reading till a probe reads it, its row a dash for a meter."""
    shown = lines(screen)
    return shown[max(number for number, line in enumerate(shown) if GRID.search(line)) + 1]


def lit(screen):
    """The subscription the line under the grid tells of, the meter the highlight is on."""
    return under_grid(screen)[2:].split("  ")[0]


def opened(label, line, keys=UNLIT):
    """Whether a screen is Subscriptions with `label`'s row highlighted, the last line it opens
    (its acts', under any of its limits) ending in `line`, and `keys` its key line: by default
    Enter naming nothing, as `− remove` is lit only by a move."""
    def shown(screen):
        drawn = lines(screen)
        at = next((at for at, row in enumerate(drawn) if row.startswith(f"› {label} ")), len(drawn))
        opens = [*itertools.takewhile(lambda below: below.startswith("    "), drawn[at + 1:])]
        return (drawn[0].startswith(PAGE) and keys in drawn and bool(opens)
                and opens[-1].endswith(line))
    return shown


def environs():
    """Each process's environment as its program started with it: an exec's, once it has."""
    for proc in Path("/proc").iterdir():
        try:
            yield dict(item.partition(b"=")[::2]
                       for item in (proc / "environ").read_bytes().split(b"\0"))
        except OSError:
            continue


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AMeterOpensItsSubscription(unittest.TestCase):
    def open(self, ends=60 * DAY, resets=0):
        """The ak screen over Claude, its login ending `ends` seconds from now, and ChatGPT,
        holding `resets` resets, its login far from its end."""
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        self.config = akconfig.write(self.home, {"fable": "claude", "astra": "codex"})
        now = time.time()
        week = {"meters": [{"name": "weekly", "used": 40, "window_secs": 604800}], "error": None}
        self.home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {
            "anthropic": week, "openai": {**week, "resets": resets}}})
        self.home.write(".agentkit/state/logins.json", {provider: {"default": {
            "email": f"{name}@acme.test", "ends": int(now + until), "plan": None,
            "checked_at": now}} for provider, name, until in (("anthropic", "reef", ends),
                                                              ("openai", "shoal", 60 * DAY))})
        self.term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        return lines(self.term.wait(lambda screen: MAIN_KEYS in lines(screen)
                                    and "ChatGPT" in screen))

    def click(self, label, shown):
        """A click on `label`'s meter on the screen `shown`."""
        row = next(number for number, line in enumerate(shown)
                   if label in line and METER.search(line)) + 1
        column = shown[row - 1].index(label) + 3
        self.term.type(f"\x1b[<0;{column};{row}M\x1b[<0;{column};{row}m")

    def on_chatgpt(self):
        """The ak screen opened, its keys' highlight on ChatGPT's meter."""
        self.open()
        self.term.keys("Up")                  # with no seat, onto the grid's last meter
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen) and lit(screen) == "ChatGPT")

    def test_the_keys_on_a_meter_and_enter_open_its_row_and_esc_comes_back_to_it(self):
        self.on_chatgpt()
        self.term.keys("Enter")
        self.term.wait(opened("ChatGPT", "    shoal@acme.test   − remove"))
        self.term.keys("Escape")
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen) and lit(screen) == "ChatGPT")

    def test_a_click_on_a_meter_on_c_opens_its_row_and_esc_draws_c(self):
        self.open()
        self.term.keys("c")
        self.click("Claude", lines(self.term.wait(lambda screen: "› Fable 5.1" in screen
                                                  and "esc back" in screen)))
        self.term.wait(opened("Claude", "    reef@acme.test   − remove"))
        self.term.keys("Escape")
        self.term.wait(lambda screen: lines(screen)[0].rsplit(" ", 1)[0].strip()
                       == "agentkit · config" and lit(screen) == "Claude")

    def test_a_login_ending_within_the_week_opens_lit_on_log_in_again_and_enter_signs_it_in(self):
        self.click("Claude", self.open(ends=2 * DAY))
        self.term.wait(opened("Claude", ")   [→ log in again]   − remove",
                              LIT.format("log in again")))
        self.term.keys("Enter")
        self.term.wait(lambda _: self.fakes["claude"].calls("login"))
        self.assertEqual([call["argv"] for call in self.fakes["claude"].calls("login")],
                         [["again"]])
        self.assertEqual(self.fakes["codex"].calls("login"), [])

    def test_enter_on_the_row_a_meter_holding_a_reset_opens_spends_none(self):
        self.click("ChatGPT", self.open(resets=1))
        self.term.wait(opened("ChatGPT", "    shoal@acme.test   → spend a reset   − remove"))
        self.term.keys("Enter", "Right")      # Enter on nothing lit, read before the move
        self.term.wait(opened("ChatGPT", "    shoal@acme.test   [→ spend a reset]   − remove",
                              LIT.format("spend a reset")))
        self.assertEqual([call for fake in self.fakes.values() for call in fake.calls("reset")],
                         [])

    def second_login(self, provider):
        """Another process's save: `provider`'s second login, its usual one now `default`."""
        text = self.config.read_text().replace(f'[providers."{provider}"]\n',
                                               f'[providers."{provider}"]\n'
                                               'accounts = ["default", "tide"]\n')
        new = self.config.with_name("config.toml.new")
        new.write_text(text)
        new.replace(self.config)

    def test_a_subscription_added_meanwhile_moves_no_row_under_the_meter_pressed(self):
        self.on_chatgpt()
        self.second_login("anthropic")          # a row over ChatGPT's
        self.term.keys("Enter")
        screen = self.term.wait(opened("ChatGPT", "    shoal@acme.test   − remove"))
        self.assertIn("  Claude II ", screen)
        self.term.keys("Escape")
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen) and "Claude II" in screen
                       and lit(screen) == "ChatGPT")

    def test_a_second_login_of_the_pressed_ones_company_leaves_it_its_row(self):
        self.on_chatgpt()
        self.second_login("openai")             # its login, listed by no name, now `default`
        self.term.keys("Enter")
        screen = self.term.wait(opened("ChatGPT I", "    shoal@acme.test   − remove"))
        self.assertIn("  ChatGPT II ", screen)
        self.term.keys("Escape")
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen) and "ChatGPT II" in screen
                       and lit(screen) == "ChatGPT I")

    def test_a_config_toml_removed_meanwhile_opens_the_shipped_subscriptions(self):
        self.on_chatgpt()
        self.config.unlink()                    # another process's, before the screen reads again
        self.term.keys("Enter")
        screen = self.term.wait(opened("ChatGPT", "    shoal@acme.test   − remove"))
        self.assertIn("  Grok ", screen)        # a shipped subscription this HOME's file left out

    def test_new_code_comes_up_on_the_meter_left_whatever_row_a_save_meanwhile_gave_it(self):
        self.on_chatgpt()
        started = time.time()                   # the menu started before this
        lock = (self.home.path / ".agentkit/state/watch.lock").open("a")
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX)
        while time.time() < int(started) + 1:   # an install, stamped as install.sh stamps
            time.sleep(0.05)
        self.home.write(".agentkit/state/installed-at", f"{int(time.time())}\n")
        home, deadline = str(self.home.path).encode(), time.monotonic() + 60
        while not any(env.get(b"HOME") == home and b"AK_MENU_CURSOR" in env for env in environs()):
            self.assertLess(time.monotonic(), deadline, "never started again")
            time.sleep(0.05)
        self.second_login("anthropic")          # a row over ChatGPT's
        fcntl.flock(lock, fcntl.LOCK_UN)
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen) and "Claude II" in screen
                       and lit(screen) == "ChatGPT")

    def test_the_pointer_off_every_meter_lights_none(self):
        self.on_chatgpt()                       # the keys' highlight, put out as off a seat's row
        shown = lines(self.term.screen())
        row = next(number for number, line in enumerate(shown)
                   if "Claude" in line and METER.search(line))
        self.term.type(f"\x1b[<35;{shown[row].index('Claude') + 3};{row + 1}M")
        self.term.wait(lambda screen: lit(screen) == "Claude")
        self.term.type("\x1b[<35;3;1M")         # onto `agentkit`
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen)
                       and not under_grid(screen).strip())


if __name__ == "__main__":
    unittest.main()
