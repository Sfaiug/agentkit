"""agentkit v5ah: a quoted quota error never spends the real quota.

Offline: every test drives the real ``adapters/muse.sh`` with a fake ``muse``
on ``PATH`` and ``HOME`` pointing at a temporary directory, so only the temp
state dir is ever read or written.  A quoted fixture line -- in the model's
final message or in tool output -- must record nothing; only the harness's own
failure signal (a ``task_lifecycle`` failed event, a ``run_terminal`` reason,
or the harness's own stderr) records a quota.  A recorded quota is trusted for
at most its own window.
"""

import calendar
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADAPTER = REPO / "adapters" / "muse.sh"

_CODE = "42" + "9"
_MODEL_ID = "muse-spark-1.3-contributor"
_FIXTURE_STAMP = "2099-01-02T03:04:05Z"
_REAL_STAMP = "2026-09-11T11:47:21Z"
# The check-10a fixture line and the real refusal reason, assembled from parts
# so that this source states them without quoting them.
_QUOTA_LINE = (_CODE + " Subscription quota exhausted for " + _MODEL_ID
               + "; " + "reset" + "s " + _FIXTURE_STAMP)
_REAL_REASON = ("model failed: API error " + _CODE
                + " [request_id=fixture-request]: Subscription quota exhausted."
                + " Your usage window " + "reset" + "s at " + _REAL_STAMP
                + ". (rate_limit_error)")

STAMP_FMT = "%Y-%m-%dT%H:%M:%SZ"


def window_secs(want, now):
    """The adapter's 5h/weekly sizing rule, evaluated at `now`."""
    return 604800 if (want - now) > 18000 else 18000


