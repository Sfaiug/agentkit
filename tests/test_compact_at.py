"""Every seat and worker compacts at the config's `compact_at`, each harness by its own setting.

`compact_at` in config.toml is a number of tokens (config.compact_at).  A seat's `interactive`
and a worker turn's `run` are told it in $AGENTKIT_COMPACT_AT (config.compact_env), and the
adapter hands it to its harness: Claude Code as CLAUDE_CODE_AUTO_COMPACT_WINDOW, Codex as
`-c model_auto_compact_token_limit=`.  Left out, nothing is told and each harness compacts
where it would on its own.  The `c` screen's `Compact at` row shows and edits it.

Offline: a temporary HOME; a fake harness `acme` whose adapter prints what it was told; the real
Claude and Codex adapters with a fake `claude` and `codex` first on PATH that write down their
environment and arguments; the row's question answered through the menu's `read` seam.
"""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, orch, terminal, worker

ESC = "\x1b"
ACME = """#!/bin/sh
case "$1" in
  interactive) printf 'seat compact=%s\\n' "${AGENTKIT_COMPACT_AT:-none}" ;;
  *) exit 1 ;;
esac
"""
MANIFEST = """version = 1
[worker]
state = []
[catalog]
"acme-1" = { efforts = ["high"] }
"""
CONFIG = """{top}[defaults]
orchestrator = "acme"
workers = ["acme"]

[models.acme]
harness = "acme"
model = "acme-1"
effort = "high"
provider = "acme"

[providers.acme]
mode = "subscription"
"""
# a harness binary that writes down how it was started, and answers nothing
FAKE = """#!/bin/sh
printf '%s\\n' "${CLAUDE_CODE_AUTO_COMPACT_WINDOW:-none}" "$@" >"$AK_TEST_STARTED"
"""


class Started(Exception):
    """The worker turn reached its sandbox: what it was handed is in `env`."""

    def __init__(self, env):
        self.env = env


def boxed(_cmd, env, *_args, **_kw):
    raise Started(env)


