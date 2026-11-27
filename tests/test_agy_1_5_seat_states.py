"""Antigravity 1.5.18 keeps its composer open during a footerless working turn."""
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import watch  # noqa: E402
from test_antigravity_seat_states import pane

RULE = "─" * 120
SPINNER = "⣾  Running command..."


def composer(row=">"):
    return f"{RULE}\n{row}\n{RULE}"


class AgySeatStates(unittest.TestCase):
    def test_live_working_capture_keeps_the_seat_busy(self):
        tail = watch.pane_tail(pane("1.5-working"))
        expected = ("working", "working.spinner", "⣷  Running command... 2s")
        self.assertEqual(watch.screen_state("antigravity", tail), expected)
        found = watch.classify("antigravity", tail, None, None, {}, 10000.0)
        self.assertEqual((found["state"], found["rule"], found["evidence"]), expected)
        self.assertFalse(watch._free("antigravity", found))

    def test_footerless_turns_with_tips_queue_background_commands_and_drafts(self):
        tip = "└ Tip: Press ctrl+o to expand tool details."
        tray = f"● [12:08:46] sleep 45 running\n  ↓ 1 more\n{RULE}"
        for spinner, rows in (
                ("⣯  Generating...", [composer()]),
                ("⠋  Loading...", [tip, composer()]),
                (SPINNER, ["▸ queued message", composer()]),
                (SPINNER, ["▸ queued message", tip, composer()]),
                (SPINNER, [tip, "  or collapse them.", "▸ first message", "  continued",
                           "▸ next message", composer(), tray]),
                (SPINNER, [composer("> unsent draft")]),
                (SPINNER, [composer("> first line\n  second line")])):
            with self.subTest(spinner=spinner, rows=rows):
                tail = watch.pane_tail("\n".join([spinner, *rows]))
                self.assertEqual(watch.screen_state("antigravity", tail),
                                 ("working", "working.spinner", spinner))

    def test_idle_muted_hint_is_an_empty_prompt(self):
        hint = "Auto mode: edits & safe commands auto-approved (shift+tab to cycle)"
        for footer in ("", "\n? for shortcuts"):
            with self.subTest(footer=footer):
                tail = composer(f"\x1b[38;5;111m>\x1b[39m \x1b[38;5;103m{hint}\x1b[39m") + footer
                self.assertEqual(watch.screen_state("antigravity", tail)[:2],
                                 ("at_prompt", "prompt.composer"))
                self.assertEqual(watch.composer_draft("antigravity", tail), "")

    def test_only_a_spinner_above_the_live_footerless_composer_counts(self):
        idle = ("at_prompt", "prompt.composer")
        for rows, expected in (
                (["  " + SPINNER, composer()], idle),
                ([composer("> " + SPINNER)], (None, "")),
                ([SPINNER, composer("> earlier turn"), composer()], idle),
                ([SPINNER, composer(), "? for shortcuts"], idle)):
            with self.subTest(rows=rows):
                self.assertEqual(watch.screen_state("antigravity", "\n".join(rows))[:2], expected)

    def test_spinner_rule_precedence(self):
        ids = [rule["id"] for rule in watch.screen("antigravity")["rules"]]
        spinner = ids.index("working.spinner")
        asking = [name for name in ids if name.startswith("asking.")]
        for name in (*asking, "draft.chooser", "working.cancel"):
            self.assertIn(name, ids[:spinner])
        for name in ("draft.typed", "prompt.composer"):
            self.assertIn(name, ids[spinner + 1:])

        tail = f"{SPINNER} (esc to cancel)\n{composer()}"
        self.assertEqual(watch.screen_state("antigravity", tail)[:2], ("working", "working.cancel"))

        for name, expected in (("permission", ("asking", "asking.permission")),
                               ("question", ("asking", "asking.question")),
                               ("chooser", ("draft", "draft.chooser"))):
            with self.subTest(name=name):
                controls = watch.pane_tail(pane(name)).splitlines()[-8:]
                tail = "\n".join([SPINNER, *controls])
                self.assertEqual(watch.screen_state("antigravity", tail)[:2], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
