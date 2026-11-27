"""The machines ak may use and what each one is: this one, each `[machines.<ssh alias>]` of
config.toml and the `suite_helper`.  Hidden here: the probe, tools/machine.sh, each tick's on all
of them side by side and one on a machine `c` adds, over ssh but for this one; how ak's ssh
reaches each, with ak's key to those it adds, and the line that makes a new machine one of them,
and how one that ran it is found; and their answers, state/machines.json, the last three days'
checks.
"""

from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
import json
import os
import shlex
import signal
import socket
import subprocess
import time

from . import config, gitcall, readings

HERE = "this one"
PROBE = config.REPO / "tools" / "machine.sh"
TIMEOUT = 10        # the seconds a machine that does not answer holds the tick, all of them
SSH = ("ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={TIMEOUT}",
       "-o", "ServerAliveInterval=15")
KEY = "machines-ssh"    # in config.SECRETS: the key pair ak reaches the machines it adds by
DAY = 86400
KEPT = 3 * DAY      # the checks "always on" is judged on; older ones go
# What the probe says, each read as its type; an answer missing one is no answer.
READINGS = {"system": str, "processor": str, "cores": int, "memory_mb": int, "free_mb": int,
            "load": float, "disk_free_mb": int, "battery": int, "power": int}
# What a probe may add, each read as its type: its host name; and where a Linux kernel keeps them,
# the running totals of the microseconds some work stood waiting for a processor, for memory and
# for the disk.
MAY = {"name": str, "cpu_stall_us": int, "memory_stall_us": int, "io_stall_us": int}


class Machine(namedtuple("Machine", "name checks said")):
    """A machine ak may use: its checks, oldest first, each [when, whether it answered], and
    what it said when it last answered, `at` then, or None."""

    @property
    def kind(self):
        """`sometimes on`, at once for a battery, `new` or `always on`: one answer in twenty may
        go to a network blip, but a laptop shut every night misses about a third."""
        if self.said and self.said["battery"]:
            return "sometimes on"
        if not self.checks or self.checks[-1][0] - self.checks[0][0] < DAY:
            return "new"
        answered = sum(1 for _, yes in self.checks if yes)
        return "always on" if 20 * answered >= 19 * len(self.checks) else "sometimes on"

    def __str__(self):
        said = self.said
        if not said:
            return f"{self.name}: {self.kind} · never answered"
        words = [self.kind, f"{said['system']} {said['processor']}",
                 f"{said['cores']} cores, load {said['load']:.1f}",
                 f"{_gb(said['memory_mb'])}, {_gb(said['free_mb'])} free",
                 f"{_gb(said['disk_free_mb'])} disk free",
                 *(["on power" if said["power"] else "on battery"] if said["battery"] else []),
                 f"last answered {_when(said['at'])}"]
        return f"{self.name}: {' · '.join(words)}"


def helpers():
    """Every machine ak may use but this one, as is one whose last answer named this host: a
    stand-in that took over as home still lists itself; nor one whose last answer said it is on
    battery, as a Mac's helper refuses work then and a Linux one's would drain it, until a check
    finds it on power."""
    record, here = _record(), socket.gethostname()
    said = {name: record.get(name, {}).get("said") or {} for name in _listed()}
    return [name for name, last in said.items()
            if last.get("name") != here and not (last.get("battery") and not last.get("power"))]


def itself(cfg):
    """The listed machine of `cfg` that is this host, the first helpers leaves out as one, or
    None."""
    record, here = _record(), socket.gethostname()
    return next((name for name in _listed(cfg)
                 if (record.get(name, {}).get("said") or {}).get("name") == here), None)


def _listed(cfg=None):
    """Every machine listed: config.toml's as is, not `config.load`'s, or `cfg`'s."""
    cfg = (config._read_toml(config.HOME / config.CONFIG_NAME) or {}) if cfg is None else cfg
    named = cfg.get("machines")
    names = [*(named if isinstance(named, dict) else ()), config.suite_helper(cfg)]
    return [name for name in dict.fromkeys(names) if name]


def work(name, cfg=None):
    """The work `name` takes.

    Unwritten marks follow the old switch while config.toml holds it, else what the machine
    last said it is: Linux without a battery takes turns too; a laptop, a Mac or one not
    answered yet tests alone.  A Mac's probe rules out turns, written or not.
    """
    cfg = (config._read_toml(config.HOME / config.CONFIG_NAME) or {}) if cfg is None else cfg
    config._work_in(cfg)
    if name == HERE:
        return ["turns", "tests"]
    named = cfg.get("machines")
    table = named.get(name, {}) if isinstance(named, dict) else {}
    said = _record().get(name, {}).get("said") or {}
    turns = cfg["turns_on_machines"] is True if "turns_on_machines" in cfg else \
        said.get("system") == "Linux" and not said.get("battery")
    marked = table["work"] if isinstance(table, dict) and "work" in table else \
        (["turns"] if turns else []) + ["tests"]
    return [word for word in marked if word != "turns" or said.get("system") != "macOS"]


