"""A seat's agy is started trusting the folder the seat opens in, so it opens on its prompt."""

import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

REPO = Path(__file__).resolve().parents[1]


class AntigravitySeatTrustsItsFolder(unittest.TestCase):
    def test_the_seats_command_line_hands_agy_its_folder_as_trusted(self):
        with tempfile.TemporaryDirectory() as temp:
            # A name whose newline `$(pwd -P)` drops, whose é bash's %q writes under LC_ALL=C as
            # $'...', which shlex.split does not read, and whose quote ends a single-quoted word.
            bin_dir, folder = Path(temp) / "bin", Path(temp).resolve() / "code" / "l'acmé\n"
            rulebook = Path(temp) / "state" / "rules.md"
            for made in (bin_dir, folder, rulebook.parent):
                made.mkdir(parents=True)
            rulebook.write_text("Follow the owner's task.\n")
            binary = bin_dir / "agy"
            binary.write_text('#!/bin/sh\nwhile [ $# -gt 1 ]; do\n'
                              '  [ "$1" = --settings ] && printf "%s\\n" "$2"; shift\ndone\n')
            binary.chmod(0o755)
            env = {"HOME": temp, "PATH": f"{bin_dir}:/usr/bin:/bin",
                   "AGENTKIT_RULEBOOK": str(rulebook), "LC_ALL": "C"}
            command = subprocess.run(
                [str(REPO / "adapters/antigravity.sh"), "interactive", "acme-flash", "high"],
                cwd=folder, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(command.returncode, 0, command.stderr)
            launched = subprocess.run(shlex.split(command.stdout), cwd=folder, env=env,
                                      stdin=subprocess.DEVNULL, capture_output=True,
                                      text=True, timeout=10)
            self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
            self.assertEqual(json.loads(launched.stdout)["trustedWorkspaces"], [str(folder)])

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_a_seat_reopened_once_its_folder_is_gone_trusts_the_one_its_agy_starts_in(self):
        with Home() as home:
            akconfig.write(home, {"acme": "antigravity"})
            said = home.path / "agy.said"
            home.fake("agy", '#!/bin/sh\nwhile [ $# -gt 1 ]; do\n'
                             '  [ "$1" = --settings ] && { pwd -P; printf "%s\\n" "$2"; }'
                             ' >"$HOME/agy.new" && mv "$HOME/agy.new" "$HOME/agy.said"; shift\n'
                             'done\n')
            seat = Seat(home, model="acme", record={"conversation": None})
            # Its harness ends and its folder goes: tmux starts such a pane's next command in HOME.
            done = home.tmux("respawn-pane", "-k", "-t", seat.pane, "true")
            self.assertEqual(done.code, 0, done.err)
            self.wait(lambda: home.tmux("display-message", "-p", "-t", seat.pane,
                                        "#{pane_dead}").out.strip() == "1", seat)
            seat.cwd.rmdir()
            done = home.ak("orch", seat.name)
            self.assertEqual(done.code, 0, done.out + done.err)
            self.wait(said.exists, seat)
            folder, settings = said.read_text().splitlines()
            self.assertEqual(json.loads(settings)["trustedWorkspaces"], [folder])

    def wait(self, ready, seat):
        """Until `ready`: a pane's process is slow to start and to end on a loaded host."""
        deadline = time.monotonic() + 300
        while not ready():
            self.assertLess(time.monotonic(), deadline, seat.capture())
            time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
