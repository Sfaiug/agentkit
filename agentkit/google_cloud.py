"""Machines ak rents from Google Cloud: `best`, `rented`, `give_back`, the month's cost (`watch`,
`said`) and renting (`need`), behind names another provider can be one more module of.  This
module alone knows Google: the service-account key `KEY`, the token its JWT buys (signed by the
openssl CLI: the standard library has no RSA), Compute Engine's Spot price list, machine types
and CPU quotas; and which machines it rents serve, till when, and how ssh reaches them
(`serving`, `ssh_config`).
"""

import base64
from collections import Counter, namedtuple
import contextlib
from datetime import datetime, timezone
import http.client
import json
import os
import re
import secrets
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
DISK_TYPES = {"Balanced PD": "pd-balanced", "Hyperdisk Balanced": "hyperdisk-balanced"}
IMAGE = "projects/debian-cloud/global/images/family/debian-13"     # "-arm64" for arm64
# The boot disks a series takes, which neither the price list nor a machine type says: Google's
# older series Persistent Disk alone, C3, C3D, H3, M3 and Z3 either, every other Hyperdisk alone.
PD, HYPERDISK = ("Balanced PD",), ("Hyperdisk Balanced",)
BOOT_DISKS = {**dict.fromkeys(["c2", "c2d", "e2", "n1", "n2", "n2d", "t2a", "t2d"], PD),
              **dict.fromkeys(["c3", "c3d", "h3", "m3", "z3"], PD + HYPERDISK)}
ADDRESS = "External IP Charge on a Spot Preemptible VM"    # the same in every region: "global"
OFFERS, FRESH_FOR = "google-cloud-offers.json", 86400    # kept a day: a listing takes a minute
# Service Usage's limits on a family's vCPUs in each region; FULL lists every region's, not only
# those changed
FAMILIES = ("/v1beta1/projects/{}/services/compute.googleapis.com/consumerQuotaMetrics/"
            "compute.googleapis.com%2Fcpus_per_vm_family?view=FULL")
LEDGER = "google-cloud-ledger.json"     # this month's meter: Google's billing export is hours late
LATE = "google-cloud-late.json"         # doctor's lines: apart, so a bad ledger hides no refusal
PASS = 180                         # seconds between the tick's passes: cron's */3 (install.sh)
UNANSWERED = []                    # Google not answering this process, which then asks no more
Rented = namedtuple("Rented", "id name zone type created until address")   # `id` survives a rename
USER, SET_UP = "ak", "/run/ak-ready"    # a machine's user for ak, and what says it is set up
READY = 600     # seconds a machine takes to come up: no rent meanwhile, nor one for a shorter life
LIFE = 12 * 3600    # a Spot machine is replaced at no cost, and a forgotten one costs no more
TRIES, POLLS = 4, 30    # a rent's creates, polled 2 s apart each: one ran 40 s on 31 Oct 2026
NEED = "google-cloud-need"      # MiB a vCPU of each suite no machine took since the last pass
REFUSALS = {"QUOTA_EXCEEDED", "quotaExceeded", "ZONE_RESOURCE_POOL_EXHAUSTED",   # Google's codes:
            "ZONE_RESOURCE_POOL_EXHAUSTED_WITH_DETAILS"}    # a zone's quota or stock is out
# A machine's setup, each line run on those that served suites on 31 Oct 2026: docker's data and
# trees in memory, as on disk a suite's cores idled in disk wait; sshd keeps a piece's connection.
STARTUP = """#!/bin/bash
set -e
useradd -m -s /bin/bash {user}
mkdir -p /var/lib/docker ~{user}/.agentkit-helper ~{user}/.ssh
mount -t tmpfs -o size=70% tmpfs /var/lib/docker
mount -t tmpfs -o size=70% tmpfs ~{user}/.agentkit-helper
echo '{key}' >~{user}/.ssh/authorized_keys
chown -R {user}: ~{user}
apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -qy docker.io docker-cli git jq
usermod -aG docker {user}
echo 'MaxStartups 500:30:1000' >/etc/ssh/sshd_config.d/ak.conf && systemctl reload ssh
touch {ready}
"""
SSH_KEY, KNOWN_HOSTS = "google-cloud-ssh", "google-cloud-known-hosts"     # beside KEY
SSH_CONFIG = "google-cloud-ssh-config"  # in config.STATE: the machines that serve, then the owner's
# A machine that held nothing this long goes back.  A new machine's first suite pays about a
# minute to boot and 4.5 to receive a whole history and build its image (measured 30 Oct 2026),
# and the tick looks only every PASS; ten idle minutes of the machines ak rents cost about €0.10.
IDLE_FOR = 600


