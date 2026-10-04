"""v5am: atomic host slots, durable FIFO, and one generation of nested test runs.

Offline: real loop processes and fake adapters, all files beneath this checkout.
"""
from contextlib import ExitStack, redirect_stdout
import errno
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import scripted
from agentkit import host, config, job as jobs, menu, notify, orch, run, watch
from agentkit import record

ADAPTER = r'''import json, os, pathlib, sys, time
if sys.argv[1] == "usage":
    print('{"meters":[{"name":"weekly","used":0}]}')
    sys.exit(0)
if sys.argv[1] == "reset-status":
    print('{"available":0}')
    sys.exit(0)
assert sys.argv[1] == "run", sys.argv
out = pathlib.Path(sys.argv[6])
root = pathlib.Path(os.environ["V5AM_FIXTURE"])
prompt = pathlib.Path(sys.argv[5]).read_text()
role = "reviewer" if prompt.startswith("You are the reviewer") else "executor"
rid = out.parent.parent.name
with (root / "calls.jsonl").open("a") as fh:
    fh.write(json.dumps({"id":rid, "role":role, "depth":os.environ["AK_RUN_DEPTH"],
                         "parent":os.environ.get("AK_PARENT_RUN")}) + "\n")
if role == "executor":
    deadline = time.monotonic() + 40
    while not (root / ("release-" + rid)).exists() and not (root / "release-all").exists():
        assert time.monotonic() < deadline, "fixture was not released"
        time.sleep(.02)
    pathlib.Path(sys.argv[4], "deliverable").write_text("fixture\n")
(out / "final.md").write_text("VERDICT: PASS\n\n## Findings\n- none\n" if role == "reviewer"
                              else "## Summary\nFixture work.\n")
(out / "session_id").write_text("fixture-" + role)
'''
LAUNCH = """import sys
from agentkit import host, job as jobs, run
host.host_readings = lambda **_kw: {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
                             "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}
run.SLOT_POLL = .03
jobs.JOB_TICK = .03
raise SystemExit(run.main(sys.argv[1:]))
"""
REFUSAL = ("a worker's worker may not start runs (depth 2); only the orchestrator, "
           "and a worker for its tests, may")


