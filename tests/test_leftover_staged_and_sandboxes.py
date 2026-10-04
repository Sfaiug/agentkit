"""Staged leftovers never wedge the done-when; every in-checkout test sandbox is swept. Offline."""

import ast
import os
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import run

# the ways a test names the top of the checkout it runs in
CHECKOUT = {"REPO", "str(REPO)", "config.REPO"}
# a suite that points TMPDIR at the checkout itself puts every temporary file there unnamed
CHECKOUT_TMPDIR = re.compile(r"""(?<!\w)TMPDIR['"]?\s*[:=]\s*(?:"?\$REPO"?|"?/proc/\$\$/cwd"?"""
                             r"""|str\((?:config\.)?REPO\))\s*(?:$|[,})])""", re.M)


def suites():
    return sorted((REPO / "tests").glob("*.py")) + sorted((REPO / "tests").glob("*.sh"))


def python_sources():
    """(file, line offset, source) of every test's Python, the shell suites' heredocs included."""
    for path in suites():
        text = path.read_text()
        if path.suffix == ".py":
            yield path.name, 0, text
            continue
        for match in re.finditer(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\s*\1\n", text, re.S):
            try:
                ast.parse(match.group(2))
            except SyntaxError:
                continue
            yield path.name, text.count("\n", 0, match.start(2)), match.group(2)


def checkout_sandboxes():
    """(site, dir, prefix) of every temporary file or directory a test makes inside the checkout."""
    found = []
    for name, offset, source in python_sources():
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            keywords = {k.arg: k.value for k in node.keywords}
            where = ast.unparse(keywords["dir"]) if "dir" in keywords else ""
            if "REPO" not in where:
                continue
            prefix = keywords.get("prefix")
            found.append((f"{name}:{offset + node.lineno}", where,
                          prefix.value if isinstance(prefix, ast.Constant) else None))
    for path in suites():
        for number, line in enumerate(path.read_text().splitlines(), 1):
            for prefix in re.findall(r'mktemp[^"]*"\$REPO/([^"/]*?)X+"', line):
                found.append((f"{path.name}:{number}", "REPO", prefix))
    return found


class LeftoverStagedAndSandboxes(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-leftover-staged-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ, {"HOME": str(self.root),
                                      "GIT_CONFIG_GLOBAL": os.devnull,
                                      "GIT_CONFIG_NOSYSTEM": "1",
                                      "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"})
        env.start()
        self.addCleanup(env.stop)
        for key in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(key, None)
        self.logs = []

    def repo(self):
        repo = Path(tempfile.mkdtemp(dir=self.root))
        run.git(repo, "init", "-b", "main")
        run.git(repo, "config", "user.name", "fixture")
        run.git(repo, "config", "user.email", "fixture@localhost")
        (repo / "app.py").write_text("value = 1\n")
        run.git(repo, "add", ".")
        run.git(repo, "commit", "-m", "baseline")
        return repo

    def committed(self, repo):
        return run.git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r",
                       "HEAD").splitlines()

    def done_when(self, repo):
        round_dir = Path(tempfile.mkdtemp(dir=self.root))
        # a run directory without regression.sh: no fix run's check to make
        lp = SimpleNamespace(wt=repo, scratch=False, state={}, every=["true"],
                             base_sha=run.git(repo, "rev-parse", "HEAD"),
                             artifacts=set(), log=self.logs.append,
                             step=lambda *_a, **_kw: None, round_dir=round_dir,
                             done_when_limit=60, turn_limit=60, run_dir=self.root)
        return run.verify_work(lp)

    def test_staged_dependency_link_is_unstaged(self):
        repo = self.repo()
        (repo / "venv").symlink_to(self.root)
        (repo / "app.py").write_text("value = 2\n")
        run.git(repo, "add", "-A")
        ok, text = self.done_when(repo)
        self.assertTrue(ok, text)
        self.assertEqual(self.committed(repo), ["app.py"])
        self.assertEqual(run.git(repo, "status", "--porcelain"), "?? venv")
        self.assertTrue(any("venv" in line and "unstaged" in line for line in self.logs),
                        self.logs)

    def test_staged_dependency_deletion_is_committed(self):
        repo = self.repo()
        (repo / "venv").symlink_to(self.root)
        run.git(repo, "add", "venv")
        run.git(repo, "commit", "-m", "existing environment link")
        run.git(repo, "rm", "--cached", "venv")
        (repo / "app.py").write_text("value = 2\n")
        ok, text = self.done_when(repo)
        self.assertTrue(ok, text)
        self.assertEqual(self.committed(repo), ["app.py", "venv"])
        self.assertEqual(run.git(repo, "status", "--porcelain"), "?? venv")
        self.assertTrue(any(line.startswith("WARN committed") and "venv" in line
                            for line in self.logs), self.logs)

    def test_other_staged_work_stays_staged(self):
        repo = self.repo()
        (repo / "venv").symlink_to(self.root)
        run.git(repo, "add", "venv")
        run.git(repo, "commit", "-m", "existing environment link")
        run.git(repo, "rm", "--cached", "venv")
        (repo / "app.py").write_text("value = 2\n")
        run.git(repo, "add", "app.py")
        (repo / "app.py").write_text("value = 1\n")
        (repo / "feature.py").write_text("new = True\n")
        ok, text = self.done_when(repo)
        self.assertTrue(ok, text)
        self.assertEqual(self.committed(repo), ["feature.py", "venv"])
        self.assertEqual(run.git(repo, "show", ":app.py"), "value = 2")

    def test_every_checkout_sandbox_is_a_named_top_level_one(self):
        sites = checkout_sandboxes()
        self.assertGreater(len(sites), 100)
        self.assertEqual([site for site in sites if site[1] not in CHECKOUT or not site[2]], [])

    def test_no_suite_points_tmpdir_at_the_checkout(self):
        sites = [f"{path.name}:{path.read_text().count(chr(10), 0, match.start()) + 1}"
                 for path in suites() for match in CHECKOUT_TMPDIR.finditer(path.read_text())]
        self.assertEqual(sites, [])

    def test_every_checkout_sandbox_is_swept_and_never_committed(self):
        repo = self.repo()
        names = sorted({prefix + "k1ll3d" for _, _, prefix in checkout_sandboxes() if prefix})
        for name in names:
            (repo / name).mkdir()
            (repo / name / "tool").write_text("stub\n")
        (repo / "app.py").write_text("value = 2\n")
        run.commit_leftovers(repo, self.logs.append, set())
        self.assertEqual(self.committed(repo), ["app.py"])
        run.sweep_sandboxes(repo, self.logs.append)
        self.assertEqual([name for name in names if (repo / name).exists()], [])

    def test_every_checkout_sandbox_is_ignored_by_the_checkouts_gitignore(self):
        repo = self.repo()
        (repo / ".gitignore").write_text((REPO / ".gitignore").read_text())
        paths = sorted({prefix + "k1ll3d/tool" for _, _, prefix in checkout_sandboxes()
                        if prefix})
        ignored = run.git(repo, "check-ignore", "--", *paths, check=False).splitlines()
        self.assertEqual(sorted(set(paths) - set(ignored)), [])


if __name__ == "__main__":
    unittest.main()
