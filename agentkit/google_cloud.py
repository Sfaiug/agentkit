"""Machines ak rents from Google Cloud: `best`, `rented`, `give_back`, the month's cost (`watch`,
`said`); renting comes later, behind the same names, so another provider is one more module.  This
module alone knows Google: the service-account key `KEY`, the token its JWT buys (signed by the
openssl CLI: the standard library has no RSA), Compute Engine's Spot price list and machine types;
and which machines it rents serve, and how ssh reaches them (`serving`, `ssh_config`).
"""

import base64
from collections import namedtuple
from datetime import datetime, timezone
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
OFFERS, FRESH_FOR = "google-cloud-offers.json", 86400    # kept a day: a listing takes a minute
LEDGER = "google-cloud-ledger.json"     # this month's meter: Google's billing export is hours late
LATE = "google-cloud-late.json"         # doctor's lines: apart, so a bad ledger hides no refusal
PASS = 180                         # seconds between the tick's passes: cron's */3 (install.sh)
UNANSWERED = []                    # Google not answering this process, which then asks no more
Rented = namedtuple("Rented", "id name zone type created until address")   # `id` survives a rename
USER, READY = "ak", "/run/ak-ready"     # a machine's user for ak, and what says it is set up
SSH_KEY, KNOWN_HOSTS = "google-cloud-ssh", "google-cloud-known-hosts"     # beside KEY
SSH_CONFIG = "google-cloud-ssh-config"  # in config.STATE: the machines ak reaches, then the owner's
HELD = "# not ready: keeps the work it holds, takes none"     # in SSH_CONFIG, before such a Host
# A machine that held nothing this long goes back.  A new machine's first suite pays about a
# minute to boot and 4.5 to receive a whole history and build its image (measured 30 Oct 2026),
# and the tick looks only every PASS; ten idle minutes of the machines ak rents cost about €0.10.
IDLE_FOR = 600


class Unavailable(config.Error):
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


def said(mb_per_core):
    """`ak doctor`'s lines: the tick's last answer while ak may rent, else `best`'s."""
    active, cap = _setting()
    if not active:
        return [f"best now {cheapest}" if (cheapest := best(mb_per_core)) else "nothing offered"]
    ledger, late = _ledger(), config._read_json(config.STATE / LATE) or []
    if ledger is None:
        return [f"cannot read {config.tilde(config.STATE / LEDGER)}: all machines go back", *late]
    if not (at := ledger["answered"]):
        return ["Google has not answered the tick yet"]
    since = f" as of {time.strftime('%-d %b %H:%M', time.localtime(at))}"
    running = sum("from" not in one for one in ledger["machines"].values())
    return [f"{running} running · €{ledger['spent']:.2f} of €{cap:.2f} this "
            f"month{since * (time.time() - at > 2 * PASS)}", *late]


def watch():
    """The tick's pass while ak may rent: the meter moved on to what Google lists, each machine
    past its end, unpriced, past the cap or idle given back and said, the other ready ones serving
    and one that served and does not answer now held for the work it holds; only then a stale
    price list."""
    active, cap = _setting()
    if not active:
        return
    listed, now = rented(), time.time()
    try:
        kept = json.loads((config.STATE / OFFERS).read_text())
        at, prices = kept["at"], {(name, region): hourly for name, region, *_, hourly
                                  in kept["offers"] if _amount(hourly)}
    except (OSError, ValueError, TypeError, KeyError):
        at, prices = 0, {}
    ledger, late = (read := _ledger()) and _moved(read, listed, now, prices), []
    routed = [name for name, _ in _routes()]     # as the last tick left them
    try:
        idle = _idle(listed, routed)
    except (OSError, subprocess.CalledProcessError):    # no ssh here: the meter moves all the same
        idle = {}
    reached, named = [], [machine.name for machine in listed]
    for machine in listed:
        if why := ("past its end" if now >= machine.until else "with no price kept" if not prices
                   else "past the cap" if not ledger or ledger["spent"] > cap
                   else "idle" if idle.get(machine.id, 0) >= IDLE_FOR else None):
            try:
                give_back(machine)
                late.append(f"{machine.name} listed {why}, given back")
            except Unavailable as exc:
                late.append(f"{machine.name} listed {why}, not given back: {exc}")
        elif machine.id in idle or (machine.address and machine.name in routed
                                    and named.count(machine.name) == 1):  # ssh reads its first Host
            reached.append(machine)
    _serve(reached, idle)
    config._write_json(config.STATE / LATE, late)
    if ledger:
        config._write_json(config.STATE / LEDGER, ledger)
    if not _amount(at) or now - at >= FRESH_FOR:
        config._write_json(config.STATE / OFFERS, {"at": now, "offers": offers()})


