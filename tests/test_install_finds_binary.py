"""A harness that is installed is never installed again, wherever its binary lives.

On 2026-09-22 install.sh ran adapters/opencode.sh install, whose only check was
`command -v opencode`.  OpenCode lives in ~/.opencode/bin, which is not on the
installer's PATH, so the verb ran the upstream installer over a working 2.0.13 and
replaced it with the channel's 1.18.32, which rejects the adapter's --standalone flag.

Every adapter verb now resolves its binary the same way -- on PATH, or failing that in
its installer's own bin dir -- and `ak update` shares that resolution and never moves a
harness below its installed version.  The fallback never shadows an explicit placement
first on PATH.  Offline throughout: every HOME is a temporary directory, every binary
and installer a fake, and no real installer ever runs.
"""

from contextlib import ExitStack, redirect_stdout, redirect_stderr
from pathlib import Path
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, update  # noqa: E402

ADAPTERS = REPO / "adapters"

# binary, adapter, own bin dir under HOME, installed version.  The opencode pair is the
# incident's own: a 2.0.13 in ~/.opencode/bin, off PATH, that install must leave alone.
HARNESSES = [
    ("claude", "claude.sh", ".local/bin", "2.1.263"),
    ("codex", "codex.sh", ".npm-global/bin", "0.153.4"),
    ("muse", "muse.sh", ".local/bin", "1.3.0"),
    ("grok", "grokbuild.sh", ".grok/bin", "1.0.40"),
    ("opencode", "opencode.sh", ".opencode/bin", "2.0.13"),
]

# Where a missing binary's installer would come from: curl for four, npm for codex.
INSTALLER_URL = {
    "claude": "https://claude.ai/install.sh",
    "muse": "https://dev.meta.ai/install.sh",
    "grok": "https://x.ai/cli/install.sh",
    "opencode": "https://opencode.ai/v2/install",
}

FAKE_BINARY = """#!/usr/bin/env bash
# fake {name}: answers --version with its planted release, and `auth list` the way the
# opencode login check asks it.  Anything else is a test bug, said out loud.
case "$1" in
  --version) echo "{name} version {version}" ;;
  auth) printf '[{{"id": "fake-login"}}]' ;;
  *) echo "fake {name}: unexpected $*" >&2; exit 2 ;;
esac
"""

# Fake opencode for the update plan: --version reads the planted release file, a bare
# `upgrade` plants the channel's older one, and `upgrade <release>` plants that one --
# which is what the revert runs after the plan refuses the downgrade.
FAKE_UPGRADABLE = """#!/usr/bin/env bash
planted="$(dirname "$0")/installed_version"
case "$1" in
  --version) echo "opencode version $(cat -- "$planted")" ;;
  upgrade)
    if [ -n "${{2:-}}" ]; then printf '%s' "$2" >"$planted"; else printf '%s' "{channel}" >"$planted"; fi ;;
  *) echo "fake opencode: unexpected $*" >&2; exit 2 ;;
esac
"""


