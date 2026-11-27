"""Check 32 runs tests/bare-install.sh as a live check whenever docker info succeeds.

tests/live.sh holds check 32 (in tests/suite_shares.py's LIVE_CHECKS) only where `docker` and
`timeout` are both on PATH and `timeout -k 5 20 docker info` exits 0, asked once as the run
chooses its checks.  Anywhere else check 32 is left out by name with no skip, so
AGENTKIT_ACCEPTANCE_REQUIRED=1 still passes.  Offline: uses a stand-in suite and fake `docker`
and `timeout` binaries in temporary directories.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import suite_shares as suite

SMOKE = (REPO / "tests/smoke.sh").read_text()
BLOCKS = suite.smoke_blocks(SMOKE)
NAMED = {name for name, _ in BLOCKS if name is not None}

# `/bin/sh` avoids splitting a `sys.executable` path that contains spaces in a `#!` line.
PYTHON_SHIM = '#!/bin/sh\nexec "$FAKE_PYTHON" "$0.py" "$@"\n'

FAKE_DOCKER = """import json, os, pathlib, sys

log = pathlib.Path(os.environ["FAKE_LOG"])
with log.open("a") as fh:
    fh.write(json.dumps(["docker", *sys.argv[1:]]) + "\\n")
if os.environ.get("FAKE_DOCKER_NOISE"):
    print("Server Version: fake-stdout")
    print("WARNING: fake-stderr", file=sys.stderr)
sys.exit(int(os.environ.get("FAKE_DOCKER_EXIT", "0")))
"""

FAKE_TIMEOUT = """import json, os, pathlib, sys

log = pathlib.Path(os.environ["FAKE_LOG"])
with log.open("a") as fh:
    fh.write(json.dumps(["timeout", *sys.argv[1:]]) + "\\n")
forced = os.environ.get("FAKE_TIMEOUT_EXIT")
if forced:
    sys.exit(int(forced))
args = sys.argv[1:]
i = 0
while i < len(args) and args[i].startswith("-"):
    i += 2 if args[i] in ("-k", "-s") else 1
cmd = args[i + 1:]
os.execvp(cmd[0], cmd)
"""

BASE_TOOLS = ("bash", "sh", "dirname", "mkdir", "rm", "mv", "cat", "sed", "tail")


def write_python_shim(path, script):
    path.with_name(f"{path.name}.py").write_text(script)
    path.write_text(PYTHON_SHIM)
    path.chmod(0o755)


def clean_bin(directory, *, docker=False, timeout=False):
    """Build a minimal PATH directory containing only base utilities plus optional fakes."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "python3").symlink_to(sys.executable)
    for tool in BASE_TOOLS:
        found = shutil.which(tool)
        if found:
            (directory / tool).symlink_to(found)
    if docker:
        write_python_shim(directory / "docker", FAKE_DOCKER)
    if timeout:
        write_python_shim(directory / "timeout", FAKE_TIMEOUT)
    return directory


