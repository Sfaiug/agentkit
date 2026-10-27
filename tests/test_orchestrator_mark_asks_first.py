"""Another model's orchestrator mark on the `c` screen asks before it moves the seat; the
builds and reviews marks save at once, asking nothing.

The owner (24 Oct): "when pressing a different orch, it should ask me to confirm. As this
restarts the session. for exec and review should be instant."  Space on that mark asks on the
card `x` asks on (terminal.confirm), nothing moved yet; Esc keeps the seat, and `Move` moves
it (menu.session_mark, orch.switch_orchestrator).  A move ak refuses (orch._switch_plan) is
said with no question.

Offline: a throwaway HOME, the keys fed in, the question card the real one with each ask
recorded, and the switch real from its plan on: the plan, the new harness's command and its
launch faked.
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
from fixtures.sandbox import Sandbox
from agentkit import config, menu, orch, terminal, update, usage
from agentkit.terminal import Key


class Keyboard:
    def take(self):
        return True


class OrchestratorMarkAsksFirst(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"],
                            {"reviewers": ["astra"], "cwd": "/", "created": 0})
        self.asked, self.launched, self.refusal = [], [], ""
        confirm = terminal.confirm

        def ask(question, meaning, *args, **kw):
            # what stood as the question was up
            self.asked.append((question, meaning, self.orchestrator(), list(self.launched)))
            return confirm(question, meaning, *args, **kw)
        for target, name, value in (
                (terminal, "confirm", ask),
                (orch, "_switch_plan", lambda *_a, **_kw: (self.refusal, None)),
                (orch, "sessions", lambda *_a, **_kw: []),
                (orch, "fresh_command", lambda *_a, **_kw: (["harness"], None)),
                (orch, "launch", lambda name, model, *_a, **_kw: self.launched.append(model)),
                (update, "agentkit_version", lambda: "abc1234"),
                (usage, "collect", lambda *_a, **_kw: usage.Readings({}))):
            self.stack.enter_context(patch.object(target, name, side_effect=value))

    def orchestrator(self):
        return config.load_session(self.cfg, "fix-api")["orchestrator"]

    def screen(self, *keys):
        with patch.object(terminal, "read_key", side_effect=[*keys, Key("esc")]), \
                redirect_stdout(io.StringIO()):
            menu.show_config(False, Keyboard(), "fix-api")

    def test_the_mark_asks_esc_keeps_the_seat_and_move_moves_it(self):
        # the highlight opens on the first model's orchestrator mark: fable's, the seat on opus
        self.screen(Key("space"), Key("esc"))
        self.assertEqual(self.asked, [("Restart fix-api on Fable 5.1?",
                                       "It starts a new conversation, handed the one it had.",
                                       "opus", [])])
        self.assertEqual((self.orchestrator(), self.launched), ("opus", []))
        self.screen(Key("space"), Key("down"), Key("enter"))
        self.assertEqual(len(self.asked), 2)
        self.assertEqual((self.orchestrator(), self.launched), ("fable", ["fable"]))

    def test_the_question_s_screen_is_laid_out_anew_on_a_resize(self):
        size, drawn, frame = [100], [], terminal.frame

        def resized():          # the terminal narrows while the question is up
            size[0] = 40
        keys = iter([Key("space"), resized, Key("esc"), Key("esc")])

        def read(*_a, **_kw):
            key = next(keys)
            return key() if callable(key) else key

        def framed(title, body=(), *args, **kw):
            drawn.append((size[0], list(body)))
            return frame(title, body, *args, **kw)
        with patch.object(terminal, "width", side_effect=lambda: size[0]), \
                patch.object(terminal, "frame", side_effect=framed), \
                patch.object(terminal, "read_key", side_effect=read), \
                redirect_stdout(io.StringIO()):
            menu.show_config(False, Keyboard(), "fix-api")
        self.assertEqual(len(self.asked), 1)
        narrow = [line for width, body in drawn if width == 40 for line in body]
        self.assertTrue(narrow)
        self.assertLessEqual(max(map(terminal.cells, narrow)), 40, narrow)

    def test_the_seat_s_own_mark_and_a_refused_move_ask_nothing(self):
        self.refusal = "fable: claude is not installed"
        self.screen(Key("space"))
        self.refusal = ""
        self.screen(Key("down"), Key("space"))      # opus's mark: the seat is on it
        self.assertEqual((self.asked, self.launched, self.orchestrator()), ([], [], "opus"))

    def test_a_builds_mark_saves_at_once_asking_nothing(self):
        self.screen(Key("right"), Key("space"))
        self.assertEqual(self.asked, [])
        self.assertEqual(config.load_session(self.cfg, "fix-api")["workers"],
                         ["opus", "astra", "fable"])


if __name__ == "__main__":
    unittest.main()
