"""The machines ak may use and what each one is: this one, each `[machines.<ssh alias>]` of
config.toml and the `suite_helper`.  Hidden here: the probe, tools/machine.sh, each tick's on
all of them side by side, over ssh but for this one; its ssh options; and the history of their
answers, state/machines.json, the last three days' checks, which only the tick writes.
"""

from collections import namedtuple
import json
import os
import shlex
import signal
import subprocess
import time

from . import config

HERE = "this one"
PROBE = config.REPO / "tools" / "machine.sh"
TIMEOUT = 10        # the seconds a machine that does not answer holds the tick, all of them
SSH = ("ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={TIMEOUT}")
DAY = 86400
KEPT = 3 * DAY      # the checks "always on" is judged on; older ones go
# What the probe says, each read as its type; an answer missing one is no answer.
READINGS = {"system": str, "processor": str, "cores": int, "memory_mb": int, "free_mb": int,
            "load": float, "disk_free_mb": int, "battery": int, "power": int}


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
    """Every machine ak may use but this one: the owner's config.toml as is, not `config.load`'s."""
    try:
        named = (config._read_toml(config.HOME / config.CONFIG_NAME) or {}).get("machines")
    except config.Error:  # one mid-edit names none: a run's suite then runs here, not fails
        named = None
    names = [*(named if isinstance(named, dict) else ()), config.suite_helper()]
    return [name for name in dict.fromkeys(names) if name]


def known():
    """Every machine ak may use, this one first, as the ticks found it."""
    names = [HERE, *helpers()]
    try:
        record = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = {}
    return [Machine(name, record.get(name, {}).get("checks", []),
                    record.get(name, {}).get("said")) for name in dict.fromkeys(names) if name]


def check():
    """The tick's: asks each machine once, side by side, and records what it answered."""
    script = PROBE.read_text()
    deadline, now = time.monotonic() + TIMEOUT, time.time()
    asked = [(machine, subprocess.Popen(
        ["bash", "-c", script] if machine.name == HERE else
        [*SSH, "--", machine.name, shlex.join(["bash", "-c", script])],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        errors="replace", start_new_session=True)) for machine in known()]
    record = {}
    for machine, proc in asked:
        said = _said(proc, deadline)
        checks = [one for one in machine.checks if one[0] > now - KEPT]
        record[machine.name] = {"checks": [*checks, [now, bool(said)]],
                                "said": {**said, "at": now} if said else machine.said}
    temp = _path().with_suffix(".tmp")
    temp.write_text(json.dumps(record) + "\n", encoding="utf-8")
    temp.replace(_path())


def _path():
    return config.STATE / "machines.json"


def _said(proc, deadline):
    """What the probe said, by READINGS, or None: it failed, said too little or still ran at
    `deadline`, and ends with all it started.  Its lines fit the pipe: waited for, then read."""
    with proc:
        try:
            if proc.wait(max(0, deadline - time.monotonic())):
                return None
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)     # unreaped, it still names its group
            return None
        said = dict(line.partition(" ")[::2] for line in proc.stdout.read().splitlines())
    try:
        return {name: kind(said[name]) for name, kind in READINGS.items()}
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
