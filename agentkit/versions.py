"""ak's own versions: ~/agentkit swapped whole for the next one, in one step.

The tick moved ~/agentkit in place, and git moves a checkout's files before its HEAD: a git
killed in a run's worktree left a lock that failed a move half way, every tick after found the
checkout `dirty`, and nothing went live for nineteen hours.  Now each version is checked out
whole beside it, under `VERSIONS`, as a worktree of ak's repository at `REPOSITORY`, and one
rename(2) exchanges the two directories: a move cut off anywhere before that leaves ~/agentkit
as it was, and nothing after it matters to what runs.  Every path stays what it was -- the cron
line, hooks, links and the project all name ~/agentkit -- and the version swapped out waits
under `VERSIONS` until no process uses it.  ~/agentkit is ak's own, never edited: what git
finds changed or added in a version swapped out keeps it there all the same.  Each version's
record in the repository is locked: a `git worktree prune` that could not see ~/agentkit would
take it, and without it no git works there and nothing moves it again.

A clone at ~/agentkit is adopted at its first move, once it is main as origin left it
(`update.left_as_is`): its repository goes to `REPOSITORY`, a link left in its place, and each
worktree added from it is pointed there, so none breaks when the clone is swapped out.  Each
step is one rename or one write, and one cut off is done again by the next move.
"""

import ctypes
import errno
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from . import config, retention

REPOSITORY = "agentkit.git"     # in config.OWN: ak's repository, each version a worktree of it
VERSIONS = "versions"           # in config.OWN: a version checked out to go live, or swapped out
CAP = 30 * 60                   # one git step, as update.STEP_CAP
AT_FDCWD = -100                 # Linux's, for renameat2
RENAME_EXCHANGE = 2             # renameat2's flag on Linux
RENAME_SWAP = 2                 # renamex_np's flag on macOS
LOCKED = ("--reason", "a version of ak's")     # each version's record, kept from any prune


def repository():
    return config.HOME / REPOSITORY


def git(where, *args):
    """(exit code, what git said) of one git command at `where`, looking for no repository
    above it; 1 when it could not run."""
    env = {**config.child_env(),
           "GIT_CEILING_DIRECTORIES": os.path.dirname(os.path.abspath(where))}
    try:
        proc = subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True,
                              timeout=CAP, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def owned(live):
    """Is `live` a version checked out here, rather than somebody's clone?"""
    try:
        named = (live / ".git").read_text().removeprefix("gitdir: ").strip()
    except OSError:         # a repository of its own, a link to one, or none
        return False
    return Path(live, named).resolve().parent.parent == repository().resolve()


def finish(live):
    """The link an adoption cut off between its two renames left out, put in: until then git
    finds no repository at `live`, and nothing could move it.  The version live locked: the code
    before the lock put it live without one."""
    if repository().is_dir() and not os.path.lexists(live / ".git"):
        (live / ".git").symlink_to(repository())
    if owned(live):
        git(repository(), "worktree", "lock", *LOCKED, str(live))     # once locked, a refusal


def adopt(live):
    """Make the clone at `live` one a version can be swapped in for: "" once it is, or why not."""
    repo, dot = repository(), live / ".git"
    if owned(live):
        return ""
    if not os.path.lexists(repo):
        if dot.is_symlink() or not dot.is_dir():
            return f"{dot} is no repository of its own"
        try:
            dot.rename(repo)
        except OSError as exc:
            return f"{dot} could not move to {repo}: {exc}"
    finish(live)
    if dot.resolve() != repo.resolve():
        return f"{dot} is not {repo}, which is there already"
    # a worktree added from the clone names its repository by the clone's path, which goes
    # with the clone: each is pointed at where the repository is now, as git itself would
    for admin in (repo / "worktrees").glob("*"):
        admin = admin.resolve()
        try:
            gitfile = Path(admin, (admin / "gitdir").read_text().strip())
            named = Path(gitfile.parent, gitfile.read_text().removeprefix("gitdir: ").strip())
            if named != admin and named.resolve() == admin:
                gitfile.write_text(f"gitdir: {admin}\n")
        except OSError:
            continue        # gone, or none of this repository's: `git worktree prune`'s
    return ""


