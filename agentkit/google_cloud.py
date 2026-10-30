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
DISK_GB = 20                       # a boot disk holding the system, a checkout and its tests
HOURS_A_MONTH = 730                # how Google turns a monthly price into an hourly one
# A Spot core or memory price of one machine family, e.g. "Spot Preemptible C4A Arm Instance
# Core running in Netherlands"; a custom shape costs more and is not offered as a type.
SPOT = re.compile(r"^Spot Preemptible (?!.*Custom)(\w+) (?:[\w-]+ )*?"
                  r"Instance (Core|Ram) running in ")
DISK = re.compile(r"^(Balanced PD|Hyperdisk Balanced) (?!IOPS|Throughput)\w+ in ")    # its GBs
# The boot disks a series takes, which neither the price list nor a machine type says: Google's
# older series Persistent Disk alone, C3, C3D, H3, M3 and Z3 either, every other Hyperdisk alone.
PD, HYPERDISK = ("Balanced PD",), ("Hyperdisk Balanced",)
BOOT_DISKS = {**dict.fromkeys(["c2", "c2d", "e2", "n1", "n2", "n2d", "t2a", "t2d"], PD),
              **dict.fromkeys(["c3", "c3d", "h3", "m3", "z3"], PD + HYPERDISK)}
ADDRESS = "External IP Charge on a Spot Preemptible VM"    # the same in every region: "global"


class Unavailable(Exception):
    """Why ak cannot say what Google offers, in plain words."""


class Offer(NamedTuple):
    name: str
    region: str
    cores: float      # physical: an arm64 vCPU is one, two x86 vCPUs share one
    memory_mb: int
    hourly: float     # euros: its cores, memory, boot disk and address, as the bill will

    def __str__(self):
        return (f"{self.name} in {self.region} · {self.cores:g} cores · "
                f"{self.memory_mb / 1024:g} GB · €{self.hourly:.3f} an hour")


def best(mb_per_core):
    """Of the offers with at least `mb_per_core` of memory a core, the one with the lowest price
    per core, or None when there is none; raises Unavailable."""
    fits = [offer for offer in offers() if offer.memory_mb >= mb_per_core * offer.cores]
    return min(fits, key=lambda offer: (offer.hourly / offer.cores, offer), default=None)


def offers():
    """Every machine type a zone offers that the price list prices."""
    path = config.SECRETS / KEY
    try:
        if not path.exists():
            raise Unavailable(f"not set up: no Google service-account key at {config.tilde(path)}")
        key = json.loads(path.read_text())
        token = _token(key)
    # out of reach, not JSON, not an object of strings, or nothing openssl signs with
    except (OSError, ValueError, TypeError, AttributeError, subprocess.CalledProcessError) as exc:
        raise Unavailable(f"cannot use {config.tilde(path)}: {exc}")
    project = key.get("project_id")
    core, ram, disk, address = {}, {}, {}, None
    for sku in _pages(token, _url("cloudbilling", f"/v1/services/{COMPUTE_SKUS}/skus"),
                      "skus", currencyCode=CURRENCY, pageSize=5000):
        description, price = sku.get("description", ""), _hourly(sku)
        spot, boot = SPOT.match(description), DISK.match(description)
        if price is None:
            continue
        if description == ADDRESS:
            address = price
        for region in sku.get("serviceRegions") or ():
            if spot:
                (core if spot[2] == "Core" else ram)[spot[1].lower(), region] = price
            elif boot:
                disk[boot[1], region] = price
    found = {}
    for zone, listed in _pages(token, _url("compute", f"/compute/v1/projects/{project}/"
                                           "aggregated/machineTypes"),
                               "items", returnPartialSuccess="true"):   # names zones it missed
        region = zone.removeprefix("zones/").rsplit("-", 1)[0]
        for kind in listed.get("machineTypes") or ():
            name, vcpus, mb = kind.get("name", ""), kind.get("guestCpus"), kind.get("memoryMb")
            family = name.split("-")[0]
            a_vcpu, a_gb = core.get((family, region)), ram.get((family, region))
            a_disk_gb = min((disk[product, region] for product in BOOT_DISKS.get(family, HYPERDISK)
                             if (product, region) in disk), default=None)
            # a shared core, an accelerator or a bundled local SSD is priced apart from the cores,
            # and bare metal is never Spot
            if (kind.get("isSharedCpu") or kind.get("accelerators") or kind.get("deprecated")
                    or kind.get("bundledLocalSsds") or name.endswith("-metal")
                    or not vcpus or not mb or None in (a_vcpu, a_gb, a_disk_gb, address)):
                continue
            cores = vcpus if kind.get("architecture") == "ARM64" else vcpus / 2
            hourly = vcpus * a_vcpu + mb / 1024 * a_gb + DISK_GB * a_disk_gb + address
            found[name, region] = Offer(name, region, cores, mb, hourly)
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
    """Each entry of `field` on every page of a listing: a list's items, or a map's pairs; raises
    Unavailable for a page missing part of the listing, as the cheapest may be in that part."""
    while True:
        page = _call(f"{url}?{urllib.parse.urlencode(query)}", token)
        if missed := page.get("unreachables"):
            raise Unavailable(f"asking Google failed: {', '.join(missed)} unreachable")
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
    """A price-list entry's steady price an hour, its last tier's, or None: a Spot core's or GB's,
    a disk's GB's or an address's."""
    try:
        expression = sku["pricingInfo"][-1]["pricingExpression"]
        price = expression["tieredRates"][-1]["unitPrice"]
        amount = int(price.get("units") or 0) + price.get("nanos", 0) / 1e9
        return amount / HOURS_A_MONTH if expression["usageUnit"].endswith("mo") else amount
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
