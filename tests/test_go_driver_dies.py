"""A run Go's ak launches is Python's to carry on too: a driver that dies leaves an ordinary dead
loop, which Python's `ak run resume` takes to its delivery, and Python's `ak run stop` ends one
going.  What Python then drives Go leaves to Python, and a driver going refuses a second.

Go builds as tests/test_go.py builds it, into the Home's own directory; `home.ak` stays this
checkout's `bin/ak`, so Go's program launches and Python's does all the rest."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest

os.environ.pop("AK_BIN", None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig
from test_go import ENV, GO

PATIENCE = 60


def wait_for(what, ready):
    late = time.monotonic() + PATIENCE
    while not ready():
        if time.monotonic() > late:
            raise AssertionError(f"no {what} after {PATIENCE} s")
        time.sleep(0.05)


def marked(run_dir):
    """Every live process carrying the run's marker: what a run started, wherever it went."""
    want = f"AGENTKIT_RUN={run_dir}".encode()
    found = []
    for entry in Path("/proc").iterdir():
        try:
            if entry.name.isdigit() and want in (entry / "environ").read_bytes().split(b"\0"):
                found.append(int(entry.name))
        except OSError:
            continue
    return found


def driver_gone(state):
    try:
        said = Path(f"/proc/{state['pid']}/stat").read_text().rsplit(")", 1)[1].split()
    except OSError:
        return True
    return said[0] == "Z" or int(said[19]) != state["process_identity"]["ticks"]


