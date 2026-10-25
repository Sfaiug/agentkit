"""Enter or a click on a role of the models screen shows why its recommendation won in the
models' place: the best rows of the assessed models, each with its quality in tenths, the
points it is behind the best on each of the role's measures and its cost a task, the
recommended row starred and the rows as good marked, a board's typical gap dim and said under
them; ↑/↓ move the evidence between the roles, and Enter or Esc brings the models back.  Where
not one measure fits beside a name each row's numbers take a line under it, the measures that
do not fit named.

Offline, on test_models_screen's fixture: a throwaway HOME, rows written by hand, the keys fed in.
"""

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import config, menu, terminal
from agentkit.terminal import Key
import test_models_screen as screen

HEAD = "builds · points behind the best on each measure · ★ recommended · = as good"
WHY = "↑↓ role   ⏎ close   r take recommended   esc back"     # while the evidence stands
GAP = "a dim number is the board's typical gap: it never ran the model on that benchmark"


class Why(screen.Screen):
    def pages(self, *keys, width=100):
        """The models screen's pages as drawn while `keys` follow `r` on `c`: (key line, its
        lines, plain and one space between words), the last drawn on each change of either."""
        drawn, frame = [], terminal.frame

        def framed(name, page=(), keyline="esc back", **kwargs):
            if "models" in name:
                lines = [" ".join(terminal.plain(line).split()) for line in page]
                if not drawn or drawn[-1] != (keyline, lines):
                    drawn.append((keyline, lines))
            return frame(name, page, keyline, **kwargs)
        with patch.object(terminal, "frame", side_effect=framed):
            self.screens([Key("char", "r"), *keys, Key("esc"), Key("esc")], width=width)
        return drawn

    def test_enter_on_a_role_shows_why_its_recommendation_won_and_esc_the_models_again(self):
        # up from the first model past the note and the knob to `builds`
        pages = self.pages(*[Key("up")] * 4, Key("enter"), Key("esc"))
        why = [lines for keys, lines in pages if keys == WHY]
        at, opus, astra = why[-1].index(HEAD), self.opus, self.astra
        self.assertEqual(why[-1][at + 1:], [
            "model quality coding long bash webdev terminal $ a task",
            f"= {opus} @ max 100.0 0.0 - 0.0 - 0.0 $8.00",
            f"= {opus} @ xhigh 96.5 3.5 - 3.4 - 3.4 $4.00",
            f"★ {astra} @ xhigh 95.5 4.5 - 4.5 - 4.5 $0.50",
            f"{opus} @ high 86.2 13.8 - 13.8 - 13.8 $2.00"])
        # the models stand again once Esc closed it
        keys, lines = pages[-1]
        self.assertEqual(keys, "↑↓ move   ⏎ why   r take recommended   esc back")
        self.assertIn(f"■ {opus} claude-opus-5-5", lines)

    def test_quality_in_tenths_tells_a_row_just_past_the_knob_and_a_typical_gap_is_said(self):
        # astra 91.7 against opus's 95.3, within 3: whole points would read 92 against 95.
        # Astra was never run on terminal, so the board's typical gap, 0 here, counts there; a
        # value on long, which no board gives, keeps it scored on half the measures
        self.cfg["within"] = 3
        config.save(self.cfg)
        astra = screen.row("codex", "gpt-6-astra", "xhigh", None, 87.55, None, cost=0.5)
        del astra["values"]["aa.terminalBench40"]
        astra["values"]["livebench.long_agentic"] = 87.55
        self.store([screen.row("claude", "claude-opus-5-5", "max", None, 95.3, None, cost=8),
                    astra])
        lines = [lines for keys, lines in self.pages(*[Key("up")] * 4, Key("enter"), Key("esc"))
                 if keys == WHY][-1]
        self.assertIn(f"› builds {self.opus} @ max 95.3 $8.00 a task 0 more as good", lines)
        self.assertEqual(lines[lines.index(HEAD) + 2:], [
            f"★ {self.opus} @ max 95.3 4.7 - 4.7 - 4.7 $8.00",
            f"{self.astra} @ xhigh 91.7 12.5 - 12.5 - 0.0 $0.50", GAP])

    def test_the_arrows_move_the_evidence_between_the_roles_and_enter_again_closes_it(self):
        pages = self.pages(*[Key("up")] * 4, Key("enter"), Key("up"), Key("down"), Key("down"),
                           Key("enter"))
        heads = [line.split(" ·")[0] for keys, lines in pages if keys == WHY
                 for line in lines if "points behind the best" in line]
        self.assertEqual(heads, ["builds", "orch", "builds", "reviews"])
        self.assertIn(f"★ {self.astra} @ xhigh 95.8 4.2 - - 4.2 4.2 $0.50",
                      [line for keys, lines in pages if keys == WHY for line in lines])
        self.assertIn(f"■ {self.opus} claude-opus-5-5", pages[-1][1])

    def test_a_click_on_a_role_opens_its_why_and_another_closes_it(self):
        spots, frame = {}, terminal.frame

        def framed(*args, **kwargs):
            drawn = frame(*args, **kwargs)
            spots.update(drawn)
            return drawn

        def click():        # on the reviews line, where the models screen drew it
            return next(Key("click", col=first + 4, row=line)
                        for line, (row, cells) in spots.items() if row == ("role", "review")
                        for first, *_ in cells)

        def keys():
            yield Key("char", "r")
            yield click()
            yield Key("char", "x")        # nothing: the page drawn as the click left it
            yield click()                 # closes it: one Esc leaves the models screen
            yield Key("esc")
            yield Key("esc")
        drawn = io.StringIO()
        with patch.object(terminal, "frame", side_effect=framed), \
                patch.object(terminal, "read_key", side_effect=keys()), redirect_stdout(drawn):
            menu.show_config(False, screen.Keyboard(), "fix-api")
        text = " ".join(terminal.plain(drawn.getvalue(), spaced=True).split())
        self.assertIn("reviews · points behind the best on each measure", text)
        self.assertIn(" ".join(WHY.split()), text)
        self.assertTrue(text.rstrip().endswith("esc back"), text[-200:])

    def test_a_phone_puts_each_row_s_numbers_under_it_and_names_the_measures_left_out(self):
        with patch.object(terminal, "height", return_value=40):
            pages = self.pages(*[Key("up")] * 5, Key("enter"), Key("esc"), width=34)
        lines = [lines for keys, lines in pages if keys == WHY][-1]
        at, opus = lines.index("model quality"), self.opus
        self.assertEqual(lines[at:], [
            "model quality", "task done steering long",
            f"= {opus} @ max 100.0", "0.0 0.0 -", f"★ {opus} @ xhigh 96.5", "3.4 3.4 -",
            f"{opus} @ high 86.2", "13.8 13.8 -", f"{self.astra} @ xhigh 84.6", "15.4 15.4 -",
            "a wider screen shows briefcase"])


if __name__ == "__main__":
    unittest.main()