def rented():
    """What Google says ak has now: every machine labelled `ak=rented`, in every zone."""
    compute, token = _login()
    found = []
    for zone, listed in _pages(token, f"{compute}/aggregated/instances", "items"):
        for one in filter(_ours, listed.get("instances") or ()):
            created = datetime.fromisoformat(one["creationTimestamp"]).timestamp()
            life = ((one.get("scheduling") or {}).get("maxRunDuration") or {}).get("seconds", 0)
            address = next((access.get("natIP") for nic in one.get("networkInterfaces") or ()
                            for access in nic.get("accessConfigs") or ()), None)
            found.append(Rented(one["id"], one["name"], zone.removeprefix("zones/"),
                                one["machineType"].split("/")[-1], created, created + int(life),
                                address))
    return found


def serving():
    """The machines ak rents that serve, as the tick last found them ready, while ak may rent."""
    return [name for name, held in _routes() if not held]


def _routes():
    """(name, whether it is held) of each machine ak rents that ssh reaches, while ak may rent."""
    lines = (config.STATE / SSH_CONFIG).read_text().splitlines() if ssh_config() else []
    return [(line[5:], before == HELD) for before, line in zip(["", *lines], lines)
            if line.startswith("Host ") and line != "Host *"]


def ssh_config():
    """ssh's words reaching those `serving` or held and every other machine as ever, while ak may
    rent."""
    path = config.STATE / SSH_CONFIG     # replaced whole, never removed
    return ("-F", str(path)) if path.exists() and _setting()[0] else ()


def give_back(machine):
    """Delete `machine`, its boot disk and address with it, if Google, asked again, says it is
    still that one and ak's; raises Unavailable with what Google refused."""
    compute, token = _login()
    url = f"{compute}/zones/{machine.zone}/instances/{machine.name}"
    found = _call(url, token, gone={})
    if found.get("id") == machine.id and _ours(found):
        _call(url, token, method="DELETE", gone={})


