"""Every harness ak ships names its newest release, so the tick keeps each one on it.

Each shipped `adapters/<h>.toml` says where its newest release is published, in `[update]
latest`: Grok Build's own check (which names the installed release first), OpenCode's 2.x
channel, Antigravity's manifest for this platform, Muse's channel.  A newer Muse build of the
same X.Y.Z is a newer release, and the tick upgrades one behind it like any other.

Offline throughout: `curl`, `grok`, `muse`, `uname` and `ldd` are stubs under a temporary HOME,
answering what the real ones answered on 30 Sep; nothing real is asked or upgraded.
"""

from contextlib import ExitStack
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, update

# every call is written down, and answered with what the test put in `answer`
CURL = '#!/bin/sh\nprintf "%s\\n" "$*" >>"{root}/asked"\ncat "{root}/answer"\n'
GROK = ('#!/bin/sh\nprintf "%s\\n" "$*" >>"{root}/asked"\n'
        'case "$*" in "update --check --json") cat "{root}/answer" ;; *) exit 2 ;; esac\n')
UNAME = '#!/bin/sh\ncase "$1" in -s) cat "{root}/os" ;; -m) cat "{root}/machine" ;; esac\n'
LDD = '#!/bin/sh\ncat "{root}/libc"\n'
MUSE = '#!/bin/sh\ncat "{root}/installed"\n'

GROK_CHECK = ('{"currentVersion":"1.0.40","latestVersion":"1.0.44","updateAvailable":true,'
              '"installer":"internal","channel":"stable","autoUpdate":null,"error":null}')
OPENCODE_CHANNEL = ('{"channel":"latest","name":"cli","distribution":"npm","version":"2.0.20",'
                    '"metadata":{"package":"@opencode/cli"},"active":true}')
AGY_MANIFEST = '{\n  "version": "1.2.14",\n  "url": "https://example.invalid/1.2.14/cli.tar.gz"\n}'
MUSE_CHANNEL = ('{"channel":"muse-stable","version":"%s","manifest_url":"https://example.invalid/'
                '?channel=muse&version=%s&file=manifest.json","min_version":null}')
AGY = "https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/"


