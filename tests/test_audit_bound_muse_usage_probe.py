"""Finding 9: bounded, cached Muse usage; fake credentials, network and harnesses only."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, muse_usage, usage, usage_probe


# Loaded only by fixture children. HTTPS is replaced before the real adapter imports it;
# even a regression that tries another network route can reach only the loopback bridge.
NETWORK = r'''
import http.client, json, os, pathlib, socket, subprocess, sys
root = pathlib.Path(os.environ["MUSE_FIXTURE"])
original_connect = socket.socket.connect
def local_connect(sock, address):
    assert isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"), "external network forbidden"
    return original_connect(sock, address)
socket.socket.connect = local_connect

class Connection:
    def __init__(self, host, port, timeout):
        assert host == "api.meta.ai" and port == 443
        assert 0 < timeout <= float(os.environ["AGENTKIT_MUSE_USAGE_TIMEOUT"])
        self.proc = None
    def request(self, method, path, body, headers):
        assert method == "POST" and path == "/v1/responses"
        assert headers["authorization"] == "Bearer " + os.environ["FIXTURE_SECRET"]
        with (root / "requests").open("a") as fh:
            fh.write(json.dumps(json.loads(body)) + "\n")
        if os.environ.get("RESPONSE") == "exception":
            raise OSError(os.environ["FIXTURE_SECRET"])
        self.proc = subprocess.Popen([str(root / "bin" / "network")], stdout=subprocess.PIPE)
    def getresponse(self):
        response = type("Response", (), {
            "__iter__": lambda obj: iter(obj.stream),
            "read": lambda obj, count: obj.stream.read(count)})()
        response.status = int(self.proc.stdout.readline())
        response.stream = self.proc.stdout
        return response
    def close(self):
        if self.proc:
            self.proc.stdout.close()
http.client.HTTPSConnection = Connection
'''


PROCESS = r'''
import http.client, json, os, pathlib, signal, subprocess, sys, time
from urllib.parse import urlsplit
root = pathlib.Path(os.environ["MUSE_FIXTURE"])
kind = pathlib.Path(sys.argv[0]).name
with (root / "pids").open("a") as fh:
    fh.write(json.dumps({"pid": os.getpid(), "kind": kind, "args": sys.argv}) + "\n")
signal.signal(signal.SIGTERM, signal.SIG_IGN)
if kind == "descendant":
    time.sleep(60)
    sys.exit(0)
subprocess.Popen([str(root / "bin" / "descendant")],
                 start_new_session=sys.platform == "linux",
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if kind == "muse":
    if sys.argv[1] == "exec":
        print("429 Subscription quota exhausted; resets at 2099-01-02T03:04:05Z", file=sys.stderr)
        # Run-path testing needs no descendant; let this one finish and reap it here.
        for child in pathlib.Path(f"/proc/{os.getpid()}/task/{os.getpid()}/children").read_text().split():
            os.kill(int(child), signal.SIGKILL)
            os.waitpid(int(child), 0)
        sys.exit(1)
    # Both streams deliberately contain the fake credential: neither may reach diagnostics.
    print(os.environ["FIXTURE_SECRET"], flush=True)
    print(os.environ["FIXTURE_SECRET"], file=sys.stderr, flush=True)
    assert os.environ["MUSE_NO_AUTO_UPDATE"] == "1"
    assert pathlib.Path(os.environ["XDG_DATA_HOME"]).is_relative_to(root)
    if os.environ.get("CREDENTIAL") != "timeout":
        time.sleep(float(os.environ.get("CREDENTIAL_DELAY", "0")))
        url = urlsplit(sys.argv[sys.argv.index("--base-url") + 1])
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=1)
        conn.request("GET", "/muse-code/models", headers={"authorization": "Bearer " + os.environ["FIXTURE_SECRET"]})
        conn.getresponse().read()
        conn.close()
    time.sleep(60)
else:
    mode = os.environ.get("RESPONSE", "success")
    if mode == "timeout":
        time.sleep(60)  # hung DNS/headers: no per-socket timeout can rescue this fake
    if mode == "drip":
        print(200, flush=True)
        while True:
            print(": keepalive", flush=True)
            time.sleep(.06)
    time.sleep(float(os.environ.get("RESPONSE_DELAY", "0")))
    status = {"capacity": 429, "quota": 429, "server": 503}.get(mode, 200)
    print(status, flush=True)
    if status != 200:
        reset = " resets at 2099-01-02T03:04:05Z" if mode == "quota" else ""
        print("Service unavailable " + os.environ["FIXTURE_SECRET"] + reset, flush=True)
    elif mode == "unknown":
        print('data: []\ndata: invalid\ndata: {"type":"response.completed"}', flush=True)
    elif mode == "empty":
        print('data: {"subscription":{}}', flush=True)
    else:
        stamp = int(time.time()) + (3600 if mode != "past" else -60)
        frame = {"type": "response.subscription_usage", "subscription": {
            "weekly": {"used_percent": 22, "resets_at": stamp + 100 if mode != "past" else stamp},
            "window": {"used_percent": 0, "resets_at": stamp, "window_duration_mins": 300}}}
        print("data: " + json.dumps(frame), flush=True)
'''


class MuseProbe(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".muse-probe-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.fixture_repo = self.root / "repo"
        for directory in ("agentkit", "agentkit/harness", "adapters"):
            (self.fixture_repo / directory).mkdir(parents=True)
        # the probe and the harness plugin that says the policy is Muse's, and nothing else
        for name in ("__init__.py", "config.py", "usage_probe.py", "muse_usage.py",
                     "harness/__init__.py", "harness/muse.py"):
            shutil.copy2(REPO / "agentkit" / name, self.fixture_repo / "agentkit" / name)
        for name in ("muse.sh", "muse-usage.sh", "muse.toml"):
            shutil.copy2(REPO / "adapters" / name, self.fixture_repo / "adapters" / name)
        self.policy = self.fixture_repo / "config.default.toml"
        self.policy.write_bytes((REPO / "config.default.toml").read_bytes())
        self.cfg = tomllib.loads(self.policy.read_text())
        self.cfg["providers"] = {"meta": self.cfg["providers"]["meta"]}
        self.home = self.root / "home"
        self.state = self.home / ".agentkit" / "state"
        self.state.mkdir(parents=True)
        self.auth = self.home / ".config" / "muse" / "auth.json"
        self.auth.parent.mkdir(parents=True)
        self.auth.write_text('{"providers":{"meta":{}}}')
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.site = self.root / "site"
        self.site.mkdir()
        (self.site / "sitecustomize.py").write_text(NETWORK)
        for name in ("muse", "network", "descendant"):
            self.script(self.bin / name, PROCESS)
        for name in ("claude", "codex", "gh", "curl"):
            self.script(self.bin / name, 'raise AssertionError("external call forbidden")')
        self.script(self.bin / "tmux", '''import os, sys
assert sys.argv[1:3] == ["-L", "agentkit-test"]
assert os.environ["TMUX_TMPDIR"].startswith(os.environ["MUSE_FIXTURE"])
raise AssertionError("this regression needs no tmux server")
''')
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        scratch = self.root / "tmp"
        scratch.mkdir()
        self.secret = "fixture-credential-do-not-print-92813"
        env = {
            "HOME": str(self.home), "PATH": f"{self.bin}:{os.environ['PATH']}",
            "XDG_CONFIG_HOME": str(self.auth.parent.parent), "XDG_DATA_HOME": str(self.root / "data"),
            "TMPDIR": str(scratch), "PYTHONPATH": str(self.site), "PYTHONDONTWRITEBYTECODE": "1",
            "MUSE_FIXTURE": str(self.root), "FIXTURE_SECRET": self.secret, "META_API_KEY": self.secret,
            "AGENTKIT_MUSE_USAGE_TIMEOUT": "2", "AGENTKIT_MUSE_USAGE_MODEL": "ignored-env-model",
            "AGENTKIT_ADAPTER_DIR": str(self.fixture_repo / "adapters"), "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "AGENTKIT_DISCORD_WEBHOOK": "off", "NO_COLOR": "1",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(sockets), "TMUX": "",
            "RESPONSE": "success", "RESPONSE_DELAY": "0", "CREDENTIAL": "success", "CREDENTIAL_DELAY": "0",
        }
        self.stack.enter_context(patch.dict(os.environ, env))
        for name in (usage_probe.DEADLINE_ENV, usage_probe.WORK_DEADLINE_ENV):
            os.environ.pop(name, None)
        (self.auth.parent / "settings.json").write_text('{"model":"ignored-settings-model"}')
        self.stack.enter_context(patch.object(config, "STATE", self.state))
        self.stack.enter_context(patch.object(config, "ensure_dirs", lambda: None))
        self.children = []
        self.addCleanup(self.clean_children)

    def script(self, path, body):
        path.write_text(f"#!{sys.executable}\n{body}\n")
        path.chmod(0o755)

    def records(self, name):
        path = self.root / name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def clean_children(self):
        # Emergency cleanup on assertion failure is confined to fixture PIDs and processes.
        for proc in self.children:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1)
        for record in self.records("pids"):
            try:
                os.kill(record["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass

    def assert_clean(self):
        for record in self.records("pids"):
            with self.subTest(process=record):
                self.assertNotIn(self.secret, json.dumps(record))
                # Zombies count as leaks too; the supervisor must reap, not merely signal.
                with self.assertRaises(ProcessLookupError):
                    os.kill(record["pid"], 0)

    def assert_safe(self, data):
        self.assertNotIn(self.secret, json.dumps(data))
        for path in self.state.iterdir():
            self.assertNotIn(self.secret, path.read_text())

    def direct(self, helper=False):
        script = "muse-usage.sh" if helper else "muse.sh"
        argv = [str(self.fixture_repo / "adapters" / script)] + ([] if helper else ["usage"])
        started = time.monotonic()
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.children.append(proc)
        stdout, stderr = proc.communicate(timeout=float(os.environ["AGENTKIT_MUSE_USAGE_TIMEOUT"]) + 2)
        self.assertEqual(proc.returncode, 0, stderr)
        self.assertEqual(stderr, "")
        self.assertLess(time.monotonic() - started, float(os.environ["AGENTKIT_MUSE_USAGE_TIMEOUT"]) + .5)
        data = json.loads(stdout)
        self.assert_safe(data)
        self.assert_clean()
        return data

    def collect(self):
        started = time.monotonic()
        data = usage.collect(self.cfg)["meta"]
        self.assertLess(time.monotonic() - started, float(os.environ["AGENTKIT_MUSE_USAGE_TIMEOUT"]) + .5)
        self.assert_safe(data)
        self.assert_clean()
        return data

    def age(self, name, seconds):
        path = self.state / name
        data = json.loads(path.read_text())
        data["fetched_at"] = time.time() - seconds
        path.write_text(json.dumps(data))

    def minute(self):
        """The host's minute since meta's adapter was last asked, as though it had gone by."""
        (self.state / "meta-probe.lock").write_text(repr(time.time() - usage.PROBE_EVERY))

    def reset(self, name):
        path = self.state / name
        data = json.loads(path.read_text())
        owner = data["providers"]["meta"] if "providers" in data else data
        for meter in owner["meters"]:
            meter["resets_at"] = time.time() - 1
        path.write_text(json.dumps(data))

    def test_fast_success_and_both_cache_ttls(self):
        first = self.collect()
        self.assertIsNone(first["error"])
        self.assertEqual([m["used"] for m in first["meters"]], [0, 22])
        self.collect()
        self.age("usage.json", 301)
        self.collect()
        self.direct(helper=True)
        self.assertEqual(len(self.records("requests")), 1)
        self.age("usage-meta-probe.json", 1801)
        self.direct()
        self.assertEqual(len(self.records("requests")), 2)

    def test_configured_model_and_effort_ignore_other_preferences(self):
        source = self.policy.read_text()
        source = source.replace('model = "muse-spark-1.3-contributor"', 'model = "fixture-from-toml"')
        source = source.replace('usage_effort = "minimal"', 'usage_effort = "fixture-effort"')
        self.policy.write_text(source)
        self.assertIsNone(self.direct()["error"])
        request = self.records("requests")[0]
        self.assertEqual(request["model"], "fixture-from-toml")
        self.assertEqual(request["reasoning"], {"effort": "fixture-effort"})
        self.assertEqual(request["input"], "x")
        self.assertEqual(request["max_output_tokens"], 16)
        self.assertEqual(len(self.records("requests")), 1)

    def test_near_deadline_success_is_kept_by_caller(self):
        os.environ.update(AGENTKIT_MUSE_USAGE_TIMEOUT="3", RESPONSE_DELAY="1.95")
        started = time.monotonic()
        self.assertIsNone(self.collect()["error"])
        self.assertGreater(time.monotonic() - started, 1.9)
        self.assertEqual(len(self.records("requests")), 1)

    def test_credential_extraction_timeout_and_success_clean_descendants(self):
        os.environ.update(META_API_KEY="", CREDENTIAL="timeout", AGENTKIT_MUSE_USAGE_TIMEOUT="1.6")
        data = self.direct()
        self.assertEqual(data["meters"], [])
        self.assertIn("credential extraction timed out", data["error"])
        self.direct()
        self.assertEqual(len([p for p in self.records("pids") if p["kind"] == "muse"]), 1)
        self.assertEqual(self.records("requests"), [])
        self.age("usage-meta-probe.json", 1801)
        os.environ.update(CREDENTIAL="success", CREDENTIAL_DELAY=".1", AGENTKIT_MUSE_USAGE_TIMEOUT="2")
        self.assertIsNone(self.collect()["error"])
        self.assertEqual(len(self.records("requests")), 1)
        self.assertEqual(list((self.root / "tmp").iterdir()), [])

    def test_model_timeouts_bound_hung_headers_and_dripping_stream(self):
        for mode in ("timeout", "drip"):
            with self.subTest(mode=mode):
                os.environ.update(RESPONSE=mode, AGENTKIT_MUSE_USAGE_TIMEOUT="1.2")
                (self.state / "usage.json").unlink(missing_ok=True)
                (self.state / "usage-meta-probe.json").unlink(missing_ok=True)
                self.minute()
                before = len(self.records("requests"))
                data = self.collect()
                self.assertEqual(data["meters"], [])
                self.assertIn("timed out", data["error"])
                self.direct()
                self.assertEqual(len(self.records("requests")), before + 1)

    def test_capacity_server_and_unknown_results_are_cached_without_leaks(self):
        for mode in ("capacity", "server", "unknown", "empty", "exception", "past"):
            with self.subTest(mode=mode):
                os.environ["RESPONSE"] = mode
                (self.state / "usage-meta-probe.json").unlink(missing_ok=True)
                before = len(self.records("requests"))
                data = self.direct()
                self.assertEqual(data["meters"], [])
                self.assertTrue(data["error"].startswith("unknown:"))
                if mode in ("capacity", "server"):
                    self.assertIn("HTTP " + ("429" if mode == "capacity" else "503"), data["error"])
                self.assertNotIn("timed out", data["error"])
                self.direct()
                self.assertEqual(len(self.records("requests")), before + 1)

    def test_quota_probe_is_spent_until_reset_then_refreshes(self):
        os.environ["RESPONSE"] = "quota"
        data = self.collect()
        self.assertTrue(data["exhausted"])
        self.assertEqual(data["meters"][0]["used"], 100)
        self.collect()
        self.assertEqual(len(self.records("requests")), 1)
        self.reset("usage.json")
        self.reset("usage-meta-probe.json")
        os.environ["RESPONSE"] = "success"
        # The window has rolled over inside both the host's minute and Muse's ten: nothing is
        # asked, and the spent reading is gone rather than shown.
        data = self.collect()
        self.assertFalse(data["exhausted"])
        self.assertEqual(data["meters"], [])
        # Past the minute the adapter is asked, and its cache answers: still no paid request.
        self.minute()
        self.age("usage.json", 301)
        self.assertEqual(self.collect()["meters"], [])
        self.assertEqual(len(self.records("requests")), 1)
        # Past the ten minutes, the one request reads the new window.
        self.minute()
        self.age("usage.json", 301)
        self.age("usage-meta-probe.json", muse_usage.CACHE_TTL)
        self.assertFalse(self.collect()["exhausted"])
        self.assertEqual(len(self.records("requests")), 2)

    @unittest.skipUnless(sys.platform == "linux", "run fixture uses Linux child bookkeeping")
    def test_recorded_run_quota_keeps_both_caches_and_wins_until_reset(self):
        self.collect()
        prompt = self.root / "prompt"
        prompt.write_text("offline fixture")
        out = self.root / "out"
        entry = self.cfg["models"][self.cfg["providers"]["meta"]["usage_model"]]
        proc = subprocess.run([str(self.fixture_repo / "adapters" / "muse.sh"), "run",
                               entry["model"], entry["effort"], str(self.fixture_repo), str(prompt), str(out)],
                              capture_output=True, text=True, timeout=3)
        self.assertEqual(proc.returncode, 1)
        # Neither cache goes, and the next read, inside the snapshot's five minutes and the
        # probe's minute, is exhausted all the same.
        self.assertTrue((self.state / "usage.json").exists())
        self.assertTrue((self.state / "usage-meta-probe.json").exists())
        self.assertTrue(self.collect()["exhausted"])
        self.assertEqual(len(self.records("requests")), 1)
        self.reset("usage-meta.json")
        self.reset("usage.json")
        self.assertFalse(self.collect()["exhausted"])
        self.assertEqual(len(self.records("requests")), 1)   # the paid probe keeps its ten minutes

    def test_overlapping_reads_make_one_request(self):
        os.environ["RESPONSE_DELAY"] = ".3"
        # Wait for both callers before checking PIDs: one may still be cleaning the shared probe.
        argv = [str(self.fixture_repo / "adapters" / "muse.sh"), "usage"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: subprocess.run(argv, capture_output=True, text=True, timeout=4), range(2)))
        for proc in results:
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIsNone(json.loads(proc.stdout)["error"])
        self.assert_clean()
        self.assertEqual(len(self.records("requests")), 1)

    def test_caller_bounds_even_an_adapter_that_ignores_the_contract(self):
        self.script(self.fixture_repo / "adapters" / "muse.sh", '''import os, pathlib, subprocess, time
root = pathlib.Path(os.environ["MUSE_FIXTURE"])
subprocess.Popen([str(root / "bin" / "network")])
time.sleep(60)
''')
        os.environ.update(RESPONSE="timeout", AGENTKIT_MUSE_USAGE_TIMEOUT="1.2")
        data = self.collect()
        self.assertIn("timed out", data["error"])

    def test_budget_validation_and_invalid_policy_make_no_request(self):
        for value in ("nan", "inf", "0", "-1", "46", "invalid"):
            with patch.dict(os.environ, AGENTKIT_MUSE_USAGE_TIMEOUT=value):
                self.assertEqual(usage_probe.budget(), 45)
        self.policy.write_text(self.policy.read_text().replace('usage_model = "spark"', 'usage_model = "missing"'))
        self.assertIn("config.toml", self.direct()["error"])
        self.assertEqual(self.records("requests"), [])

    def test_cancelled_direct_probe_reaps_descendants(self):
        os.environ["RESPONSE"] = "timeout"
        argv = [str(self.fixture_repo / "adapters" / "muse.sh"), "usage"]
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.children.append(proc)
        deadline = time.monotonic() + 1
        while not any(p["kind"] == "descendant" for p in self.records("pids")):
            self.assertLess(time.monotonic(), deadline, "fixture did not start")
            time.sleep(.01)
        proc.terminate()
        stdout, stderr = proc.communicate(timeout=2)
        self.assertEqual(stderr, "")
        self.assertIn("cancelled", json.loads(stdout)["error"])
        self.assert_clean()
        self.direct()
        self.assertEqual(len(self.records("requests")), 1)


if __name__ == "__main__":
    unittest.main()
