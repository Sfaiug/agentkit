"""`ak lease`: one turn creating the lease on ak's remote where the remote holds none, and
swapping a new value in where it holds this machine's own.  This hides where the lease is, how it
is read and written, what a machine keeps of the values it made, whether the lease is its own
(`ours`), and what a machine watching another's lease keeps of the value it reads and when it
sends a standby's swap of its own or a still home's removal of the lease (`watch`).

The lease says which machine is ak's home: `REF` in the repository at the push address of ak's
checkout.  It changes only by compare-and-swap, so two machines never both create it and a swap
replaces only the value its turn read.  The checkout is asked that address and nothing else.  A
repository of the lease's own, with no setting but git's defaults and the user's, reads and writes
there, so no setting of the checkout makes the read and the write differ or writes into it.  Each
value made is a ref under `MADE` there, named for its stamp (`pair_clock`).  A read asks git for
its housekeeping there, so what git removes of the values no ref names, and when, is git's.  git
writes a ref whole or not at all, and a value is kept before it is sent, so a create the remote
refused or never answered sends that same value on the next turn.

One turn at a time makes, reads and writes that repository, a standby's watch counted as one, so
what a turn read is still what is kept when it writes: two at once would read one lease, and the
one whose swap lost would delete the ref of the value that won, so the next turn would read this
machine's own lease as another's.  The lock is on the folder the repository is in, which mkdir
makes whole or finds there before anything of git's; a turn that finds it taken ends.  The kernel
lets it go when the process ends, however it ends, and the folder is the lock, so there is no file
of the lease's own.

A lease is this machine's own where a ref git lists under `MADE` names its value: those refs are
the one record of what this machine made, so one that lost the ref of its lease reads it as
another's.  Another's ends the claim: the turn keeps none of the values made, makes and writes
nothing, so this machine has no proof (`proof_age`) till a turn makes a value again, where the
remote holds no lease.  Every turn that finds its own keeps of what it made only that value, then
makes a new one and swaps it in, so the lease changes as often as turns are taken; a swap the
remote refused or never answered is not sent again, as the next turn makes another.
"""

import contextlib
import fcntl
import functools
import os
import re
import secrets
import subprocess

from . import config, gitcall, pair_clock, update

REF = "refs/agentkit/home"
MADE = "refs/made/"
# A standby's record of the lease it watches (`watch`): one ref, which git writes whole or not at
# all, so no pass meets a set of them to make consistent.
SEEN = "refs/seen"
REMOTE = 45     # seconds for each call that reaches the remote
# How long a watch reads one lease unchanged, by the younger of its clocks, before it sends a
# standby's swap or a home's removal: twice `pause.STALE`, so the machine whose lease it is has
# stood still a while by then.  A number, as `pause` imports this module.
STILL = 20 * 60
VALUE = rb"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})"
# One address, of printable bytes without a space, that is no option: the one string git
# resolved, which the read and the write each take whole.
ADDRESS = re.compile(rb"(?!-)[!-~]+\n")


def main(argv):
    if argv:
        raise config.Error("usage: ak lease")
    try:
        _turn()
    # a git that did not exit 0 (CalledProcessError) among them, or one past its bound: whatever
    # ended the turn, the next turn's read says what the remote holds
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 0


def _turn():
    # a home's client, a standby among them, takes none: the lease it made would be its own while
    # its home lives
    if config.server_alias():
        return
    git, env = _checkout()
    address = _address(git)
    _locked(lambda: _alone(git, env, address))


def _alone(git, env, address):
    """The turn at the lease at `address`, with no other under way."""
    read = _read(git, env, address)
    if read:
        kept = _kept(git)
        # this machine's own where a ref names it.  What is kept shrinks to the value read and the
        # one made next, or would grow a ref a turn; the value read stays, as it is the proof
        # (`proof_age`) till a turn reads the next.  Of another's, none is kept: the remote has
        # said this machine is not the home.
        own = any(value == read for value, _ in kept)
        for value, name in kept:
            if value != read:
                git("update-ref", "-d", name, value, check=False)
        if own:
            _swap(git, address, read, pair_clock.now())
        return
    made = ("for-each-ref", "--count=1", "--format=%(objectname)", MADE)
    if not git(*made):
        _make(git, pair_clock.now())
    value = git(*made)
    if re.fullmatch(VALUE + b"\n", value):
        git("push", address, f"{value[:-1].decode()}:{REF}", f"--force-with-lease={REF}:",
            timeout=REMOTE, check=False)