def built(home):
    """Go's program in the Home's own directory, as tests/test_go.py builds it."""
    go = home.root / "go-ak"
    done = subprocess.run(["go", "build", "-o", go, "./cmd/ak"], cwd=GO, env=ENV,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return go


class GoLaunches(unittest.TestCase):
    def launch(self, repo=None, *flags):
        """A run Go launched in the background, scratch unless `repo` makes the Home's project of
        that name, its driver in the executor's turn."""
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, repo) if repo else None
        akconfig.write(home, ["opus", "astra"])
        fakes = fakeadapter.install(home, claude="work", codex="pass")
        began = fakes["claude"].dir / "began"
        fakes["claude"].behave({"sh": f"touch {began}; sleep 600"}, "work")
        go = built(home)
        task = taskfile.write(home, rig.path if rig else "none", "Add retry file")
        done = home.run(go, "run", str(task), *flags, "--bg")
        self.assertEqual(done.code, 0, done.out + done.err)
        run_dir = taskfile.only_run(home)
        wait_for("executor's turn", began.exists)
        state = json.loads((run_dir / "run.json").read_text())
        self.assertEqual(state["state"], "running")
        self.assertNotIn("driver", state)
        again = home.run(go, "run", "resume", run_dir.name)
        self.assertEqual(again.code, 2, again.out + again.err)
        self.assertEqual(again.err, f"ak run: {run_dir.name} is still running as pid {state['pid']}\n")
        return home, run_dir, state

    def test_python_resumes_a_run_whose_driver_was_killed_and_delivers_it(self):
        home, run_dir, state = self.launch()
        os.kill(state["pid"], signal.SIGKILL)
        wait_for("dead driver", lambda: driver_gone(state))
        left = json.loads((run_dir / "run.json").read_text())
        self.assertEqual((left["state"], left.get("deaths")), ("running", None))

        done = home.ak("run", "resume", run_dir.name, timeout=300)

        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue(done.out.rstrip("\n").endswith(f"PASS, delivered -> {run_dir / 'result.md'}"), done.out)
        state = json.loads((run_dir / "run.json").read_text())
        self.assertEqual((state["state"], state["verdict"]), ("pass", "PASS"))
        lines = (run_dir / "result.md").read_text().splitlines()
        self.assertEqual(lines[0], "# PASS, delivered — Add retry file")
        workspace = home.path / ".agentkit/work" / run_dir.name
        self.assertEqual(lines[lines.index("## Deliverables") + 1],
                         f"- [retry.txt]({workspace / 'retry.txt'})")
        self.assertEqual(marked(run_dir), [])

    def test_python_resumes_a_repo_run_whose_driver_was_killed_and_it_passes_on_its_branch(self):
        home, run_dir, state = self.launch("widgets", "--no-merge")
        os.kill(state["pid"], signal.SIGKILL)
        wait_for("dead driver", lambda: driver_gone(state))

        done = home.ak("run", "resume", run_dir.name, timeout=300)

        self.assertEqual(done.code, 0, done.out + done.err)
        state = json.loads((run_dir / "run.json").read_text())
        self.assertEqual({key: state.get(key) for key in ("state", "verdict", "no_merge", "merged", "branch")},
                         {"state": "pass", "verdict": "PASS", "no_merge": True, "merged": False,
                          "branch": "ak/add-retry-file"})
        lines = (run_dir / "result.md").read_text().splitlines()
        self.assertEqual(lines[0], "# NOT MERGED (1 of 3) — Add retry file")
        self.assertEqual(lines[1], "Why: --no-merge")
        tree = home.run("git", "-C", state["worktree"], "ls-tree", "--name-only", "HEAD")
        self.assertIn("retry.txt", tree.out.split())
        self.assertEqual(marked(run_dir), [])

    def test_go_leaves_the_stop_of_a_run_python_took_over_to_python(self):
        home, run_dir, state = self.launch()
        os.kill(state["pid"], signal.SIGKILL)
        wait_for("dead driver", lambda: driver_gone(state))
        home.spawn("run", "resume", run_dir.name)
        record = lambda: json.loads((run_dir / "run.json").read_text())
        wait_for("Python's loop", lambda: record()["pid"] != state["pid"] and record()["state"] == "running")

        done = home.run(home.root / "go-ak", "run", "stop", run_dir.name)

        self.assertEqual(done.code, 3, done.out + done.err)
        self.assertEqual(record()["state"], "running")
        self.assertEqual(home.ak("run", "stop", run_dir.name).code, 0)
        wait_for("end of what the run started", lambda: not marked(run_dir))

    def test_a_foreground_run_dies_with_its_terminal_and_go_carries_it_on_its_session(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        fakes = fakeadapter.install(home, claude="work", codex="pass")
        began = fakes["claude"].dir / "began"
        fakes["claude"].behave({"sh": f"touch {began}; sleep 600"}, "work")
        go = built(home)
        task = taskfile.write(home, "none", "Add retry file")
        terminal = subprocess.Popen([go, "run", str(task)], cwd=home.path, env=home._env(None),
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(terminal.wait)
        wait_for("executor's turn", began.exists)
        run_dir = taskfile.only_run(home)
        state = json.loads((run_dir / "run.json").read_text())

        os.killpg(terminal.pid, signal.SIGINT)

        wait_for("dead driver", lambda: driver_gone(state))
        left = json.loads((run_dir / "run.json").read_text())
        self.assertEqual((left["state"], left["pid"], left.get("error")), ("running", state["pid"], None))
        done = home.run(go, "run", "resume", run_dir.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(json.loads((run_dir / "run.json").read_text())["state"], "pass")
        self.assertEqual([run["argv"][5:] for run in fakes["claude"].runs()], [["sid-claude-1"]])
        self.assertEqual(marked(run_dir), [])

    def test_python_stops_a_run_go_is_driving_and_nothing_of_it_stays(self):
        home, run_dir, state = self.launch()

        done = home.ak("run", "stop", run_dir.name)

        self.assertEqual(done.code, 0, done.out + done.err)
        wait_for("end of the driver", lambda: driver_gone(state))
        wait_for("end of what the run started", lambda: not marked(run_dir))
        state = json.loads((run_dir / "run.json").read_text())
        self.assertEqual((state["state"], state["verdict"], state["error"]),
                         ("stopped", "STOPPED", "stopped by the user"))

    def test_python_stops_a_repo_run_go_is_driving_and_its_checkout_and_branch_go(self):
        home, run_dir, state = self.launch("widgets", "--no-merge")

        done = home.ak("run", "stop", run_dir.name)

        self.assertEqual(done.code, 0, done.out + done.err)
        wait_for("end of the driver", lambda: driver_gone(state))
        wait_for("end of what the run started", lambda: not marked(run_dir))
        state = json.loads((run_dir / "run.json").read_text())
        self.assertEqual(state["state"], "stopped")
        self.assertFalse(Path(state["worktree"]).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
