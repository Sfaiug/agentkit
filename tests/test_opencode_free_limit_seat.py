"""An OpenCode seat whose free usage is spent shows `out of usage`, at any width; offline.

OpenCode wraps its own error over as many rows as the terminal needs, so no screen row carries
the whole of it; the seat's session in opencode.db ends its failed turn in an `idle` row holding
that error -- `provider.quota`, 429 -- which the seat is read by instead.  The rows have the
shapes OpenCode 2.1.1 writes, under invented ids; HOME is temporary, and no model, meter, pane
or process is reached.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, usage, watch  # noqa: E402
from agentkit.harness import opencode  # noqa: E402

NAME, SESSION = "fix-api", "ses_0acme1free2limit3seat4"
PROMPT = "Reply with exactly the word PONG and nothing else."
FREE = ("Free usage limit reached. Free models work in OpenCode (https://opencode.ai); "
        "subscribe to OpenCode Go to keep going: https://opencode.ai/go")
SPENT = {"type": "provider.quota", "message": FREE, "status": 429, "response": {"body": json.dumps(
    {"type": "error", "error": {"type": "FreeUsageLimitError", "message": FREE}})}}
OVERLOADED = {"type": "provider.internal", "status": 503,
              "message": "The provider is overloaded. Please try again later."}
FOOTER = "  ┃  Build auto · DeepSeek V4.1 Flash Free OpenCode · max"


def screen(said, width):
    """The seat as OpenCode 2.1.1 draws a failed turn at that width, blank rows dropped."""
    rows = textwrap.wrap(f"Error: {said}", width - 5)
    return "\n".join([f"  ┃  {PROMPT}", "  ┃", *(f"     {row}" for row in rows),
                      "     Build · DeepSeek V4.1 Flash Free · 534ms", "  ┃", FOOTER])


class OpencodeFreeLimitSeat(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-opencode-free-limit-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        stack = ExitStack()
        self.addCleanup(stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, key, root / key.lower()))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AK_", "AGENTKIT_", "XDG_"))
               and not k.startswith("OPENCODE_")}
        env.update(HOME=str(root), AK_RUN_DEPTH="0", AK_MAX_RUNS="0",
                   AGENTKIT_DISCORD_WEBHOOK="off", AGENTKIT_TMUX_SOCKET="agentkit-test",
                   PYTHONDONTWRITEBYTECODE="1")
        stack.enter_context(patch.dict(os.environ, env, clear=True))
        config.ensure_dirs()
        (config.HOME / "config.toml").write_text(
            (REPO / "config.default.toml").read_text() + '\n[models.flash-free]\nharness = '
            '"opencode"\nmodel = "opencode/deepseek-v4.1-flash-free"\neffort = "max"\n'
            'provider = "opencode"\n[providers.opencode]\n')
        self.cfg = config.load()
        self.now = 1_800_000_000
        stack.enter_context(patch.object(watch.time, "time", lambda: self.now))
        self.seat = {"name": NAME, "path": str(root), "created": self.now - 60,
                     "attached": False, "exited": False, "legacy": False}
        stack.enter_context(patch.object(orch, "sessions", lambda: [self.seat]))
        stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        stack.enter_context(patch.object(watch, "pane_text", lambda _: self.pane))
        stack.enter_context(patch.object(watch, "boot_id", return_value="boot"))
        self.typed, self.marked = [], []
        stack.enter_context(patch.object(
            watch, "type_into", side_effect=lambda _, keys, *a, **k: self.typed.append(keys) or True))
        stack.enter_context(patch.object(
            usage, "mark_exhausted", side_effect=lambda cfg, provider, **kw: self.marked.append(
                provider)))
        stack.enter_context(patch.object(watch.notify, "shaped", return_value=0))
        stack.enter_context(patch.object(usage, "collect", return_value={"opencode": {
            "provider": "opencode", "meters": [], "resets": 0}}))
        config.save_session(self.cfg, NAME, "flash-free", ["flash-free"], {"cwd": str(root)})
        opencode.launched(NAME, root, SESSION)
        self.db = opencode.database()
        self.db.parent.mkdir(parents=True)

    def failed(self, error, width):
        """The seat's session ending in a turn OpenCode failed with that error, its screen at
        that width."""
        self.db.unlink(missing_ok=True)
        rows = (("user", {"text": PROMPT}),
                ("assistant", {"content": [], "finish": "error", "error": error}),
                ("idle", {"outcome": "failed", "error": error}))
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TABLE session_message (id text PRIMARY KEY, session_id text NOT"
                       " NULL, type text NOT NULL, seq integer NOT NULL, time_created integer"
                       " NOT NULL, time_updated integer NOT NULL, data text NOT NULL)")
            for seq, (kind, data) in enumerate(rows):
                at = self.now * 1000 + seq
                db.execute("INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (f"msg_{seq}", SESSION, kind, seq, at, at,
                            json.dumps({"time": {"created": at}, **data})))
        db.close()
        self.pane = screen(error["message"], width)
        self.typed.clear()
        self.marked.clear()
        watch.seat_write(NAME, usage_wait=None, usage_refusal=None)
        # a spent window is acted on when first seen (test_seat_spent_mid_turn)
        watch.seat_account(self.cfg, self.seat, "opencode", "opencode", self.pane, False,
                           lambda _: None)
        return watch.session_state(NAME, session=self.seat, cfg=self.cfg, records=[])["word"]

    def test_the_free_limit_is_out_of_usage_at_any_width(self):
        for width in (160, 80):
            with self.subTest(width=width):
                self.assertEqual(self.failed(SPENT, width), "out of usage")
                self.assertEqual((self.marked, self.typed), (["opencode"], []))

    def test_an_overloaded_provider_is_retried_not_out_of_usage(self):
        for width in (160, 80):
            with self.subTest(width=width):
                self.assertNotEqual(self.failed(OVERLOADED, width), "out of usage")
                self.assertEqual(self.marked, [])
                self.assertEqual(watch.stalled_on("opencode", self.pane, NAME, lambda _: None),
                                 "503")


if __name__ == "__main__":
    unittest.main()