def ours():
    """The value of the lease on ak's remote where it is this machine's own, as a turn tells it:
    under the turn's lock, the lease read as a turn reads it and a ref under MADE naming the value
    read.  False where another turn holds the lock, no lease is read, or anything is raised.  It
    writes no ref."""
    try:
        git, env = _checkout()
        address = _address(git)
        return _locked(lambda: (read := _read(git, env, address))
                       and any(value == read for value, _ in _kept(git)) and read) or False
    except Exception:   # whatever it was, no lease is known to be this machine's
        return False


def _kept(git):
    """Each value this machine keeps and the name of its ref, by `git` in the lease's
    repository."""
    return [line.split(b" ", 1) for line in
            git("for-each-ref", "--format=%(objectname) %(refname)", MADE).splitlines()]


def _swap(git, address, read, stamp):
    """A new value, made and kept for `stamp` (`_make`), sent to `address` as a swap from `read`:
    its exit is not read, as the next read says what the remote holds."""
    value = _make(git, stamp)
    git("push", address, f"{value.decode()}:{REF}",
        f"--force-with-lease={REF}:{read.decode()}", timeout=REMOTE, check=False)


def _make(git, stamp):
    """A new value, kept under the name for `stamp` before it is sent, by `git` in the lease's
    repository."""
    # its own message, as every other part of it is any machine's
    value = git("commit-tree", git("mktree").strip(), "-m", secrets.token_hex(16),
                own=gitcall.STAMP).strip()
    # only as a name no ref holds, so no value kept is replaced
    git("update-ref", _named(stamp), value, "")
    return value


def _unlinked(git, name):
    """Whether `name` is no symbolic ref, by `git` in the lease's repository: update-ref writes
    through one to the ref it names, there or not.  Only `symbolic-ref -q` exiting 1 says so, for
    a plain ref, which update-ref's empty old value refuses, or none; it exits 0 at a symbolic ref
    and 128 at one it cannot follow, a chain too long among them.  The lock keeps the name as it
    is till the write."""
    try:
        git("symbolic-ref", "-q", name)
    except subprocess.CalledProcessError as error:
        return error.returncode == 1
    return False


def _taken(git, address, read, stamp):
    """A standby's swap from `read`, as a turn sends one (`_swap`), its value kept for `stamp`
    where no ref holds the name."""
    if _unlinked(git, _named(stamp)):
        _swap(git, address, read, stamp)


def removal(git, address, read, _stamp):
    """The lease at `address` removed as a swap from `read`, by `git` in the lease's repository: a
    home's in a standby's swap's place, which makes no value and keeps none, so the next turn
    finds the remote holding no lease and creates one, as a home does.  Its exit is not read, as
    the next read says what the remote holds."""
    git("push", address, f":{REF}", f"--force-with-lease={REF}:{read.decode()}",
        timeout=REMOTE, check=False)


def watch(takes, sends=_taken):
    """A watch of the lease another machine holds, a standby's or a home's that keeps no value, at
    each pass: SEEN at a commit made here whose message is the value read and the stamp of the
    pass that first read it (`_seen`), the lease read as a turn reads it, under its lock.  A value
    SEEN holds with a stamp of this boot leaves it as it is, and once that stamp is STILL old by
    `age_at_least`, where `takes` says this machine may take the lease, `sends` is sent from it
    with this pass's stamp, a standby's swap (`_taken`) unless named; any other value read puts it
    at a commit of that value and this pass's stamp, as a stamp of another boot counts for nothing;
    whatever else is met once the lock is held, no lease among it, removes it.  Each is one
    update-ref of SEEN at most, which git does whole or not at all, and what it refused stays as it
    was: a home writes no value twice, so a record of an older value matches no later read.  Where
    another turn holds the lock, or the lease's folder cannot be made or opened, none of them.
    Nothing is fetched from the remote, nor written to it but what `sends` sends, and whatever the
    watch meets is dropped unsaid."""
    with contextlib.suppress(Exception):
        _locked(lambda: _watched(takes, sends))


