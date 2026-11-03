"""What `ak run gc` takes, planted in a Home (tests/fixtures/akbin.py) the way ak leaves it.

`planted(home)` plants one of each kind of run, checkout, log and job the collector takes, and
`Leftovers(home)` one of each family outside runs and jobs, each with the line the dry run names
it by.  Nothing here imports agentkit.
"""

import json
import os
import time

from fixtures.akbin import AK

DAY = 86400
# Each held path is opened by a process of the box before the program starts; the shell is
# the box's first process, so the box and its holders end with it.
HOLD = ('until [ "$1" = -- ]; do exec 3<"$1"; sleep 600 & shift; done; shift; exec 3<&-; '
        '"$0" "$@"')
# a full disk shortens retention to a day: the ages here are those of a disk with room
ROOM = {"AGENTKIT_GC_DISK_PERCENT": "100"}


def git(home, *args):
    done = home.run("git", *args)
    assert done.code == 0, done.err
    return done.out


def repository(home):
    """~/code/acme, a repository with one commit, made the first time it is asked for."""
    repo = home.path / "code" / "acme"
    if not repo.exists():
        repo.mkdir(parents=True)
        git(home, "-C", str(repo), "init", "-q")
        git(home, "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "start")
    return repo


def branches(home):
    """The local branches of ~/code/acme."""
    return git(home, "-C", str(repository(home)), "for-each-ref", "--format=%(refname:short)",
               "refs/heads").split()


def checkout(home, run_id):
    """The run's own checkout, ~/.agentkit/wt/<id>, on its branch `ak/<id>`."""
    wt = home.path / ".agentkit" / "wt" / run_id
    git(home, "-C", str(repository(home)), "worktree", "add", "-q", "-b", f"ak/{run_id}", str(wt))
    return wt


def run(home, run_id, days, **fields):
    """A run of ~/code/acme on `ak/<id>` ended `days` back, its record as old; a None field is
    left out."""
    ended = time.time() - days * DAY
    record = {"run_id": run_id, "repo": str(repository(home)), "branch": f"ak/{run_id}",
              "started_at": ended - 600, "finished_at": ended, **fields}
    home.write(f".agentkit/runs/{run_id}/run.json",
               {key: value for key, value in record.items() if value is not None}, ago=days * DAY)
    return home.path / ".agentkit" / "runs" / run_id


def planted(home):
    """One of each kind the dry run names for runs and jobs, and its line, in the order printed:
    the sweep's merged checkouts and sandboxes, then the collector's gone jobs, its runs by
    name, and its finished jobs."""
    agentkit = home.path / ".agentkit"
    merged = checkout(home, "acme-merged")
    run(home, "acme-merged", 1, state="pass", merged=True, worktree=str(merged))
    sandbox = agentkit / "tmp" / "smoke-acme"
    sandbox.mkdir(parents=True)
    os.utime(sandbox, (time.time() - 2 * DAY,) * 2)
    gone = home.write(".agentkit/jobs/acme-gone/job.json",
                      {"tasks": [{"name": "fix-api", "run_id": "acme-gone-1",
                                  "state": "running"}]},
                      ago=31 * DAY).parent
    ended = checkout(home, "acme-ended")
    run(home, "acme-ended", 8, state="fail", worktree=str(ended))
    # merged, its checkout already gone: its log is what is left to take
    logged = run(home, "acme-merged-log", 1, state="pass", merged=True,
                 worktree=str(agentkit / "wt" / "acme-merged-log"))
    log = home.write(".agentkit/runs/acme-merged-log/log.txt", "round 1: PASS\n", ago=DAY)
    old = run(home, "acme-old", 31, state="pass")
    throwaway = run(home, "acme-throwaway", 8, state="pass",
                    repo=str(agentkit / "tmp" / "acme-suite"))
    done = home.write(".agentkit/jobs/acme-done/job.json",
                      {"tasks": [{"run_id": "acme-done-1", "state": "merged"}],
                       "finished_at": time.time() - 8 * DAY}, ago=8 * DAY).parent
    assert logged == log.parent
    return {
        "merged worktree": f"gc: would remove merged-worktree {merged}",
        "smoke sandbox": f"gc: would remove smoke-sandbox {sandbox}",
        "gone job": f"gc: would stop gone-job {gone}: the job's launcher gone and nothing "
                    "written for 30 days",
        "ended worktree": f"gc: would remove ended-worktree {ended}",
        "merged log": f"gc: would compress merged-log {log}",
        "old run": f"gc: would remove old-run {old}",
        "throwaway run": f"gc: would remove throwaway-run {throwaway}",
        "finished job": f"gc: would remove finished-job {done}",
    }


def plant(path, days, data=None):
    """A file holding `data`, or a folder when there is none, last changed `days` back."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if data is None:
        path.mkdir()
    else:
        path.write_text(data if isinstance(data, str) else json.dumps(data))
    stamp = time.time() - days * DAY
    os.utime(path, (stamp, stamp))
    return path


class Leftovers:
    """One of each family planted in a Home, past all that keeps it off the plan or, `kept`,
    short of it: kepter than its age, held open, or its seat alive."""

    def __init__(self, home, kept=False):
        self.home, ak = home, home.path / ".agentkit"
        # the box's /tmp and /var/tmp, bound whole: a path bwrap is handed is one it holds
        self.tmp, self.var = plant(home.root / "box-tmp", 0), plant(home.root / "box-var", 0)
        now = time.time()
        view = plant(ak / "tmp" / "view.html", 2, "<html></html>")
        plant(ak / "tmp" / "view.html.agentkit-ephemeral.json", 0, {
            "version": 1, "kind": "viewer", "path": str(view), "pid": None,
            "created_at": now - 2 * DAY, "finished_at": now - 2 * DAY})
        orphan = plant(ak / "wt" / ("new-fix" if kept else "old-fix"), 0 if kept else 2)
        passed = checkout(home, "passed-fix")
        run(home, "passed-fix", 6.5 if kept else 8.5, state="pass", merged=False, no_merge=True,
            worktree=str(passed))
        seat = plant(ak / "state" / "notify-acme-seat.json", 2, {})
        if kept:
            plant(ak / "state" / "session-acme-seat.json", 0, {})
        # kept, the entry names a checkout still there
        trusted = orphan if kept else ak / "wt" / "gone-fix"
        claude = plant(home.path / ".claude.json", 0, {"projects": {str(trusted): {}}})
        plant(self.tmp / "acme-notes", 3.5)
        plant(self.var / "acme" / "build", 0.5 if kept else 3.5)
        plant(ak / "env" / "acme.env", 0, "TMPDIR=/var/tmp/acme\n")
        old = plant(ak / "old-notes", 8.5)
        talk = plant(home.path / ".gemini" / "antigravity-cli" / "conversations" / "talk.db",
                     29.5 if kept else 31.5, "")
        self.expected = [
            f"gc: would remove viewer {view}",
            f"gc: would remove orphan-worktree {orphan}: no run record",
            f"gc: would remove unmerged-worktree {passed}: passed, never merged, ended 8 days ago",
            f"gc: would remove seat-file {seat}: seat acme-seat is gone",
            f"gc: would prune harness-entries {claude}: 1 trust entries and 0 MCP servers name a "
            "gone smoke sandbox or checkout",
            "gc: would remove tmp-entry /tmp/acme-notes: untouched for 3 days",
            "gc: would remove tmp-entry /var/tmp/acme/build: untouched for 3 days",
            f"gc: would remove home-entry {old}: untouched for 8 days",
            f"gc: would remove conversation {talk}: untouched for 31 days",
        ]
        # kept, these are as old as when taken, and held open
        self.held = [str(view), "/tmp/acme-notes", str(old)] if kept else []

    def ak(self, *args):
        """The program run once in a box with a /tmp, a /var/tmp and processes of its own,
        on a disk with room."""
        box = ("bwrap", "--dev-bind", "/", "/", "--bind", str(self.tmp), "/tmp",
               "--bind", str(self.var), "/var/tmp", "--unshare-pid", "--as-pid-1",
               "--proc", "/proc")
        return self.home.run(*self.home.box(box), "sh", "-c", HOLD, AK, *self.held, "--", *args,
                             env=ROOM)

    def seen(self):
        """Every file and folder planted, its bytes and when it last changed."""
        return {str(path): (path.read_bytes() if path.is_file() else None,
                            path.lstat().st_mtime_ns)
                for root in (self.home.path, self.tmp / "acme-notes", self.var / "acme")
                for path in (root, *sorted(root.rglob("*")))}