class Unavailable(config.Error):
    """Why ak cannot say what Google offers, in plain words."""
    codes = None    # Google's own, for a request it refused with a 4xx: it did nothing of it


class Offer(NamedTuple):
    name: str
    region: str
    cores: float      # physical: an arm64 vCPU is one, two x86 vCPUs share one
    memory_mb: int
    hourly: float     # euros: its cores, memory, boot disk and address, as the bill will
    zones: list = ()
    image: str = ""
    disk: str = ""    # its boot disk's type
    vcpus: int = 0    # as quotas count them; none in a list kept before, which is listed anew

    @property
    def cpus(self):     # the vCPUs its machine counts, as a suite's VMs are given them
        return self.cores if self.image.endswith("-arm64") else 2 * self.cores

    def __str__(self):
        return (f"{self.name} in {self.region} · {self.cores:g} cores · "
                f"{self.memory_mb / 1024:g} GB · €{self.hourly:.3f} an hour")


def best(mb_per_cpu, offered):
    """The offers with at least `mb_per_cpu` of memory a vCPU, the lowest price per core first."""
    return sorted((offer for offer in offered if offer.memory_mb >= mb_per_cpu * offer.cpus),
                  key=lambda offer: (offer.hourly / offer.cores, offer))


def renting():
    """Whether ak may rent: `[google_cloud]` active; a config.toml mid-edit says no."""
    with contextlib.suppress(config.Error):
        return _setting()[0]


def need(mb_per_cpu):
    """A suite no machine took asks a pass for one of `mb_per_cpu` MiB a vCPU; fails nothing."""
    if renting():
        with contextlib.suppress(OSError), (config.STATE / NEED).open("a") as noted:
            noted.write(f"{mb_per_cpu}\n")


