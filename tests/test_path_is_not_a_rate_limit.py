"""Paths, line references and run ids never park a provider, hide its login, or excuse a failed adapter."""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, harness, run, usage, worker
import check_harness_contract as contract

PATHS = (
    "/tmp/acme-429/run/log.txt",
    "~/.agentkit/wt/20261004-0726-review-pr-acme-429/round-1/log.txt",
    "./acme-429/run.log",
    "acme-429/log.txt",
    "/tmp/429",
    "/tmp/acme(429)/run.log",
    "20261004-0726-review-pr-acme-429",
    "log-429.txt",
    r"C:\tmp\acme-429\log.txt",
    r"\\acme\429\log.txt",
    "/tmp/acme:429",
    "agentkit/run.py:429:7",
    'File "/tmp/acme/run.py", line 429, in main',
    "20261004-0726-run.log.429",
    "20261004-0726-run.log-429",
    "20261004-0726-run.log.503",
    "20261004-0726-run.log-529",
    "run.log.429",
    "run.log-429",
    "~/.agentkit/wt/20261005-0626-fix-agentkit-quota-wait/round-1/log.txt",
    "/home/acme/.agentkit/runs/20261005-0626-fix-agentkit-rate-limit-wait/log.txt",
    "20261005-0626-fix-agentkit-overloaded-at-capacity",
    "20261005-0626-fix-agentkit-authentication-error",
)
# what a worker names: its run's own directory, named by the run id, never by the checkout's name
RUN_DIR = "/home/acme/.agentkit/runs/20261004-0726-review-pr-acme-429"
REFUSALS = {
    "claude": "API Error:429",
    "codex": "429 Too Many Requests",
    "muse": "429",
    "grokbuild": "429",
    "opencode": '{"error":{"status":429}}',
    "antigravity": "(code 429)",
}