def exchange(one, other):
    """Swap the directories at `one` and `other` in one rename(2)."""
    libc = ctypes.CDLL(None, use_errno=True)
    paths = os.fsencode(one), os.fsencode(other)
    if hasattr(libc, "renameat2"):
        failed = libc.renameat2(AT_FDCWD, paths[0], AT_FDCWD, paths[1], RENAME_EXCHANGE)
    elif hasattr(libc, "renamex_np"):
        failed = libc.renamex_np(*paths, RENAME_SWAP)
    else:
        raise OSError(errno.ENOSYS, "no rename here swaps two directories", str(one))
    if failed:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(one), None, str(other))


def remove(path):
    """A version under `VERSIONS` and git's record of it, gone."""
    if git(repository(), "worktree", "remove", "--force", "--force", str(path))[0]:
        if retention.safe(path):        # never through a link
            shutil.rmtree(path, ignore_errors=True)
        git(repository(), "worktree", "unlock", str(path))
        git(repository(), "worktree", "prune")


def repair(*paths):
    """Did each version's record of where it is come out right?  A swap leaves the two crossed."""
    # the clone adopted is no worktree of the repository, and git would fail the lot over it
    return git(repository(), "worktree", "repair", *(str(path) for path in paths
                                                     if (path / ".git").is_file()))[0] == 0


def tidy(live):
    """Each version under `VERSIONS` no process uses, and that holds nothing git finds changed
    or added in it, gone.  Each worktree's record of where it is is put right first: one swap
    cut off before it left the two crossed, and git would remove the wrong one's."""
    from . import gc
    try:
        found = sorted((config.HOME / VERSIONS).iterdir())
    except OSError:
        return
    if not repair(live, *found):
        return      # a record still crossed would have git remove the live one's
    held = gc.tmp_processes()[0]
    for path in found:
        code, changes = git(path, "--no-optional-locks", "status", "--porcelain")
        # a checkout cut off part way lists only what it never wrote: nobody's work; a status
        # git could not read proves nothing
        kept = code != 0 or any(line[:2] not in (" D", "D ") for line in changes.splitlines())
        if not kept and not retention.busy(path.resolve(), held):
            remove(path)


def switch(live, commit):
    """Put `commit` live at `live`, swapped in whole: "" once it is or there is nothing to move,
    else why not, `live` then as it was.  Forward only, as a fast-forward went: a commit `live`
    already has moves nothing, and one beside it is refused."""
    live = live.resolve()       # a link at ~/agentkit stays, and what it names is swapped
    if git(live, "merge-base", "--is-ancestor", commit, "HEAD")[0] == 0:
        return ""
    if git(live, "merge-base", "--is-ancestor", "HEAD", commit)[0] != 0:
        return f"{commit[:12]} is not ahead of what {live} has"
    why = adopt(live)
    if why:
        return why
    tidy(live)
    (config.HOME / VERSIONS).mkdir(parents=True, exist_ok=True)
    new = Path(tempfile.mkdtemp(prefix=f"{commit[:12]}.", dir=config.HOME / VERSIONS))
    code, said = git(repository(), "worktree", "add", "--quiet", "--detach", "--lock", *LOCKED,
                     str(new), commit)
    if code:
        remove(new)
        return f"{commit[:12]} could not be checked out in {new}: {said}"
    try:
        new.chmod(live.stat().st_mode & 0o7777)    # mkdtemp's is the owner's alone
        exchange(live, new)
    except OSError as exc:
        remove(new)
        return f"{new} could not be swapped in for {live}: {exc}"
    repair(live, new)
    return ""
