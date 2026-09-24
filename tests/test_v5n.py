"""v5n: a seat never reads working without evidence; offline.

The classifier reports facts -- `asking`, `working`, `at_prompt`, `draft` -- and
`watch.session_state` turns them into the one word a row says.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_v4n import Sandbox
from agentkit import config, menu, orch, terminal, watch

FIX = REPO / "tests/fixtures"
DRAFT = "Fix the login redirect"
NOW = 20000


def tail(name):
    return watch.pane_tail((FIX / name).read_text(encoding="utf-8", errors="replace"))


class SeatNeverSaysWorking(Sandbox):
    def test_v5n_draft_fixtures_classify(self):
        for harness in ("claude", "codex", "muse"):
            with self.subTest(harness=harness):
                found = watch.classify(harness, tail(f"{harness}-draft-pane.txt"),
                                       {}, None, {}, NOW)
                self.assertEqual(found["state"], "draft")
                self.assertEqual(found["rule"], "prompt.draft")
                self.assertIn(DRAFT, found["evidence"])

    def test_v5n_suggestion_fixtures_read_at_prompt(self):
        for harness in ("claude", "codex", "muse"):
            with self.subTest(harness=harness):
                found = watch.classify(harness, tail(f"{harness}-suggestion-pane.txt"),
                                       {}, None, {}, NOW)
                self.assertEqual(found["state"], "at_prompt")
        # The ghosts captured on 15 Sep: dim suggestions, not typed text. The empty box
        # holds no ghost offline, so both texts are replayed into the real empty
        # composer in the bundle's verified ghost shape -- the inverted first
        # character with only the remainder faint.
        base = (FIX / "claude-suggestion-pane.txt").read_text(encoding="utf-8", errors="replace")
        empty = "\x1b[39m❯\xa0\x1b[7m \x1b[0m"
        self.assertIn(empty, base)
        for text in ("you write it",
                     "Also fix the login page non-200 thing you mentioned"):
            with self.subTest(text=text):
                ghost = ("\x1b[39m❯\xa0\x1b[7m" + text[0] + "\x1b[0m"
                         + "\x1b[2m" + text[1:] + "\x1b[0m")
                found = watch.classify("claude", watch.pane_tail(base.replace(empty, ghost)),
                                       {}, None, {}, NOW)
                self.assertEqual(found["state"], "at_prompt")
                self.assertEqual(found["rule"], "prompt.suggestion")

    def test_v5n_no_rule_no_fact_at_prompt(self):
        found = watch.classify("claude", watch.pane_tail("some output no rule names\nmore lines"),
                               {}, None, {}, NOW)
        self.assertEqual(found["state"], "at_prompt")
        self.assertEqual(found["rule"], "none")
        self.assertTrue(found["evidence"])

    def test_v5n_config_error_reads_at_prompt(self):
        with patch.object(config, "manifest", side_effect=config.Error("fixture broken")), \
                patch.object(watch, "pane_text", return_value=""):
            found = watch.live_state({"name": "seat", "legacy": False}, harness="claude", pane="")
            self.assertEqual(found["state"], "at_prompt")
            self.assertIn("fixture broken", found["evidence"])

    def test_v5n_working_deadline(self):
        # A turn past three hours keeps the word and says how long it has run.
        old = {"event": "UserPromptSubmit", "at": NOW - (3 * 3600 + 60)}
        fresh = {"event": "UserPromptSubmit", "at": NOW - (2 * 3600 + 59 * 60)}
        for fact, reason in ((old, "turn running 3h"), (fresh, "")):
            with self.subTest(reason=reason):
                found = watch.classify("claude", "", fact, None, {}, NOW)
                self.assertEqual(found["state"], "working")
                with patch("agentkit.menu.notify.last", return_value=None), \
                        patch.object(watch, "load_state", return_value={"stalls": {}}):
                    answer = watch.session_state("seat", NOW, session={"name": "seat"},
                                                 cfg=self.cfg, records=[], live=found,
                                                 harness="claude", previous={})
                self.assertEqual((answer["word"], answer["reason"]), ("working", reason))

    def test_v5n_rollup_ranks_and_the_prompt_reads_at_prompt(self):
        order = list(menu.STATE_ORDER)
        self.assertEqual(order, ["needs you", "working", "done"])
        for word in order:
            self.assertIn(word, terminal.STATE_STYLES)
            self.assertIn(word, terminal.STATES)
        self.assertEqual(menu.rollup({"working": 1}), "working")
        self.assertEqual(menu.rollup(["working", "done"]), "working")
        self.assertEqual(menu.rollup(["needs you", "working", "done"]), "needs you")
        # At its prompt a seat reads at_prompt whether or not it was opened since.
        for opened in (None, NOW - 10, NOW + 10):
            with self.subTest(opened=opened):
                found = watch.classify("claude", tail("claude-prompt-pane.txt"),
                                       {}, opened, {}, NOW)
                self.assertEqual(found["state"], "at_prompt")
        self.assertNotIn("waiting for you", (REPO / "agentkit/terminal.py").read_text())

    def test_v5n_draft_row_shows_text(self):
        # The draft is no state: it is why this seat needs him, in the row's last column.
        seat = {"name": "seat", "created": 100}
        live = {"state": "draft", "since": NOW - 90,
                "began": NOW - 90, "authority": "screen",
                "rule": "prompt.draft", "evidence": DRAFT}
        with patch.object(watch, "live_state", return_value=live), \
                patch.object(watch, "seat_model", return_value=("claude", "anthropic")), \
                patch.object(watch, "announce"), \
                patch("agentkit.menu.notify.last", return_value=None), \
                patch.object(menu, "run_records", return_value=[]), \
                patch.object(config, "load_session", return_value={"orchestrator": "astra"}), \
                patch.object(watch, "load_state", return_value={"stalls": {}}):
            row = menu.row(self.cfg, 1, seat)
        self.assertEqual(row[3], "needs you")
        self.assertIn(DRAFT, row[4])
        self.assertEqual(row[5], orch.age(NOW - 90))

    def test_v5n_faint_ignores_extended_colours(self):
        self.assertTrue(watch.has_dim("\x1b[2mghost\x1b[0m"))
        self.assertTrue(watch.has_dim("\x1b[0;2mghost\x1b[0m"))
        # a `2` naming a colour is never faint: truecolor, 256-colour, background
        self.assertFalse(watch.has_dim("\x1b[38;2;246;226;183mhi\x1b[0m"))
        self.assertFalse(watch.has_dim("\x1b[48;2;10;10;10mhi\x1b[0m"))
        self.assertFalse(watch.has_dim("\x1b[38;5;2mhi\x1b[0m"))
        self.assertFalse(watch.has_dim("\x1b[48;5;2mhi\x1b[0m"))
        self.assertFalse(watch.has_dim("\x1b[3m\x1b[38;5;246mhi\x1b[0m"))
        self.assertFalse(watch.has_dim("\x1b[22mhi\x1b[0m"))
        self.assertFalse(watch.has_dim("plain, no attributes at all"))

    def test_v5n_truecolor_draft_stays_draft(self):
        draft = (FIX / "claude-draft-pane.txt").read_text(encoding="utf-8", errors="replace")
        repaint = draft.replace("\x1b[39m❯", "\x1b[38;2;246;226;183m❯")
        self.assertNotEqual(repaint, draft)
        found = watch.classify("claude", watch.pane_tail(repaint), {}, None, {}, NOW)
        self.assertEqual(found["state"], "draft")
        self.assertEqual(found["rule"], "prompt.draft")

    def test_v5n_transcript_echoes_never_read_as_drafts(self):
        for harness, name in (("claude", "claude-stall-pane.txt"),
                              ("claude", "claude-auth-pane.txt"),
                              ("codex", "codex-stall-pane.txt"),
                              ("codex", "codex-auth-pane.txt"),
                              ("codex", "codex-auth-401-pane.txt"),
                              ("muse", "muse-stall-pane.txt")):
            with self.subTest(name=name):
                found = watch.classify(harness, tail(name), {}, None, {}, NOW)
                self.assertEqual(found["state"], "at_prompt")
                self.assertNotEqual(found["rule"], "prompt.draft")
        # the live seat's own bytes, captured on tmux -L agentkit-test: a bright
        # transcript echo above newer output, with an empty composer underneath.
        pane = "\n".join([
            "\x1b[38;5;239m\x1b[48;5;237m❯\xa0\x1b[38;5;231mSay OK\x1b[39m",
            "\x1b[38;5;220m\x1b[49m✻\x1b[39m \x1b[38;5;220mAPI Error: 400 upstream connect error\x1b[39m",
            "\x1b[38;5;246m✳ Brewed for 0s · done 6:46 PM\x1b[39m",
            "\x1b[38;5;244m" + "─" * 60,
            "\x1b[39m❯\xa0\x1b[7m \x1b[0m",
            "\x1b[38;5;244m" + "─" * 60,
            "  \x1b[38;5;211m⏵⏵ bypass permissions on\x1b[38;5;246m"
            " (shift+tab to cycle) · ← for agents\x1b[39m",
        ])
        found = watch.classify("claude", watch.pane_tail(pane), {}, None, {}, NOW)
        self.assertEqual(found["state"], "at_prompt")
        self.assertNotEqual(found["rule"], "prompt.draft")

    def test_v5n_prompt_window_and_veto_come_from_the_manifest(self):
        for harness in ("claude", "codex", "muse"):
            rules = {rule["id"]: rule for rule in watch.screen(harness)["rules"]}
            for rid, state in (("prompt.draft", "draft"),
                               ("prompt.suggestion", "at_prompt")):
                with self.subTest(harness=harness, rule=rid):
                    self.assertEqual(rules[rid]["state"], state)
                    self.assertEqual(rules[rid]["lines"], 8)
                    self.assertIn("esc to interrupt", rules[rid]["none"])
                    self.assertTrue(rules[rid]["chrome"])
        # the declared window, not a hardcoded slice: footers the manifest itself
        # names may pile up under the composer without losing the draft.
        draft = (FIX / "claude-draft-pane.txt").read_text(encoding="utf-8", errors="replace")
        pane = draft + "\n? for shortcuts\n23% context left\n"
        found = watch.classify("claude", watch.pane_tail(pane), {}, None, {}, NOW)
        self.assertEqual(found["state"], "draft")
        self.assertEqual(found["rule"], "prompt.draft")
        # ... and the declared veto holds even where the draft rule runs first: a
        # bright composer under a running turn is the turn's, never a draft.
        parsed = watch.screen("claude")
        reordered = dict(parsed, rules=sorted(
            parsed["rules"], key=lambda rule: 0 if rule["id"] == "prompt.draft" else 1))
        running = "❯ typed line\nesc to interrupt\n? for shortcuts\n"
        with patch.object(watch, "screen", return_value=reordered):
            found = watch.classify("claude", watch.pane_tail(running), {}, None, {}, NOW)
        self.assertNotEqual(found["rule"], "prompt.draft")

    def test_v5n_prompt_placeholders_read_empty(self):
        for harness in ("claude", "codex", "muse"):
            with self.subTest(harness=harness):
                found = watch.classify(harness, tail(f"{harness}-prompt-pane.txt"),
                                       {}, None, {}, NOW)
                self.assertEqual(found["state"], "at_prompt")
                self.assertEqual(found["rule"], "prompt.composer")

    def test_v5n_fallback_stays_undated(self):
        for now in (1000, 1100, 1200):
            with self.subTest(now=now):
                found = watch.classify("claude", watch.pane_tail("some output\nmore lines"),
                                       {}, None, {}, now)
                self.assertEqual(found["state"], "at_prompt")
                self.assertEqual(found["rule"], "none")
                self.assertIsNone(found["since"])
                self.assertIsNone(found["began"])

    def test_v5n_row_word_matches_status_word(self):
        seat = {"name": "seat", "created": 100}
        notice = {"kind": "done", "text": "Checks passed", "time": 1000,
                  "opened_at": None, "last_progress_at": None}
        cases = [({"word": "idle", "state": "at_prompt", "since": 500,
                   "began": 500, "authority": "screen",
                   "rule": "prompt.composer", "evidence": ""}, None),
                 ({"word": "draft unsent", "state": "draft", "since": NOW - 90,
                   "began": NOW - 90, "authority": "screen",
                   "rule": "prompt.draft", "evidence": DRAFT}, None),
                 ({"word": "stuck", "state": "working", "since": 500,
                   "began": 500, "authority": "hook",
                   "rule": "UserPromptSubmit", "evidence": ""}, None),
                 ({"word": "idle", "state": "at_prompt", "since": 500,
                   "began": 500, "authority": "screen",
                   "rule": "prompt.composer", "evidence": ""}, notice),
                 ({"word": "working", "state": "working", "since": 2000,
                   "began": 2000, "authority": "hook",
                   "rule": "UserPromptSubmit", "evidence": ""}, notice)]
        for live, last in cases:
            with self.subTest(word=live["word"], notice=bool(last)):
                with patch.object(watch, "live_state", return_value=live), \
                        patch("agentkit.menu.notify.last", return_value=last), \
                        patch.object(config, "load_session",
                                     return_value={"orchestrator": "astra"}), \
                        patch.object(watch, "load_state", return_value={"stalls": {}}):
                    self.assertEqual(menu.row(self.cfg, 1, seat)[3], menu.status(seat)[0])

    def test_v5n_holds_text_ignores_attributes(self):
        # a reset in the middle of the echoed line must not split the needle
        pane = ("\x1b[1m›\x1b[0m Fix the\x1b[0m login redirect\n"
                "  \x1b[38;2;246;226;183mdefault default\x1b[39m · ~\n")
        self.assertTrue(watch._holds_text(pane, "Fix the login redirect"))
        self.assertFalse(watch._holds_text(pane, "something else"))

    def check_v5n_delivery(self, panes, text):
        events = []
        panes = list(panes)

        def out(*args, socket=None, client=False):
            if args[0] == "send-keys":
                events.append("send")
                return 0, ""
            if args[0] == "capture-pane":
                events.append("capture")
                return 0, panes.pop(0) if len(panes) > 1 else panes[0]
            return 0, ""

        with patch.object(orch, "tmux_out", side_effect=out), \
                patch.object(watch.time, "sleep", lambda s: None):
            ok = watch.type_checked({"name": "seat"}, text, lambda line: None, "claude")
        return ok, events

    def test_v5n_delivery_confirm_reads_attributes(self):
        # the confirm scan strips `-e` attributes, so a real composer still counts
        # and the send is watched until the line leaves it.
        draft = (FIX / "claude-draft-pane.txt").read_text(encoding="utf-8", errors="replace")
        prompt = (FIX / "claude-prompt-pane.txt").read_text(encoding="utf-8", errors="replace")
        ok, events = self.check_v5n_delivery([draft, prompt], "Fix the login redirect")
        self.assertTrue(ok)
        self.assertGreaterEqual(events.count("capture"), 2)

    def test_v5n_delivery_without_composer_counts_as_sent(self):
        ok, events = self.check_v5n_delivery(["sleep 600\n"], "continue")
        self.assertTrue(ok)
        self.assertEqual(events, ["capture", "send", "send"])

    def test_v5n_notice_outranked_by_working(self):
        seat = {"name": "seat", "created": 100}
        notice = {"kind": "done", "text": "Checks passed", "time": 1000,
                  "opened_at": None, "last_progress_at": None}
        live_new = {"word": "working", "state": "working", "since": 2000,
                    "began": 2000, "authority": "hooks",
                    "rule": "UserPromptSubmit", "evidence": ""}
        with patch.object(watch, "live_state", return_value=live_new), \
                patch("agentkit.menu.notify.last", return_value=notice), \
                patch.object(config, "load_session", return_value={"orchestrator": "astra"}), \
                patch.object(watch, "load_state", return_value={"stalls": {}}):
            self.assertEqual(menu.status(seat)[0], "working")
            row = menu.row(self.cfg, 1, seat)
            self.assertEqual(row[3], "working")
            self.assertNotIn("Checks passed", row[4])
        live_old = {"word": "idle", "state": "at_prompt", "since": 500,
                    "began": 500, "authority": "screen",
                    "rule": "prompt.composer", "evidence": ""}
        with patch.object(watch, "live_state", return_value=live_old), \
                patch("agentkit.menu.notify.last", return_value=notice), \
                patch.object(config, "load_session", return_value={"orchestrator": "astra"}), \
                patch.object(watch, "load_state", return_value={"stalls": {}}):
            self.assertEqual(menu.status(seat)[0], "done")
            row = menu.row(self.cfg, 1, seat)
            self.assertEqual(row[3], "done")
            self.assertIn("Checks passed", row[4])


if __name__ == "__main__":
    unittest.main(verbosity=2)
