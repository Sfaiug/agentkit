"""A line ak types into a seat reaches it with no control code, whoever wrote the line: a typed
escape is a key.  Every printable character stays the line's own.  A hand-back carrying a
spinner's frames moved the composer's cursor on each one and landed scrambled, under an Enter
that never matched it (22 Oct 2026).

Offline: every read of the seat and every key into it are fakes under `watch`.
"""

from contextlib import contextmanager
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import watch  # noqa: E402

SEAT = {"name": "acme", "created": 10}
RAW = "Fix \"a\u00a0b.py\", \"\ue000.py\": \x1b[32mPASS\x1b[0m / \x1b[?25l◒  Upgrading\x1b[999D\x1b[J◇  done\tnow\n"
CLEAN = "Fix \"a\u00a0b.py\", \"\ue000.py\": PASS / ◒  Upgrading◇  done now "


class TypedLineHasNoControlCode(unittest.TestCase):
    def setUp(self):
        self.typed, self.compared, self.entered = [], [], False

        @contextmanager
        def held(name):
            yield name

        def send_line(session, text, log, typed=lambda: None, **_kw):
            self.typed.append(text)
            typed()
            return True

        def send_enter(session, log):
            self.entered = True
            return True

        def holds(name, session, line, cfg=None, **_kw):
            self.compared.append(line)
            return "empty" if self.entered else "line"

        fakes = [(watch, {
            "seat_held": held, "_send_line": send_line, "_send_enter": send_enter,
            "composer_holds": holds, "kept_asked_first": lambda *_a, **_kw: None,
            "seat_model": lambda *_a: (None, None), "owner_question": lambda *_a: False,
            "pinned": lambda session: session, "_past_text": lambda *_a: None,
            "takes_line": lambda *_a, **_kw: True, "quiet_prompt": lambda *_a: True,
            "_editor_kept": lambda *_a: {}, "pane_unread": lambda *_a: False}),
            (watch.config, {"resolve_session": lambda name: name, "load": dict}),
            (watch.notify, {"last": lambda *_a: None}),
            (watch.time, {"sleep": lambda _s: None})]
        for target, names in fakes:
            for name, fake in names.items():
                patcher = patch.object(target, name, fake)
                patcher.start()
                self.addCleanup(patcher.stop)

    def test_a_line_typed_into_a_seat_has_its_control_codes_removed(self):
        self.assertTrue(watch.type_into(SEAT, RAW, lambda _line: None))
        self.assertEqual(self.typed, [CLEAN])

    def test_a_line_typed_at_the_prompt_is_compared_and_marked_as_typed(self):
        marks = []
        self.assertTrue(watch.type_at_prompt(SEAT, RAW, lambda _line: None,
                                             receipt=marks.append))
        self.assertEqual(self.typed, [CLEAN])
        self.assertEqual(marks, [{"line": CLEAN, "seat": 10}])
        self.assertEqual(set(self.compared), {CLEAN})
        # the caller keeps its own text: given back with that mark, the line is the one sent
        self.assertTrue(watch.type_at_prompt(SEAT, RAW, lambda _line: None, typed=marks[0]))
        self.assertEqual(self.typed, [CLEAN])


if __name__ == "__main__":
    unittest.main()