class InstallFindsBinary(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".install-finds-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        # The only PATH the adapters see: bash and the pipes they use, symlinked in, so
        # no real harness binary on this box can leak into a "not on PATH" assertion.
        self.tools = self.root / "tools"
        self.tools.mkdir()
        for tool in ("bash", "head", "grep", "cat", "dirname"):
            target = shutil.which(tool)
            self.assertIsNotNone(target, f"{tool} is required to drive the adapters")
            (self.tools / tool).symlink_to(target)
        self.env = {"HOME": str(self.home), "PATH": str(self.tools)}

    def plant(self, name, bindir, version):
        binary = self.home / bindir / name
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text(FAKE_BINARY.format(name=name, version=version))
        binary.chmod(0o755)
        return binary

    def adapter(self, script, *args, **kwargs):
        env = dict(self.env)
        env.update(kwargs.pop("env", {}))
        return subprocess.run([str(ADAPTERS / script), *args], capture_output=True,
                              text=True, env=env, **kwargs)

    def snapshot(self):
        """Every file under HOME, by relative path and bytes: install must change none."""
        return {path.relative_to(self.home): path.read_bytes()
                for path in sorted(self.home.rglob("*")) if path.is_file()}

    def test_install_finds_binary_in_own_bin_dir(self):
        for name, script, bindir, version in HARNESSES:
            with self.subTest(harness=name):
                self.plant(name, bindir, version)
                proc = self.adapter(script, "install")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("already installed", proc.stdout)
                self.assertIn(version, proc.stdout)

    def test_path_placement_keeps_precedence_over_own_bin_dir(self):
        # Where both answer, PATH wins: the smoke gate plants its fakes first on PATH
        # against a real HOME, and the fallback must never shadow one of them.
        pathbin = self.root / "pathbin"
        pathbin.mkdir()
        for name, script, bindir, version in HARNESSES:
            with self.subTest(harness=name):
                self.plant(name, bindir, version)
                fake = pathbin / name
                fake.write_text(FAKE_BINARY.format(name=name, version="9.9.9-path"))
                fake.chmod(0o755)
                proc = self.adapter(script, "install",
                                    env={"PATH": f"{pathbin}:{self.tools}"})
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("9.9.9-path", proc.stdout)
                self.assertNotIn(version, proc.stdout)
                fake.unlink()

    def test_install_changes_nothing(self):
        self.plant("opencode", ".opencode/bin", "2.0.13")
        before = self.snapshot()
        self.assertTrue(before)
        proc = self.adapter("opencode.sh", "install")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("2.0.13", proc.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_login_finds_binary_in_own_bin_dir(self):
        # Past the installed check, each login answers about its own login: opencode is
        # already logged in (the fake auth store says so), the rest are not, on stdin
        # that is no terminal.  None of them may say the binary is not installed.
        (self.home / ".config" / "opencode").mkdir(parents=True)
        (self.home / ".config" / "opencode" / "opencode.json").write_text(
            json.dumps({"provider": {"mimo": {"options": {"apiKey": "tp-dummy"}}}}))
        for name, script, bindir, version in HARNESSES:
            with self.subTest(harness=name):
                self.plant(name, bindir, version)
                proc = self.adapter(script, "login", stdin=subprocess.DEVNULL)
                said = proc.stdout + proc.stderr
                self.assertNotIn("is not installed", said)
                if name == "opencode":
                    self.assertEqual(proc.returncode, 0, said)
                    self.assertIn("already logged in", proc.stdout)
                else:
                    self.assertEqual(proc.returncode, 1, said)
                    self.assertIn("not logged in", said)

    def test_usage_finds_binary_in_own_bin_dir(self):
        # Grok's probe checks the binary before the login: with the binary found and no
        # login saved, it reports the missing login, never a missing install.
        self.plant("grok", ".grok/bin", "1.0.40")
        proc = self.adapter("grokbuild.sh", "usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        usage = json.loads(proc.stdout)
        self.assertEqual(usage["meters"], [])
        self.assertIn("grok login", usage["error"])
        self.assertNotIn("not installed", usage["error"])

    def test_update_keeps_higher_installed_version(self):
        # The incident's shape end to end: 2.0.13 installed in ~/.opencode/bin, off PATH,
        # and a channel whose upgrade would plant 1.18.32.  The plan puts 2.0.13 back and
        # says kept; the gates and the self-move are stand-ins.
        bindir = self.home / ".opencode" / "bin"
        bindir.mkdir(parents=True)
        (bindir / "installed_version").write_text("2.0.13")
        (bindir / "opencode").write_text(FAKE_UPGRADABLE.format(channel="1.18.32"))
        (bindir / "opencode").chmod(0o755)
        plan = [{"name": "opencode", "version": ["opencode", "--version"],
                 "upgrade": ["opencode", "upgrade"],
                 "revert": ["opencode", "upgrade", "{version}"],
                 "env": {}, "cannot": "", "snapshot_dir": ""}]
        real_step = update.step

        def fake_step(cmd, fh, env=None, timeout=None):
            if Path(cmd[0]).name == "opencode":
                return real_step(cmd, fh, env, timeout)
            self.assertEqual(cmd[0], "bash")   # only the gates take another road
            return True

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, self.env))
        stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for attr in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            stack.enter_context(patch.object(config, attr, config.HOME / attr.lower()))
        config.ensure_dirs()
        (self.root / "agentkit" / ".git").mkdir(parents=True)
        out = io.StringIO()
        with patch.object(update, "harnesses", return_value=plan), \
                patch.object(update, "step", side_effect=fake_step), \
                patch.object(update, "fresh_gate",
                             return_value=(True, "passed (fixture)")), \
                patch.object(update, "working_sessions", return_value=[]), \
                patch.object(update, "update_agentkit", return_value=0), \
                redirect_stdout(out), redirect_stderr(out):
            self.assertEqual(update.main([]), 0)
        text = out.getvalue()
        self.assertIn("kept: installed 2.0.13 is newer than the channel's 1.18.32", text)
        self.assertIn("update: opencode: kept, installed 2.0.13 is newer than "
                      "the channel's 1.18.32", text)
        self.assertEqual((bindir / "installed_version").read_text(), "2.0.13")

    def test_missing_binary_still_installs(self):
        # Nothing planted anywhere: each install runs its own installer -- curl with its
        # URL, npm with the codex package -- and the opencode URL is the v2 channel.
        log = self.root / "installer.log"
        (self.tools / "curl").write_text(
            "#!/usr/bin/env bash\n"
            f"printf 'curl %s\\n' \"$*\" >>'{log}'\n"
            "echo :\n")
        (self.tools / "curl").chmod(0o755)
        (self.tools / "npm").write_text(
            "#!/usr/bin/env bash\n"
            f"printf 'npm %s\\n' \"$*\" >>'{log}'\n")
        (self.tools / "npm").chmod(0o755)
        for name, script, _, _ in HARNESSES:
            with self.subTest(harness=name):
                proc = self.adapter(script, "install")
                self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = log.read_text().splitlines()
        for name, _, _, _ in HARNESSES:
            with self.subTest(harness=name):
                if name == "codex":
                    self.assertIn("npm i -g @openai/codex", lines)
                else:
                    self.assertIn(f"curl -fsSL {INSTALLER_URL[name]}", lines)


if __name__ == "__main__":
    unittest.main()
