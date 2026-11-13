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

A move is final only once a tick of the version it put live completes with its install.sh passed
(`final`): until then the version it replaced is kept (`kept`) and nothing else moves, for the
way back (`back`) to run from.

A clone at ~/agentkit is adopted at its first move, once it is main as origin left it
(`update.left_as_is`): its repository goes to `REPOSITORY`, a link left in its place, and each
worktree added from it is pointed there, so none breaks when the clone is swapped out.  Each
step is one rename or one write, and one cut off is done again by the next move.
"""

import ctypes
from contextlib import contextmanager
import errno
import fcntl
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

from . import config, retention

REPOSITORY = "agentkit.git"     # in config.OWN: ak's repository, each version a worktree of it
VERSIONS = "versions"           # in config.OWN: a version checked out to go live, or swapped out
CAP = 30 * 60                   # one git step or a version's prepare, as update.STEP_CAP
AT_FDCWD = -100                 # Linux's, for renameat2
RENAME_EXCHANGE = 2             # renameat2's flag on Linux
RENAME_SWAP = 2                 # renamex_np's flag on macOS
LOCKED = "a version of ak's"   # why each version's record is locked, kept from any prune
NOT_RUN = (":!go", ":!tests", ":!docs", ":!*.md")   # what no running process holds
CODE_ENV = "AK_RUN_CODE"        # the checkout a run's processes run: `enter`'s
KEEP = "keep/ak"                # under config.TMP: a link to the bin/ak the last move swapped out


def repository():
    return config.HOME / REPOSITORY


@contextmanager
def holding():
    directory = config.HOME / VERSIONS
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield directory
    finally:
        os.close(fd)


@contextmanager
def checkout(code=None):
    """A stable code path; only the swappable install needs a shared commit checkout."""
    source = Path.home() / "agentkit"
    path = Path(code) if code else config.REPO
    if path != source.resolve() and path.parent != config.HOME / VERSIONS:
        yield path
        return
    with holding() as directory:
        if not (source / "bin" / "ak").is_file():
            source = config.REPO
        elif why := adopt(source):
            raise config.Error(why)
        commit = path.name if code and path.parent == directory else "HEAD"
        code, sha = git(source, "rev-parse", "--verify", f"{commit}^{{commit}}")
        if code:
            raise config.Error(f"cannot read ak version: {sha}")
        path = directory / sha
        if not path.exists():
            new = Path(tempfile.mkdtemp(prefix=f"{sha[:12]}.", dir=directory))
            code, said = git(source, "clone", "--quiet", "--shared", "--no-checkout", str(source), str(new))
            if not code:
                code, said = git(new, "checkout", "--quiet", "--detach", sha)
            if code:
                raise config.Error(f"cannot check out ak {sha[:12]}: {said}")
            new.rename(path)
        yield path


def keep_link():
    """Where a move keeps the version it replaced; None on a client, which runs no tick that could
    make its moves final, so keeps nothing, a link a server left it included."""
    return None if config.server_alias() else config.TMP / KEEP


def kept():
    """The version the last move replaced, while that move is not final: the folder of the bin/ak
    `keep_link` names, else None."""
    link = keep_link()
    try:
        return Path(os.readlink(link)).parents[1] if link else None
    except OSError:
        return None


def final(ended, completed=True):
    """A tick's end at `ended`.  Only a tick that began from the folder at ~/agentkit now proves
    that version runs, and one that `completed` makes the move that put it live final, once no
    install.sh is owed (`update.PENDING`): a version that never installs is put back.  One that
    began in the version the move replaced, the tick that made it among them, sets the link's
    time to its end however it ends: no tick of the version live runs while it holds the tick
    lock, so `back` counts its hour from there."""
    from . import update     # here, not at the top: it imports this module
    link = keep_link()
    if not (link and config.BEGAN and os.path.lexists(link)):
        return
    with holding():     # as `switch` holds it from a move's link to its exchange
        replaced = kept()
        try:
            if replaced and os.path.samestat(config.BEGAN, os.stat(replaced)):
                os.utime(link, (ended, ended), follow_symlinks=False)
            elif (completed and os.path.samestat(config.BEGAN, os.stat(update.agentkit_dir()))
                    and not (config.STATE / update.PENDING).exists()):
                link.unlink(missing_ok=True)
        except OSError:
            pass        # no ~/agentkit: nothing of it ran


def enter(path):
    """All imports and child commands come from the same checkout after this exec."""
    os.environ[CODE_ENV] = str(path)
    os.environ["PATH"] = os.pathsep.join((str(path / "bin"), os.environ.get("PATH", os.defpath)))
    if path != config.REPO:
        sys.stdout.flush()
        sys.stderr.flush()
        os.execv(sys.executable, [sys.executable, str(path / "bin" / "ak"), *sys.argv[1:]])


def live():
    """The checkout a seat runs, and what its server runs for it: ~/agentkit, whichever process
    starts it -- a run on a version under `VERSIONS`, a worktree, another clone -- as a seat
    outlives them all; this one where there is no ~/agentkit."""
    from . import update     # here, not at the top: it imports this module
    return update.agentkit_dir() if update.agentkit_dir().is_dir() else config.REPO


def unpinned(env):
    """`env` without what `enter` put in it, for what outlives this process: no version's `bin`
    on its PATH, whose `ak` would run that version, and no `CODE_ENV`."""
    kept = {key: value for key, value in env.items() if key != CODE_ENV}
    if "PATH" in kept:
        kept["PATH"] = os.pathsep.join(entry for entry in kept["PATH"].split(os.pathsep)
                                       if Path(entry).parent.parent != config.HOME / VERSIONS)
    return kept


def dispatch(argv):
    from . import record, worker
    if argv[:2] == ["run", "--lander"]:
        with checkout(config.REPO) as path:
            enter(path)
    elif (argv[:1] == ["hand-in"] and os.environ.get(worker.RUN_MARKER)
            and (path := os.environ.get(CODE_ENV))):
        enter(Path(path))
    elif len(argv) >= 3 and argv[:2] in (["run", "resume"], ["run", "merge"]):
        state = record.read_state(config.RUNS / argv[2]) or {}
        if code := state.get("ak_checkout"):
            with checkout(code) as path:
                enter(path)
    if config.REPO.parent == config.HOME / VERSIONS:
        enter(config.REPO)


def git(where, *args):
    """(exit code, what git said) of one git command at `where`, looking for no repository
    above it; 1 when it could not run."""
    return run(["git", "-C", str(where), *args],
               GIT_CEILING_DIRECTORIES=os.path.dirname(os.path.abspath(where)))


def run(cmd, cwd=None, **env):
    """(exit code, what `cmd` said); 1 when it could not run or ran past `CAP`.  All it started
    stops with it, past the cap or with this process cut off: a build left running would go on
    writing in the version removed for it, its own session keeping it from any ^C."""
    try:
        with subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, start_new_session=True, encoding="utf-8",
                              errors="replace", env={**config.child_env(), **env}) as proc:
            try:
                out, err = proc.communicate(timeout=CAP)
            except subprocess.TimeoutExpired as exc:
                return 1, str(exc)
            finally:
                if proc.returncode is None:     # not waited for, so its group is still its own
                    os.killpg(proc.pid, signal.SIGKILL)
    except OSError as exc:
        return 1, str(exc)
    return proc.returncode, (out + err).strip()


def owned(live):
    """git's record of `live`, the one its .git names, when it is a version checked out here;
    None for somebody's clone."""
    try:
        named = (live / ".git").read_text().removeprefix("gitdir: ").strip()
    except OSError:         # a repository of its own, a link to one, or none
        return None
    record = Path(live, named).resolve()
    return record if record.parent.parent == repository().resolve() else None