class PathIsNotARateLimit(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-path-429-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AK_", "AGENTKIT_"))}
        env.update(HOME=str(self.root), AK_RUN_DEPTH="0", AK_MAX_RUNS="0",
                   AGENTKIT_DISCORD_WEBHOOK="off")
        self.stack.enter_context(patch.dict(os.environ, env, clear=True))
        config.ensure_dirs()
        self.cfg = {"models": {"acme": {"harness": "grokbuild", "model": "acme-model",
                                     "effort": "high", "provider": "acme"}},
                    "providers": {"acme": {"mode": "subscription"}}}

    def turn(self, text, said):
        def fake(_cfg, _name, _body, _workspace, out, *_args, **_kw):
            out.mkdir(parents=True, exist_ok=True)
            (out / "final.md").write_text(text)
            (out / "stderr.log").write_text(said)
            (out / "events.jsonl").write_text(json.dumps({"type": "error", "error": said}) + "\n")
            return 1, text, "acme-session", False, False
        return fake

    def test_paths_and_run_ids_are_not_limit_words(self):
        for path in PATHS:
            # an error event is read re-encoded, as run.failures gives it
            for said in (f"Stopped at {path}", *("\n".join(run.failures(json.dumps(
                    {"type": "error", "error": f"Stopped at{gap}{path}"}), None))
                    for gap in (" ", "\n", "\t", "\r\n"))):
                with self.subTest(said=said):
                    self.assertFalse(harness.limited(said))
                    self.assertIsNone(usage.probe_refused(said))
                    for name in REFUSALS:
                        self.assertEqual(harness.load(name).failure(said), (None, None), name)
                        self.assertEqual(harness.load(name).failure(said, ran=False), (None, None),
                                         name)
                        self.assertIsNone(run.ran_dry(1, said, name), name)

    def test_real_refusals_still_count_beside_a_path(self):
        for name, refusal in REFUSALS.items():
            for said in (refusal, f"{PATHS[0]}: {refusal}", f"{refusal}; log: {PATHS[0]}"):
                with self.subTest(name=name, said=said):
                    self.assertTrue(harness.limited(said))
                    self.assertEqual(usage.probe_refused(said), "rate limited")
                    self.assertEqual(harness.load(name).failure(said)[0], harness.LIMITED)
                    self.assertIsNotNone(run.ran_dry(1, said, name))
        for said in ("HTTP/1.1 429 Too Many Requests", "429.",
                     json.dumps({"error": "429\nTry again later", "path": PATHS[0]}),
                     json.dumps({"status": 429, "path": PATHS[0]})):
            with self.subTest(said=said):
                self.assertTrue(harness.limited(said))
        self.assertFalse(harness.says(f"HTTP {PATHS[0]} 503", "HTTP~5##"))
        # a harness's own dotted name is its word, not a file name
        opencode = harness.load("opencode")
        for said in ("provider.rate-limit", "/tmp/20261005-0626-fix-api.provider.rate-limit",
                     json.dumps({"type": "error", "error": {
                "type": "provider.rate-limit", "status": 429, "message": "Too Many Requests"}})):
            with self.subTest(said=said):
                self.assertEqual(opencode.failure(said)[0], harness.LIMITED)
        self.assertEqual(opencode.failure(
            json.dumps({"type": "error", "error": {"type": "provider.quota"}}))[0], harness.SPENT)

    def test_a_word_beside_a_path_or_in_a_url_is_still_said(self):
        for name, word, expected in (("opencode", "quota", harness.SPENT),
                                     ("claude", "rate_limit_error", harness.LIMITED),
                                     ("opencode", "overloaded", harness.REFUSAL)):
            for message in [word + gap + "/tmp/acme/log.txt" for gap in ("\n", "\t", "\r\n")] + [
                    f"Error: [/tmp/acme/log.txt][{word}]", f"Error: (/tmp/acme/log.txt)({word})",
                    f"Error: https://api.acme.test/?error=/{word}",
                    f"Stopped at /tmp/20261005-0626-fix-api.{word}",
                    f"Stopped at C:\\tmp\\t20261005-0626-fix-api-{word}"]:
                # an error event is read re-encoded, its newlines and tabs escaped
                event = "\n".join(run.failures(json.dumps({"type": "error", "error": message}), None))
                for said in (message, event):
                    with self.subTest(name=name, said=said):
                        self.assertEqual(harness.load(name).failure(said)[0], expected)

    def test_a_path_inside_a_word_s_gap_never_hides_it(self):
        for said in ("Error: model acme/acme-v2.6-pro not found",
                     "Error: model acme/acme-v2.6-pro does not exist",
                     "Error: model acme/acme-v2.6-pro is not supported"):
            with self.subTest(said=said):
                self.assertEqual(run.cannot_run(1, "", said, harness="opencode"), said)

    def test_a_status_joined_by_a_hyphen_is_still_the_status(self):
        for said, word in (("HTTP-503", "HTTP~5##"), ("status-503", "status~5##"),
                           ("API Error-503", "API Error~5##"), ("API Error-429", "429")):
            with self.subTest(said=said):
                self.assertTrue(harness.says(said, word))
        for name in REFUSALS:
            for said in ("HTTP-503", "status-503"):
                with self.subTest(name=name, said=said):
                    self.assertIn(harness.load(name).failure(said)[0],
                                  (harness.REFUSAL, harness.OUTAGE))

    def test_an_http_status_line_in_a_failure_event_is_still_the_status(self):
        out = Path(tempfile.mkdtemp(prefix="status-", dir=self.root))
        for message, names, expected in (
                ("HTTP/1.1 429", ("codex", "claude", "muse", "grokbuild", "opencode"), harness.LIMITED),
                ("HTTP/2 429", ("codex", "claude", "muse", "grokbuild", "opencode"), harness.LIMITED),
                ("HTTP/1.1 503", ("codex", "claude", "muse", "grokbuild", "opencode"), harness.REFUSAL),
                ("HTTP/2 (code 429)", ("antigravity",), harness.LIMITED)):
            (out / "events.jsonl").write_text(json.dumps({"type": "error", "error": message}) + "\n")
            for name in names:
                with self.subTest(name=name, message=message):
                    said = run.harness_said(out, "The request failed.", name)
                    self.assertEqual(harness.load(name).failure(said)[0], expected)

    def test_a_worker_naming_a_path_is_not_parked(self):
        for name in REFUSALS:
            self.cfg["models"]["acme"]["harness"] = name
            said = f"Stopped at {RUN_DIR}/log.txt"
            for refusal in (False, True):
                message = f"{REFUSALS[name]}; {said}" if refusal else said
                with self.subTest(name=name, refusal=refusal), \
                        patch.object(worker, "turn", side_effect=self.turn(message, message)), \
                        patch.object(usage, "account", return_value=(None, None)), \
                        patch.object(usage, "replenish", return_value=(False, 0.0)), \
                        patch.object(usage, "mark_exhausted", return_value=2_000_000_000) as parked, \
                        patch.object(run, "transient_wait", side_effect=AssertionError("waited")):
                    args = (self.cfg, "acme", "Do the task.", self.root,
                            self.root / name / "round-1" / "executor", "executor", None, lambda _: None)
                    if refusal:
                        with self.assertRaises(run.RanDry):
                            run.call_retrying(*args)
                        parked.assert_called_once()
                    else:
                        self.assertEqual(run.call_retrying(*args),
                                         (1, message, "acme-session", False))
                        parked.assert_not_called()

    def test_usage_asks_auth_and_keeps_logged_in_for_a_path_error(self):
        self.cfg["models"]["acme"]["harness"] = "claude"
        for error in (f"Cannot read {RUN_DIR}/credentials.json",
                      f"HTTP 429; log: {RUN_DIR}/log.txt"):
            with self.subTest(error=error), \
                    patch.object(usage.subprocess, "run") as probe, \
                    patch.object(usage, "_resets", return_value=0.0), \
                    patch.object(worker, "auth_ok", return_value=(True, "logged in")) as auth:
                probe.return_value.returncode = 0
                probe.return_value.stdout = json.dumps({"meters": [], "error": error})
                fresh = usage._probe(self.cfg, "acme", 1_800_000_000)
                if error.startswith("HTTP"):
                    auth.assert_not_called()
                    self.assertNotIn("logged_in", fresh)
                else:
                    auth.assert_called_once_with("claude")
                    self.assertTrue(fresh["logged_in"])
                    self.assertTrue(usage._kept({}, fresh, 1_800_000_000)["logged_in"])

    def test_an_empty_failed_adapter_turn_is_a_contract_failure(self):
        for refusal in (False, True):
            snapshot = self.root / "usage.json"
            snapshot.write_text('{"providers": {}}')
            said = f"Stopped at {RUN_DIR}/log.txt"
            if refusal:
                said = f"429; {said}"
            output = io.StringIO()
            with self.subTest(refusal=refusal), redirect_stdout(output), \
                    patch.object(contract, "unavailable", return_value=("", False)), \
                    patch.object(worker, "turn", side_effect=self.turn("", said)):
                counts = contract.check(self.cfg, self.root / str(refusal), snapshot,
                                        self.root / "home", "grokbuild")
                self.assertEqual(counts, (0, 0, 1, 0) if refusal else (0, 1, 0, 0),
                                 output.getvalue())
                providers = json.loads(snapshot.read_text())["providers"]
                if refusal:
                    self.assertIn("exhausted_until", providers["acme"])
                else:
                    self.assertIn("adapter exited 1", output.getvalue())
                    self.assertIn("final.md is empty", output.getvalue())
                    self.assertEqual(providers, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