def _watched(takes, sends):
    """The watch, with no turn under way."""
    env, made = {}, None
    try:
        git, env = _checkout()
        address = _address(git)
        read = _read(git, env, address)
        # after the read: a stamp before it may be older than the value read
        stamp = pair_clock.now()
        seen = read and _seen(git)
        if seen and seen[0] == read and seen[1].boot == stamp.boot:
            # The record stays, whatever what is sent meets: the next pass reads what the remote
            # holds.  Nothing the repository lacks is fetched, as for `_seen`.
            with contextlib.suppress(Exception):
                git = functools.partial(git, env={**env, "GIT_NO_LAZY_FETCH": "1"})
                if takes and seen[1].age_at_least() >= STILL:
                    sends(git, address, read, stamp)
            return
        if read:
            made = git("commit-tree", git("mktree").strip(), "-m", _message(read, stamp),
                       own=gitcall.STAMP).strip()
    except Exception:   # whatever it was, no value is watched
        pass
    # in the lease's repository, which the read may not have reached; its exit is not read, as
    # what git refused stays as it was
    _git("update-ref", "--no-deref", *((SEEN, made) if made else ("-d", SEEN)),
         env={**env, "GIT_DIR": str(_repo())}, check=False)


def _seen(git):
    """The value and the stamp SEEN holds, by `git` in the lease's repository; None where git gives
    no commit for SEEN, or its message is not exactly `_message` of them.  Its message alone is
    read: its tree, parents and dates are no part of the record."""
    # an object the repository lacks is none, where a promisor remote would have git fetch it: the
    # lease's commit among them
    own = {"GIT_NO_LAZY_FETCH": "1"}
    try:
        # SEEN's own object: `cat-file commit SEEN` would read refs/heads/refs/seen where SEEN is
        # not there, and the commit a tag names; the pattern matches refs under SEEN too
        named = re.fullmatch(b"commit (" + VALUE + b") " + SEEN.encode() + b"\n", git(
            "for-each-ref", "--format=%(objecttype) %(objectname) %(refname)", SEEN, own=own))
        if not named:
            return None
        message = git("cat-file", "commit", named[1], own=own).partition(b"\n\n")[2]
    except subprocess.CalledProcessError:
        return None
    value, _, line = message.partition(b" ")
    stamp = pair_clock.read(os.fsdecode(line.removesuffix(b"\n")))
    if stamp and re.fullmatch(VALUE, value) and message == _message(value, stamp):
        return value, stamp
    return None


def _message(value, stamp):
    """The message of SEEN's commit for the lease's `value` and the `stamp` that first read it,
    one line, as git ends the message it is given."""
    return value + b" " + os.fsencode(stamp.line()) + b"\n"


def _checkout():
    """git in ak's checkout, by `_git`, and the environment it is given, which `_read` turns to
    the lease's repository."""
    checkout = update.agentkit_dir()
    env = gitcall.project_env(checkout)
    return functools.partial(_git, cwd=checkout, env=env), env


def _address(git):
    """The one push address of ak's checkout, by `git` there: none, two, or one that reads as an
    option raises."""
    # every push address, so that more than one ends the turn: git would print the first alone
    told = git("remote", "get-url", "--push", "--all", "origin")
    if not ADDRESS.fullmatch(told):
        raise ValueError("ak's checkout has no one push address")
    return told[:-1].decode()