def said(mb_per_cpu):
    """`ak doctor`'s lines: the tick's last answer while ak may rent, else `best`'s."""
    active, cap = _setting()
    if not active:
        fits = best(mb_per_cpu, offers())
        return [f"best now {fits[0]}" if fits else "nothing offered"]
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
    past its end, unpriced, past the cap or idle given back and said, the other ready ones serving;
    only then a stale price list and quotas, and a machine rented for a need noted while none
    comes up."""
    wanted, (active, cap) = _noted(config.STATE / NEED), _setting()
    if not active:
        return
    listed, now = rented(), time.time()
    try:
        kept = json.loads((config.STATE / OFFERS).read_text())
        at, offered = kept["at"], [Offer(*one) for one in kept["offers"]]
        limits = kept.get("limits") or {}
    except (OSError, ValueError, TypeError, KeyError):
        at, offered, limits = 0, [], {}
    prices = {(one.name, one.region): one.hourly for one in offered if _amount(one.hourly)}
    ledger, late = (read := _ledger()) and _moved(read, listed, now, prices), []
    try:
        idle = _idle(listed)
    except (OSError, subprocess.CalledProcessError):    # no ssh here: the meter moves all the same
        idle = {}
    ready = []
    for machine in listed:
        if why := ("past its end" if now >= machine.until else "with no price kept" if not prices
                   else "past the cap" if not ledger or ledger["spent"] > cap
                   else "idle" if idle.get(machine.id, 0) >= IDLE_FOR else None):
            try:
                give_back(machine)
                late.append(f"{machine.name} listed {why}, given back")
            except Unavailable as exc:
                late.append(f"{machine.name} listed {why}, not given back: {exc}")
        elif machine.id in idle:
            ready.append(machine)
    _serve(ready)
    config._write_json(config.STATE / LATE, late)
    if ledger:
        config._write_json(config.STATE / LEDGER, ledger)
    if not _amount(at) or now - at >= FRESH_FOR or not all(one.vcpus for one in offered):
        offered = offers()
        limits = _limits({one.region for one in offered})
        config._write_json(config.STATE / OFFERS, {"at": now, "offers": offered, "limits": limits})
    # none coming up: on the meter by name or listed, not ready, since less than READY ago
    if wanted and ledger and all(now - since >= READY for since in [
            *(one.get("from", 0) for one in ledger["machines"].values()),
            *(one.created for one in listed if one.id not in idle)]):
        late += _rent(ledger, wanted, cap, now, offered, limits, {one.zone for one in listed})
        config._write_json(config.STATE / LATE, late)


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
    """{name: its end} of the machines ak rents that serve, as the tick last found them ready,
    while ak may rent."""
    text = (config.STATE / SSH_CONFIG).read_text() if ssh_config() else ""
    return {name: int(until) for name, until in re.findall(r"^Host (.+)\n  # until (\d+)$",
                                                             text, re.M)}


def ssh_config():
    """ssh's words reaching those `serving` and every other machine as ever, while ak may rent."""
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
    """Every machine type the price list prices, with the zones of its region offering it."""
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
        region = (zone := zone.removeprefix("zones/")).rsplit("-", 1)[0]
        for kind in listed.get("machineTypes") or ():
            name, vcpus, mb = kind.get("name", ""), kind.get("guestCpus"), kind.get("memoryMb")
            family = name.split("-")[0]
            a_vcpu, a_gb = core.get((family, region)), ram.get((family, region))
            product = min((one for one in BOOT_DISKS.get(family, HYPERDISK) if (one, region)
                           in disk), key=lambda one: disk[one, region], default=None)
            a_disk_gb = disk.get((product, region))
            # a shared core, an accelerator or a bundled local SSD is priced apart from the cores,
            # and bare metal is never Spot
            if (kind.get("isSharedCpu") or kind.get("accelerators") or kind.get("deprecated")
                    or kind.get("bundledLocalSsds") or name.endswith("-metal")
                    or not vcpus or not mb or None in (a_vcpu, a_gb, a_disk_gb, address)):
                continue
            arm = kind.get("architecture") == "ARM64"
            hourly = vcpus * a_vcpu + mb / 1024 * a_gb + DISK_GB * a_disk_gb + address
            found.setdefault((name, region), Offer(name, region, vcpus if arm else vcpus / 2, mb,
                                                   hourly, [], IMAGE + "-arm64" * arm,
                                                   DISK_TYPES[product], vcpus)).zones.append(zone)
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


def _noted(path):
    """The most MiB a vCPU noted at `path`, 0 for none, taken: a suite noting next notes anew."""
    try:
        return max(map(int, path.replace(path.with_suffix(".taken")).read_text().split()))
    except (OSError, ValueError):
        return 0