def offers():
    """Every machine type a zone offers that the price list prices."""
    compute, token = _login()
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
    for zone, listed in _pages(token, f"{compute}/aggregated/machineTypes",
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


def _login():
    path = config.SECRETS / KEY
    try:
        if not path.exists():
            raise Unavailable(f"not set up: no Google service-account key at {config.tilde(path)}")
        key = json.loads(path.read_text())
        return _url("compute", f"/compute/v1/projects/{key.get('project_id')}"), _token(key)
    # out of reach, not JSON, not an object of strings, or nothing openssl signs with
    except (OSError, ValueError, TypeError, AttributeError, subprocess.CalledProcessError) as exc:
        raise Unavailable(f"cannot use {config.tilde(path)}: {exc}")


def _setting():
    """Whether ak may rent, and the most a month may cost, 0 for no number: an owner's slip."""
    cap = (table := config.load().get("google_cloud") or {}).get("max_month")
    return table.get("active") is True, cap if _amount(cap) else 0


def _amount(value):
    """Whether `value` is a number ak could have written: a NaN passes any cap, a string none."""
    return type(value) in (int, float) and 0 <= value < 1e12


def _ledger():
    """The meter as the tick left it, at nothing before its first, None if it cannot be read."""
    try:
        ledger = json.loads((config.STATE / LEDGER).read_text())
        numbers = [ledger["answered"], ledger["spent"], *(
            value for one in ledger["machines"].values()
            for value in (one["price"], one["until"], one.get("from", 0)))]
        return ledger if all(map(_amount, numbers)) else None
    except FileNotFoundError:
        return {"answered": 0, "spent": 0, "machines": {}}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return None     # losing the month's total never reads as money left


def _moved(ledger, listed, now, prices):
    """`ledger` moved on to `now`, Google listing `listed`: each machine charged since the last
    answer, one new since its creation, one gone up to its allowed end, at the dearer of its kept
    price and its type's there, else the dearest kept; only this month's time counts, in UTC.
    One on the meter by name, with `from` when it was asked for, Google has not listed yet: no
    listing can show it gone, so it stays until one names it, and past its end is paid whole."""
    start = datetime(*time.gmtime(now)[:2], 1, tzinfo=timezone.utc).timestamp()
    since, kept, machines = ledger["answered"], ledger["machines"], {}
    spent = ledger["spent"] if since >= start else 0
    for one in listed:
        old = kept.pop(one.id, None) or kept.pop(one.name, None)
        price = max(old["price"] if old else 0, prices.get(
            (one.type, one.zone.rsplit("-", 1)[0]), max(prices.values(), default=0)))
        machines[one.id] = {"price": price, "until": one.until}
        paid_from = since if old and "from" not in old else one.created
        spent += price * max(0, now - max(paid_from, start)) / 3600
    for key, gone in kept.items():
        if "from" in gone and now < gone["until"]:
            machines[key] = gone
        else:
            spent += gone["price"] * max(0, min(now, gone["until"]) - max(
                gone.get("from", since), start)) / 3600
    return {"answered": now, "spent": spent, "machines": machines}


def _idle(listed, routed):
    """{id: seconds it has held nothing} of each of `listed` READY, asked side by side by
    tools/helper's `idle` with ak's key, made when missing; the address of one not `routed` yet
    forgotten first, as Google hands addresses out again and ssh refuses an old host key there."""
    from . import helper, machines    # here, not at the top: both read this module
    key, known = config.SECRETS / SSH_KEY, config.SECRETS / KNOWN_HOSTS
    if not key.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", USER, "-f", key],
                       capture_output=True, check=True)
    reached = [one for one in listed if one.address]
    for one in reached:
        if one.name not in routed:
            subprocess.run(["ssh-keygen", "-R", one.address, "-f", known], capture_output=True)
    known.with_name(f"{KNOWN_HOSTS}.old").unlink(missing_ok=True)     # ssh-keygen's copy
    line = f"test -e {READY} && {helper._line('idle')}"
    said = machines.ask([[*machines.SSH, *(word for option in _reach(one).items()
                                           for word in ("-o", '%s="%s"' % option)),
                          "--", one.name, line] for one in reached])
    return {one.id: int(answer) if answer.strip().isdigit() else 0
            for one, answer in zip(reached, said) if answer is not None}


def _reach(machine):
    """How ssh reaches `machine`: at its address as USER by ak's key alone, its host key learned."""
    return {"HostName": machine.address, "User": USER, "IdentityFile": config.SECRETS / SSH_KEY,
            "IdentitiesOnly": "yes", "UserKnownHostsFile": config.SECRETS / KNOWN_HOSTS,
            "StrictHostKeyChecking": "accept-new"}


def _serve(machines, ready):
    """The ssh config, written whole: `machines` as ssh reaches each, held but those `ready` by
    id, then every other as ever."""
    path = config.STATE / SSH_CONFIG
    temp = path.with_suffix(".tmp")
    temp.write_text("".join(f"{HELD}\n" * (one.id not in ready) + f"Host {one.name}\n" + "".join(
        '  %s "%s"\n' % option for option in _reach(one).items()) for one in machines)
        + "Host *\n  Include ~/.ssh/config\n")
    temp.replace(path)


def _ours(machine):
    return (machine.get("labels") or {}).get("ak") == "rented"


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


def _call(url, token=None, data=None, method=None, gone=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if UNANSWERED:
        raise Unavailable(UNANSWERED[0])
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, headers, method=method),
                                    timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.request.HTTPError as exc:     # Google's answer: 403 Forbidden, 404 Not Found ...
        if exc.code == 404 and gone is not None:
            return gone
        raise Unavailable(f"Google refused: {exc.reason}")
    except OSError as exc:      # no answer: it costs a process one TIMEOUT, no more
        UNANSWERED.append(f"asking Google failed: {getattr(exc, 'reason', exc)}")
        raise Unavailable(UNANSWERED[0])
    except (http.client.HTTPException, ValueError) as exc:   # http's, json's
        raise Unavailable(f"asking Google failed: {exc}")


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
