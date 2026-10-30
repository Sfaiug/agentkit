"""`ak doctor` names the machine Google Cloud rents for the least money per core right now: an
arm64 vCPU is a core, two x86 vCPUs one; a type costs its cores and memory, so among sizes of a
family the most cores win; one with less memory a core than a test piece is estimated to need is
passed over, and bare metal, never Spot.
Black-box: `AK_BIN` asks a fake Google on the loopback (`AK_GOOGLE_URL`).
"""

import http.server
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REPO, Home

ECHO = {"AGENTKIT_ADAPTER_DIR": str(REPO / "tests/fixtures/adapters")}
SPOT, NL = "Spot Preemptible", ["europe-west4"]


def sku(description, regions, nanos):
    rate = {"unitPrice": {"units": "0", "nanos": nanos}}
    return {"description": description, "serviceRegions": regions, "pricingInfo": [
        {"pricingExpression": {"usageUnit": "h", "tieredRates": [rate]}}]}


SKUS = [sku(f"{SPOT} C4A Arm Instance Core running in Netherlands", NL, 5_000_000),
        sku(f"{SPOT} C4A Arm Instance Ram running in Netherlands", NL, 600_000),
        sku(f"{SPOT} N2D AMD Instance Core running in Netherlands", NL, 3_000_000),
        sku(f"{SPOT} N2D AMD Instance Ram running in Netherlands", NL, 400_000),
        sku("N2D AMD Instance Core running in Netherlands", NL, 1),   # not Spot
        # the cheapest of all, where no zone offers it
        sku(f"{SPOT} T2A Arm Instance Core running in Iowa", ["us-central1"], 1_000),
        sku(f"{SPOT} T2A Arm Instance Ram running in Iowa", ["us-central1"], 1_000)]


def kind(name, vcpus, gb, architecture="ARM64"):
    return {"name": name, "guestCpus": vcpus, "memoryMb": int(gb * 1024),
            "architecture": architecture}


# Per core an hour: every c4a-standard €0.0074, and c4a-standard-4 €0.030 an hour to the -8's
# €0.059; n2d-standard-8 €0.0092, half that were its vCPUs cores; c4a-highcpu-8 €0.00515 with
# 256 MB a core.  The c4a-standard-16 and -96 tie with more cores, but one has a local SSD and
# the other is bare metal.
ZONES = [{"zones/europe-west4-a": {"machineTypes": [
             kind("c4a-standard-4", 4, 16), kind("c4a-standard-8", 8, 32),
             kind("c4a-highcpu-8", 8, 2), kind("n2d-standard-8", 8, 32, "X86_64"),
             {**kind("c4a-standard-16-lssd", 16, 64), "bundledLocalSsds": {"partitionCount": 1}},
             kind("c4a-standard-96-metal", 96, 384)]}},
         {"zones/us-central1-a": {"warning": {"code": "NO_RESULTS_ON_PAGE"}}}]
BEST = "rented machines: best now c4a-standard-8 in europe-west4 · 8 cores · 32 GB · €0.059 an hour"


class FakeGoogle(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def answer(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.answer({"access_token": "ya29.acme"})

    def do_GET(self):
        self.server.asked.append(self.path)
        url = urlsplit(self.path)
        pages = {"/v1/services/6F81-5844-456A/skus": [{"skus": SKUS[:5]}, {"skus": SKUS[5:]}],
                 "/compute/v1/projects/acme-build/aggregated/machineTypes":
                     [{"items": zones, **self.server.missed} for zones in ZONES]}
        listing, at = pages[url.path], int(parse_qs(url.query).get("pageToken", ["0"])[0])
        self.answer({**listing[at], **({"nextPageToken": str(at + 1)}
                                       if at + 1 < len(listing) else {})})


class GoogleBestMachine(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, {"echo": {"harness": "echo", "model": "echo-1"}})
        self.google = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeGoogle)
        self.google.asked, self.google.missed = [], {}
        threading.Thread(target=self.google.serve_forever, daemon=True).start()
        self.addCleanup(self.google.server_close)
        self.addCleanup(self.google.shutdown)

    def key(self):
        with tempfile.NamedTemporaryFile() as pem:
            subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-out", pem.name], check=True,
                           capture_output=True)
            self.home.write(".agentkit/secrets/google-cloud.json", {
                "project_id": "acme-build", "client_email": "ak@acme-build.example",
                "private_key": Path(pem.name).read_text()})

    def rented(self):
        url = f"http://127.0.0.1:{self.google.server_address[1]}"
        done = self.home.ak("doctor", env={**ECHO, "AK_GOOGLE_URL": url})
        self.assertEqual(done.code, 0, done.out + done.err)
        return [line for line in done.out.splitlines() if line.startswith("rented machines: ")]

    def test_the_lowest_price_per_core_among_offered_types_with_the_memory_wins(self):
        self.key()
        self.assertEqual(self.rented(), [BEST])
        skus = [path for path in self.google.asked if "/skus?" in path]
        self.assertEqual(len(skus), 2, "every page of the price list")
        self.assertTrue(all("currencyCode=EUR" in path for path in skus), skus)

    def test_a_zone_google_could_not_reach_leaves_no_best(self):
        self.key()
        self.google.missed = {"unreachables": ["zones/us-central1-c"]}
        self.assertEqual(self.rented(), ["rented machines: asking Google failed: "
                                         "zones/us-central1-c unreachable"])

    def test_a_key_ak_cannot_use_is_a_plain_line(self):
        for key in ("{", [], None, {"private_key": 7}):
            self.home.write(".agentkit/secrets/google-cloud.json", key)
            [line] = self.rented()
            self.assertTrue(line.startswith("rented machines: cannot use"), line)

    def test_without_a_key_ak_is_not_set_up_and_asks_nobody(self):
        [line] = self.rented()
        self.assertTrue(line.startswith("rented machines: not set up"), line)
        self.assertEqual(self.google.asked, [])


if __name__ == "__main__":
    unittest.main()
