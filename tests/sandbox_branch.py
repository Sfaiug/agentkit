"""A gate suite's sandbox on GitHub: a branch of its own in `<login>/agentkit-smoke`.

`open <clone> <seed>` clones that repository into <clone> -- making it, with its `main`, only
where it is missing -- removes the branches killed suites left there (CEILING), and pushes the
files under <seed> as a new root commit on a branch of the suite's own, which the clone's
`origin/HEAD` then names: a run from the clone bases on that branch and merges into it, as a
fresh clone's run does with the default branch.  `close <clone>` removes every branch on origin
holding that commit: the suite's own and its run's.  No suite writes `main` or another live
suite's branch, so suites never wait for one another, and none needs a scope beyond today's.

    python3 tests/sandbox_branch.py open <clone> <seed>
    python3 tests/sandbox_branch.py close <clone>
"""

import secrets
import shutil
import subprocess
import sys
import time

NAME = "agentkit-smoke"
# A suite killed before `close` leaves its branches to a later `open`, which removes one once its
# newest commit is older than this.  A live suite's branches are younger than the suite, its seed
# committed at `open`, and ak ends every suite sooner: the landing suite at record.CEILING_HOURS,
# tests/live.sh at update.LIVE_CAP, tests/e2e-fresh.sh at update.E2E_CAP.  A day is four times
# the longest, and leaves a suite started by hand a working day.
CEILING = 24 * 3600
SEED = "sandbox.seed"   # the clone's own git config: the commit its suite's branches hold


def git(clone, *args, check=True):
    return subprocess.run(["git", "-C", str(clone), *args], check=check, text=True,
                          stdout=subprocess.PIPE).stdout.strip()


def branches(clone, *only):
    """(name, sha, committed) of each branch origin had at the last fetch."""
    lines = git(clone, "for-each-ref", *only, "--format=%(refname:strip=3) %(objectname) "
                "%(committerdate:unix)", "refs/remotes/origin/").splitlines()
    return [(name, sha, int(at)) for name, sha, at in map(str.split, lines) if name != "HEAD"]


def delete(clone, found):
    """Delete those branches on origin, each only while origin still has it where it was seen."""
    if not found:
        return 0
    leases = [f"--force-with-lease=refs/heads/{name}:{sha}" for name, sha, _ in found]
    return subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", *leases,
                           *(f":refs/heads/{name}" for name, _, _ in found)]).returncode


def open_branch(clone, seed):
    login = subprocess.run(["gh", "api", "user", "--jq", ".login"], check=True, text=True,
                           stdout=subprocess.PIPE).stdout.strip()
    repo = f"{login}/{NAME}"
    clone_it = ["gh", "repo", "clone", repo, str(clone), "--", "-q"]
    if subprocess.run(clone_it).returncode:
        # Another suite may make it first; the clone tells.
        subprocess.run(["gh", "repo", "create", repo, "--private"])
        subprocess.run(clone_it, check=True)
    git(clone, "config", "user.email", "sandbox@localhost")
    git(clone, "config", "user.name", "sandbox")
    if not branches(clone):
        # Just made, and `main` written here alone: pushed before any suite's branch, it is the
        # default GitHub makes, whatever the account names its own.  Another suite making it at
        # once may push its `main` first, and either serves.
        tree = git(clone, "hash-object", "-w", "-t", "tree", "/dev/null")
        git(clone, "push", "-q", "origin", git(clone, "commit-tree", tree, "-m", NAME) +
            ":refs/heads/main", check=False)
        git(clone, "ls-remote", "--exit-code", "origin", "refs/heads/main")
    old = time.time() - CEILING
    # Another suite may delete one first: its lease then fails that one alone, and nothing is lost.
    delete(clone, [b for b in branches(clone) if b[0] != "main" and b[2] < old])
    # random, not a pid: a container's suite has a pid space of its own
    branch = f"suite-{secrets.token_hex(6)}"
    git(clone, "switch", "-q", "--orphan", branch)
    shutil.copytree(seed, clone, dirs_exist_ok=True)
    git(clone, "add", "-A")
    # its branch's name in it: two suites' seeds of the same files in the same second are
    # otherwise one commit, and each suite's `close` would take the other's branches too
    git(clone, "commit", "-qm", f"seed {branch}")
    git(clone, "config", SEED, git(clone, "rev-parse", "HEAD"))
    git(clone, "push", "-q", "-u", "origin", branch)
    git(clone, "remote", "set-head", "origin", branch)
    print(f"{repo}: {branch}")
    return 0


def close_branch(clone):
    seed = git(clone, "config", SEED, check=False)
    if not seed:
        return 0     # nothing of this suite's ever reached origin
    git(clone, "fetch", "-q", "--prune", "origin")
    return delete(clone, branches(clone, f"--contains={seed}"))


if __name__ == "__main__":
    sys.exit({"open": open_branch, "close": close_branch}[sys.argv[1]](*sys.argv[2:]))
