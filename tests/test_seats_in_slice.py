"""A seat's harness starts inside a scope of its own in the seats slice, whatever server it is on.

Offline: a fake tmux that records what it is asked and answers the way tmux 3.5a does, a user
manager that is a yes or a no, and fake `systemd-run`s of the versions the test names, one on
ak's PATH and another first on the pane's: each records its argv and execs what follows its
`--`, the way a scope hands over to the work.  No real tmux, unit or seat.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, orch

# The manager's scope, as far as the pane can tell: the work runs in the same process once the
# unit is made.  Like the real one, 258 and later expand `${NAME}` in it unless told not to,
# and one older than 254 knows no such switch and refuses the scope over it.
SYSTEMD_RUN = '''#!{python}
import json, os, re, sys
said = "{said}"
if sys.argv[1:] == ["--version"]:
    print(said)
    sys.exit(0)
with open(os.environ["AK_SEATS_LOG"], "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
version, split = int(said.split()[1]), sys.argv.index("--")
options, rest = sys.argv[1:split], sys.argv[split + 1:]
if version < 254 and any(option.startswith("--expand-environment") for option in options):
    sys.exit("systemd-run: unrecognized option '--expand-environment=no'")
if version >= 258 and "--expand-environment=no" not in options:
    rest = [re.sub(r"\\$\\{{(\\w+)\\}}", lambda m: os.environ.get(m.group(1), ""), word)
            for word in rest]
os.execvp(rest[0], rest)
'''
# A harness that says what it was handed, quote for quote and dollar for dollar.
HARNESS = [sys.executable, "-c", "import json, sys; print(json.dumps(sys.argv[1:]))",
           "--resume", "it's ${HOME}"]


class SeatsInSlice(Sandbox):
    def setUp(self):
        super().setUp()
        # the toolkit's own server, under its own names: the fake tmux below is all it reaches
        self.stack.enter_context(patch.dict(os.environ, {orch.SOCKET_ENV: orch.SOCKET}))
        self.manager = True
        self.stack.enter_context(patch.object(orch, "user_manager", lambda: self.manager))
        self.server_up = True
        self.calls = []
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        # ak's own `systemd-run`, and the other version a server's older PATH finds first
        self.bin, self.stray = self.root / "bin", self.root / "stray"
        self.systemd_run(258, 252)
        self.log = self.root / "systemd-run.jsonl"
        self.stack.enter_context(patch.dict(os.environ, {
            "PATH": f"{self.bin}:{os.environ['PATH']}", "AK_SEATS_LOG": str(self.log),
            "XDG_RUNTIME_DIR": "/run/user/4242"}))
        # what `systemd-run` says of itself is asked once per process; each test names its own
        orch._LITERAL.clear()
        self.addCleanup(orch._LITERAL.clear)
        config.save_session(self.cfg, "acme", "opus", ["opus"])

    def systemd_run(self, version, stray):
        for where, said in ((self.bin, version), (self.stray, stray)):
            where.mkdir(exist_ok=True)
            (where / "systemd-run").write_text(SYSTEMD_RUN.format(
                python=sys.executable, said=f"systemd {said} (fake)"))
            (where / "systemd-run").chmod(0o755)

    def tmux(self, *args, socket=None, client=False, unit=None, path_shim=False, **_kw):
        self.calls.append((args, unit, path_shim))
        if args[0] == "source-file":
            return (0, "") if self.server_up else (1, "no server running")
        if args[0] == "show-options":
            return 0, "%3"
        if args[0] == "display-message":
            return 0, "acme"
        return 0, ""

    def launched(self, verb):
        """The pane command and the server's own unit of each `new-session`/`respawn-pane`."""
        return [(args[-1], unit) for args, unit, _ in self.calls if verb in args]

    def scope(self, line):
        """The unit a pane command puts its harness in, after checking the line around it."""
        words = shlex.split(line)
        self.assertEqual(words[:2], ["env", "XDG_RUNTIME_DIR=/run/user/4242"])
        self.assertEqual(words[2:6], [str(self.bin / "systemd-run"), "--user",
                                      "--slice=agentkit-seats.slice", "--scope"])
        self.assertIn("--quiet", words[6:words.index("--")])
        self.assertEqual(words[words.index("--") + 1:], HARNESS)
        unit = next(word for word in words if word.startswith("--unit="))
        return unit.removeprefix("--unit=")

    def ran(self, line, cwd=None):
        """What the harness was handed when the pane's shell ran that line through the scope."""
        pane = {**os.environ, "PATH": f"{self.stray}:{os.environ['PATH']}"}
        out = subprocess.run(["sh", "-c", line], capture_output=True, text=True, timeout=60,
                             env=pane, cwd=cwd)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_a_new_seat_and_a_respawn_spawn_with_the_shim_first_on_path(self):
        # tmux gives a pane the client's PATH, so the spawn calls carry the shim dir first.
        from agentkit import guard
        with patch.object(config, "HOME", self.root / ".agentkit"):
            orch.start("acme", self.root, HARNESS, "opus")
            orch._start_harness("acme", "opus", self.root, HARNESS, {"name": "acme"})
        for verb in ("new-session", "respawn-pane"):
            shimmed = [p for a, _, p in self.calls if verb in a]
            self.assertTrue(shimmed and all(shimmed), f"{verb} did not spawn with path_shim")
        # a management call that spawns no pane is not shimmed
        self.assertFalse(any(p for a, _, p in self.calls if "list-sessions" in a))

    def test_a_a_seat_on_a_server_already_up_runs_its_harness_in_its_own_scope(self):
        orch.start("acme", self.root, HARNESS, "opus")
        (line, server_unit), = self.launched("new-session")
        self.assertIsNone(server_unit)          # the server is not this command's to place
        self.assertTrue(self.scope(line).startswith("agentkit-seat-acme-"))
        # a scope that expands is told not to, and the harness gets exactly what it was given
        self.assertIn("--expand-environment=no", shlex.split(line))
        self.assertEqual(self.ran(line), HARNESS[3:])
        self.assertEqual(len(self.log.read_text().splitlines()), 1)

    def test_b_each_resume_starts_a_scope_whose_name_none_before_it_had(self):
        orch.start("acme", self.root, HARNESS, "opus")
        units = [self.scope(self.launched("new-session")[0][0])]
        session = {"name": "acme", "exited": True}
        orch.launch("acme", "opus", self.root, HARNESS, None, session=session)
        # a tick from cron cannot be moved itself, and the pane's harness still goes in as a scope
        with patch.object(orch, "can_scope", return_value=False):
            orch.launch("acme", "opus", self.root, HARNESS, None, session=session)
        respawned = self.launched("respawn-pane")
        self.assertEqual(len(respawned), 2)
        units += [self.scope(line) for line, _ in respawned]
        self.assertEqual(len(set(units)), 3)
        for unit in units:
            self.assertRegex(unit, r"^agentkit-seat-acme-[0-9a-f]+$")

    def test_c_a_server_this_command_starts_is_placed_and_the_harness_in_a_scope_beside_it(self):
        self.server_up = False
        orch.start("acme", self.root, HARNESS, "opus")
        (line, server_unit), = self.launched("new-session")
        self.assertEqual(server_unit, "agentkit-seat-acme")
        self.assertNotEqual(self.scope(line), server_unit)

    def test_d_where_no_manager_answers_the_harness_starts_plainly(self):
        self.manager = False
        orch.start("acme", self.root, HARNESS, "opus")
        orch.launch("acme", "opus", self.root, HARNESS, None, session={"name": "acme"})
        lines = [line for line, _ in self.launched("new-session") + self.launched("respawn-pane")]
        self.assertEqual(lines, [shlex.join(HARNESS)] * 2)

    def test_e_a_systemd_run_too_old_for_the_switch_is_not_handed_it(self):
        self.systemd_run(252, 258)
        orch.start("acme", self.root, HARNESS, "opus")
        (line, _), = self.launched("new-session")
        self.scope(line)
        self.assertFalse(any(re.match("--expand", word) for word in shlex.split(line)))
        self.assertEqual(self.ran(line), HARNESS[3:])

    def test_f_a_systemd_run_found_through_a_relative_path_entry_runs_from_the_seat_too(self):
        seat = self.root / "acme"
        seat.mkdir()
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.root)
        with patch.dict(os.environ, {"PATH": f"bin:{os.environ['PATH']}"}):
            orch.start("acme", seat, HARNESS, "opus")
        (line, _), = self.launched("new-session")
        self.scope(line)
        self.assertEqual(self.ran(line, cwd=seat), HARNESS[3:])

    def test_g_a_path_entry_through_a_symlink_and_dot_dot_runs_the_file_it_found(self):
        (self.root / "versions/current").mkdir(parents=True)
        self.bin.rename(self.root / "versions/bin")
        (self.root / "current").symlink_to(self.root / "versions/current")
        with patch.dict(os.environ, {"PATH": f"{self.root}/current/../bin:{os.environ['PATH']}"}):
            orch.start("acme", self.root, HARNESS, "opus")
        (line, _), = self.launched("new-session")
        self.assertEqual(self.ran(line), HARNESS[3:])
        self.assertEqual(len(self.log.read_text().splitlines()), 1)

    def test_h_a_caller_whose_directory_is_gone_runs_the_absolute_one_it_found(self):
        gone = self.root / "gone"
        gone.mkdir()
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(gone)
        gone.rmdir()
        orch.start("acme", self.root, HARNESS, "opus")
        (line, _), = self.launched("new-session")
        self.scope(line)


class ShimDelivery(unittest.TestCase):
    """The real tmux_out, not the mock: path_shim puts the seat-guard dir first on the PATH tmux
    gives the pane it spawns (tmux copies the client's PATH), and only on a spawn."""

    def test_path_shim_puts_the_shim_first_on_the_spawn_clients_path(self):
        from agentkit import config, guard, orch
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        seen = []

        def fake_run(argv, **kw):
            seen.append((kw.get("env") or {}).get("PATH", ""))
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch.object(config, "HOME", Path(tmp.name) / ".agentkit"), \
                patch.object(orch, "fix_term", lambda: ""), \
                patch("subprocess.run", fake_run):
            shim = str(guard.shim_dir())
            orch.tmux_out("new-session", path_shim=True, socket="x")
            self.assertEqual(seen[-1].split(os.pathsep)[0], shim)       # a spawn carries the shim
            self.assertTrue((Path(tmp.name) / ".agentkit/bin/tmux").is_symlink())
            orch.tmux_out("list-sessions", socket="x")
            self.assertNotEqual(seen[-1].split(os.pathsep)[0], shim)    # a query does not


if __name__ == "__main__":
    unittest.main()