class HarnessLatest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-harness-latest-")
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name).resolve()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, text in (("bin/curl", CURL), ("bin/uname", UNAME), ("bin/ldd", LDD),
                           ("bin/muse", MUSE), (".grok/bin/grok", GROK)):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text.format(root=root))
            (root / name).chmod(0o755)
        self.write(os="Linux", machine="x86_64", libc="\tlibc.so.6 => /lib/libc.so.6")
        # grok only where its installer puts it: on no PATH, the way a fresh shell has it
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "PATH": f"{root / 'bin'}:/usr/bin:/bin",
            config.ADAPTER_DIR_ENV: str(REPO / "adapters")}))
        for name in ("GROK_BIN_DIR", "MUSE_CHANNEL"):
            os.environ.pop(name, None)

    def write(self, **files):
        for name, text in files.items():
            (self.root / name).write_text(text + "\n")

    def asked(self):
        path = self.root / "asked"
        return path.read_text().splitlines() if path.exists() else []

    def latest(self, name, answer):
        """What the shipped manifest's `[update] latest` names when its source says `answer`."""
        self.write(answer=answer)
        (plan,) = update.harnesses({"models": {name: {"harness": name}}})
        return update.latest(plan)

    def test_every_shipped_harness_names_where_its_newest_release_is(self):
        shipped = sorted(path.stem for path in (REPO / "adapters").glob("*.toml"))
        cfg = {"models": {name: {"harness": name} for name in shipped}}
        self.assertEqual({h["name"]: bool(h["latest"]) for h in update.harnesses(cfg)},
                         dict.fromkeys(shipped, True))

    def test_grok_names_its_check_s_latest_not_the_installed_release(self):
        self.assertEqual(self.latest("grokbuild", GROK_CHECK), "1.0.44")
        self.assertEqual(self.asked(), ["update --check --json"])
        self.assertEqual(self.latest("grokbuild", '{"currentVersion":"1.0.40","error":"offline"}'),
                         "")

    def test_opencode_names_its_2x_channel_s_release(self):
        self.assertEqual(self.latest("opencode", OPENCODE_CHANNEL), "2.0.20")
        self.assertEqual(self.asked(), ["-fsSL https://opencode.ai/update/api/latest/cli/npm"])

    def test_antigravity_asks_the_manifest_its_installer_names_for_this_platform(self):
        for os_name, machine, libc, platform in (
                ("Linux", "x86_64", "\tlibc.so.6 => /lib/libc.so.6", "linux_amd64"),
                ("Linux", "aarch64", "\t/lib/ld-musl-aarch64.so.1 (0x7f)", "linux_arm64_musl"),
                ("Darwin", "arm64", "", "darwin_arm64"),
                ("Darwin", "x86_64", "", "darwin_amd64")):
            with self.subTest(platform):
                (self.root / "asked").unlink(missing_ok=True)
                self.write(os=os_name, machine=machine, libc=libc)
                self.assertEqual(self.latest("antigravity", AGY_MANIFEST), "1.2.14")
                self.assertEqual(self.asked(), [f"-fsSL {AGY}{platform}.json"])

    def test_muse_names_its_channel_s_build_the_way_the_launcher_asks(self):
        build = MUSE_CHANNEL % ("1.4.1-R4503.1", "1.4.1-R4503.1")
        self.assertEqual(self.latest("muse", build), "1.4.1-R4503.1")
        os.environ["MUSE_CHANNEL"] = "muse-canary"
        self.latest("muse", build)
        self.assertEqual(self.asked(), [
            "-fsSL -A muse-code/launcher-3 https://api.meta.ai/muse-code/channels/muse-stable",
            "-fsSL -A muse-code/launcher-3 https://api.meta.ai/muse-code/channels/muse-canary"])

    def test_a_newer_build_of_the_same_release_is_a_newer_release(self):
        installed = "Muse Code 1.4.1 (1.4.1-R4503.1)"
        for newest, behind in (("1.4.1-R4600.1", True), ("1.4.1-R4503.2", True),
                               ("1.4.2-R10.1", True), ("1.4.1-R4503.1", False),
                               ("1.4.1-R4400.1", False), ("1.4.0-R9999.1", False),
                               ("1.4.1", False)):
            with self.subTest(newest):
                self.assertEqual(update._downgrade(newest, installed), behind)
        # a label that names no build says nothing about which build of it is installed
        self.assertFalse(update._downgrade("1.4.1-R4600.1", "Muse Code 1.4.1"))
        self.assertTrue(update._downgrade("1.0.44", "grok 1.0.40 (eb1a2256660d) [stable]"))
        self.assertEqual(update.kept({"muse": "Muse Code 1.4.1 (1.4.1-R4600.1)"},
                                     {"muse": installed}),
                         {"muse": ("kept", "installed 1.4.1-R4600.1 is newer than "
                                           "the channel's 1.4.1-R4503.1")})

    def test_the_tick_upgrades_a_muse_one_build_behind(self):
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        config.ensure_dirs()
        # the tick moves only from the checkout it runs from: here, a throwaway one
        (self.root / "agentkit").mkdir()
        self.stack.enter_context(patch.object(config, "REPO", self.root / "agentkit"))
        self.stack.enter_context(patch.object(
            config, "load", return_value={"models": {"muse": {"harness": "muse"}}}))
        start = self.stack.enter_context(patch.object(update, "start"))
        self.write(installed="Muse Code 1.4.1 (1.4.1-R4503.1)",
                   answer=MUSE_CHANNEL % ("1.4.1-R4503.1", "1.4.1-R4503.1"))
        update.keep_current(lambda line: None, now=1_000_000.0)
        start.assert_not_called()                   # on the channel's build: nothing to do
        self.write(answer=MUSE_CHANNEL % ("1.4.1-R4600.1", "1.4.1-R4600.1"))
        update.keep_current(lambda line: None, now=1_000_000.0 + update.ASK_EVERY)
        start.assert_called_once_with("muse")


if __name__ == "__main__":
    unittest.main(verbosity=2)
