"""The live-write guard: a seat's scp/rsync/sftp shim refuses a transfer that writes to the live host,
and runs the real tool otherwise (a read from live included).  A file reaches live only through the repo.

Offline: each shim is its tool first on PATH; a fake real tool behind it only logs its argv. No host
is reached. The live host is the `live_host` alias set in config.toml, which `config.live_host()` reads.
"""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
REAL = "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> \"$RAN_LOG\"\nexit 0\n"
# (tool, argv) a seat may not run: the transfer WRITES to the live host.
REFUSED = (("scp", ["localfile", "live:/etc/nginx.conf"]),
           ("scp", ["-i", "/keys/id", "-P", "22", "dir/x", "live:/srv/app"]),
           ("scp", ["f", "info@live:/x"]),
           ("scp", ["localfile", "scp://live/srv/x"]),          # URI destination
           ("rsync", ["-az", "build/", "live:/srv/app/"]),
           ("rsync", ["-az", "build/", "live:/srv/app/", "--exclude", "node_modules"]),  # option after dest
           ("rsync", ["-az", "build/", "live:/srv/app/", "-e", "ssh"]),                  # -e takes a value
           ("rsync", ["f", "info@live:/x"]),
           ("sftp", ["live"]),                                  # sftp connects and can put files
           ("sftp", ["info@live"]),
           ("sftp", ["live:/srv"]))
# (tool, argv) that run the real tool: a read FROM live, another host, or a purely local copy.
ALLOWED = (("scp", ["live:/etc/nginx.conf", "./local"]),       # download: a read, not a write
           ("scp", ["live:/var/log/app.log", "./"]),           # download
           ("scp", ["f", "other:/x"]),
           ("scp", ["a", "b"]),                              # local to local
           ("scp", ["-r", "dir", "/tmp/backup"]),
           ("rsync", ["-az", "live:/srv/app/", "backup/"]),    # download from live
           ("rsync", ["-az", "build/", "other:/x", "--exclude", "live"]),  # a file named live, not the host
           ("rsync", ["dir/", "other:/x"]),
           ("sftp", ["other"]),
           ("sftp", ["otherhost:/srv"]))


class LiveWrite(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / ".agentkit/state").mkdir(parents=True)
        (self.home / ".agentkit/state/session-mine.json").write_text("{}\n")
        (self.home / ".agentkit/config.toml").write_text('live_host = "live"\n')   # the owner's live host
        self.shimdir = self.home / "shim"
        self.realdir = self.home / "real"
        self.shimdir.mkdir()
        self.realdir.mkdir()
        for tool in ("scp", "rsync", "sftp"):
            (self.shimdir / tool).symlink_to(REPO / f"tools/{tool}-shim")
            real = self.realdir / tool
            real.write_text(REAL)
            real.chmod(0o755)
        self.ran = self.home / "ran.log"
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("AK_RUN_ROLE", "AGENTKIT_SESSION")}
        self.env.update(HOME=str(self.home), AGENTKIT_SESSION="mine", RAN_LOG=str(self.ran),
                        PATH=f"{self.shimdir}{os.pathsep}{self.realdir}{os.pathsep}{os.environ.get('PATH', '')}")

    def run_tool(self, tool, args, **env):
        self.ran.write_text("")
        result = subprocess.run([str(self.shimdir / tool), *args], capture_output=True,
                                text=True, timeout=30, env={**self.env, **env})
        ran = self.ran.read_text() if self.ran.exists() else ""
        return result, ran

    def test_a_write_to_the_live_host_is_refused(self):
        for tool, args in REFUSED:
            with self.subTest(tool=tool, args=args):
                result, ran = self.run_tool(tool, args)
                self.assertEqual(result.returncode, 1, (tool, args, result.stderr))
                self.assertIn(f"`{tool}` to live", result.stderr)
                self.assertNotIn("live", ran)        # the real tool never ran the transfer

    def test_a_read_from_live_other_host_or_local_copy_runs(self):
        for tool, args in ALLOWED:
            with self.subTest(tool=tool, args=args):
                result, ran = self.run_tool(tool, args)
                self.assertEqual(result.returncode, 0, (tool, args, result.stderr))
                self.assertTrue(ran.strip(), (tool, args, "reached no real tool"))

    def test_a_worker_and_a_seatless_shell_run_the_real_tool(self):
        for env in ({"AK_RUN_ROLE": "worker"}, {"AGENTKIT_SESSION": ""}):
            with self.subTest(env=env):
                result, ran = self.run_tool("scp", ["f", "live:/x"], **env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("live", ran)

    def test_no_live_host_configured_lets_every_transfer_run(self):
        # config.toml names no live host: ak ships with none, so there is nothing to guard.
        (self.home / ".agentkit/config.toml").write_text("max_runs = 0\n")
        result, ran = self.run_tool("scp", ["f", "live:/x"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("live", ran)

    def test_config_live_host_overrides_the_alias(self):
        # The owner's live host is `prod`, not `live`: prod is refused, and a plain `live` runs.
        (self.home / ".agentkit/config.toml").write_text('live_host = "prod"\n')
        refused, ran = self.run_tool("scp", ["f", "prod:/srv/app"])
        self.assertEqual(refused.returncode, 1, refused.stderr)
        self.assertIn("`scp` to prod", refused.stderr)
        self.assertNotIn("prod", ran)
        allowed, ran = self.run_tool("scp", ["f", "live:/srv/app"])
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertIn("live", ran)

    def test_config_live_host_empty_turns_the_guard_off(self):
        (self.home / ".agentkit/config.toml").write_text('live_host = ""\n')
        result, ran = self.run_tool("scp", ["f", "live:/x"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("live", ran)


if __name__ == "__main__":
    unittest.main()