class Slots(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-v5am-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        home = self.root / ".agentkit"
        self.stack.enter_context(patch.object(config, "HOME", home))
        for key in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, key, home / key.lower()))
        self.stack.enter_context(patch.object(config, "CODE", self.root / "code"))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "PYTHONPATH": str(REPO), "PYTHONDONTWRITEBYTECODE": "1",
            "PATH": str(self.bin) + ":" + os.environ["PATH"], "NO_COLOR": "1",
            "AK_MAX_RUNS": "2", "AK_SLOT_POLL": ".03", "AK_RUN_DEPTH": "0", "AK_PARENT_RUN": "",
            "AK_RUN_ROLE": "", "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_JOB_DIR": "", "AGENTKIT_UNATTENDED": "", "IDLE_COMPACT_STATE": "",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "AK_NOTIFY_SINK": "dry-run",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_DISCORD_USER_ID": "",
            config.ADAPTER_DIR_ENV: str(adapters), "V5AM_FIXTURE": str(self.root),
            "AK_HOST_READINGS": json.dumps({"free_mb": 4096, "mem_total_mb": 16384,
                                             "load": 1, "cpus": 8,
                                             "unit_memory_current_mb": 100,
                                             "unit_memory_high_mb": 1000})}))
        # A caller's AK_MIN_FREE_MB or AK_MAX_LOAD, judged against the fixed readings here,
        # can keep every slot shut for good.
        for var in ("AK_MIN_FREE_MB", "AK_MAX_LOAD"):
            os.environ.pop(var, None)
        self.stack.enter_context(patch.object(host, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        # A handoff on a host with a user manager would put the child in a real scope, which
        # stops itself -- SIGTERM to the child -- as its run ends.
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.script(self.bin / "tmux", 'import sys\nassert sys.argv[1:3] == ["-L", "agentkit-test"]\nsys.exit(1)\n')
        for name in ("gh", "claude", "codex", "muse"):
            self.script(self.bin / name, 'raise AssertionError("external call forbidden")\n')
        self.cfg = config.load()
        for harness in {entry["harness"] for entry in self.cfg["models"].values()}:
            self.script(adapters / (harness + ".sh"), ADAPTER)
        self.executor = self.cfg["defaults"]["workers"][0]
        self.reviewer = next(name for name in self.cfg["defaults"]["workers"]
                             if config.model(self.cfg, name)["provider"] !=
                             config.model(self.cfg, self.executor)["provider"])
        config.ensure_dirs()
        self.procs = []
        self.addCleanup(self.cleanup_processes)

    def script(self, path, body):
        path.write_text(f"#!{sys.executable}\n{scripted(body)}")
        path.chmod(0o755)

    def cleanup_processes(self):
        (self.root / "release-all").touch()
        for proc, _ in self.procs:
            if proc.poll() is None:
                watch.kill_tree(proc.pid, log=lambda _: None)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    def title(self, name, root=None):
        # A run's end sweeps its id's marker host-wide, and the id is its minute and title:
        # each copy of this file on the host names its runs by its own temporary directory.
        return f"{(root or self.root).name} {name}"

    def task(self, name, probe="", root=None):
        root = root or self.root
        task = root / (name + ".md")
        task.write_text(f"---\nrepo: none\nrounds: 1\n---\n# {self.title(name, root)}\n\n"
                        "## Done when\n"
                        "```bash\ntest -f deliverable\nprintf '%s' \"$AK_RUN_DEPTH\" > depth\n"
                        f"{probe}```\n")
        return str(task)

    def start(self, *args, env=None):
        path = self.root / f"process-{len(self.procs)}.log"
        with path.open("w") as output:
            proc = subprocess.Popen([sys.executable, "-c", LAUNCH, *args], cwd=REPO,
                                    env={**os.environ, **(env or {})}, stdout=output,
                                    stderr=subprocess.STDOUT, start_new_session=True)
        self.procs.append((proc, path))
        return proc

    def launch(self, name, **kw):
        return self.start(self.task(name), "--exec", self.executor, "--review", self.reviewer, **kw)

    def states(self):
        return [(d, s) for d in record.run_dirs() if (s := record.read_state(d))]

    def wait(self, predicate, seconds=15):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            result = predicate()
            if result:
                return result
            time.sleep(.03)
        logs = "\n".join(path.read_text() for _, path in self.procs)
        self.fail("fixture timed out\n" + logs[-12000:])

    def receipt(self, name, state=None):
        return self.wait(lambda: next(((d, s) for d, s in self.states()
                                      if s.get("title") == self.title(name) and
                                      (state is None or s.get("state") == state)), None))

    def calls(self, role="executor"):
        path = self.root / "calls.jsonl"
        return [entry for line in (path.read_text().splitlines() if path.exists() else [])
                if (entry := json.loads(line))["role"] == role]

    def started(self, name):
        directory, state = self.receipt(name, "running")
        self.wait(lambda: any(call["id"] == directory.name for call in self.calls()))
        return directory, state

    def release(self, directory):
        (self.root / ("release-" + directory.name)).touch()
        self.wait(lambda: record.read_state(directory).get("state") == "pass")

    def finish_all(self):
        (self.root / "release-all").touch()
        for proc, path in self.procs:
            self.assertEqual(proc.wait(timeout=20), 0, path.read_text())

    def recover(self):
        popen = subprocess.Popen

        def launch(*args, **kwargs):
            proc = popen(*args, **kwargs)
            self.procs.append((proc, Path(kwargs["stdout"].name)))
            return proc

        with patch.object(subprocess, "Popen", side_effect=launch):
            watch.recover_runs(self.cfg, log=lambda _: None)

    def test_v5am_third_queues_and_starts_when_slot_frees(self):
        self.launch("one")
        first, _ = self.started("one")
        self.launch("two")
        self.started("two")
        self.launch("three")
        third, state = self.receipt("three", "queued")
        self.assertTrue(state["queued_at"])
        self.assertTrue((third / "task.md").is_file())
        self.assertEqual(len(self.calls()), 2)
        self.release(first)
        self.started("three")
        self.assertRegex((third / "log.txt").read_text().splitlines()[0],
                         r"^waited \d+ min for a slot \(count\)$")
        self.finish_all()

    def test_v5am_launch_claim_survives_background_handoff(self):
        os.environ["AK_MAX_RUNS"] = "1"
        task = self.task("reserved")
        directory = config.RUNS / ("20260919-1200-" + run.slugify(self.title("reserved")))
        directory.mkdir()
        (directory / "task.md").write_text(Path(task).read_text())
        (directory / "log.txt").touch()
        run.capture_launch(directory)
        before = record.read_state(directory)
        self.assertEqual(before["state"], "queued")
        self.assertEqual(before["pid"], os.getpid())
        self.assertEqual(run.slot_counts({"run_id": "new"})[0], 0)

        self.launch("waiter")
        _, waiting = self.receipt("waiter", "queued")
        self.assertEqual(run.slot_note(waiting), "waiting for a slot · 1 ahead")
        popen = subprocess.Popen

        def launch(*args, **kwargs):
            proc = popen(*args, **kwargs)
            self.procs.append((proc, Path(kwargs["stdout"].name)))
            return proc

        with patch.object(subprocess, "Popen", side_effect=launch):
            run.spawn_bg(directory, [task, "--bg", "--exec", self.executor,
                                     "--review", self.reviewer])
        _, after = self.started("reserved")
        self.assertEqual(after["pid"], self.procs[-1][0].pid)
        self.assertEqual(after["queued_at"], before["queued_at"])
        self.assertTrue(after["slot_started_at"])
        self.assertEqual(run.slot_counts({"run_id": "new"})[0], 1)
        self.assertFalse(run.queued(directory))  # the parent cannot adopt its child's slot
        self.assertEqual(len(self.calls()), 1)
        self.release(directory)
        self.started("waiter")
        self.finish_all()

    def test_v5am_failed_background_handoff_releases_launch_claim(self):
        os.environ["AK_MAX_RUNS"] = "1"
        directory = config.RUNS / ("20260919-1200-" + run.slugify(self.title("reserved")))
        directory.mkdir()
        task = self.task("reserved")
        (directory / "task.md").write_text(Path(task).read_text())
        run.capture_launch(directory)
        with patch.object(subprocess, "Popen", side_effect=OSError("fork failed")):
            with self.assertRaisesRegex(config.Error, "fork failed"):
                run.spawn_bg(directory, [task, "--bg"])
        self.assertEqual(record.read_state(directory)["state"], "interrupted")
        self.assertEqual(run.slot_counts({"run_id": "new"})[0], 0)
        self.launch("next")
        self.started("next")
        self.finish_all()

    def test_v5am_fifo_including_dead_waiter(self):
        os.environ["AK_MAX_RUNS"] = "1"
        self.launch("one")
        first, _ = self.started("one")
        second_proc = self.launch("two")
        second, _ = self.receipt("two", "queued")
        self.launch("three")
        self.receipt("three", "queued")
        second_proc.terminate()
        second_proc.wait(timeout=5)
        self.release(first)
        time.sleep(.15)
        self.assertEqual(len(self.calls()), 1)  # a live waiter cannot jump a dead one
        self.recover()
        self.started("two")
        self.assertEqual(len(self.calls()), 2)
        self.release(second)
        self.started("three")
        self.assertEqual([c["id"].rsplit("-", 1)[-1] for c in self.calls()], ["one", "two", "three"])
        (self.root / "release-all").touch()
        for proc, _ in self.procs:
            proc.wait(timeout=15)
        self.wait(lambda: all(s["state"] == "pass" for _, s in self.states()))
        self.wait(lambda: not record.process_active(record.read_state(second)))

    def test_v5am_resume_waits(self):
        os.environ["AK_MAX_RUNS"] = "1"
        victim = self.launch("resume-me")
        saved, _ = self.started("resume-me")
        watch.kill_tree(victim.pid, log=lambda _: None)
        victim.wait(timeout=5)
        with patch.object(run, "notify_recovery"):
            run.reap(saved, record.read_state(saved))
        self.launch("occupier")
        first, _ = self.started("occupier")
        self.start("resume", saved.name)
        _, state = self.receipt("resume-me", "queued")
        self.assertEqual(state["resume_from"], "interrupted")
        self.release(first)
        self.wait(lambda: len([c for c in self.calls() if c["id"] == saved.name]) == 2)
        self.release(saved)
        for proc, _ in self.procs[1:]:
            self.assertEqual(proc.wait(timeout=15), 0)

    def test_v5am_job_parallel_four_never_exceeds_two(self):
        tasks = [self.task(name) for name in ("one", "two", "three", "four")]
        self.start(*tasks, "--parallel", "4", "--exec", self.executor, "--review", self.reviewer)
        self.wait(lambda: len(self.calls()) == 2)
        self.assertEqual(sum(s["state"] == "running" for _, s in self.states()), 2)
        released = set()
        while len(released) < 4:
            current = [(d, s) for d, s in self.states() if s["state"] == "running"]
            self.assertLessEqual(len(current), 2)
            for directory, _ in current:
                if directory.name not in released:
                    released.add(directory.name)
                    self.release(directory)
                    break
            else:
                self.wait(lambda: any(c["id"] not in released for c in self.calls()))
        self.finish_all()

    def test_v5am_child_shares_parent_slot_and_exports_next_depth(self):
        os.environ["AK_MAX_RUNS"] = "1"
        self.launch("parent")
        parent, _ = self.started("parent")
        # the done-when proves its own depth, and the depth file it wrote is still
        # there: a delivered scratch run's workspace stays with its run
        child_task = self.task("child", 'test "$AK_RUN_DEPTH" = 2\n')
        self.start(child_task, "--exec", self.executor, "--review", self.reviewer,
                   env={"AK_RUN_DEPTH": "1", "AK_PARENT_RUN": parent.name})
        child, state = self.started("child")
        self.assertEqual(state["parent_run"], parent.name)
        self.assertEqual(state["run_depth"], 1)
        self.assertEqual(run.slot_counts({"run_id": "new"})[0], 1)
        self.finish_all()
        for call in self.calls() + self.calls("reviewer"):
            self.assertEqual(call["depth"], "1" if call["id"] == parent.name else "2")
            self.assertEqual(call["parent"], parent.name)
        self.assertEqual((Path(record.read_state(child)["worktree"]) / "depth").read_text(), "2")

    def test_v5am_depth_two_refused_before_directory(self):
        for args in ([self.task("forbidden")], ["resume", "missing"],
                     [self.task("a"), self.task("b")]):
            proc = self.start(*args, env={"AK_RUN_DEPTH": "2", "AK_MAX_RUNS": "0"})
            self.assertEqual(proc.wait(timeout=5), 2)
            self.assertEqual(self.procs[-1][1].read_text().strip(), REFUSAL)
            self.assertEqual(record.run_dirs(), [])
            self.assertEqual(jobs.job_dirs(), [])

    def test_v5am_tick_adopts_dead_queued_waiter(self):
        os.environ["AK_MAX_RUNS"] = "1"
        self.launch("one")
        first, _ = self.started("one")
        proc = self.launch("orphan")
        orphan, state = self.receipt("orphan", "queued")
        proc.terminate()
        proc.wait(timeout=5)
        self.assertEqual(run.reap(orphan, record.read_state(orphan))["state"], "queued")
        self.release(first)
        with patch.object(subprocess, "Popen", side_effect=OSError("temporary fork failure")):
            watch.recover_runs(self.cfg, log=lambda _: None)
        self.assertEqual(record.read_state(orphan)["state"], "queued")
        self.assertEqual(record.read_state(orphan)["queued_at"], state["queued_at"])
        with patch.object(notify, "shaped") as cards:
            self.recover()
            self.recover()
            cards.assert_not_called()
        _, adopted = self.started("orphan")
        self.assertEqual(adopted["queued_at"], state["queued_at"])
        self.release(orphan)
        self.wait(lambda: not record.process_active(record.read_state(orphan)))
        self.procs[0][0].wait(timeout=5)

    def test_v5am_status_menu_and_seat_bar_say_waiting(self):
        os.environ["AK_MAX_RUNS"] = "1"
        self.launch("one")
        first, _ = self.started("one")
        self.launch("two")
        directory, state = self.receipt("two", "queued")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_status(["--plain"]), 0)
        self.assertIn("waiting", out.getvalue())
        self.assertIn("waiting for a slot · limit full (1 running) · 0 ahead", out.getvalue())
        self.assertNotIn("offers recovery", out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_status([]), 0)
        self.assertIn("waiting for a slot · limit full (1 running) · 0 ahead", out.getvalue())
        self.assertFalse(menu.v5o_needs_look(state))
        self.assertEqual(len(self.calls()), 1)
        self.release(first)
        self.started("two")
        self.finish_all()

    def test_v5am_a_copy_beside_this_one_ends_only_its_own_runs(self):
        # Another copy of this file on the host, in its own home, ends a "one" of its own
        # while this copy's still works: its end-of-run sweep must leave ours running.
        self.launch("one")
        first, _ = self.started("one")
        beside = Path(tempfile.mkdtemp(prefix=".v5am-", dir=self.root))
        (beside / "release-all").touch()
        other = self.start(self.task("one", root=beside), "--exec", self.executor,
                           "--review", self.reviewer,
                           env={"HOME": str(beside), "V5AM_FIXTURE": str(beside)})
        self.assertEqual(other.wait(timeout=20), 0, self.procs[-1][1].read_text())
        self.release(first)
        self.assertEqual(len(self.calls()), 1)
        self.finish_all()

    def test_v5am_zero_disables_cap(self):
        os.environ["AK_MAX_RUNS"] = "0"
        for name in ("one", "two", "three", "four"):
            self.launch(name)
        self.wait(lambda: len(self.calls()) == 4)
        self.assertEqual(sum(s["state"] == "running" for _, s in self.states()), 4)
        self.finish_all()

    def test_v5am_concurrent_cold_usage_cache_keeps_all_runs_running(self):
        os.environ["AK_MAX_RUNS"] = "0"
        # Hold all four readers once each has assembled its snapshot, and let them all write it
        # at once: every write takes the cache's one lock, so every rename succeeds.  Only
        # collect's own publish is held; a probe publishes its answer the moment it has it.
        barrier = '''import os, pathlib, time
from agentkit import usage
root = pathlib.Path(os.environ["V5AM_FIXTURE"])
store, replace = usage._store, pathlib.Path.replace
def publish(*args, **kwargs):
    (root / ("cache-ready-" + str(os.getpid()))).touch()
    end = time.monotonic() + 10
    while len(list(root.glob("cache-ready-*"))) < 4:
        assert time.monotonic() < end, "cache publishers did not meet"
        time.sleep(.01)
    return store(*args, **kwargs)
def rename(path, target):
    try:
        return replace(path, target)
    except FileNotFoundError:
        (root / ("cache-raced-" + str(os.getpid()))).touch()
        raise
usage._store, pathlib.Path.replace = publish, rename
'''
        with patch.dict(globals(), {"LAUNCH": barrier + LAUNCH}):
            for name in ("one", "two", "three", "four"):
                self.launch(name)
        self.wait(lambda: len(self.calls()) == 4)
        self.assertEqual(len(list(self.root.glob("cache-ready-*"))), 4)
        self.assertEqual(len(list(self.root.glob("cache-raced-*"))), 0)
        self.assertEqual(sum(s["state"] == "running" for _, s in self.states()), 4)
        self.finish_all()
        # With every writer gone, each one's change landed whole: the snapshot reads, holds
        # every provider, and no writer's temporary file is left beside it.
        cache = json.loads((config.STATE / "usage.json").read_text())
        self.assertEqual(set(cache["providers"]), set(self.cfg["providers"]))
        self.assertEqual(list(config.STATE.glob("usage.tmp*")), [])

    def test_v5am_usage_retry_is_specific_and_bounded(self):
        cache = config.STATE / "usage.json"
        collision = FileNotFoundError(errno.ENOENT, "missing", str(cache.with_suffix(".tmp")),
                                      None, str(cache))
        snapshot = {"provider": "fixture"}
        with patch.object(run.usage, "collect", side_effect=[collision, snapshot]) as collect:
            self.assertEqual(run.collect_usage(self.cfg), snapshot)
            self.assertEqual(collect.call_count, 2)
        for error, expected in ((collision, 2),
                                (FileNotFoundError(errno.ENOENT, "missing", "other.tmp"), 1),
                                (PermissionError(errno.EACCES, "denied", str(cache)), 1)):
            with self.subTest(error=repr(error)), \
                    patch.object(run.usage, "collect", side_effect=error) as collect:
                with self.assertRaises(type(error)):
                    run.collect_usage(self.cfg)
                self.assertEqual(collect.call_count, expected)

    def test_v5am_simultaneous_launches_claim_atomically(self):
        for name in ("one", "two", "three", "four", "five", "six"):
            self.launch(name)
        self.wait(lambda: len(self.states()) == 6 and len(self.calls()) == 2)
        self.assertEqual(sum(s["state"] == "running" for _, s in self.states()), 2)
        queued = sorted((s for _, s in self.states() if s["state"] == "queued"), key=run.slot_order)
        self.finish_all()
        admitted = sorted((s for _, s in self.states()), key=lambda s: s["slot_started_at"])
        self.assertEqual([s["run_id"] for s in admitted[2:]], [s["run_id"] for s in queued])

    def test_v5am_config_default_file_and_env(self):
        os.environ.pop("AK_MAX_RUNS")
        self.assertEqual(config.max_runs(), 0)
        path = config.HOME / "config.toml"
        path.write_text("max_runs = 2\n")
        self.assertEqual(config.max_runs(), 2)
        os.environ["AK_MAX_RUNS"] = "4"
        self.assertEqual(config.max_runs(), 4)
        for value in ("-1", "two", "", "1.5"):
            os.environ["AK_MAX_RUNS"] = value
            with self.assertRaises(config.Error):
                config.max_runs()

        os.environ.pop("AK_MAX_RUNS")
        for value in ("-1", "true", '"3"'):
            path.write_text(f"max_runs = {value}\n")
            with self.assertRaises(config.Error):
                config.max_runs()

    def test_v5am_anyway_still_waits_and_dead_identity_takes_no_slot(self):
        os.environ["AK_MAX_RUNS"] = "1"
        self.launch("one")
        first, _ = self.started("one")
        stale = config.RUNS / "stale"
        stale.mkdir()
        owner = record.process_owner()
        owner["process_identity"]["ticks"] -= 1
        record.save_state(stale, {"run_id": stale.name, "state": "running", **owner})
        self.start(self.task("two"), "--anyway", "--exec", self.executor,
                   "--review", self.reviewer)
        _, queued = self.receipt("two", "queued")
        self.assertEqual(run.slot_note(queued), "waiting for a slot · limit full (1 running) · 0 ahead")
        self.release(first)
        self.started("two")
        self.finish_all()

    def test_v5am_killed_stall_resume_waiter_is_recovered(self):
        os.environ["AK_MAX_RUNS"] = "1"
        victim = self.launch("stalled")
        saved, _ = self.started("stalled")
        watch.kill_tree(victim.pid, log=lambda _: None)
        victim.wait(timeout=5)
        state = record.read_state(saved)
        state["stall_resume_at"] = time.time()
        record.save_state(saved, state)
        self.launch("occupier")
        first, _ = self.started("occupier")
        waiter = self.start("resume", saved.name, "--rounds", "2")
        _, state = self.receipt("stalled", "queued")
        self.assertEqual(state["resume_from"], "running")
        waiter.terminate()
        waiter.wait(timeout=5)
        self.release(first)
        self.recover()
        self.wait(lambda: len([c for c in self.calls() if c["id"] == saved.name]) == 2)
        self.assertEqual(record.read_state(saved)["rounds"], 2)
        self.assertEqual(record.read_state(saved)["queued_at"], state["queued_at"])
        self.release(saved)
        self.wait(lambda: not record.process_active(record.read_state(saved)))

    def test_v5am_invalid_queued_task_does_not_block_followers(self):
        os.environ["AK_MAX_RUNS"] = "1"
        self.launch("one")
        first, _ = self.started("one")
        proc = self.launch("broken")
        broken, _ = self.receipt("broken", "queued")
        proc.terminate()
        proc.wait(timeout=5)
        (broken / "task.md").unlink()
        self.launch("three")
        self.receipt("three", "queued")
        self.recover()
        self.wait(lambda: record.read_state(broken)["state"] == "error")
        self.release(first)
        third, _ = self.started("three")
        self.release(third)


if __name__ == "__main__":
    unittest.main()
