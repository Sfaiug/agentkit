"""A job's tasks in one repository prepare at once, and none fails on another's config write.

Each preparation turns git's automatic gc off in the config its repository's checkouts share,
and git refuses a config write outright while another holds that file's lock: on 11 Nov 2026
tests/test_key_a_job_waits_for_usage.py failed so on its first run.  Here git writes that
setting as on a disk slow enough for the two tasks' preparations to meet at it every time.
Black-box, as tests/test_key_exhausted_resume.py.
"""

import shlex
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akbin, taskfile
from test_key_exhausted_resume import TITLES, record, staged

# Holds the lock git takes on the file it writes, then lets git take it: a contender's own
# write meets it there, and git refuses that one as it would.
SLOW = """#!/bin/sh
git={git} dir=.
[ "$1" = -C ] && dir=$2
case " $* " in
*" --get"*) ;;
*" config "*" gc.auto "*|*" config "*" maintenance.auto "*)
    case " $* " in
    *" --worktree "*) lock=$("$git" -C "$dir" rev-parse --absolute-git-dir)/config.worktree.lock ;;
    *) lock=$("$git" -C "$dir" rev-parse --path-format=absolute --git-common-dir)/config.lock ;;
    esac
    if (set -C; : >"$lock") 2>/dev/null; then
        sleep 3
        rm -f "$lock"
    fi ;;
esac
exec "$git" "$@"
"""


class AJobsTasksPrepareAtOnce(unittest.TestCase):
    def test_every_task_of_a_job_in_one_fresh_repository_passes(self):
        home = staged(type(self), ["opus"], claude="work", codex="pass")
        home.fake("git", SLOW.format(git=shlex.quote(
            shutil.which("git", path=":".join(akbin.SYSTEM)))))
        tasks = [str(taskfile.write(home, self.rig.path, title)) for title in TITLES]
        done = home.ak("run", *tasks, "--no-merge", timeout=600)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual([record(run)["state"] for run in taskfile.runs(home)],
                         ["pass"] * len(TITLES))


if __name__ == "__main__":
    unittest.main()