def _rent(ledger, wanted, cap, now, offered, limits, taken):
    """How renting a machine of `wanted` MiB a vCPU went, in lines: by price per core, zones
    where ak has none (`taken`) first, as Google took both Spot machines of one zone in 6 s on 30
    Oct 2026; none past a quota of `limits`, every machine Google lists counted; on the meter by
    name till Google says it made none; living what the cap leaves."""
    left = cap - ledger["spent"] - sum(one["price"] * max(0, one["until"] - one.get("from", now))
                                       for one in ledger["machines"].values()) / 3600
    # the public half of the key `_idle` made, or OSError before any machine is on the meter
    (compute, token), key = _login(), (config.SECRETS / f"{SSH_KEY}.pub").read_text().strip()
    said, tries, used, full = [f"nothing offered with {wanted} MiB a vCPU"], TRIES, Counter(), {}
    vcpus = {one.name: one.vcpus for one in offered}   # a type's, offered in any region
    for zone, listed in _pages(token, f"{compute}/aggregated/instances", "items"):
        region = zone.removeprefix("zones/").rsplit("-", 1)[0]
        for one in listed.get("instances") or ():    # ak's or not: a quota counts both
            kind = one["machineType"].split("/")[-1]
            used.update(dict.fromkeys(_quotas(kind, region, limits), vcpus.get(kind, 0)))
    for offer in best(wanted, offered):
        if (life := int(min(LIFE, left * 3600 / offer.hourly))) < READY:
            said = [f"rents nothing: €{cap - left:.2f} of €{cap:.2f} spent this month or held "
                    f"to the machines' ends leaves less than {READY // 60} minutes of {offer.name}"]
            continue
        if out := [one for one in _quotas(offer.name, offer.region, limits)
                   if used[one] + offer.vcpus > limits[one]]:
            full.update(dict.fromkeys(out))
            said = ["too little quota left: " + "; ".join(
                f"{one}: {used[one]:g} of {limits[one]:g} vCPUs in use" for one in full)]
            continue
        for zone in sorted(offer.zones, key=taken.__contains__):
            name, asked = f"ak-{secrets.token_hex(6)}", time.time()    # past refusals' polls
            ledger["machines"][name] = {"price": offer.hourly, "from": asked, "until": asked + life}
            config._write_json(config.STATE / LEDGER, ledger)
            try:
                codes = _create(compute, token, zone, _machine(name, zone, offer, life, key))
            except Unavailable as exc:
                return [f"{name} asked for in {zone}, kept on the meter: {exc}"]
            if codes is None:
                return [f"{name} rented: {offer.name} in {zone}"]
            del ledger["machines"][name]
            config._write_json(config.STATE / LEDGER, ledger)
            said, tries = [f"{offer.name} in {zone} refused: {' '.join(sorted(codes))}"], tries - 1
            if not tries or not codes & REFUSALS:
                return said
    return said


def _limits(regions):
    """{quota: the vCPUs Google lets the project hold of it}, named as `_quotas` names them, of
    `regions`; none if any cannot be read, as a less specific one would hold a family instead."""
    unanswered = len(UNANSWERED)
    try:
        compute, token = _login()
        project, found = compute.rsplit("/", 1)[1], {}
        for limit in _call(_url("serviceusage", FAMILIES.format(project)), token).get(
                "consumerQuotaLimits") or ():
            for bucket in limit.get("quotaBuckets") or ():
                if {"region", "vm_family"} <= (where := bucket.get("dimensions") or {}).keys():
                    found[f"{where['vm_family']} in {where['region']}"] = int(
                        bucket["effectiveLimit"])
        for region in regions:
            for quota in _call(f"{compute}/regions/{region}", token).get("quotas") or ():
                if quota["metric"].endswith("CPUS"):
                    found[f"{quota['metric']} in {region}"] = quota["limit"]
        for quota in _call(compute, token).get("quotas") or ():
            if quota["metric"] == "CPUS_ALL_REGIONS":
                found[quota["metric"]] = quota["limit"]
    except (Unavailable, LookupError, TypeError, ValueError, AttributeError):
        del UNANSWERED[unanswered:]     # the rent still asks Compute, which answered the offers
        return {}
    return found


def _quotas(kind, region, limits):
    """The quotas of `limits` a machine of type `kind` in `region` counts against: its family's
    there, the most specific Google lists, and all regions'; but none of -1, Google's no limit."""
    family = kind.split("-")[0].upper()
    mine = next((one for one in (f"{family} in {region}", f"{family}_CPUS in {region}",
                                 f"CPUS in {region}") if one in limits), None)
    return [one for one in (mine, "CPUS_ALL_REGIONS") if limits.get(one, -1) >= 0]


def _create(compute, token, zone, machine):
    """Google's codes for why it made nothing of `machine`, None once made; Unavailable: unknown."""
    try:
        operation = _call(f"{compute}/zones/{zone}/instances", token, machine)
    except Unavailable as exc:
        if exc.codes is None:
            raise
        return exc.codes
    polls = 0
    while operation.get("status") != "DONE":
        if (polls := polls + 1) > POLLS:
            raise Unavailable(f"Google had not made it after {POLLS} polls")
        time.sleep(2)
        operation = _call(f"{compute}/zones/{zone}/operations/{operation.get('name')}", token)
    return _codes(operation) if "error" in operation else None


