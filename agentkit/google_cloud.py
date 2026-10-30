"""Machines ak rents from Google Cloud: the best one to rent now (`best`); renting, listing and
returning them come later, behind the same names, so another provider is one more module.  This
module alone knows Google: the service-account key `KEY`, the token its JWT buys (signed by the
openssl CLI: the standard library has no RSA), Compute Engine's Spot price list and machine types.
"""

import base64
import http.client
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from typing import NamedTuple

from . import config

KEY = "google-cloud.json"          # in config.SECRETS as it is when read, wherever a test moves it
TIMEOUT = 30                       # a page of the price list is 5,000 entries, on a host under load
# A project's own key may not read its billing account's currency (billingAccounts.get: 403).
CURRENCY = "EUR"
COMPUTE_SKUS = "6F81-5844-456A"    # Compute Engine's service in the price list
# A Spot core or memory price of one machine family, e.g. "Spot Preemptible C4A Arm Instance
# Core running in Netherlands"; a custom shape costs more and is not offered as a type.
SPOT = re.compile(r"^Spot Preemptible (?!.*Custom)(\w+) (?:[\w-]+ )*?"
                  r"Instance (Core|Ram) running in ")


class Unavailable(Exception):
    """Why ak cannot say what Google offers, in plain words."""


class Offer(NamedTuple):
    name: str
    region: str
    cores: float      # physical: an arm64 vCPU is one, two x86 vCPUs share one
    memory_mb: int
    per_core: float   # euros an hour: a core and its share of the memory

    def __str__(self):
        return (f"{self.name} in {self.region} · {self.cores:g} cores · "
                f"{self.memory_mb / 1024:g} GB · €{self.per_core * self.cores:.3f} an hour")


def best(mb_per_core):
    """Of the offers with at least `mb_per_core` of memory a core, the one with the lowest price
    per core, the most cores among equals, or None when there is none; raises Unavailable."""
    fits = [offer for offer in offers() if offer.memory_mb >= mb_per_core * offer.cores]
    return min(fits, key=lambda offer: (offer.per_core, -offer.cores, offer), default=None)


def offers():
    """Every machine type a zone offers that the price list prices."""
    path = config.SECRETS / KEY
    if not path.exists():
        raise Unavailable(f"not set up: no Google service-account key at {config.tilde(path)}")
    try:
        key = json.loads(path.read_text())
        token = _token(key)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise Unavailable(f"cannot use {config.tilde(path)}: {exc}")
    project = key.get("project_id")
    core, ram = {}, {}
    for sku in _pages(token, _url("cloudbilling", f"/v1/services/{COMPUTE_SKUS}/skus"),
                      "skus", currencyCode=CURRENCY, pageSize=5000):
        spot, price = SPOT.match(sku.get("description", "")), _hourly(sku)
        if spot and price is not None:
            for region in sku.get("serviceRegions") or ():
                (core if spot[2] == "Core" else ram)[spot[1].lower(), region] = price
    found = {}
    for zone, listed in _pages(token, _url("compute", f"/compute/v1/projects/{project}/"
                                           "aggregated/machineTypes"),
                               "items", returnPartialSuccess="true"):
        region = zone.removeprefix("zones/").rsplit("-", 1)[0]
        for kind in listed.get("machineTypes") or ():
            name, vcpus, mb = kind.get("name", ""), kind.get("guestCpus"), kind.get("memoryMb")
            family = name.split("-")[0]
            a_vcpu, a_gb = core.get((family, region)), ram.get((family, region))
            # a shared core, an accelerator or a bundled local SSD is priced apart from the cores,
            # and bare metal is never Spot
            if (kind.get("isSharedCpu") or kind.get("accelerators") or kind.get("deprecated")
                    or kind.get("bundledLocalSsds") or name.endswith("-metal")
                    or not vcpus or not mb or None in (a_vcpu, a_gb)):
                continue
            cores = vcpus if kind.get("architecture") == "ARM64" else vcpus / 2
            # from the vCPUs and memory a core has, the same for every size of a family to the
            # last bit, as the type's price over its cores is not: a tie goes to the most cores
            per_core = vcpus / cores * a_vcpu + mb / 1024 / cores * a_gb
            found[name, region] = Offer(name, region, cores, mb, per_core)
    return list(found.values())


def _token(key):
    """An access token for `key`'s service account, bought with a JWT it signs."""
    now = int(time.time())
    url = _url("oauth2", "/token")
    claims = {"iss": key.get("client_email"), "aud": url, "iat": now, "exp": now + 3600,
              "scope": "https://www.googleapis.com/auth/cloud-platform"}
    unsigned = ".".join(_b64(json.dumps(part).encode())
                        for part in ({"alg": "RS256", "typ": "JWT"}, claims))
    read, write = os.pipe()
    with os.fdopen(write, "w") as pipe:
        pipe.write(key.get("private_key") or "")
    with os.fdopen(read):
        signed = subprocess.run(["openssl", "dgst", "-sha256", "-sign", f"/dev/fd/{read}"],
                                input=unsigned.encode(), capture_output=True, pass_fds=(read,),
                                check=True)
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": f"{unsigned}.{_b64(signed.stdout)}"}).encode()
    return _call(url, data=body)["access_token"]


def _pages(token, url, field, **query):
    """Each entry of `field` on every page of a listing: a list's items, or a map's pairs."""
    while True:
        page = _call(f"{url}?{urllib.parse.urlencode(query)}", token)
        entries = page.get(field) or ()
        yield from entries.items() if isinstance(entries, dict) else entries
        if not page.get("nextPageToken"):
            return
        query["pageToken"] = page["nextPageToken"]


def _call(url, token=None, data=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, headers),
                                    timeout=TIMEOUT) as response:
            return json.load(response)
    except (OSError, http.client.HTTPException, ValueError) as exc:   # urllib's, http's, json's
        raise Unavailable(f"asking Google failed: {getattr(exc, 'reason', exc)}")


def _url(host, path):
    # the answer key's fake Google answers for every host
    return os.environ.get("AK_GOOGLE_URL", f"https://{host}.googleapis.com") + path


def _hourly(sku):
    """A price-list entry's steady price, its last tier's, or None: a Spot core's or GB's an
    hour."""
    try:
        price = sku["pricingInfo"][-1]["pricingExpression"]["tieredRates"][-1]["unitPrice"]
        return int(price.get("units") or 0) + price.get("nanos", 0) / 1e9
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
