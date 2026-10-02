"""Finding 12: real launch boundaries, with offline harnesses and repo-local state."""

import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, statusbar, update


class PinnedHome(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory(prefix=".ak-test-pins-", dir=REPO))
        root = self.root = Path(tmp)
        binaries = root / "bin"
        binaries.mkdir()
        (root / "sockets").mkdir(mode=0o700)
        self.enterContext(patch.dict(os.environ, {
            "HOME": str(root), "TMPDIR": str(root), "XDG_CONFIG_HOME": str(root / ".config"),
            "PATH": f"{binaries}:/usr/bin:/bin", "PIN_RECORD": str(root / "launches.jsonl"),
            "TMUX_TMPDIR": str(root / "sockets"), "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "AGENTKIT_DISCORD_WEBHOOK": "off",
        }))
        os.environ.pop(config.ADAPTER_DIR_ENV, None)
        os.environ.pop("TMUX", None)
        # Deliberately hostile inherited values, with no interactive shell initialization.
        os.environ.update(MUSE_NO_AUTO_UPDATE="0", MUSE_LAUNCHER_INSTALL="1", DISABLE_AUTOUPDATER="0")
        self.enterContext(patch.multiple(config, HOME=root / ".agentkit", **{
            name: root / ".agentkit" / name.lower()
            for name in ("TMP", "STATE", "RUNS", "WT", "SECRETS", "ENV", "WORK")
        }))
        config.ensure_dirs()
        launcher = binaries / "muse"
        launcher.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
