"""Proofs and checks have worker walls, throwaway HOME writes and process teardown."""

from contextlib import ExitStack
import errno
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import account_home, in_account_home
from agentkit import box, config, gate, hand_in, run, worker


class ChecksBoxed(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-checks-boxed-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(account_home(self.root))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GH_TOKEN": "fixture-token",
            "GH_CONFIG_DIR": str(self.root / ".config/gh"),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for key in ("HOME", "RUNS", "STATE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.object(run, "dirty_paths", return_value=[]))
        self.stack.enter_context(patch.object(worker, "kill_marked"))
        self.stack.enter_context(patch.object(gate, "derived_heavy_limit", return_value=2))
        self.stack.enter_context(patch.object(gate._SuiteMeasure, "save"))
        self.credential = self.root / ".config/gh/hosts.yml"
        self.credential.parent.mkdir(parents=True)
        self.credential.write_text("fixture-login")
        self.lp = SimpleNamespace(scratch=True, wt=self.root, run_dir=self.root,
                                  done_when_limit=10, turn_limit=10, log=lambda _: None)

    def command(self, source):
        return shlex.join([sys.executable, "-u", "-c", source])

    def proof(self, command):
        return run.proof_on(self.lp, command, self.root / "proof.log")

    def check(self, command, **kwargs):
        return gate.run_done_when([command], self.root, self.root / "check.log", set(),
                                  limit=10, silence=5, **kwargs)

    def credentials_command(self):
        return self.command(
            "import json, os; from pathlib import Path; "
            "print(json.dumps({'file': Path(os.environ['GH_CONFIG_DIR'], 'hosts.yml').read_text(), "
            "'token': os.environ.get('GH_TOKEN')}))")

    def test_proof_cannot_read_credential_file_or_token(self):
        result = self.proof(self.credentials_command())
        self.assertEqual((result["returncode"], result["killed"]), (0, False), result)
        self.assertEqual(json.loads(result["output"]), {"file": "", "token": None})
        self.assertEqual(self.credential.read_text(), "fixture-login")

    def test_done_when_cannot_read_credential_file_or_token(self):
        for suffix in ("", " # AK_SHARD"):
            with self.subTest(command=suffix or "whole"):
                ok, text = self.check(self.credentials_command() + suffix)
                self.assertTrue(ok, text)
                seen = [json.loads(line) for line in text.splitlines() if line.startswith('{"file"')]
                self.assertTrue(seen, text)
                self.assertEqual(seen, [{"file": "", "token": None}] * len(seen))
                self.assertEqual(self.credential.read_text(), "fixture-login")

    def test_proof_and_check_cannot_read_ssh_keys(self):
        key = self.root / ".ssh/id_fixture"
        key.parent.mkdir()
        key.write_text("fixture-key")
        command = self.command(
            "import os; from pathlib import Path; p = Path(os.environ['HOME'], '.ssh/id_fixture'); "
            "print('key:' + (p.read_text() if p.exists() else ''))")
        result = self.proof(command)
        self.assertEqual((result["returncode"], result["output"].strip()), (0, "key:"), result)
        ok, text = self.check(command)
        self.assertTrue(ok, text)
        self.assertIn("key:\n", text + "\n")
        self.assertNotIn("fixture-key", text)
        self.assertEqual(key.read_text(), "fixture-key")

    def alive(self):
        with (self.root / "alive.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        return False

    def test_manager_outside_the_box_is_unavailable(self):
        runtime = self.root / "runtime"
        (runtime / "systemd").mkdir(parents=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        # A relative name fits AF_UNIX even when the checkout path is long.
        listener.bind(str((runtime / "systemd/private").relative_to(REPO)))
        listener.listen(16)
        bindir = self.root / "bin"
        bindir.mkdir()
        binary = bindir / "systemd-run"
        binary.write_text("#!/bin/sh\nexit 97\n")
        binary.chmod(0o755)
        command = self.command(
            f"import sys; sys.path.insert(0, {str(REPO)!r}); "
            "from agentkit import orch; print(orch.user_manager())")
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": "runtime",
                                     "PATH": f"{bindir}:{os.environ['PATH']}"}):
            for name in ("proof", "whole", "sharded"):
                with self.subTest(command=name):
                    if name == "proof":
                        result = self.proof(command)
                        self.assertEqual(result["returncode"], 0, result)
                        text = result["output"]
                    else:
                        ok, text = self.check(command + (" # AK_SHARD" if name == "sharded" else ""))
                        self.assertTrue(ok, text)
                    seen = [line for line in text.splitlines() if line in ("True", "False")]
                    self.assertTrue(seen, text)
                    self.assertEqual(seen, ["False"] * len(seen))

    def stop_sleeper(self):
        # The pre-fix failure also cleans up its own fixture, without inspecting host PIDs.
        (self.root / "stop").touch()
        deadline = time.monotonic() + 5
        while self.alive() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(self.alive(), "fixture sleep did not stop")

    def test_done_when_ends_unmarked_detached_background_sleep(self):
        sleeper = self.root / "sleeper.py"
        sleeper.write_text(
            "import fcntl, subprocess, sys, time\nfrom pathlib import Path\n"
            "root = Path(sys.argv[1])\n"
            "with (root / 'alive.lock').open('a') as lock:\n"
            " fcntl.flock(lock, fcntl.LOCK_EX)\n"
            " child = subprocess.Popen(['sleep', '600'], env={}, start_new_session=True, "
            "pass_fds=(lock.fileno(),))\n"
            " (root / 'ready').touch()\n"
            " while not (root / 'stop').exists():\n  time.sleep(.01)\n"
            " child.terminate()\n child.wait()\n")
        self.addCleanup(self.stop_sleeper)
        command = self.command(
            "import subprocess, sys, time; from pathlib import Path; "
            f"root = Path({str(self.root)!r}); "
            "subprocess.Popen([sys.executable, str(root / 'sleeper.py'), str(root)], "
            "env={}, start_new_session=True, stdin=subprocess.DEVNULL, "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
            "deadline = time.monotonic() + 5\n"
            "while not (root / 'ready').exists():\n"
            " if time.monotonic() > deadline: raise RuntimeError('fixture sleep never started')\n"
            " time.sleep(.01)")
        ok, text = self.check(command)
        self.assertTrue(ok, text)
        self.assertTrue((self.root / "ready").exists())
        self.assertFalse(self.alive(), "done-when left its background sleep running")

    def test_output_and_signal_status_are_preserved(self):
        for command, code in (("printf 'partial'; exit 7", 7),
                              ("printf 'partial'; kill -TERM $$", -15),
                              ("printf 'partial'; exit 143", 143)):
            with self.subTest(command=command):
                result = self.proof(command)
                self.assertEqual((result["returncode"], result["killed"], result["output"]),
                                 (code, False, "partial"))
                ok, text = self.check(command)
                self.assertFalse(ok, text)
                self.assertIn(f"[exit {code}]\npartial", text)

    def test_a_check_writes_where_its_project_says(self):
        # Caches and a suite's own services still work, but only workspace writes persist.
        home = tempfile.TemporaryDirectory(prefix=".ak-test-checks-boxed-home-", dir=REPO)
        self.addCleanup(home.cleanup)
        outside = Path("/tmp", self.root.name)
        for name in ("proof", "check", "sharded"):
            with self.subTest(command=name), patch.dict(os.environ, {"HOME": home.name}):
                cache, scratch = Path(home.name, ".cache", name), outside / name
                command = self.command(
                    "import os, socket, tempfile; from pathlib import Path; "
                    f"paths = [Path({str(cache)!r}), Path({str(scratch)!r})]\n"
                    "for path in paths:\n"
                    " path.parent.mkdir(parents=True, exist_ok=True)\n"
                    " path.write_text('written')\n"
                    " assert path.read_text() == 'written'\n"
                    "with tempfile.TemporaryDirectory() as tmp:\n"
                    " assert str(Path(tmp).parent) == os.environ['TMPDIR']\n"
                    " with socket.socket(socket.AF_UNIX) as server, socket.socket(socket.AF_UNIX) as client:\n"
                    "  server.bind(tmp + '/server')\n"
                    "  server.listen(1)\n"
                    "  client.connect(tmp + '/server')\n"
                    "  connection, _ = server.accept()\n"
                    "  connection.close()\n"
                    f"Path({str(self.root / name)!r}).write_text('workspace')")
                if name == "proof":
                    result = self.proof(command)
                    self.assertEqual(result["returncode"], 0, result)
                else:
                    ok, text = self.check(command + (" # AK_SHARD" if name == "sharded" else ""))
                    self.assertTrue(ok, text)
                self.assertFalse(cache.exists())
                self.assertFalse(scratch.exists())
                self.assertEqual((self.root / name).read_text(), "workspace")

    def test_a_check_leaves_no_program_ak_runs_later(self):
        homes = tempfile.TemporaryDirectory(prefix=".ak-test-checks-boxed-homes-", dir=REPO)
        self.addCleanup(homes.cleanup)
        home, account = (Path(homes.name, name) for name in ("home", "account"))
        for place in (home, account):
            (place / "bin").mkdir(parents=True)
            (place / ".bashrc").write_text("# original\n")
            (place / ".ssh").mkdir()
            (place / ".ssh/id_fixture").write_text("fixture-key")
        for name in ("proof", "check", "sharded"):
            with self.subTest(command=name), account_home(account), \
                    patch.dict(os.environ, {"HOME": str(home),
                                            "PATH": f"{home / 'bin'}:{os.environ['PATH']}"}):
                command = self.command(
                    "import os, pwd, subprocess; from pathlib import Path\n"
                    f"assert pwd.getpwuid(os.getuid()).pw_dir == {str(account)!r}\n"
                    f"for place in map(Path, {[str(home), str(account)]!r}):\n"
                    " program = place / 'bin/ak-fixture-later'\n"
                    " program.write_text('#!/bin/sh\\nprintf check-only\\n')\n"
                    " program.chmod(0o755)\n"
                    " (place / 'owner-yes').write_text('check-only')\n"
                    " assert (place / 'owner-yes').read_text() == 'check-only'\n"
                    " with (place / '.bashrc').open('a') as shell:\n"
                    "  shell.write('# check-only\\n')\n"
                    " assert (place / '.bashrc').read_text() == '# original\\n# check-only\\n'\n"
                    " assert not (place / '.ssh/id_fixture').exists()\n"
                    "assert subprocess.check_output(['ak-fixture-later']) == b'check-only'\n"
                    f"Path({str(self.root / name)!r}).write_text('workspace')")
                if name == "proof":
                    result = self.proof(command)
                    self.assertEqual(result["returncode"], 0, result)
                else:
                    ok, text = self.check(command + (" # AK_SHARD" if name == "sharded" else ""))
                    self.assertTrue(ok, text)
                for place in (home, account):
                    self.assertFalse((place / "bin/ak-fixture-later").exists())
                    self.assertFalse((place / "owner-yes").exists())
                    self.assertEqual((place / ".bashrc").read_text(), "# original\n")
                    self.assertEqual((place / ".ssh/id_fixture").read_text(), "fixture-key")
                self.assertEqual((self.root / name).read_text(), "workspace")

    def test_a_check_cannot_write_elsewhere(self):
        outside = tempfile.TemporaryDirectory(prefix=".ak-test-checks-boxed-readonly-", dir=REPO)
        self.addCleanup(outside.cleanup)
        path = Path(outside.name, "host-file")
        for name in ("proof", "check"):
            with self.subTest(command=name):
                command = self.command(f"from pathlib import Path; Path({str(path)!r}).touch()")
                if name == "proof":
                    result = self.proof(command)
                    self.assertNotEqual(result["returncode"], 0, result)
                    text = result["output"]
                else:
                    ok, text = self.check(command)
                    self.assertFalse(ok, text)
                self.assertIn("Read-only file system", text)
                self.assertFalse(path.exists())

    def test_a_check_cannot_forge_the_owner_yes_store(self):
        # The owner's yes store is out of a boxed check's reach: it cannot write a yes, create the
        # first one where none exists, or rename the state directory away to recreate it unmasked.
        config.STATE.mkdir(parents=True, exist_ok=True)
        store = config.STATE / "owner-yes"
        run_json = store / "run.json"
        create = self.command(f"from pathlib import Path\np = Path({str(run_json)!r})\n"
                              "p.parent.mkdir(parents=True, exist_ok=True)\np.write_text('forged')\n")
        self.assertNotEqual(self.proof(create)["returncode"], 0)
        self.assertFalse(store.exists())                       # no first yes was created
        store.mkdir()
        run_json.write_text("real-yes")
        moved = config.STATE.with_name("state-moved")
        rename = self.command(f"from pathlib import Path\nstate = Path({str(config.STATE)!r})\n"
                             f"state.rename({str(moved)!r})\np = Path({str(run_json)!r})\n"
                             "p.parent.mkdir(parents=True, exist_ok=True)\np.write_text('forged')\n")
        self.assertNotEqual(self.proof(rename)["returncode"], 0)
        self.assertEqual(run_json.read_text(), "real-yes")     # the real yes is untouched
        self.assertFalse(moved.exists())                       # the state dir cannot be renamed away

    def test_a_nested_check_starts_beside_a_crowded_folder(self):
        home = self.root / "home with space"
        crowded = home / "crowded"
        mounted = crowded / "mounted"
        mounted.mkdir(parents=True)
        workspace, out = (self.root / name for name in ("workspace", "out"))
        workspace.mkdir()
        out.mkdir()
        (home / ".bashrc").write_text("original")
        probe = ("import json\nfrom pathlib import Path\nerrors = []\n"
                 "for path in (Path.home() / 'new-file', Path.home() / '.bashrc'):\n"
                 " try:\n  path.write_text('check-only')\n"
                 " except OSError as exc:\n  errors.append(exc.errno)\n"
                 " else:\n  errors.append(None)\n"
                 "Path.cwd().joinpath('ran').touch()\nprint(json.dumps(errors))\n")
        script = self.root / "nested.py"
        script.write_text(
            "import json, os, subprocess, sys\nfrom pathlib import Path\n"
            f"home, crowded, mounted, workspace, out = map(Path, "
            f"{list(map(str, (home, crowded, mounted, workspace, out)))!r})\n"
            "if sys.argv[1] == 'mount':\n"
            " subprocess.run(['mount', '--make-rprivate', '/'], check=True)\n"
            " subprocess.run(['mount', '-t', 'tmpfs', 'tmpfs', str(mounted)], check=True)\n"
            " os.execvp('setpriv', ['setpriv', '--inh-caps=-all', '--ambient-caps=-all', "
            "sys.executable, __file__, 'check'])\n"
            f"sys.path.insert(0, {str(REPO)!r})\n"
            f"sys.path.insert(0, {str(REPO / 'tests')!r})\n"
            "from agentkit import box\nfrom fixtures.sandbox import account_home\n"
            "os.environ['HOME'] = str(home)\ncounts, writes = [], []\n"
            "with account_home(home):\n"
            " for entries in (0, 2500):\n"
            "  for number in range(entries):\n"
            "   (crowded / str(number)).touch()\n"
            f"  with box.command([sys.executable, '-c', {probe!r}], dict(os.environ), out, "
            "cwd=workspace, home_overlay=True) as (cmd, env, spawn):\n"
            "   counts.append(len(cmd[:cmd.index('--')]))\n"
            "   spawn.pop('stop')\n"
            "   result = subprocess.run(cmd, env=env, cwd=workspace, capture_output=True, "
            "text=True, timeout=30, **spawn)\n"
            "  assert result.returncode == 0, result.stderr\n"
            "  writes.append(json.loads(result.stdout))\n"
            "print(json.dumps({'counts': counts, 'writes': writes}))\n")
        result = subprocess.run(
            ["unshare", "--user", "--map-current-user", "--mount", "--keep-caps",
             sys.executable, str(script), "mount"], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        seen = json.loads(result.stdout)
        self.assertEqual(seen["counts"][0], seen["counts"][1])
        self.assertEqual(seen["writes"], [[errno.EROFS, errno.EROFS]] * 2)
        self.assertTrue((workspace / "ran").exists())
        self.assertFalse((home / "new-file").exists())
        self.assertEqual((home / ".bashrc").read_text(), "original")

    def test_declared_writes_inside_home_still_persist(self):
        home = self.root / "home"
        workspace, out, state = (home / name for name in ("workspace", "out", "state"))
        workspace.mkdir(parents=True)
        out.mkdir()
        source = ("from pathlib import Path\n"
                  f"for place in map(Path, {[str(workspace), str(out), str(state)]!r}):\n"
                  " (place / 'kept').write_text('declared')\n"
                  f"Path({str(home / 'cache')!r}).write_text('temporary')")
        with patch.dict(os.environ, {"HOME": str(home)}), \
                box.command([sys.executable, "-c", source], dict(os.environ), out,
                            cwd=workspace, state=("$HOME/state",),
                            home_overlay=True) as (cmd, env, spawn):
            spawn.pop("stop")
            result = subprocess.run(cmd, env=env, cwd=workspace, capture_output=True,
                                    text=True, timeout=10, **spawn)
        self.assertEqual(result.returncode, 0, result.stderr)
        for place in (workspace, out, state):
            self.assertEqual((place / "kept").read_text(), "declared")
        self.assertFalse((home / "cache").exists())

    def test_missing_home_overlay_support_refuses_before_the_check_starts(self):
        bindir = self.root / "bin"
        bindir.mkdir()
        wrapper = bindir / "bwrap"
        wrapper.write_text("#!/bin/sh\ncase \" $* \" in\n"
                           " *' --tmp-overlay '*) printf 'bwrap: overlayfs unavailable\\n' >&2; exit 1;;\n"
                           "esac\nexec " + shlex.quote(shutil.which("bwrap")) + ' "$@"\n')
        wrapper.chmod(0o755)
        with patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}):
            result = self.proof("touch started")
            self.assertEqual(result["returncode"], 126, result)
            self.assertFalse(hand_in.proof_failed(result), result)
            ok, text = self.check("touch started")
            self.assertFalse(ok, text)
            for output in (result["output"], text):
                self.assertIn("overlayfs unavailable", output)
                self.assertIn("install bubblewrap with --tmp-overlay support", output)
                self.assertIn("kernel that allows overlayfs in unprivileged user namespaces", output)
        self.assertFalse((self.root / "started").exists())

    def test_a_box_that_cannot_start_proves_nothing(self):
        # bwrap exits 1 on a mount it cannot make, before its supervisor runs the command.
        bindir = self.root / "bin"
        bindir.mkdir()
        wrapper = bindir / "bwrap"
        missing = self.root / "missing-mount-source"
        wrapper.write_text("#!/bin/sh\nexec " + shlex.join(
            [shutil.which("bwrap"), "--ro-bind", str(missing), str(missing)]) + ' "$@"\n')
        wrapper.chmod(0o755)
        with patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}):
            result = self.proof("touch started; exit 7")
            self.assertFalse((self.root / "started").exists())
            self.assertEqual((result["returncode"], result["killed"]), (126, False), result)
            self.assertFalse(hand_in.proof_failed(result), result)
            ok, text = self.check("true")
            self.assertFalse(ok, text)
            self.assertIn("[exit 126]", text)
            for output in (result["output"], text):
                self.assertIn("missing-mount-source", output)
                self.assertNotIn(box.OVERLAY_REMEDY, output)

    def test_a_missing_home_is_not_missing_overlay_support(self):
        home = self.root / "absent-home"
        with patch.dict(os.environ, {"HOME": str(home)}):
            result = self.proof("touch started")
            self.assertEqual(result["returncode"], 126, result)
            ok, text = self.check("touch started")
            self.assertFalse(ok, text)
            for output in (result["output"], text):
                self.assertIn("absent-home", output)
                self.assertNotIn(box.OVERLAY_REMEDY, output)
        self.assertFalse((self.root / "started").exists())

    def test_orphans_are_reaped_while_the_output_drains(self):
        # The shell is gone at once; its background child holds the output and leaves
        # exited children to PID 1, which must not let them pile up until forks fail.
        source = (
            "import os, pathlib, time\n"
            "while os.getppid() != 1:\n    time.sleep(.01)\n"
            "for _ in range(20):\n"
            "    child = os.fork()\n"
            "    if child == 0:\n        os.fork()\n        os._exit(0)\n"
            "    os.waitpid(child, 0)\n"
            "time.sleep(1)\n"
            "states = []\n"
            "for entry in pathlib.Path('/proc').iterdir():\n"
            "    try:\n"
            "        states.append((entry / 'stat').read_text().rsplit(')', 1)[1].split()[0])\n"
            "    except (OSError, IndexError):\n        pass\n"
            "print('zombies', states.count('Z'))\n")
        for name in ("proof", "check"):
            with self.subTest(command=name):
                command = self.command(source) + " &"
                text = (self.proof(command)["output"] if name == "proof"
                        else self.check(command)[1])
                self.assertIn("zombies 0", text)

    def test_a_launcher_keeps_the_supervisor_it_loaded(self):
        # A probe may check out another revision of ak's own checkout under the launcher.
        copy = self.root / "copy"
        shutil.copytree(REPO / "agentkit", copy / "agentkit",
                        ignore=shutil.ignore_patterns("__pycache__"))
        driver = (
            "import sys\nfrom pathlib import Path\nfrom types import SimpleNamespace\n"
            "sys.path.insert(0, sys.argv[1])\nfrom agentkit import box, gate, run\n"
            "Path(box.__file__).write_text('raise SystemExit(99)\\n')\n"
            "root = Path(sys.argv[2])\n"
            "lp = SimpleNamespace(scratch=True, wt=root, run_dir=root, done_when_limit=10,\n"
            "                     turn_limit=10, log=lambda _: None)\n"
            "print(run.proof_on(lp, 'printf started; exit 7', root / 'proof.log'))\n"
            "print(gate.run_done_when(['printf started; exit 7'], root, root / 'check.log', set(),\n"
            "                         limit=10, silence=5)[1])\n")
        result = in_account_home([sys.executable, "-c", driver, str(copy), str(self.root)],
                                 self.root,
                                capture_output=True, text=True, timeout=120)
        self.assertIn("{'returncode': 7, 'output': 'started', 'killed': False}", result.stdout,
                      result)
        self.assertIn("[exit 7]\nstarted", result.stdout, result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
