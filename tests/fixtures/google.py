"""Google Cloud for an answer-key Home, stood in for by a loopback HTTP server of the test's own.

`Google(home, skus, zones)` answers `ak doctor` on every host Google has (`AK_GOOGLE_URL`): a
token for any signed JWT, Compute Engine's price list from `skus` and the machine types zones
offer from `zones`, each a list of pages handed out in order.  `sku` and `kind` make their
entries, `ADDRESS` is a Spot machine's address.  `missed` joins every page of machine types,
`{"unreachables": [...]}` naming zones Google could not reach.  `buckets`, {(region, family):
vCPUs}, are Service Usage's `cpus_per_vm_family`, None refused, and `quotas`, {region or
project: {metric: vCPUs}}, Compute Engine's.  `asked` is every path asked, oldest first, `made` every machine,
answered by the next of `answers`, `(body, code, bytes promised that never come)`, else made.
`key` writes a service-account key ak can sign with, `rented` runs `ak doctor` and gives its
rented-machines lines, `at` a tick on the test clock, `close` stops it:

    from fixtures.akbin import Home
    from fixtures.google import Google, kind
    with Home() as home:
        google = Google(home, [[]], [{"zones/europe-west4-a": {"machineTypes": [
            kind("c4a-standard-8", 8, 32)]}}])
        google.key()
        assert google.rented() == ["rented machines: nothing offered"]
        google.close()
"""

import http.server
import json
import subprocess
import tempfile
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fixtures import akconfig
from fixtures.akbin import AK, REPO

SPOT, NL, IOWA = "Spot Preemptible", ["europe-west4"], ["us-central1"]
PROJECT = "/compute/v1/projects/acme-build"
ECHO = {"AGENTKIT_ADAPTER_DIR": str(REPO / "tests/fixtures/adapters")}
# Every `bin/ak` gives `google_cloud` the test clock, at the time in the file it names.
CLOCK = """
import sys, time
if sys.argv[:1] == [{ak!r}]:
    sys.path[:0] = [{repo!r}, {tests!r}]
    from fixtures.clock import Clock
    from agentkit import google_cloud
    del sys.path[:2]
    google_cloud.time = Clock(time.sleep)
    google_cloud.time.time = lambda: float(open({now!r}).read())
"""


def sku(description, regions, nanos, unit="h"):
    rate = {"unitPrice": {"units": "0", "nanos": nanos}}
    return {"description": description, "serviceRegions": regions, "pricingInfo": [
        {"pricingExpression": {"usageUnit": unit, "tieredRates": [rate]}}]}


def kind(name, vcpus, gb, architecture="ARM64"):
    return {"name": name, "guestCpus": vcpus, "memoryMb": int(gb * 1024),
            "architecture": architecture}


ADDRESS = sku("External IP Charge on a Spot Preemptible VM", ["global"], 2_500_000)
SKUS = [sku(f"{SPOT} C4A Arm Instance Core running in Netherlands", NL, 700_000_000),
        sku(f"{SPOT} C4A Arm Instance Ram running in Netherlands", NL, 12_500_000),
        sku("Hyperdisk Balanced Capacity in Netherlands", NL, 73_000_000, "GiBy.mo"), ADDRESS]