def _machine(name, zone, offer, life, key):
    """What Google is asked to make: Spot, deleted by Google itself at its end whatever becomes
    of this host, its boot disk with it, reached by `key`, the public half of ak's, alone."""
    startup = STARTUP.format(user=USER, key=key, ready=SET_UP)
    return {"name": name, "machineType": f"zones/{zone}/machineTypes/{offer.name}",
            "labels": {"ak": "rented"}, "scheduling": {
                "provisioningModel": "SPOT", "instanceTerminationAction": "DELETE",
                "maxRunDuration": {"seconds": str(life)}, "automaticRestart": False,
                "onHostMaintenance": "TERMINATE"},
            "disks": [{"boot": True, "autoDelete": True, "initializeParams": {
                "sourceImage": offer.image, "diskSizeGb": str(DISK_GB),
                "diskType": f"zones/{zone}/diskTypes/{offer.disk}"}}],
            "networkInterfaces": [{"accessConfigs": [{"type": "ONE_TO_ONE_NAT"}]}],
            "metadata": {"items": [{"key": "block-project-ssh-keys", "value": "true"},
                                   {"key": "startup-script", "value": startup}]}}


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


def _idle(listed):
    """{id: seconds it has held nothing} of each of `listed` READY, asked side by side by
    tools/helper's `idle` with ak's key, made when missing; the address of one not serving yet
    forgotten first, as Google hands addresses out again and ssh refuses an old host key there."""
    from . import helper, machines    # here, not at the top: both read this module
    key, known, was = config.SECRETS / SSH_KEY, config.SECRETS / KNOWN_HOSTS, serving()
    if not key.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", USER, "-f", key],
                       capture_output=True, check=True)
    reached = [one for one in listed if one.address]
    for one in reached:
        if one.name not in was:
            subprocess.run(["ssh-keygen", "-R", one.address, "-f", known], capture_output=True)
    known.with_name(f"{KNOWN_HOSTS}.old").unlink(missing_ok=True)     # ssh-keygen's copy
    line = f"test -e {SET_UP} && {helper._line('idle')}"
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


def _serve(machines):
    """The ssh config, written whole: `machines` with their ends and as ssh reaches each, then
    every other as ever."""
    path = config.STATE / SSH_CONFIG
    temp = path.with_suffix(".tmp")
    temp.write_text("".join(f"Host {one.name}\n  # until {int(one.until)}\n" + "".join(
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
    return _call(url, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                            "assertion": f"{unsigned}.{_b64(signed.stdout)}"})["access_token"]


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
    # Google's APIs take JSON, its token endpoint a form; a reply cut short raises IncompleteRead
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"} if token else {}
    body = data and (json.dumps(data) if token else urllib.parse.urlencode(data)).encode()
    if UNANSWERED:
        raise Unavailable(UNANSWERED[0])
    try:
        with urllib.request.urlopen(urllib.request.Request(url, body, headers, method=method),
                                    timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.request.HTTPError as exc:     # Google's answer: 403 Forbidden, 404 Not Found ...
        if exc.code == 404 and gone is not None:
            return gone
        refused = Unavailable(f"Google refused: {exc.reason}")
        refused.codes = _codes(exc) if exc.code < 500 else None
        raise refused
    except OSError as exc:      # no answer: it costs a process one TIMEOUT, no more
        UNANSWERED.append(f"asking Google failed: {getattr(exc, 'reason', exc)}")
        raise Unavailable(UNANSWERED[0])
    except (http.client.HTTPException, ValueError) as exc:   # http's, json's
        raise Unavailable(f"asking Google failed: {exc}")


def _codes(answer):
    """Google's codes in an operation or a refusal's body: its errors' codes or reasons."""
    try:
        errors = (answer if isinstance(answer, dict) else json.load(answer))["error"]["errors"]
        return {one.get("code") or one.get("reason") for one in errors} - {None}
    except (OSError, ValueError, LookupError, TypeError, AttributeError, http.client.HTTPException):
        return set()


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