class V5AH(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5ah-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.state = self.home / ".agentkit" / "state"
        self.state.mkdir(parents=True)
        self.bindir = self.root / "bin"
        self.bindir.mkdir()
        self.work = self.root / "work"
        self.work.mkdir()
        # The adapter under test must only ever see the temp HOME.
        self.assertNotEqual(str(self.home), os.path.expanduser("~"))

    def _env(self):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env["PATH"] = str(self.bindir) + os.pathsep + env.get("PATH", "")
        env.pop("AGENTKIT_MUSE_PROVIDER", None)
        return env

    def _workspace(self, name):
        ws = self.work / name
        ws.mkdir(parents=True, exist_ok=True)
        prompt = self.work / (name + ".prompt")
        prompt.write_text("fixture prompt\n")
        return ws, prompt

    def _write_muse(self, stdout_text="", stderr_text="", rc=0):
        """A fake `muse`: ignores its args, emits the given streams."""
        out_p = self.bindir / "muse.stdout"
        err_p = self.bindir / "muse.stderr"
        out_p.write_text(stdout_text)
        err_p.write_text(stderr_text)
        fake = self.bindir / "muse"
        fake.write_text(
            "#!/usr/bin/env bash\n"
            "cat -- " + shlex.quote(str(out_p)) + "\n"
            "cat -- " + shlex.quote(str(err_p)) + " >&2\n"
            "exit " + str(rc) + "\n"
        )
        fake.chmod(0o755)

    def _run(self, ws, prompt, out):
        return subprocess.run(
            [str(ADAPTER), "run", "fixture-model", "minimal",
             str(ws), str(prompt), str(out)],
            env=self._env(), capture_output=True, text=True, timeout=60)

    def _usage(self, adapter):
        return subprocess.run(
            [str(adapter), "usage"],
            env=self._env(), capture_output=True, text=True, timeout=60)

    def _meta(self):
        path = self.state / "usage-meta.json"
        return json.loads(path.read_text()) if path.exists() else None

    def _usage_adapter_with_probe(self, probe):
        """A copy of the real adapter beside a fake probe helper."""
        adir = self.root / "adapters"
        adir.mkdir(exist_ok=True)
        shutil.copy2(ADAPTER, adir / "muse.sh")
        (adir / "probe.json").write_text(json.dumps(probe))
        helper = adir / "muse-usage.sh"
        helper.write_text("#!/usr/bin/env bash\ncat -- "
                          + shlex.quote(str(adir / "probe.json")) + "\n")
        helper.chmod(0o755)
        return adir / "muse.sh"

    def test_v5ah_run_terminal_text_quote_records_nothing(self):
        ws, prompt = self._workspace("a")
        event = {"payload": {"kind": "run_terminal", "text": _QUOTA_LINE}}
        self._write_muse(stdout_text=json.dumps(event) + "\n", rc=0)
        sentinel = {"sentinel": "v5ah-a"}
        (self.state / "usage.json").write_text(json.dumps(sentinel))
        out = self.work / "out-a"
        proc = self._run(ws, prompt, out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIsNone(self._meta(), "quote in final text recorded a quota")
        self.assertEqual(json.loads((self.state / "usage.json").read_text()),
                         sentinel)
        final_has_quote = _QUOTA_LINE in (out / "final.md").read_text()
        self.assertTrue(final_has_quote, "quote did not reach final.md")

    def test_v5ah_tool_output_quote_records_nothing(self):
        ws, prompt = self._workspace("b")
        event = {"payload": {"kind": "tool_result", "tool": "read",
                             "output": _QUOTA_LINE}}
        self._write_muse(stdout_text=json.dumps(event) + "\n", rc=0)
        sentinel = {"sentinel": "v5ah-b"}
        (self.state / "usage.json").write_text(json.dumps(sentinel))
        out = self.work / "out-b"
        proc = self._run(ws, prompt, out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIsNone(self._meta(), "quote in tool output recorded a quota")
        self.assertEqual(json.loads((self.state / "usage.json").read_text()),
                         sentinel)
        events_has_quote = _QUOTA_LINE in (out / "events.jsonl").read_text()
        self.assertTrue(events_has_quote, "quote did not reach events.jsonl")

    def test_v5ah_task_lifecycle_failed_records_quota(self):
        ws, prompt = self._workspace("c")
        event = {"payload": {"kind": "task_lifecycle",
                             "event": {"kind": "failed",
                                       "reason": _REAL_REASON}}}
        self._write_muse(stdout_text=json.dumps(event) + "\n", rc=1)
        (self.state / "usage.json").write_text(json.dumps({"primed": True}))
        (self.state / "usage-meta-probe.json").write_text(
            json.dumps({"primed": True}))
        out = self.work / "out-c"
        proc = self._run(ws, prompt, out)
        after = time.time()
        self.assertEqual(proc.returncode, 1, proc.stderr)
        meta = self._meta()
        self.assertIsNotNone(meta, "harness failure recorded no quota")
        want = calendar.timegm(time.strptime(_REAL_STAMP, STAMP_FMT))
        self.assertEqual(meta["meters"],
                         [{"name": "quota", "used": 100, "resets_at": want,
                           "window_secs": window_secs(want, after)}])
        # neither cache goes: one holds every other provider's reading, the other when a
        # paid request was last spent
        self.assertEqual(json.loads((self.state / "usage.json").read_text()), {"primed": True})
        self.assertEqual(json.loads((self.state / "usage-meta-probe.json").read_text()),
                         {"primed": True})

    def test_v5ah_stderr_only_refusal_records_quota(self):
        ws, prompt = self._workspace("d")
        self._write_muse(stderr_text=_QUOTA_LINE + "\n", rc=1)
        (self.state / "usage.json").write_text(json.dumps({"primed": True}))
        out = self.work / "out-d"
        proc = self._run(ws, prompt, out)
        after = time.time()
        self.assertEqual(proc.returncode, 1, proc.stderr)
        meta = self._meta()
        self.assertIsNotNone(meta, "stderr refusal recorded no quota")
        want = calendar.timegm(time.strptime(_FIXTURE_STAMP, STAMP_FMT))
        self.assertEqual(meta["meters"],
                         [{"name": "quota", "used": 100, "resets_at": want,
                           "window_secs": window_secs(want, after)}])
        self.assertEqual(json.loads((self.state / "usage.json").read_text()), {"primed": True})
        logged = _QUOTA_LINE in (out / "stderr.log").read_text()
        self.assertTrue(logged, "refusal did not reach stderr.log")

    def test_v5ah_stale_window_record_falls_through_to_probe(self):
        now = int(time.time())
        probe = {"provider": "meta",
                 "meters": [{"name": "weekly", "used": 22,
                             "resets_at": now + 500000,
                             "window_secs": 604800}],
                 "error": None}
        adapter = self._usage_adapter_with_probe(probe)
        stale = {"meters": [{"name": "quota", "used": 100,
                             "resets_at": now + 10 * 86400,
                             "window_secs": 604800}]}
        meta_path = self.state / "usage-meta.json"
        meta_path.write_text(json.dumps(stale))
        old = now - 604801
        os.utime(meta_path, (old, old))
        proc = self._usage(adapter)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), probe)
        # The stale record is dropped, so even the real probe helper -- which
        # trusts a record on its reset timestamp alone -- answers fresh next.
        self.assertFalse(meta_path.exists(), "stale record was left in place")
        # The same record written fresh is trusted again: age is the discriminator.
        meta_path.write_text(json.dumps(stale))
        proc = self._usage(adapter)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["meters"], stale["meters"])

    def test_v5ah_past_reset_record_is_dropped(self):
        now = int(time.time())
        probe = {"provider": "meta",
                 "meters": [{"name": "weekly", "used": 22,
                             "resets_at": now + 500000,
                             "window_secs": 604800}],
                 "error": None}
        adapter = self._usage_adapter_with_probe(probe)
        past = {"meters": [{"name": "quota", "used": 100,
                            "resets_at": now - 60, "window_secs": 604800}]}
        (self.state / "usage-meta.json").write_text(json.dumps(past))
        proc = self._usage(adapter)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), probe)


if __name__ == "__main__":
    unittest.main()
