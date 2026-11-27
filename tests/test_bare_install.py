"""tests/bare-install.sh archives HEAD into a bare Debian container and maps exit codes cleanly.

Offline: puts a fake `docker` (and in one test a recording `timeout`) on PATH and runs the real
script inside a small temporary git checkout.
"""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tests" / "bare-install.sh"
IMAGE = "docker.io/library/debian:trixie-slim"

FAKE_DOCKER = f"""#!{sys.executable}
import json, os, pathlib, sys

out = pathlib.Path(os.environ["FAKE_DOCKER_DIR"])
(out / "args.json").write_text(json.dumps(sys.argv[1:]))
(out / "stdin.tar").write_bytes(sys.stdin.buffer.read())
lines = int(os.environ.get("FAKE_DOCKER_LINES", "0"))
for i in range(1, lines + 1):
    print(f"line-{{i:03d}}")
sys.exit(int(os.environ.get("FAKE_DOCKER_EXIT", "0")))
"""

FAKE_TIMEOUT = f"""#!{sys.executable}
import json, os, pathlib, sys

out = pathlib.Path(os.environ["FAKE_DOCKER_DIR"])
(out / "timeout.json").write_text(json.dumps(sys.argv[1:]))
args = sys.argv[1:]
i = 0
while i < len(args) and args[i].startswith("-"):
    i += 2 if args[i] in ("-k", "-s") else 1
# Skip the duration argument and exec the wrapped command directly.
cmd = args[i + 1:]
os.execvp(cmd[0], cmd)
"""


def make_checkout(root):
    """Create a small git checkout with committed files plus dirty/untracked worktree changes."""
    repo = root / "checkout"
    (repo / "nested").mkdir(parents=True)
    (repo / "README.md").write_text("committed readme\n")
    (repo / "nested" / "file.txt").write_text("nested content\n")
    install = repo / "install.sh"
    install.write_text("#!/usr/bin/env bash\necho ok\n")
    install.chmod(0o755)
    git_env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "add", "README.md", "nested/file.txt", "install.sh"],
        ["git", "-c", "user.name=acme", "-c", "user.email=acme@example.com",
         "commit", "-q", "-m", "initial"],
    ):
        subprocess.run(cmd, cwd=repo, env=git_env, check=True)
    # Uncommitted edits and untracked files must not enter the archive sent to docker.
    (repo / "README.md").write_text("dirty working tree\n")
    (repo / "untracked.txt").write_text("must not be archived\n")
    return repo


def write_executable(path, content):
    path.write_text(content)
    path.chmod(0o755)


class BareInstall(unittest.TestCase):
    def run_script(self, cwd, *, docker_exit=0, docker_lines=0, wrap_timeout=False):
        tmp = tempfile.TemporaryDirectory(prefix="bare-install-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        fake_bin = root / "bin"
        record = root / "record"
        fake_bin.mkdir()
        record.mkdir()
        write_executable(fake_bin / "docker", FAKE_DOCKER)
        if wrap_timeout:
            write_executable(fake_bin / "timeout", FAKE_TIMEOUT)
        env = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            "FAKE_DOCKER_DIR": str(record),
            "FAKE_DOCKER_EXIT": str(docker_exit),
            "FAKE_DOCKER_LINES": str(docker_lines),
        }
        proc = subprocess.run([str(SCRIPT)], cwd=cwd, env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        return proc, record

    def test_runs_bare_debian_container_with_commit_archive_and_exits_0(self):
        with tempfile.TemporaryDirectory(prefix="bare-checkout-") as tmp:
            checkout = make_checkout(Path(tmp))
            proc, record = self.run_script(checkout)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        args = json.loads((record / "args.json").read_text())
        self.assertEqual(args[0], "run")
        self.assertIn(IMAGE, args)
        image_at = args.index(IMAGE)
        flags = args[1:image_at]
        self.assertEqual(flags, ["--rm", "-i"])
        for flag in flags:
            self.assertFalse(
                flag in ("-v", "--volume", "--mount", "--name")
                or flag.startswith(("-v", "--volume=", "--mount=", "--name=")),
                f"unexpected docker run flag: {flag}",
            )

        cmd = args[image_at + 1:]
        self.assertEqual(cmd[:3], ["timeout", "-k", "30"])
        self.assertTrue(cmd[3].isdigit() and int(cmd[3]) > 0, cmd[3])
        self.assertEqual(cmd[4:6], ["sh", "-c"])
        self.assertEqual(len(cmd), 7)
        inner = cmd[6]
        for token in ("sudo", "git", "ca-certificates", "~/agentkit", "install.sh", "ak --help"):
            self.assertIn(token, inner)

        with tarfile.open(record / "stdin.tar", "r:*") as archive:
            files = {
                member.name: (archive.extractfile(member).read().decode(), member.mode)
                for member in archive.getmembers()
                if member.isfile()
            }
        self.assertEqual(
            {name: data for name, (data, _) in files.items()},
            {
                "README.md": "committed readme\n",
                "nested/file.txt": "nested content\n",
                "install.sh": "#!/usr/bin/env bash\necho ok\n",
            },
        )
        self.assertTrue(files["install.sh"][1] & stat.S_IXUSR)

    def test_exits_1_and_prints_last_lines_when_docker_fails(self):
        with tempfile.TemporaryDirectory(prefix="bare-checkout-") as tmp:
            checkout = make_checkout(Path(tmp))
            for code in (1, 2, 125):
                with self.subTest(fake_exit=code):
                    proc, _ = self.run_script(checkout, docker_exit=code, docker_lines=60)
                    self.assertEqual(proc.returncode, 1)
                    combined = proc.stdout + proc.stderr
                    self.assertIn("line-060", combined)
                    self.assertNotIn("line-001", combined)

    def test_exits_1_when_git_archive_fails(self):
        with tempfile.TemporaryDirectory(prefix="bare-nongit-") as tmp:
            proc, _ = self.run_script(Path(tmp), docker_exit=0)
        self.assertEqual(proc.returncode, 1)
        self.assertTrue((proc.stdout + proc.stderr).strip())

    def test_outer_timeout_wraps_docker_and_exceeds_inner(self):
        with tempfile.TemporaryDirectory(prefix="bare-checkout-") as tmp:
            checkout = make_checkout(Path(tmp))
            proc, record = self.run_script(checkout, wrap_timeout=True)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        outer_args = json.loads((record / "timeout.json").read_text())
        docker_args = json.loads((record / "args.json").read_text())
        self.assertEqual(outer_args[:2], ["-k", "30"])
        self.assertEqual(outer_args[3:5], ["docker", "run"])
        outer_secs = int(outer_args[2])
        inner_secs = int(docker_args[docker_args.index(IMAGE) + 4])
        self.assertGreater(inner_secs, 0)
        self.assertGreater(outer_secs, inner_secs)


if __name__ == "__main__":
    unittest.main()
