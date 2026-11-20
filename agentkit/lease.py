"""`ak lease`: one turn creating the lease on ak's remote where the remote holds none, and
swapping a new value in where it holds this machine's own.  This hides where the lease is, how it
is read and written, and what a machine keeps of the values it made.

The lease says which machine is ak's home: `REF` in the repository at the push address of ak's
checkout.  It changes only by compare-and-swap, so two machines never both create it and a swap
replaces only the value its turn read.  The checkout is asked that address and nothing else.  A
repository of the lease's own, with no setting but git's defaults and the user's, reads and writes
there, so no setting of the checkout makes the read and the write differ or writes into it.  Each
value made is a ref under `MADE` there, named for its stamp (`pair_clock`).  git writes a ref
whole or not at all, and a value is kept before it is sent, so there is no lock and no file of the
lease's own, and a create the remote refused or never answered sends that same value on the next
turn.

A lease is this machine's own where its repository holds the lease's commit: git keeps a commit
past its ref, and a turn fetches nothing into it.  Another's ends the turn.  Every turn that finds
its own keeps of what it made only that value, then makes a new one and swaps it in, so the lease
changes as often as turns are taken; a swap the remote refused or never answered is not sent
again, as the next turn makes another.
"""

import re
import secrets
import subprocess

from . import config, gitcall, pair_clock, update

REF = "refs/agentkit/home"
MADE = "refs/made/"
REMOTE = 45     # seconds for each call that reaches the remote
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
    checkout = update.agentkit_dir()
    env = gitcall.project_env(checkout)

    def git(*args, timeout=None, check=True, own=None):
        """git's output, as bytes, since text would lose a carriage return or a byte no UTF-8
        holds; one that does not exit 0 raises, unless `check` is off."""
        done = gitcall.run_capped(
            ["git", *args], timeout or gitcall.local_cap(), cwd=checkout,
            stdin=subprocess.DEVNULL,
            env={name: value for name, value in {**gitcall.tool_env(), **env, **(own or {})}.items()
                 if value is not None})
        if check:
            done.check_returncode()
        return done.stdout

    # every push address, so that more than one ends the turn: git would print the first alone
    told = git("remote", "get-url", "--push", "--all", "origin")
    if not ADDRESS.fullmatch(told):
        return
    address = told[:-1].decode()
    repo = _repo()
    env["GIT_DIR"] = str(repo)      # the checkout is the working folder alone from here on
    git("init", "-q", "--bare", "--template=", str(repo))
    held = git("ls-remote", address, REF, timeout=REMOTE)
    # the pattern matches any name ending as REF does, which is no lease
    read = next((line.partition(b"\t")[0] for line in held.split(b"\n")
                 if re.fullmatch(VALUE + b"\t" + REF.encode(), line)), None)
    if read:
        # this machine's own where its commit is here; another's ends the turn
        git("cat-file", "-e", read + b"^{commit}")
        # what is kept shrinks to the value read and the one made next, or would grow a ref a turn
        kept = git("for-each-ref", "--format=%(objectname) %(refname)", MADE)
        for value, name in (line.split(b" ", 1) for line in kept.splitlines()):
            if value != read:
                git("update-ref", "-d", name, value, check=False)
        # made and kept as the create's below
        stamp = pair_clock.now()
        value = git("commit-tree", git("mktree").strip(), "-m", secrets.token_hex(16),
                    own=gitcall.STAMP).strip()
        git("update-ref", MADE + stamp.line().replace(" ", "_"), value, "")
        git("push", address, f"{value.decode()}:{REF}",
            f"--force-with-lease={REF}:{read.decode()}", timeout=REMOTE, check=False)
        return
    made = ("for-each-ref", "--count=1", "--format=%(objectname)", MADE)
    if not git(*made):
        stamp = pair_clock.now()
        # its own message, as every other part of it is any machine's
        value = git("commit-tree", git("mktree").strip(), "-m", secrets.token_hex(16),
                    own=gitcall.STAMP).strip()
        # only as a name no ref holds: two turns at once each keep their own
        git("update-ref", MADE + stamp.line().replace(" ", "_"), value, "")
    value = git(*made)
    if re.fullmatch(VALUE + b"\n", value):
        git("push", address, f"{value[:-1].decode()}:{REF}", f"--force-with-lease={REF}:",
            timeout=REMOTE, check=False)


def proof_age():
    """Seconds since this machine last knew it was the home, by `age_at_most`: a turn makes a value,
    named for its stamp, only right after the remote said the lease is this machine's or that there
    is none, so those stamps are its proofs and the youngest is the one that counts.  None for no
    proof: none made, or a read that fails, as a clock that cannot be read does; a name holding no
    stamp is none.  It asks no remote."""
    repo = _repo()
    try:
        code, names, _ = gitcall.tool_run(["git", "for-each-ref", "--format=%(refname)", MADE],
                                          env={**gitcall.project_env(repo), "GIT_DIR": str(repo)})
        if code != 0:
            return None
        stamps = [pair_clock.read(name[len(MADE):].replace("_", " "))
                  for name in names.splitlines()]
        return min((stamp.age_at_most() for stamp in stamps if stamp), default=None)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _repo():
    """The lease's own repository, where the values this machine made are kept."""
    return config.TMP / "lease" / "repo"