record = pathlib.Path(os.environ["PIN_RECORD"])
pin = os.environ.get("MUSE_NO_AUTO_UPDATE")
install = os.environ.get("MUSE_LAUNCHER_INSTALL")
with record.open("a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "pin": pin, "install": install}) + "\\n")
if install == "1" or pin != "1":
    record.with_suffix(".updated").write_text("updated")
if "--version" in sys.argv:
    print("Muse Code 1.1.1")
    print("build 1.1.1-R2514.1 (commit abcdef123)")
else:
    print('{"payload":{"kind":"run_terminal","text":"offline"}}')
''')
        launcher.chmod(0o755)


def records(root):
    return [json.loads(line) for line in (root / "launches.jsonl").read_text().splitlines()]


def muse():
    return next(h for h in update.harnesses() if h["name"] == "muse")


def adapter(*args):
    return subprocess.run([str(REPO / "adapters/muse.sh"), *args],
                          text=True, capture_output=True, check=True)


class HarnessUpdatePins(PinnedHome):
    def test_interactive_headless_and_install_checks_are_pinned(self):
        root = self.root
        prompt = root / "prompt.md"
        prompt.write_text("offline fixture")
        adapter("run", "fake model", "ultra", str(root), str(prompt), str(root / "out"))
        assert (root / "out/final.md").read_text().strip() == "offline"
        for session in ([], ["resume-me"]):
            cmd = shlex.split(adapter("interactive", "fake model", "ultra", *session).stdout)
            subprocess.run(cmd, check=True, capture_output=True)
        installed = adapter("install").stdout
        assert "build 1.1.1-R2514.1 (commit abcdef123)" in installed
        assert all(r["pin"] == "1" and r["install"] == "0" for r in records(root))
        assert not (root / "launches.updated").exists()
        assert records(root)[1]["argv"][-3:] == ["fake model", "--reasoning-effort", "ultra"]

    def test_version_and_dry_run_preserve_build_identity(self):
        root = self.root
        for name in ("claude", "codex"):
            path = root / "bin" / name
            path.write_text('#!/bin/sh\n[ "$DISABLE_AUTOUPDATER" = 1 ] || exit 9\necho "1.0.0 (full build)"\n')
            path.chmod(0o755)
        identity = update.version(muse())
        assert identity == "Muse Code 1.1.1; build 1.1.1-R2514.1 (commit abcdef123)"
        out = io.StringIO()
        with redirect_stdout(out):
            assert update.main(["--dry-run"]) == 0
        assert identity in out.getvalue()
        assert "frozen installed release" in out.getvalue()
        assert "versioned reinstall" in out.getvalue()
        assert all(r["pin"] == "1" and r["install"] == "0" for r in records(root))
        assert not (root / "launches.updated").exists()
        (root / "bin/muse").write_text('#!/bin/sh\necho "Muse 1.1.1 broken"\nexit 1\n')
        assert update.version(muse()) == ""

    def test_only_explicit_upgrade_enables_installer(self):
        root = self.root
        with (root / "update.log").open("w") as fh:
            assert update.step(muse()["upgrade"], fh, muse()["env"])
        assert records(root) == [{"argv": [], "pin": "1", "install": "1"}]
        assert (root / "launches.updated").exists()

    def test_detached_seat_pins_its_command_with_stale_tmux_environment(self):
        root = self.root
        assert shutil.which("tmux"), "offline detached coverage requires tmux"
        cfg = {"models": {"fixture": {"harness": "muse", "model": "fake model", "effort": "ultra",
                                       "provider": "meta"}}, "providers": {"meta": {}}}
        conf = root / "tmux.conf"
        conf.write_text("set -g remain-on-exit on\nset -g default-shell /bin/bash\n")
        self.enterContext(patch.object(orch, "tmux_conf", lambda: conf))
        self.enterContext(patch.object(statusbar, "dress", lambda *a, **kw: None))
        # The private tmux server needs no unit in the host's real systemd manager.
        self.enterContext(patch.object(orch, "in_slice",
                                       lambda argv, unit, socket=None, env=None, **_kw: (argv, env)))
        cmd, conversation = orch.fresh_command(cfg, "fixture")
        assert conversation is None
        # This checkout's absolute path exceeds Unix's socket length limit. A relative -S
        # keeps the real socket in this repository, as in the existing retention tests.
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(root / "sockets")
        def tmux_argv(socket, *args):
            assert socket == "agentkit-test"
            return ["tmux", "-L", "agentkit-test", "-S", "./agentkit-test", *args]
        self.enterContext(patch.object(orch, "tmux_argv", tmux_argv))
        try:
            orch.start("pin-fixture", root, cmd, "fixture")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not (root / "launches.jsonl").exists():
                time.sleep(.02)
            assert records(root)[0]["pin"] == "1"
            assert records(root)[0]["install"] == "0"
            assert not (root / "launches.updated").exists()
        finally:
            subprocess.run(tmux_argv("agentkit-test", "kill-server"), capture_output=True)

    def test_installer_keeps_claude_and_codex_guards(self):
        # Run only the existing configuration/alias sections, in the fake HOME. Installing
        # packages, logins, cron and the live acceptance gates is deliberately outside this test.
        source = (REPO / "install.sh").read_text()
        start = source.index("# --- yolo") if "# --- yolo" in source else source.index("# (a) Claude")
        end = source.index("# --- (e) the phone key")
        prelude = f"ROLE=server\nREPO={shlex.quote(str(REPO))}\nPY3={shlex.quote(sys.executable)}\n"
        subprocess.run(["bash", "-c", prelude + source[start:end]], check=True, capture_output=True)
        settings = json.loads((self.root / ".claude/settings.json").read_text())
        assert settings["env"]["DISABLE_AUTOUPDATER"] == "1"
        assert "check_for_update_on_startup = false" in (self.root / ".codex/config.toml").read_text()
        # Run the actual offline assertion block too: a stale exact alias string here would
        # otherwise make every real update fail its own smoke gate after all unit tests passed.
        smoke = (REPO / "tests/smoke.sh").read_text()
        check = smoke[smoke.index("# --- 7b:"):smoke.index("# --- 7c:")]
        prelude += f"FAKE={shlex.quote(str(self.root))}\n"
        prelude += 'ok() { printf "%s\\n" "$*"; }\nno() { printf "%s\\n" "$*" >&2; exit 1; }\n'
        proc = subprocess.run(["bash", "-c", prelude + check], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "7b install.sh yolo defaults and update pins" in proc.stdout


if __name__ == "__main__":
    unittest.main()
