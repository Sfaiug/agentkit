"""A gate suite's sandbox is a branch of its own in one repository, removed after it.

tests/sandbox_branch.py runs against one bare origin through a fake `gh`: two suites open at once,
a run off each pushes its branch and merges it, and each `close` removes only its own, writing
neither `main` nor the other suite's refs.  The repository is made once, where it is missing, and
a branch a killed suite left goes once it is older than the ceiling.  Offline.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import record, update
import sandbox_branch

GH = r'''#!/bin/bash
echo "$*" >>"$FAKE/gh.log"
case "$*" in
  "api user --jq .login") echo acme ;;
  "repo create acme/agentkit-smoke --private --add-readme")
    [ ! -e "$FAKE/origin.git" ] && git init -q -b main "$FAKE/readme" &&
      echo "# agentkit-smoke" >"$FAKE/readme/README.md" && git -C "$FAKE/readme" add -A &&
      git -C "$FAKE/readme" commit -qm init && git clone -q --bare "$FAKE/readme" "$FAKE/origin.git" ;;
  "repo clone acme/agentkit-smoke "*" -- -q") git clone -q "$FAKE/origin.git" "$4" ;;
  *) exit 97 ;;
esac
'''
# Origin's update hook names every ref written, and refuses `main`.
HOOK = '#!/bin/sh\necho "$1" >>"$FAKE/updates"\n[ "$1" != refs/heads/main ]\n'
CREATE = "repo create acme/agentkit-smoke --private --add-readme"


def ago(age):
    """The environment that dates a commit `age` seconds back."""
    when = f"@{int(time.time() - age)} +0000"
    return {"GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when}


class SandboxBranch(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="sandbox-branch-")
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name)
        (root / "bin").mkdir()
        (root / "bin/gh").write_text(GH)
        (root / "bin/gh").chmod(0o755)
        (root / "seed/tests").mkdir(parents=True)
        (root / "seed/tests/test_hello.py").write_text("from hello import hello\n")
        (root / "gitconfig").write_text("[user]\n\tname = acme\n\temail = acme@localhost\n")
        self.env = {**os.environ, "FAKE": str(root), "HOME": str(root), "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": str(root / "gitconfig"),
                    "PATH": f"{root / 'bin'}:{os.environ['PATH']}"}

    def git(self, *args, **env):
        return subprocess.run(["git", *args], cwd=self.root, env={**self.env, **env}, check=True,
                              text=True, capture_output=True).stdout.strip()

    def sandbox(self, *args):
        return subprocess.Popen([sys.executable, str(REPO / "tests/sandbox_branch.py"), *args],
                                cwd=self.root, env=self.env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def done(self, *procs):
        for proc in procs:
            out = proc.communicate(timeout=60)[0]
            self.assertEqual(proc.returncode, 0, out)

    def heads(self):
        """{ref: sha} of every branch on origin."""
        return dict(line.split() for line in self.git(
            "-C", "origin.git", "for-each-ref", "--format=%(refname) %(objectname)",
            "refs/heads/").splitlines())

    def written(self):
        return (self.root / "updates").read_text().splitlines()

    def leftover(self, name, age):
        """A branch a killed suite left on origin, its one commit `age` seconds old."""
        sha = self.git("-C", "origin.git", "commit-tree", "main^{tree}", "-m", name, **ago(age))
        self.git("-C", "origin.git", "update-ref", f"refs/heads/{name}", sha)

    def run_from(self, clone):
        """What `ak run` does from `clone`: a branch off origin/HEAD, pushed and merged into it.
        Its refs on origin: the suite's and the run's."""
        base = self.git("-C", clone, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        self.assertEqual(base, "origin/" + self.git("-C", clone, "branch", "--show-current"))
        self.git("-C", clone, "checkout", "-q", "-b", f"ak/fix-{clone}", base)
        (self.root / clone / "hello.py").write_text("def hello():\n    return 'hello'\n")
        self.git("-C", clone, "add", "-A")
        self.git("-C", clone, "commit", "-qm", "fix")
        suite = base.removeprefix("origin/")
        self.git("-C", clone, "push", "-q", "origin", f"ak/fix-{clone}", f"HEAD:refs/heads/{suite}")
        return {f"refs/heads/{suite}", f"refs/heads/ak/fix-{clone}"}

    def test_two_suites_at_once_each_remove_only_their_own(self):
        # made long ago: its `main` is as old as a dead suite's branch, and stays
        subprocess.run(["gh", *CREATE.split()], check=True,
                       env={**self.env, **ago(2 * sandbox_branch.CEILING)})
        self.leftover("suite-dead-old", sandbox_branch.CEILING + 3600)
        self.leftover("suite-dead-young", sandbox_branch.CEILING - 3600)
        (self.root / "origin.git/hooks/update").write_text(HOOK)
        (self.root / "origin.git/hooks/update").chmod(0o755)
        # a delete of `main` reaches the hook, not git's own refusal of the default branch's
        self.git("-C", "origin.git", "config", "receive.denyDeleteCurrent", "ignore")
        main = self.heads()["refs/heads/main"]
        (self.root / "gh.log").unlink()
        self.done(self.sandbox("open", "a", "seed"), self.sandbox("open", "b", "seed"))
        self.assertNotIn(CREATE, (self.root / "gh.log").read_text().splitlines())
        for clone in "ab":
            self.assertEqual(self.git("-C", clone, "ls-files"), "tests/test_hello.py")
        a, b = self.run_from("a"), self.run_from("b")
        heads = self.heads()
        self.assertEqual(set(heads), {"refs/heads/main", "refs/heads/suite-dead-young", *a, *b})
        for clone, own in (("a", a), ("b", b)):
            seen = len(self.written())
            self.done(self.sandbox("close", clone))
            self.assertEqual(set(self.written()[seen:]), own)
            heads = {ref: sha for ref, sha in heads.items() if ref not in own}
            self.assertEqual(self.heads(), heads)
        self.assertEqual(heads, {"refs/heads/main": main,
                                 "refs/heads/suite-dead-young": heads["refs/heads/suite-dead-young"]})
        self.assertNotIn("refs/heads/main", self.written())

    def test_a_missing_repository_is_made_once_with_its_main(self):
        self.done(self.sandbox("open", "a", "seed"))
        self.done(self.sandbox("open", "b", "seed"))
        self.assertEqual((self.root / "gh.log").read_text().splitlines().count(CREATE), 1)
        self.assertEqual(self.git("-C", "origin.git", "symbolic-ref", "HEAD"), "refs/heads/main")
        self.assertEqual(self.git("-C", "origin.git", "ls-tree", "--name-only", "main"), "README.md")
        self.assertEqual(len(self.heads()), 3)

    def test_the_ceiling_outlasts_every_suite_ak_runs(self):
        self.assertGreater(sandbox_branch.CEILING,
                           max(3600 * record.CEILING_HOURS, update.LIVE_CAP, update.E2E_CAP))


if __name__ == "__main__":
    unittest.main(verbosity=2)
