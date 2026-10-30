"""Google Cloud for an answer-key Home, stood in for by a loopback HTTP server of the test's own.

`Google(home, skus, zones)` answers `ak doctor` on every host Google has (`AK_GOOGLE_URL`): a
token for any signed JWT, Compute Engine's price list from `skus` and the machine types zones
offer from `zones`, each a list of pages handed out in order.  `sku` and `kind` make their
entries, `ADDRESS` is a Spot machine's address.  `missed` joins every page of machine types,
`{"unreachables": [...]}` naming zones Google could not reach; `asked` is every path asked, oldest
first.  `key` writes a service-account key ak can sign with, `rented` runs `ak doctor` and gives
its rented-machines lines, and `close` stops it:

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
from fixtures.akbin import REPO

SPOT, NL, IOWA = "Spot Preemptible", ["europe-west4"], ["us-central1"]
ECHO = {"AGENTKIT_ADAPTER_DIR": str(REPO / "tests/fixtures/adapters")}


def sku(description, regions, nanos, unit="h"):
    rate = {"unitPrice": {"units": "0", "nanos": nanos}}
    return {"description": description, "serviceRegions": regions, "pricingInfo": [
        {"pricingExpression": {"usageUnit": unit, "tieredRates": [rate]}}]}


def kind(name, vcpus, gb, architecture="ARM64"):
    return {"name": name, "guestCpus": vcpus, "memoryMb": int(gb * 1024),
            "architecture": architecture}


ADDRESS = sku("External IP Charge on a Spot Preemptible VM", ["global"], 2_500_000)


class Google(http.server.ThreadingHTTPServer):
    def __init__(self, home, skus, zones):
        super().__init__(("127.0.0.1", 0), _Answers)
        self.home, self.skus, self.zones, self.asked, self.missed = home, skus, zones, [], {}
        # europe-west4-a's machines; by name, those read again as others and refused deletions
        self.machines, self.again, self.refused, self.silent = [], {}, set(), False
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


class _Answers(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def answer(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.server.asked.append(self.path)
        if self.server.silent:
            return
        self.rfile.read(int(self.headers["Content-Length"]))
        self.answer({"access_token": "ya29.acme"})

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
        pages = {"/v1/services/6F81-5844-456A/skus": [{"skus": skus} for skus in self.server.skus],
                 "/compute/v1/projects/acme-build/aggregated/machineTypes":
                     [{"items": zones, **self.server.missed} for zones in self.server.zones],
                 "/compute/v1/projects/acme-build/aggregated/instances":
                     [{"items": {"zones/europe-west4-a": {"instances": self.server.machines}}}]}
        listing, at = pages[url.path], int(parse_qs(url.query).get("pageToken", ["0"])[0])
        self.answer({**listing[at], **({"nextPageToken": str(at + 1)}
                                       if at + 1 < len(listing) else {})})