class CompactAt(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="compact-at-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "acme.sh").write_text(ACME)
        (adapters / "acme.sh").chmod(0o755)
        (adapters / "acme.toml").write_text(MANIFEST)
        self.home = self.root / "home"
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.home), config.ADAPTER_DIR_ENV: str(adapters), "NO_COLOR": "1",
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        for name in (config.ACCOUNT_ENV, config.COMPACT_ENV, "CLAUDE_CODE_AUTO_COMPACT_WINDOW"):
            os.environ.pop(name, None)
        stack.enter_context(patch.object(config, "HOME", self.home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.home / name.lower()))
        stack.enter_context(patch.dict(config._MANIFESTS))
        stack.enter_context(patch.dict(config._CATALOGS))
        config.ensure_dirs()
        self.path = self.home / "config.toml"
        self.rulebook = self.root / "rulebook.md"
        self.rulebook.write_text("rules\n")

    def write(self, top=""):
        self.path.write_text(CONFIG.format(top=top))
        return config.load()

    def seat(self, cfg):
        return orch.command(cfg, "acme", rulebook=self.rulebook)[-1]

    def turn(self, cfg):
        workspace, out = self.root / "ws", self.root / "out"
        workspace.mkdir(exist_ok=True)
        with patch.object(worker, "auth_ok", return_value=(True, "")), \
                patch.object(worker.box, "command", boxed), self.assertRaises(Started) as started:
            worker.call(cfg, "acme", "do the thing", workspace, out, "executor")
        return started.exception.env.get(config.COMPACT_ENV)

    def test_seats_and_workers_are_told_the_setting_and_nothing_without_it(self):
        cfg = self.write("compact_at = 300000\n\n")
        self.assertEqual(config.compact_at(cfg), 300000)
        self.assertEqual(self.seat(cfg), "compact=300000")
        self.assertEqual(self.turn(cfg), "300000")
        cfg = self.write()
        self.assertIsNone(config.compact_at(cfg))
        self.assertEqual(self.seat(cfg), "compact=none")
        # one a launch above this was told is not handed down past a config without it
        with patch.dict(os.environ, {config.COMPACT_ENV: "300000"}):
            self.assertIsNone(self.turn(cfg))

    def test_a_setting_that_is_not_a_positive_number_of_tokens_is_an_error_naming_it(self):
        for value in ("0", "-5", '"300k"', "true", "1.5"):
            cfg = self.write(f"compact_at = {value}\n\n")
            with self.assertRaises(config.Error) as caught:
                config.compact_env(cfg)
            self.assertIn("compact_at must be a positive number of tokens", str(caught.exception))
            self.assertIn("compact_at must be", menu.compact_value(cfg))

    def started(self, harness, verb, told):
        """How the real adapter of `harness` starts it: the line `interactive` prints, or what
        the fake binary `run` started wrote down."""
        bin_dir, started = self.root / "bin", self.root / "started"
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / harness).write_text(FAKE)
        (bin_dir / harness).chmod(0o755)
        workspace, out = self.root / "ws", self.root / "out"
        workspace.mkdir(exist_ok=True)
        prompt = self.root / "prompt.md"
        prompt.write_text("hi\n")
        args = (["m-1", "high"] if verb == "interactive"
                else ["m-1", "high", str(workspace), str(prompt), str(out)])
        env = {**os.environ, **told, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
               "AK_TEST_STARTED": str(started), config.RULEBOOK_ENV: str(self.rulebook),
               "AGENTKIT_CLAUDE_CHECKED": "1"}
        env.pop(config.ADAPTER_DIR_ENV)
        done = subprocess.run([str(REPO / "adapters" / f"{harness}.sh"), verb, *args], env=env,
                              capture_output=True, text=True, timeout=60)
        if verb == "interactive":
            self.assertEqual(done.returncode, 0, done.stderr)
            return done.stdout
        return started.read_text()

    def test_claude_and_codex_take_it_in_their_own_settings(self):
        told = {config.COMPACT_ENV: "300000"}
        for verb in ("interactive", "run"):
            claude = self.started("claude", verb, told)
            if verb == "interactive":
                self.assertIn("CLAUDE_CODE_AUTO_COMPACT_WINDOW=300000 ", claude)
            else:
                self.assertEqual(claude.splitlines()[0], "300000")
            self.assertIn("model_auto_compact_token_limit=300000",
                          self.started("codex", verb, told))
            # untold, each compacts where it would on its own
            self.assertNotIn("300000", self.started("claude", verb, {}))
            self.assertNotIn("model_auto_compact_token_limit", self.started("codex", verb, {}))

    def step(self, answer):
        with patch.object(menu, "read", side_effect=[answer]), \
                patch.object(menu, "pause") as pause, patch.object(terminal, "width", return_value=40), \
                patch.object(terminal, "frame") as frame, redirect_stdout(io.StringIO()):
            menu.config_compact(config.load())
        # a phone's 40 columns hold every line the screen draws
        self.assertTrue(all(terminal.cells(line) <= 40 for line in frame.call_args.args[1]))
        return pause

    def setting(self):
        return tomllib.loads(self.path.read_text()).get("compact_at")

    def test_the_row_shows_and_writes_it(self):
        cfg = self.write()
        self.assertEqual(menu.compact_value(cfg), "auto · each harness's own")
        for answer, tokens in (("300k", 300000), ("250000", 250000)):
            self.assertEqual(self.step(answer).call_count, 0)
            self.assertEqual(self.setting(), tokens)
        self.assertEqual(menu.compact_value(config.load()), "250,000 tokens")
        self.assertEqual(oct(self.path.stat().st_mode & 0o777), "0o600")
        before = self.path.read_text()
        for answer in ("", ESC):
            self.assertEqual(self.step(answer).call_count, 0)
            self.assertEqual(self.path.read_text(), before)
        for answer, words in (("lots", "a number of tokens or auto, not 'lots'"),
                              ("0", "compact_at must be a positive number of tokens")):
            pause = self.step(answer)
            self.assertEqual(pause.call_count, 1)
            self.assertIn(words, pause.call_args.args[0])
            self.assertEqual(self.path.read_text(), before)
        self.assertEqual(self.step("auto").call_count, 0)
        self.assertIsNone(self.setting())

    def test_c_shows_the_row_with_its_value_from_a_pipe(self):
        self.write("compact_at = 300000\n\n")
        out = io.StringIO()
        with patch.object(menu, "read", side_effect=[]), patch.object(terminal, "width", return_value=100), \
                redirect_stdout(out):
            menu.show_config(False)
        text = terminal.ANSI.sub("", out.getvalue())
        self.assertIn("300,000 tokens", text)
        rows = [line.split()[0] for line in text.splitlines() if line.startswith("  ")]
        self.assertLess(rows.index("Compact"), rows.index("Version"))


if __name__ == "__main__":
    unittest.main()
