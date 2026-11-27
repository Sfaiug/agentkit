"""A seat whose word turns `needs you` lights every bar's right end twice.

The owner, 24 Nov 2026: the count at line one's right end, `! 2 other seats need you`, rose in
silence under the pane the owner reads.  At the one moment a seat's word turns `needs you`, one
tmux call on ak's server sets `@ak_news` globally and queues three changes, at half, one and one
and a half `motion.PULSE`: every bar's right end is lit -- the tone a cell turning `needs you`
pulses to on the `ak` screen -- then its own yellow, lit, its own.  The same word told again, or
another word, sets nothing; a session renamed while it is lit ends unlit.

Black-box: the program AK_BIN names, its tmux calls logged, on a tmux server of its own with
three seats of tests/fixtures/akseat.py.  tmux itself notes what line one draws on each bar after
every option set there (an `after-set-option` hook), and the test waits on tmux's own clock
(`run-shell -d`), so no wall-clock time is asserted.  The tests run in their order.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

PULSE = 0.3                             # motion.PULSE
YELLOW, LIT = "d79200", "dcbd78"        # the warning's colour in the dark shades, and lit
SEATS = ("acme", "beta", "gamma")
LINE, NOTES = "@line", "@notes"         # line one's format on a client 120 wide, what it drew
# After every option set, each bar notes the flag and line one as it draws it then.
NOTE = " ; ".join(f'set-option -aF -t ={name}: {NOTES} "#{{@ak_news}} #{{E:{LINE}}}|"'
                  for name in SEATS)


def commands(argv):
    """The commands of one logged tmux call, the flags before the first left out."""
    while argv and argv[0].startswith("-"):
        argv = argv[1 + (argv[0][-1] in "cfLST"):]
    words, found = [], []
    for word in [*argv, ";"]:
        if word != ";":
            words.append(word)
        elif words:
            found, words = [*found, words], []
    return found


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TheBarPulsesOnNews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home(tmux_log=True)
        cls.addClassCleanup(home.close)
        cls.seats = {name: Seat(home, name, screen="claude-working-pane.txt")
                     for name in ("acme", "beta")}
        cls.seats["gamma"] = Seat(home, "gamma", screen="claude-question-pane.txt")
        for name in SEATS:
            assert home.ak("orch", "why", name).code == 0
        line = home.tmux("show-options", "-v", "-t", "=acme:", "status-format[0]")
        assert line.code == 0 and "@ak_need" in line.out, line
        for done in (home.tmux("set-option", "-g", LINE,
                               line.out.rstrip("\n").replace("#{client_width}", "120")),
                     home.tmux("set-hook", "-g", "after-set-option", NOTE)):
            assert done.code == 0, done.err

    def setUp(self):
        self.settle()
        for name in SEATS:
            self.assertEqual(self.home.tmux("set-option", "-u", "-t", f"={name}:", NOTES).code, 0)
        self.since = len(self.home.calls("tmux"))

    def settle(self):
        """Once every change queued so far has run: tmux runs its timers in turn."""
        done = self.home.tmux("run-shell", "-d", f"{2 * PULSE:g}")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.option("-g", "@ak_news"), "")

    def turn(self, name, screen):
        self.seats[name].show(screen)
        done = self.home.ak("orch", "why", name)
        self.assertEqual(done.code, 0, done.err)

    def option(self, *where):
        done = self.home.tmux("show-options", "-qv", *where)
        self.assertEqual(done.code, 0, done.err)
        return done.out.rstrip("\n")

    def queued(self):
        """The commands that set `@ak_news` or queue a change, of each call since this test
        began that holds one."""
        return [found for call in self.home.calls("tmux")[self.since:]
                if (found := [command for command in commands(call) if command[0] == "run-shell"
                              or command[:1] == ["set-option"] and "@ak_news" in command])]

    def noted(self, name):
        """(flag, the right end's tone, its text) at each moment that bar noted from the first
        with the flag set, one the same as the moment before it left out."""
        seen = []
        for note in self.option("-t", f"={name}:", NOTES).split("|")[:-1]:
            flag, _, line = note.partition(" ")
            end = line.split("#[align=right]", 1)[1]
            tone = next((tone for tone in (YELLOW, LIT) if f"fg=#{tone}" in end), "")
            moment = (flag, tone, end.split("bold]", 1)[-1].split("#[", 1)[0])
            if (flag or seen) and seen[-1:] != [moment]:
                seen.append(moment)
        return seen

    def test_a_a_seat_turning_lights_every_bar_twice_on_tmuxs_clock(self):
        self.turn("beta", "claude-question-pane.txt")
        (call,) = self.queued()     # one call, which tmux runs whole or refuses whole
        lit, *changes = call
        self.assertEqual(lit[:3], ["set-option", "-g", "@ak_news"])
        self.assertEqual(len(lit), 4)
        flag = lit[3]
        self.assertTrue(flag)
        self.assertEqual([command[:3] + command[4:5] for command in changes],
                         [["run-shell", "-b", "-d", "-C"]] * 3)
        for command, pulses in zip(changes, (0.5, 1, 1.5), strict=True):
            self.assertAlmostEqual(float(command[3]), pulses * PULSE)
        self.settle()
        for name, count in (("acme", "2 other seats need"),
                            ("beta", "1 other seat needs"),
                            ("gamma", "1 other seat needs")):
            end = f"! {count} you"
            self.assertEqual(self.noted(name), [(flag, LIT, end), ("", YELLOW, end)] * 2, name)
            said = self.home.tmux("display-message", "-p", "-t", f"={name}:", f"#{{E:{LINE}}}")
            self.assertIn(f"#[align=right]#[range=right]#[fg=#{YELLOW},bold]", said.out, name)

    def test_b_the_same_word_again_or_a_word_turning_elsewhere_sets_nothing(self):
        self.turn("beta", "claude-question-pane.txt")
        self.turn("beta", "claude-working-pane.txt")
        self.settle()
        self.assertEqual(self.queued(), [])
        self.assertIn("1 other seat needs you", self.option("-t", "=acme:", "@ak_need"))
        for name in SEATS:
            self.assertEqual(self.noted(name), [], name)

    def test_c_a_session_renamed_while_lit_ends_unlit(self):
        rename = 'if-shell -F "#{@ak_news}" "rename-session -t =acme: acme-two"'
        done = self.home.tmux("set-hook", "-ga", "after-set-option", rename)
        self.assertEqual(done.code, 0, done.err)
        self.addCleanup(self.home.tmux, "set-hook", "-gu", "after-set-option[1]")
        self.turn("beta", "claude-question-pane.txt")
        (call,) = self.queued()
        flag = call[0][3]
        self.settle()
        # noted lit as it was renamed, and drawn in its own yellow since
        self.assertEqual(self.noted("acme-two")[:1], [(flag, LIT, "! 2 other seats need you")])
        said = self.home.tmux("display-message", "-p", "-t", "=acme-two:", f"#{{E:{LINE}}}")
        self.assertIn(f"#[range=right]#[fg=#{YELLOW},bold]! 2 other seats need you", said.out)


if __name__ == "__main__":
    unittest.main()