def _locked(then):
    """What `then()` gives, with no other turn under way: under the lock on the lease's folder,
    made where it is not there.  Where another holds it, nothing, and None."""
    repo = _repo()
    repo.parent.mkdir(parents=True, exist_ok=True)
    folder = os.open(repo.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(folder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:     # another turn is under way, and the next firing takes its own
        pass
    else:
        return then()
    finally:
        os.close(folder)


def _read(git, env, address):
    """The value of the lease at `address`, or None for none, read through the lease's repository,
    made ready first: `git` works in that repository from here on, the checkout its working folder
    alone."""
    env["GIT_DIR"] = str(_repo())
    git("init", "-q", "--bare", "--template=", str(_repo()))
    held = git("ls-remote", address, REF, timeout=REMOTE)
    # Each turn makes a commit here and drops the ref of the one before, and no other call here
    # starts git's housekeeping, so without this the commits no ref names stay for ever.  What it
    # does is git's; whatever it exits or raises leaves the read as it is.
    with contextlib.suppress(Exception):
        git("gc", "--auto", check=False)
    # the pattern matches any name ending as REF does, which is no lease
    return next((line.partition(b"\t")[0] for line in held.split(b"\n")
                 if re.fullmatch(VALUE + b"\t" + REF.encode(), line)), None)


def proof_age():
    """Seconds since the oldest value this machine keeps was made, by `age_at_most`: its proof that
    it is the home.  A turn that reads this machine's own lease keeps only that value and the one it
    makes next, so this machine's lease on the remote, its swap taken or not, was made no earlier
    than the oldest kept, and a standby has seen it stand still for no longer than that value's age.
    The youngest is no proof: a turn makes a value right after its read, so on a remote that answers
    reads and refuses pushes it stays young while the lease stands still.  None for no proof: none
    kept, or a read that raises, as a git that does not exit 0 and a clock that cannot be read do;
    a name holding no stamp is none.  It asks no remote."""
    try:
        # the variables git keeps for one repository dropped, as `gitcall.project_env` drops them
        local = _git("rev-parse", "--local-env-vars").split()
        names = _git("for-each-ref", "--format=%(refname)", MADE,
                     env={**dict.fromkeys(map(os.fsdecode, local)), "GIT_DIR": str(_repo())})
        # one name a line, as git forbids a control character in one, read as the turn's git was
        # given it: a name may hold any other byte
        stamps = (_stamp(os.fsdecode(name)) for name in names.split(b"\n"))
        return max((stamp.age_at_most() for stamp in stamps if stamp), default=None)
    except Exception:
        return None


def watching():
    """Whether this machine only watches the lease: it keeps no value it made, as `proof_age` reads
    one, a ref under MADE whose name holds a stamp, and its watch holds a record of the lease made
    on this boot, SEEN giving a value and a stamp (`_seen`) whose boot is this one.  A pass that
    cannot read the lease removes the record, so one there says this machine can.  No for whatever
    is raised, a listing git refused among it, which `proof_age` reads as none kept.  It only reads,
    by git in the lease's repository as `proof_age` runs it, and asks no remote."""
    try:
        local = _git("rev-parse", "--local-env-vars").split()
        git = functools.partial(_git, env={**dict.fromkeys(map(os.fsdecode, local)),
                                           "GIT_DIR": str(_repo())})
        held = _seen(git)
        return bool(held) and held[1].boot == pair_clock.now().boot \
            and not any(_stamp(os.fsdecode(name)) for _, name in _kept(git))
    except Exception:
        return False


def _git(*args, cwd=None, env=None, timeout=None, check=True, own=None):
    """git's output, as bytes, since text would lose a carriage return or a byte no UTF-8 holds;
    one that does not exit 0 raises, unless `check` is off."""
    given = {**gitcall.tool_env(), **(env or {}), **(own or {})}
    done = gitcall.run_capped(
        ["git", *args], timeout or gitcall.local_cap(), cwd=cwd, stdin=subprocess.DEVNULL,
        env={name: value for name, value in given.items() if value is not None})
    if check:
        done.check_returncode()
    return done.stdout


def _named(stamp):
    """The ref the value made at `stamp` is kept as, which `_stamp` reads back."""
    return MADE + stamp.line().replace(" ", "_")


def _stamp(name):
    """The stamp `_named` gave the ref `name`, or None for a name it gives no stamp."""
    stamp = pair_clock.read(" ".join(name.removeprefix(MADE).split("_", 2)))
    return stamp if stamp and _named(stamp) == name else None


def _repo():
    """The lease's own repository, where the values this machine made are kept."""
    return config.TMP / "lease" / "repo"