def finish(live):
    """The link an adoption cut off between its two renames left out, put in: until then git
    finds no repository at `live`, and nothing could move it.  The version live locked: the code
    before the lock put it live without one."""
    if repository().is_dir() and not os.path.lexists(live / ".git"):
        (live / ".git").symlink_to(repository())
    record = owned(live)
    if record and record.is_dir():      # a record gone, no lock brings back
        # as `git worktree lock` writes it, which finds a record by the path held in it: a swap
        # cut off before its repair leaves that path the version swapped out's
        (record / "locked").write_text(f"{LOCKED}\n")


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
    """Each version under `VERSIONS` no process uses or move keeps (`kept`), and that holds
    nothing git finds changed or added in it, gone.  Each worktree's record of where it is is put
    right first: one swap cut off before it left the two crossed, and git would remove the wrong
    one's."""
    with holding():
        _tidy(live)


def _tidy(live):
    from . import gc
    try:
        found = sorted((config.HOME / VERSIONS).iterdir())
    except OSError:
        return
    if not repair(live, *found):
        return      # a record still crossed would have git remove the live one's
    held, keep = gc.tmp_processes()[0], kept()
    for path in found:
        code, changes = git(path, "--no-optional-locks", "status", "--porcelain")
        # a checkout cut off part way lists only what it never wrote: nobody's work; a status
        # git could not read proves nothing
        changed = code != 0 or any(line[:2] not in (" D", "D ") for line in changes.splitlines())
        if not changed and path != keep and not retention.busy(path.resolve(), held):
            remove(path)


def keep_times(live, new, commit):
    """A landing that brings nothing a process runs keeps the modules' times, so no process open
    on them finds its code moved (`update.code_moved`) and restarts for nothing."""
    if git(live, "diff", "--quiet", "HEAD", commit, "--", ".", *NOT_RUN)[0]:
        return
    try:
        for path in (new / "agentkit").glob("*.py"):
            old = (live / "agentkit" / path.name).stat()
            os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    except OSError:
        pass            # a time not kept costs one restart


def switch(live, commit):
    """Put `commit` live at `live`, swapped in whole once its `install.sh --prepare` passed: ""
    once it is or there is nothing to move, else why not, `live` then as it was.  Forward only,
    as a fast-forward went: a commit `live` already has moves nothing, and one beside it is
    refused."""
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
    code, said = git(repository(), "worktree", "add", "--quiet", "--detach", "--lock", "--reason",
                     LOCKED, str(new), commit)
    if code:
        remove(new)
        return f"{commit[:12]} could not be checked out in {new}: {said}"
    # every seat's hooks and the tick run ~/agentkit/bin/ak, so a version goes live ready to run:
    # Go's is built from go/, which git does not track
    code, said = run([str(new / "install.sh"), "--prepare"], new)
    if code:
        remove(new)
        return f"{commit[:12]} could not be prepared in {new}: {said or f'exit {code}'}"
    keep = keep_link()
    try:
        new.chmod(live.stat().st_mode & 0o7777)    # mkdtemp's is the owner's alone
        keep_times(live, new, commit)
        with holding():     # a tick of the version replaced, completing between them, would take it
            if keep:
                # before the exchange, which leaves the version replaced at `new`: a move cut
                # off right after it is kept too
                keep.parent.mkdir(parents=True, exist_ok=True)
                keep.symlink_to(new / "bin" / "ak")
            exchange(live, new)
    except OSError as exc:
        if kept() == new:       # nothing was replaced
            keep.unlink(missing_ok=True)
        remove(new)
        return f"{new} could not be swapped in for {live}: {exc}"
    repair(live, new)
    return ""