class Google(http.server.ThreadingHTTPServer):
    def __init__(self, home, skus, zones):
        super().__init__(("127.0.0.1", 0), _Answers)
        self.home, self.skus, self.zones, self.asked, self.missed = home, skus, zones, [], {}
        # europe-west4-a's machines; by name, those read again as others and refused deletions
        self.machines, self.again, self.refused, self.silent = [], {}, set(), False
        self.made, self.answers, self.buckets, self.quotas = [], [], {}, {}
        self.env = {**ECHO, "AK_GOOGLE_URL": f"http://127.0.0.1:{self.server_address[1]}"}
        # ak doctor checks the models a config names: one that asks nobody
        akconfig.write(home, {"echo": {"harness": "echo", "model": "echo-1"}})
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def close(self):
        self.shutdown()
        self.server_close()

    def key(self):
        with tempfile.NamedTemporaryFile() as pem:
            subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-out", pem.name], check=True,
                           capture_output=True)
            self.home.write(".agentkit/secrets/google-cloud.json", {
                "project_id": "acme-build", "client_email": "ak@acme-build.example",
                "private_key": Path(pem.name).read_text()})

    def rented(self):
        done = self.home.ak("doctor", env=self.env)
        if done.code:
            raise AssertionError(done.out + done.err)
        return [line for line in done.out.splitlines() if line.startswith("rented machines: ")]

    def at(self, when, cap=50):
        """At `when` and a cap of `cap` euros, 0 not active, what a tick asked Google, whom it
        deleted, and `ak doctor`'s lines then."""
        home, toml = self.home, self.home.path / ".agentkit/config.toml"
        toml.write_text(toml.read_text().split("\n[google_cloud]")[0] + "\n[google_cloud]\n"
                        f"active = {'true' if cap else 'false'}\nmax_month = {cap}\n")
        home.write("clock/sitecustomize.py", CLOCK.format(
            ak=AK, repo=str(Path(AK).resolve().parents[1]), tests=str(REPO / "tests"),
            now=str(home.path / "clock" / "now")))
        self.env["PYTHONPATH"] = str(home.path / "clock")
        home.write("clock/now", str(when))
        start, done = len(self.asked), home.tick(env=self.env)
        assert done.code == 0, done.out + done.err
        asked = self.asked[start:]
        return asked, [one[7:] for one in asked if one.startswith("DELETE ")], [
            line.removeprefix("rented machines: ") for line in self.rented()]


class _Answers(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def answer(self, body, code=200, more=0):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data) + more))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.server.asked.append(self.path)
        if self.server.silent:
            return
        data = self.rfile.read(int(self.headers["Content-Length"]))
        if not self.path.endswith("/instances"):
            return self.answer({"access_token": "ya29.acme"})
        self.server.made.append(json.loads(data))
        self.answer(*self.server.answers.pop(0) if self.server.answers else [{"status": "DONE"}])

    def do_DELETE(self):
        self.server.asked.append(f"DELETE {(name := self.path.rsplit('/', 1)[1])}")
        return self.send_error(403) if name in self.server.refused else self.answer({})

    def do_GET(self):
        self.server.asked.append(self.path)
        url = urlsplit(self.path)
        if "/instances/" in url.path:
            found = ({one["name"]: one for one in self.server.machines} | self.server.again).get(
                url.path.rsplit("/", 1)[1])
            return self.answer(found) if found else self.send_error(404)
        if url.path.endswith("%2Fcpus_per_vm_family"):
            if self.server.buckets is None:
                return self.send_error(403)
            return self.answer({"consumerQuotaLimits": [{"quotaBuckets": [{
                "effectiveLimit": str(limit), "dimensions": {"region": region, "vm_family": family}}
                for (region, family), limit in self.server.buckets.items()]}]})
        if url.path == PROJECT or url.path.startswith(f"{PROJECT}/regions/"):
            quotas = self.server.quotas.get(url.path.rsplit("/", 1)[1], {})
            return self.answer({"quotas": [{"metric": metric, "limit": float(limit)}
                                           for metric, limit in quotas.items()]})
        pages = {"/v1/services/6F81-5844-456A/skus": [{"skus": skus} for skus in self.server.skus],
                 f"{PROJECT}/aggregated/machineTypes":
                     [{"items": zones, **self.server.missed} for zones in self.server.zones],
                 f"{PROJECT}/aggregated/instances":
                     [{"items": {"zones/europe-west4-a": {"instances": self.server.machines}}}]}
        listing, at = pages[url.path], int(parse_qs(url.query).get("pageToken", ["0"])[0])
        self.answer({**listing[at], **({"nextPageToken": str(at + 1)}
                                       if at + 1 < len(listing) else {})})
