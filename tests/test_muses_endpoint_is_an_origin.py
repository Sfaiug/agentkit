"""Muse's usage probe asks the origin `AK_MUSE_URL` names in place of Meta's and of the base
Muse's login names, and, unset, what it asked before; so the key that judges the probe hands its
adapter that origin, not a `sitecustomize.py` only Python would load."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import usage_probe
from agentkit.harness import muse_usage
import test_key_muse_usage_survives_a_retired_model as key


def opened(scheme, log):
    """http.client's connection for `scheme`, logging where each request goes and refusing it."""
    class Connection:
        def __init__(self, host, port, timeout):
            self.where = (scheme, host, port)

        def request(self, method, path, body, headers):
            log.append((*self.where, method, path))
            raise OSError("no network here")

        def close(self):
            pass
    return Connection


class Origin(unittest.TestCase):
    def asked(self, base=None, url=None):
        """Where the probe sent its requests, with Muse's login naming `base` and `AK_MUSE_URL`
        set to `url`."""
        log, env = [], {usage_probe.WORK_DEADLINE_ENV: str(time.monotonic() + 30),
                        "META_API_KEY": "fixture-key", **({"AK_MUSE_URL": url} if url else {})}
        with tempfile.TemporaryDirectory(prefix="ak-test-muse-origin-") as tmp, \
                mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(muse_usage, "AUTH", Path(tmp) / "auth.json"), \
                mock.patch.object(muse_usage, "model_policy", lambda: [("muse-acme-1", "low")]), \
                mock.patch("http.client.HTTPConnection", opened("http", log)), \
                mock.patch("http.client.HTTPSConnection", opened("https", log)):
            if base:
                muse_usage.AUTH.write_text(json.dumps(
                    {"providers": {"meta": {"api_key": "acme-key", "api_base_url": base}}}))
            self.assertEqual(muse_usage.fresh()["error"], "unknown: responses probe failed")
        return log

    def test_unset_it_asks_meta(self):
        self.assertEqual(self.asked(), [("https", "api.meta.ai", 443, "POST", "/v1/responses")])

    def test_unset_it_asks_the_base_muse_logs_in_to(self):
        self.assertEqual(self.asked("https://muse.acme.example/v1"),
                         [("https", "muse.acme.example", 443, "POST", "/v1/responses")])

    def test_set_it_is_asked_in_place_of_either(self):
        for base in (None, "https://muse.acme.example/v1"):
            self.assertEqual(self.asked(base, "http://127.0.0.1:8123"),
                             [("http", "127.0.0.1", 8123, "POST", "/v1/responses")])

    def test_the_key_hands_its_adapter_the_origin_and_no_sitecustomize(self):
        run, handed = subprocess.run, []

        def adapter(argv, env, **kw):
            handed.append(env["AK_MUSE_URL"])
            paths = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
            self.assertEqual([p for p in paths if (Path(p) / "sitecustomize.py").exists()], [])
            return run(argv, env=env, **kw)
        with mock.patch.object(subprocess, "run", adapter):
            data, requests = key.RetiredModel().usage({key.RETIRED: 200})
        self.assertIsNone(data["error"])
        self.assertEqual(len(requests), 1)
        self.assertRegex(handed[0], r"^http://127\.0\.0\.1:\d+$")


if __name__ == "__main__":
    unittest.main()