def max_runs(name, cfg=None):
    """The most model turns `name` runs at once (`[machines."NAME"] max_runs`), or None: no cap."""
    cfg = (config._read_toml(config.HOME / config.CONFIG_NAME) or {}) if cfg is None else cfg
    config._work_in(cfg)
    if name == HERE:
        return None
    named = cfg.get("machines")
    table = named.get(name) if isinstance(named, dict) else None
    return table.get("max_runs") if isinstance(table, dict) else None


def known():
    """Every machine ak may use, this one first, as the ticks found it: each listed, so the
    tick asks each what it is."""
    names, record = [HERE, *_listed()], _record()
    return [Machine(name, record.get(name, {}).get("checks", []),
                    record.get(name, {}).get("said")) for name in dict.fromkeys(names) if name]


def check():
    """The tick's: asks each machine once, side by side, and records what it answered.  The
    record keeps the last three days' checks of each machine, of one the tick did not ask too:
    one `add` asked meanwhile.  Each answer is kept over time first (readings), so a record
    that cannot be written loses none of them."""
    now, names = time.time(), [machine.name for machine in known()]
    answers = {name: _said(answer)
               for name, (answer, _) in zip(names, ask([_probe(name) for name in names]))}
    readings.keep(now, {name: said for name, said in answers.items() if said})

    def change(record):
        for name, said in answers.items():
            was = record.get(name, {})
            record[name] = {"checks": [*was.get("checks", []), [now, bool(said)]],
                            "said": {**said, "at": now} if said else was.get("said")}
        for name, was in list(record.items()):
            was["checks"] = [one for one in was.get("checks", []) if one[0] > now - KEPT]
            if not was["checks"]:
                del record[name]
    _write(change)


def add(name):
    """`name`, an ssh address, asked once as `check` asks each machine, and its answer recorded:
    "" for the caller to write its `[machines.<name>]`, else why not.  One ak may use already is
    not asked."""
    if name in (HERE, *_listed()):
        return f"{name} is a machine already"
    now = time.time()
    # typing it answers the question ssh would ask of a host key it has not seen: that one is
    # learned, and one it knows otherwise still refused
    [(answer, errors)] = ask([_probe(name, "-o", "StrictHostKeyChecking=accept-new")])
    if not _recorded(name, answer, now):
        last = (errors or "").strip().splitlines()[-1:]     # ssh's own, or the probe's
        return (f"{name} did not answer in {TIMEOUT} seconds" if errors is None
                else f"{name} did not answer" + "".join(f": {line}" for line in last))
    return ""


def found():
    """Each machine that ran the line (join_line) on the home's Tailscale network: of each peer
    online, on Linux, of the home's Tailscale user and no machine already (a listed one known by
    the host `ssh -G` gives its name), asked once as `add` asks one, but as `ak@<its Tailscale
    name>` by ak's key alone.  Those that answered, each recorded as `add` records one, and "";
    else none, and why."""
    try:
        [(shown, _)] = ask([["tailscale", "status", "--json"]])
        status = json.loads(shown or "{}")
    except (OSError, ValueError):       # no tailscale here, or no status from it
        status = {}
    if status.get("BackendState") != "Running":
        return [], "no Tailscale network here to look through"
    named = _listed()
    hosts = {line.partition(" ")[2].lower().removesuffix(".")
             for name, (shown, _) in zip(named, ask([["ssh", "-G", "--", name] for name in named]))
             for line in (shown or f"hostname {name.rpartition('@')[2]}").splitlines()
             if line.startswith("hostname ")}
    me, names = (status.get("Self") or {}).get("UserID"), []
    for peer in (status.get("Peer") or {}).values():
        dns = (peer.get("DNSName") or "").lower().removesuffix(".")
        if (dns and peer.get("Online") and peer.get("OS") == "linux" and peer.get("UserID") == me
                and not hosts & {dns, dns.split(".")[0], *(peer.get("TailscaleIPs") or ())}):
            names.append(f"ak@{dns}")
    # no config read, so no key but ak's is offered; a host key is learned as a typed address's
    # is, Tailscale vouching for whom it reaches
    alone = ("-F", "none", "-o", "IdentitiesOnly=yes", "-o",
             f'IdentityFile="{config.SECRETS / KEY}"', "-o", "StrictHostKeyChecking=accept-new")
    now = time.time()
    answers = ask([[*SSH, *alone, "--", name, shlex.join(_probe(HERE))] for name in names])
    names = [name for name, (answer, _) in zip(names, answers) if _recorded(name, answer, now)]
    return names, "" if names else "no machine on your Tailscale network answered ak's key"


def _recorded(name, answer, now):
    """Whether `name`'s answer to the probe asked at `now` says what it is, recorded if so as
    its first check."""
    said = _said(answer)
    if said:
        _write(lambda record: record.update({name: {"checks": [[now, True]],
                                                    "said": {**said, "at": now}}}))
    return bool(said)


