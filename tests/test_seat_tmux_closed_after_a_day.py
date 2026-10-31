"""A seat's finished auxiliary tmux sessions keep their screens, then close after a day.

Offline: the shim calls an argv recorder; the tick sees a fake tmux and a temporary HOME.
"""

import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from fixtures.sidesessions import REPO, SideSessions
from agentkit import config, guard, orch


class FinishedTmux(SideSessions):
    def test_the_tick_saves_and_closes_only_tagged_sessions_dead_for_a_day(self):
        self.add("$1", "old")
        self.add("$2", "recent", (3600,))
        self.add("$3", "running", (25 * 3600, None))
        self.add("$4", "by-hand", owner="")
        self.add("$5", "marked-seat", mark="1")
        self.add("$6", "recorded-seat")
        config.session_path("recorded-seat").write_text("{}")
        self.add("$7", "mixed", (25 * 3600, 3600))
        self.add("$8", "several-windows", (25 * 3600, 26 * 3600))
        self.add("$9", "boundary", (86400,))
        self.tick()
        self.assertEqual(self.closed, ["$1", "$8", "$9"])
        saved = list(config.TMP.glob("tmux-*.txt"))
        self.assertEqual(len(saved), 3)
        screens = "".join(path.read_text() for path in saved)
        for pane in ("%0", "%70", "%71", "%80"):
            self.assertIn(f"  last screen {pane}  \n\n", screens)
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in saved))

    def test_failed_capture_or_exclusive_creation_never_authorizes_closing(self):
        self.add("$1", "old")
        self.capture_error = True
        self.tick()
        self.assertEqual(self.closed, [])
        self.capture_error = False
        victim = self.root / "keep"
        victim.write_text("untouched")
        (config.TMP / "tmux-collision.txt").symlink_to(victim)
        with patch.object(orch.uuid, "uuid4") as uuid:
            uuid.return_value.hex = "collision"
            self.tick()
        self.assertEqual(victim.read_text(), "untouched")
        self.assertEqual(self.closed, [])

    def test_a_linked_tmp_directory_is_never_used(self):
        self.add("$1", "old")
        config.TMP.rmdir()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        config.TMP.symlink_to(elsewhere, target_is_directory=True)
        self.tick()
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertEqual(self.closed, [])

    def test_a_session_changed_during_capture_is_kept(self):
        for change in ("respawned", "marked", "renamed", "new-pane", "emptied", "untagged"):
            with self.subTest(change=change):
                self.sessions.clear()
                self.add("$1", "old")
                fields, windows = self.sessions["$1"]
                self.after_capture = {
                    "respawned": lambda: windows[0][0].update(pane_dead="0", pane_dead_time=""),
                    "marked": lambda: fields.update({orch.MARK: "1"}),
                    "renamed": lambda: fields.update(session_name="recorded-seat"),
                    "new-pane": lambda: windows[0].append({"pane_id": "%99", "pane_dead": "0",
                                                          "pane_dead_time": ""}),
                    "emptied": lambda: fields.update({guard.TMUX_OWNER: ""}),
                    "untagged": lambda: self.owners.update({"$1": ""}),
                }[change]
                config.session_path("recorded-seat").write_text("{}")
                self.tick()
                self.assertEqual(self.closed, [])

    def test_the_shim_tags_every_creation_and_preserves_output_and_exit_status(self):
        shimdir, realdir = self.root / "shim", self.root / "real"
        shimdir.mkdir()
        realdir.mkdir()
        (shimdir / "tmux").symlink_to(REPO / "tools/tmux-shim")
        real = realdir / "tmux"
        real.write_text(f"#!{sys.executable}\nimport json, sys\n"
                        "print(json.dumps(sys.argv[1:]))\nsys.exit(3)\n")
        real.chmod(0o755)
        env = {**os.environ, "PATH": os.pathsep.join([str(shimdir), str(realdir),
                                                    os.environ.get("PATH", "")])}
        for command in ("new-session", "new", "new-s"):
            args = ["-uL", "elsewhere", command, "-d", "-s", "watch", ";",
                    "new-session", "-d", "echo finished"]
            result = subprocess.run([str(shimdir / "tmux"), *args], env=env,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 3, result.stderr)
            tag = ["-e", "AGENTKIT_SESSION=acme", "-e", f"{guard.TMUX_OWNER}=acme"]
            self.assertEqual(json.loads(result.stdout),
                             [*args[:3], *tag, *args[3:8], *tag, *args[8:]])
        for override in ({"AK_RUN_ROLE": "worker"}, {"AGENTKIT_SESSION": ""}):
            result = subprocess.run([str(shimdir / "tmux"), "new-session", "-d"],
                                    env={**env, **override}, capture_output=True, text=True,
                                    timeout=15)
            self.assertEqual(json.loads(result.stdout), ["new-session", "-d"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