class BareInstallIsALiveCheck(unittest.TestCase):
    def make_standin(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-bare-live-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "tests").mkdir()
        for name in ("live.sh", "suite_shares.py", "acceptance.sh"):
            (root / "tests" / name).write_text((REPO / "tests" / name).read_text())
        stub = SMOKE[:SMOKE.index('export PATH="$REPO/bin:$PATH"')]
        stub += 'WORK="$HOME/work"; mkdir -p "$WORK"; . "$REPO/tests/acceptance.sh"\n'
        stub += "".join(f"# --- {name}: fixture\necho 'ran {name}'; ok '{name} fixture'\n"
                        for name in sorted(NAMED))
        stub += "# --- shared result ---\nfinish\n"
        (root / "tests/smoke.sh").write_text(stub)
        return root

    def run_live(self, root, *, docker=True, timeout=True, docker_exit=0,
                 timeout_exit="", noise=False, script="live.sh", extra_env=None):
        tag = f"bin-{int(docker)}-{int(timeout)}-{docker_exit}-{timeout_exit}-{int(noise)}"
        bin_dir = clean_bin(root / tag, docker=docker, timeout=timeout)
        log = root / f"calls-{tag}.jsonl"
        if log.exists():
            log.unlink()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AK_", "AGENTKIT_"))}
        env.update(
            HOME=str(root),
            PATH=str(bin_dir),
            AGENTKIT_ACCEPTANCE_REQUIRED="1",
            FAKE_PYTHON=sys.executable,
            FAKE_LOG=str(log),
            FAKE_DOCKER_EXIT=str(docker_exit),
            FAKE_TIMEOUT_EXIT=str(timeout_exit),
        )
        if noise:
            env["FAKE_DOCKER_NOISE"] = "1"
        if extra_env:
            env.update(extra_env)
        proc = subprocess.run(["bash", f"tests/{script}"], cwd=root, env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        ran = {line.removeprefix("ran ") for line in proc.stdout.splitlines()
               if line.startswith("ran ")}
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return proc, ran, calls

    def test_32_is_a_live_check_and_not_a_model_call(self):
        self.assertIn("32", suite.LIVE_CHECKS)
        self.assertNotIn("32", suite.MODEL_CALLS)
        live = set(suite.smoke_owners(BLOCKS, REPO, 1, live=True))
        landing = set(suite.smoke_owners(BLOCKS, REPO, 1, live=False))
        self.assertIn("32", live)
        self.assertNotIn("32", landing)

    def test_live_run_holds_32_when_docker_info_exits_0_asked_once(self):
        root = self.make_standin()
        proc, ran, calls = self.run_live(root, docker=True, timeout=True, docker_exit=0, noise=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(ran, suite.LIVE_CHECKS)
        self.assertIn("32", ran)
        self.assertEqual(calls, [
            ["timeout", "-k", "5", "20", "docker", "info"],
            ["docker", "info"],
        ])
        self.assertIn("0 skipped", proc.stdout)
        self.assertNotIn("SKIP", proc.stdout)

        # Plain landing smoke.sh never runs 32 and never probes docker.
        plain_proc, plain_ran, plain_calls = self.run_live(
            root, docker=True, timeout=True, docker_exit=0, script="smoke.sh"
        )
        self.assertEqual(plain_proc.returncode, 0, plain_proc.stdout + plain_proc.stderr)
        self.assertNotIn("32", plain_ran)
        self.assertEqual(plain_calls, [])

    def test_live_run_leaves_32_out_without_skip_when_probe_cannot_succeed(self):
        root = self.make_standin()
        cases = (
            ("no docker", dict(docker=False, timeout=True)),
            ("no timeout", dict(docker=True, timeout=False)),
            ("docker info exits 1", dict(docker=True, timeout=True, docker_exit=1)),
            ("timeout exits 124", dict(docker=True, timeout=True, timeout_exit="124")),
        )
        for label, kwargs in cases:
            with self.subTest(label):
                proc, ran, calls = self.run_live(root, **kwargs)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(ran, suite.LIVE_CHECKS - {"32"})
                self.assertNotIn("32", ran)
                self.assertIn("0 skipped", proc.stdout)
                self.assertNotIn("SKIP", proc.stdout)
                if not kwargs["docker"] or not kwargs["timeout"]:
                    self.assertEqual(calls, [])
                elif kwargs.get("timeout_exit"):
                    self.assertEqual(calls, [["timeout", "-k", "5", "20", "docker", "info"]])
                else:
                    self.assertEqual(calls, [
                        ["timeout", "-k", "5", "20", "docker", "info"],
                        ["docker", "info"],
                    ])

    def test_live_run_without_model_calls_keeps_32_only_with_docker(self):
        root = self.make_standin()
        with_docker = self.run_live(root, docker=True, timeout=True, docker_exit=0,
                                    extra_env={"AK_LIVE_NO_MODEL_CALLS": "1"})
        self.assertEqual(with_docker[0].returncode, 0, with_docker[0].stdout + with_docker[0].stderr)
        self.assertEqual(with_docker[1], suite.LIVE_CHECKS - suite.MODEL_CALLS)
        self.assertIn("32", with_docker[1])

        without_docker = self.run_live(root, docker=True, timeout=True, docker_exit=1,
                                       extra_env={"AK_LIVE_NO_MODEL_CALLS": "1"})
        self.assertEqual(without_docker[0].returncode, 0,
                         without_docker[0].stdout + without_docker[0].stderr)
        self.assertEqual(without_docker[1], suite.LIVE_CHECKS - suite.MODEL_CALLS - {"32"})
        self.assertIn("0 skipped", without_docker[0].stdout)

    def test_real_check_32_block_runs_bare_install_in_repo_and_tracks_exit(self):
        block = next(body for name, body in BLOCKS if name == "32")
        with tempfile.TemporaryDirectory(prefix=".ak-test-bare-block-", dir=REPO) as tmp:
            root = Path(tmp)
            repo = root / "checkout"
            other = root / "elsewhere"
            work = root / "work"
            (repo / "tests").mkdir(parents=True)
            other.mkdir()
            work.mkdir()
            (repo / "tests" / "acceptance.sh").write_text(
                (REPO / "tests" / "acceptance.sh").read_text()
            )
            stub = repo / "tests" / "bare-install.sh"
            stub.write_text(
                '#!/usr/bin/env bash\n'
                'pwd >"$STUB_PWD"\n'
                'printf "%s\\n" "${STUB_MSG:-}" >&2\n'
                'exit "${STUB_EXIT:-0}"\n'
            )
            stub.chmod(0o755)
            script = (
                'set -uo pipefail\n'
                '. "$REPO/tests/acceptance.sh"\n'
                + block
                + '\nfinish\n'
            )
            for code in (0, 1):
                with self.subTest(exit_code=code):
                    pwd_file = root / f"pwd-{code}"
                    failed = root / f"failed-{code}"
                    Path(f"{failed}.tmp").write_text("")
                    env = {
                        k: v for k, v in os.environ.items()
                        if not k.startswith(("AK_", "AGENTKIT_"))
                    }
                    env.update(
                        HOME=str(root),
                        SMOKE_CALLER_HOME=str(root),
                        REPO=str(repo),
                        WORK=str(work),
                        AGENTKIT_ACCEPTANCE_REQUIRED="1",
                        AK_LIVE_FAILED=str(failed) + ".tmp",
                        AK_LIVE_FAILED_FINAL=str(failed),
                        STUB_PWD=str(pwd_file),
                        STUB_EXIT=str(code),
                        STUB_MSG="bare-install boom" if code else "",
                    )
                    proc = subprocess.run(["bash", "-c", script], cwd=other, env=env,
                                          stdin=subprocess.DEVNULL, capture_output=True,
                                          text=True, timeout=30)
                    self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
                    self.assertEqual(Path(pwd_file.read_text().strip()).resolve(), repo.resolve())
                    if code == 0:
                        self.assertIn("PASS  32 ", proc.stdout)
                        self.assertIn("1 passed, 0 failed, 0 skipped", proc.stdout)
                        self.assertEqual(failed.read_text(), "")
                    else:
                        self.assertIn("FAIL  32 ", proc.stdout)
                        self.assertIn("bare-install boom", proc.stdout)
                        self.assertIn("0 passed, 1 failed, 0 skipped", proc.stdout)
                        self.assertEqual(failed.read_text().splitlines(), ["32"])


if __name__ == "__main__":
    unittest.main()