def ssh(name, *options):
    """The words of ak's ssh to `name` with ssh's `options`, its command after them: SSH's own
    config, ak's key, once made, offered after the keys that gives it."""
    keys = [word for path in _keys(name) for word in ("-o", f'IdentityFile="{path}"')]
    return [*SSH, *options, *keys, "--", name]


def _keys(name):
    """The key files ak's ssh names for `name`: none until ak's key is made, then the ones SSH's
    own config gives `name` (`ssh -G`), in its order, and ak's last, so a machine set up by hand
    is offered first what it was.  Naming any ends the defaults ssh offers while none is, so
    they are named too; the config's own it drops as named twice."""
    key = config.SECRETS / KEY
    if not key.exists():
        return []
    [(shown, _)] = ask([["ssh", "-G", "--", name]])     # bounded, a config's `Match exec` with it
    read = (line.partition(" ") for line in (shown or "").splitlines())
    return [*(path for setting, _, path in read if setting == "identityfile"), key]


def public_key():
    """The public half of ak's key (`ssh`), the pair made the first time it is asked for, its
    private half its owner's alone."""
    key = config.SECRETS / KEY
    config.ensure_dirs()
    with config._record_lock(key):      # two screens asking at once make one pair
        if not key.exists():
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "ak", "-f", key],
                           stdin=subprocess.DEVNULL, capture_output=True, check=True)
    return key.with_name(f"{KEY}.pub").read_text().strip()


def join_line():
    """The line that makes a new Linux machine one ak reaches by its key, over Tailscale:
    tools/join.sh as this install's origin has it on its default branch, so a fork's is its own,
    or on GitHub's name for that branch where the clone has none."""
    origin = gitcall.git(config.REPO, "remote", "get-url", "origin", check=False)
    branch = gitcall.git(config.REPO, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD",
                         check=False).removeprefix("origin/") or "HEAD"
    url = (f"https://raw.githubusercontent.com/{gitcall.owner_name(origin)}/{branch}/"
           "tools/join.sh")
    return f"curl -fsSL {shlex.quote(url)} | sudo bash -s -- {shlex.quote(public_key())} tailscale"


def _probe(name, *options):
    """The command asking `name` what it is, over ssh given `options`."""
    script = PROBE.read_text()
    return (["bash", "-c", script] if name == HERE else
            [*ssh(name, *options), shlex.join(["bash", "-c", script])])


def _record():
    """The record, of each machine whose entry is a table, its last answer none where that is
    not one: ak writes neither, and a check it keeps stays."""
    try:
        record = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {name: was if isinstance(was.get("said") or {}, dict) else {**was, "said": None}
            for name, was in record.items() if isinstance(was, dict)} \
        if isinstance(record, dict) else {}


def _write(change):
    """`change` the record under its lock: the tick and `add` each read it, change it and write
    it whole, through the one temporary file, so each keeps what the other wrote."""
    with config._record_lock(_path()):
        record = _record()
        change(record)
        temp = _path().with_suffix(".tmp")
        temp.write_text(json.dumps(record) + "\n", encoding="utf-8")
        temp.replace(_path())


def _path():
    return config.STATE / "machines.json"


def ask(commands):
    """Of each of `commands`, run side by side: what it printed, None if it failed or still ran
    TIMEOUT on, and what it said on stderr, None if it still ran.  It ends with all it started.
    Each is read while it runs, so no pipe it fills, as with a long ssh banner, holds it."""
    deadline = time.monotonic() + TIMEOUT
    procs = [subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, errors="replace",
                              start_new_session=True) for command in commands]
    with ThreadPoolExecutor(max(1, len(procs))) as pool:
        return list(pool.map(lambda proc: _answer(proc, deadline), procs))


def _answer(proc, deadline):
    with proc:
        try:
            out, errors = proc.communicate(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)     # unreaped, it still names its group
            return None, None
        return None if proc.returncode else out, errors


def _said(answer):
    """What the probe answered, by READINGS and those of MAY it gave, or None: it did not
    answer or said too little."""
    said = dict(line.partition(" ")[::2] for line in (answer or "").splitlines())
    try:
        return ({name: kind(said[name]) for name, kind in READINGS.items()}
                | {name: kind(said[name]) for name, kind in MAY.items() if name in said})
    except (KeyError, ValueError):
        return None


def _gb(mb):
    gb = mb / 1024
    return f"{gb:.1f}".removesuffix(".0") + " GB" if gb < 10 else f"{gb:.0f} GB"


def _when(at):
    """Its hour and minute, with its day unless that is today."""
    day = time.localtime(at)
    today = time.localtime(time.time())[:3] == day[:3]
    return time.strftime("%H:%M" if today else f"{day.tm_mday} %b %H:%M", day)
