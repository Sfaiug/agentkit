"""Read-only host and cgroup counters, with no agentkit imports or policy."""

import json
import os
import time
from pathlib import Path
from typing import NamedTuple

PROC = Path("/proc")
OWN_CGROUP = PROC / "self/cgroup"
CGROUP_ROOT = Path("/sys/fs/cgroup")


def cpu_count():
    return os.cpu_count() or 1


def alive(pid):
    """Process existence only; run ownership also requires process_active's identity check."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ProcStat(NamedTuple):
    """The fields of `/proc/<pid>/stat` ak reads: state letter, parent, start in clock ticks."""
    state: str
    ppid: int
    start: int

    @property
    def exited(self):
        """A zombie or a dead task: it runs nothing, though it may still answer kill(0)."""
        return self.state in ("Z", "X")


def proc_stat(pid, proc_root=PROC):
    """That process's `ProcStat`, or None where its stat cannot be read.

    The command name sits in parentheses and may hold spaces or `)`, so the fields are
    counted after the last `)`.  Linux keeps 15 bytes of a name, which may end inside a
    UTF-8 character, so the name is never decoded strictly.  What None means -- gone,
    hidden, or not proof of anything -- is the caller's to say.
    """
    try:
        fields = ((Path(proc_root) / str(pid) / "stat").read_text(errors="replace")
                  .rsplit(")", 1)[1].split())
        return ProcStat(fields[0], int(fields[1]), int(fields[19]))
    except (OSError, ValueError, IndexError):
        return None


def process_identity(pid):
    """Linux process birth, including the boot so a reboot cannot recycle an identity."""
    stat = proc_stat(pid)
    if stat is None or stat.exited:
        return None
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        btime = next(line.split()[1] for line in Path("/proc/stat").read_text().splitlines()
                     if line.startswith("btime "))
        return {"boot": boot, "ticks": stat.start,
                "started_at": int(btime) + stat.start / os.sysconf("SC_CLK_TCK")}
    except (OSError, ValueError, StopIteration):
        return None


def _cgroup_text(pid="self", cgroup_file=None):
    if cgroup_file is None:
        cgroup_file = (os.environ.get("AK_CGROUP_FILE") or OWN_CGROUP
                       if pid == "self" else PROC / str(pid) / "cgroup")
    try:
        return Path(cgroup_file).read_text()
    except (OSError, ValueError, TypeError):
        return None


def process_cgroup(pid="self", cgroup_file=None):
    """The unified cgroup holding a process, relative to the cgroup root, or None."""
    text = _cgroup_text(pid, cgroup_file)
    return next((row[3:] for row in (text or "").splitlines()
                 if row.startswith("0::")), None)


def cgroup_contains(name, pid="self"):
    """Whether the process's membership names this group, including legacy hierarchies."""
    return name in (_cgroup_text(pid) or "")


def cgroup_path(relative="", cgroup_root=None):
    root = cgroup_root if cgroup_root is not None else os.environ.get("AK_CGROUP_ROOT", CGROUP_ROOT)
    return Path(root) / relative.lstrip("/")


def cgroup_pids(relative, *, complete=False):
    """The pids, in order, the kernel holds in that cgroup and every one under it: a group's own
    `cgroup.procs` leaves out its children's.  A list or directory that cannot be read adds none,
    or, with `complete`, makes the answer None, since it may hide any process; a threaded
    child's list never can be read, and its processes are on its thread root's."""
    pids, unread = [], []
    for directory, _, _ in os.walk(cgroup_path(relative), onerror=unread.append):
        try:
            pids += [int(pid) for pid in (Path(directory) / "cgroup.procs").read_text().split()]
        except (OSError, ValueError) as error:
            unread.append(error)
    return None if complete and unread else sorted(pids)


def memory_mb(name, meminfo=None, *, whole=False):
    """One host memory counter in MiB, or None when missing or unreadable."""
    path = Path(meminfo) if meminfo else PROC / "meminfo"
    try:
        for line in path.read_text().splitlines():
            if line.startswith(f"{name}:"):
                value = line.split()[1]
                return int(value) // 1024 if whole else float(value) / 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _mem_total_mb(meminfo=None):
    return memory_mb("MemTotal", meminfo, whole=True)


def cgroup_tasks(cgroup):
    """(tasks running, ceiling), with None for each missing or unreadable counter."""
    numbers = []
    for name in ("pids.current", "pids.max"):
        try:
            value = (cgroup / name).read_text().strip()
        except OSError:
            value = ""
        numbers.append(int(value) if value.isdigit() else None)
    return tuple(numbers)


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _reading(readings, *names):
    for name in names:
        value = _number(readings.get(name))
        if value is not None:
            return value
    return None


def _g(value):
    if value is None:
        return "?"
    value = value / 1024
    return f"{value:.1f}".rstrip("0").rstrip(".")


def resident_bytes(pid, proc_root=PROC):
    """Resident bytes for one pid from its statm, or None where unread."""
    try:
        resident = int((Path(proc_root) / str(pid) / "statm").read_text().split()[1])
    except (OSError, ValueError, IndexError):
        return None
    try:
        return resident * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError):
        return None


def _unit_memory(readings):
    """(used, high, raw, name, swap) for the cgroup the gate reads, or None.

    ``used`` excludes reclaimable file cache; ``raw`` includes it or is None
    where the readings predate it; neither includes ``swap``. A list carries the nearest
    limit first, so the first valid entry wins.
    """
    limits = readings.get("unit_limits")
    if isinstance(limits, (tuple, list)):
        for entry in limits:
            if not isinstance(entry, (tuple, list)):
                continue
            if len(entry) == 2:
                used, high = entry
                if (_number(used) is not None and _number(high) is not None
                        and high >= 0):
                    return (used, high, None, None, 0.0)
            elif len(entry) >= 3:
                used, high, raw = entry[0], entry[1], entry[2]
                name = entry[3] if len(entry) > 3 else None
                swap = _number(entry[4] if len(entry) > 4 else None) or 0.0
                if (_number(used) is None or _number(high) is None
                        or high < 0):
                    continue
                raw = _number(raw)
                name = name if isinstance(name, str) and name else None
                return (used, high, raw, name, swap)
    current = _reading(readings, "unit_memory_current_mb", "memory_current_mb")
    high = _reading(readings, "unit_memory_high_mb", "memory_high_mb")
    if current is not None and high is not None and high >= 0:
        raw = _reading(readings, "unit_memory_raw_mb", "unit_memory_with_cache_mb",
                       "memory_raw_mb")
        name = readings.get("unit_memory_name", readings.get("unit_name"))
        name = name if isinstance(name, str) and name else None
        return (current, high, raw, name, _reading(readings, "unit_memory_swap_mb") or 0.0)
    return None


def _slice_or_unit_memory(readings):
    """(used, high, raw, name, swap) for the slice, else the nearest limited unit."""
    used = _reading(readings, "slice_memory_used_mb")
    high = _reading(readings, "slice_memory_high_mb")
    if used is not None and high is not None and high >= 0:
        return (used, high, None, None, _reading(readings, "slice_memory_swap_mb") or 0.0)
    return _unit_memory(readings)


def _read_number(path, *, bytes_to_mb=False):
    try:
        value = path.read_text().strip()
    except OSError:
        return None
    if value == "max":
        return None
    try:
        value = float(value)
    except ValueError:
        return None
    return value / (1024 * 1024) if bytes_to_mb else value


def _swap_mb(cgroup):
    """A cgroup's memory in swap in MB, 0 where none is accounted.

    Named beside RAM, never added to it: a cap bounds RAM alone, the kernel moves cold pages
    to swap to make room, and what paging them back costs shows as memory pressure, which the
    gate reads over a minute.  Counted as RAM, seats' cold swap kept every run out of a calm
    slice for a day (25 Oct 2026).
    """
    return _read_number(Path(cgroup) / "memory.swap.current", bytes_to_mb=True) or 0.0


def _reclaimable_mb(path):
    """Reclaimable file cache in MB from a cgroup's memory.stat, or None.

    The kernel reclaims file cache under pressure, before any OOM kill: the pages on its
    file lists, active_file and inactive_file. tmpfs and shared memory sit on the anon
    lists, which no reclaim frees without swap, and locked or ramfs pages on the
    unevictable one, so `file`, which counts them all, would overstate it.
    """
    try:
        text = path.read_text()
    except OSError:
        return None
    values = []
    for line in text.splitlines():
        key, _, rest = line.partition(" ")
        if key in ("active_file", "inactive_file"):
            try:
                values.append(float(rest.split()[0]))
            except (ValueError, IndexError):
                continue
    return sum(values) / (1024 * 1024) if values else None


def _unit_memory_limits(cgroup_file=None, cgroup_root=None, *, all_limits=False, hard=False):
    """The nearest ancestor with a finite memory.high, as one (used, high, raw, name, swap).

    The used figure excludes reclaimable file cache; neither it nor raw includes swap. An empty
    list means no finite limit or no reading of its use. With `all_limits`, include each
    enclosing limit, memory.max too: a child cannot spend its parent's headroom.
    With `hard`, read only enclosing memory.max caps; reclaim frees file cache before an
    OOM kill there too, and where memory.stat cannot say how much, all of it counts.
    """
    try:
        relative = next(line.split("::", 1)[1] for line in
                        (_cgroup_text(cgroup_file=cgroup_file) or "").splitlines()
                        if "::" in line)
    except (OSError, StopIteration, IndexError):
        return []
    root = cgroup_path(cgroup_root=cgroup_root)
    current = root / relative.lstrip("/")
    limits = []
    while current == root or root in current.parents:
        high = _read_number(current / ("memory.max" if hard else "memory.high"),
                            bytes_to_mb=True)
        if all_limits and not hard:
            cap = _read_number(current / "memory.max", bytes_to_mb=True)
            if cap is not None:
                high = min(high, cap) if high is not None else cap
        if high is not None:
            raw = _read_number(current / "memory.current", bytes_to_mb=True)
            cache = _reclaimable_mb(current / "memory.stat")
            if cache is None and hard:
                cache = 0.0
            if raw is not None and cache is not None:
                swap = _swap_mb(current)
                limits.append((max(0.0, raw - cache), high, raw,
                               current.name if current != root else "/", swap))
            if not (all_limits or hard):
                return limits
        if current == root:
            break
        current = current.parent
    return limits


def _pressure_avg(text):
    """The larger `some` percentage of avg10 and avg60 in a pressure body, or None when it
    says none: two calm ten-second readings must not hide a minute of stalls."""
    for line in text.splitlines():
        if line.startswith("some "):
            try:
                return max(float(part.split("=", 1)[1]) for part in line.split()
                           if part.startswith(("avg10=", "avg60=")))
            except ValueError:
                return None
    return None


def _slice_pressure(slice_dir, resource):
    """The cgroup's `some` stalls for a resource (`_pressure_avg`), or None where nothing answers."""
    if slice_dir is None:
        return None
    try:
        return _pressure_avg((slice_dir / f"{resource}.pressure").read_text())
    except OSError:
        return None


def _cpu_pressure(paths, delay):
    """Current CPU stall percentage over a measured window, across the named groups.

    PSI's cumulative `some total` catches contention now, including short bursts
    the ten-second average dilutes. Missing or reset counters are no reading.
    """
    def totals():
        readings = {}
        for path in paths:
            try:
                for line in path.read_text().splitlines():
                    if line.startswith("some "):
                        for field in line.split():
                            if field.startswith("total="):
                                readings[path] = int(field.split("=", 1)[1])
            except (OSError, ValueError):
                continue
        return readings

    first = totals()
    if not first:
        return None
    began = time.monotonic()
    time.sleep(delay)
    second = totals()
    elapsed = time.monotonic() - began
    if elapsed <= 0:
        return None
    rates = [(value - first[path]) / (elapsed * 10000) for path, value in second.items()
             if path in first and value >= first[path]]
    return max(rates) if rates else None


def _slice_cpu_stat(slice_dir):
    """The cgroup's cpu.stat counters as {name: value}, or None where nothing answers.

    Counters are cumulative since the cgroup was created.
    """
    if slice_dir is None:
        return None
    try:
        text = (slice_dir / "cpu.stat").read_text()
    except OSError:
        return None
    counters = {}
    for line in text.splitlines():
        key, _, rest = line.partition(" ")
        if not key:
            continue
        try:
            counters[key] = int(rest.split()[0])
        except (ValueError, IndexError):
            continue
    return counters


def _slice_cpu_quota(cgroup):
    """The cgroup's CPU quota in cores, or None when it sets none.

    `max` sets none.
    """
    if cgroup is None:
        return None
    try:
        parts = (cgroup / "cpu.max").read_text().split()
        if len(parts) != 2 or parts[0] == "max":
            return None
        return int(parts[0]) / int(parts[1])
    except (OSError, ValueError, ZeroDivisionError):
        return None


def _cpu_usage_usec(cgroup):
    """The cgroup's cumulative `cpu.stat` `usage_usec`, or None when it cannot be read."""
    try:
        for line in (cgroup / "cpu.stat").read_text().splitlines():
            if line.startswith("usage_usec"):
                return float(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _cpu_rates(cgroups, delay=0.1):
    """Each readable cgroup's live CPU use in cores, from one shared sample window.

    Two samples of `usage_usec` around a tenth of a second of sleep: the rate over the
    measured window.  A single sample is cumulative since the cgroup was made, which says
    nothing live; dividing by the measured elapsed rather than the requested sleep keeps
    a delayed wakeup from overestimating.  A cgroup unreadable at either sample is left out.
    """
    first = {cgroup: _cpu_usage_usec(cgroup) for cgroup in cgroups}
    first = {cgroup: value for cgroup, value in first.items() if value is not None}
    if not first:
        return {}
    start = time.monotonic()
    time.sleep(delay)
    second = {cgroup: _cpu_usage_usec(cgroup) for cgroup in first}
    elapsed = time.monotonic() - start
    if elapsed <= 0:
        return {}
    return {cgroup: max(0.0, (second[cgroup] - value) / (elapsed * 1000000))
            for cgroup, value in first.items() if second[cgroup] is not None}


CPU_WEIGHT_MAX = 10000   # the kernel's top cpu.weight


def _cpu_weight(cgroup):
    try:
        return int((cgroup / "cpu.weight").read_text())
    except (OSError, ValueError):
        return None


def kept_cpu(slice_dir, delay=0.1):
    """The slice's live CPU use this process cannot take for itself, or None where it takes none.

    The kernel shares a parent's CPU among its busy children by weight, so a cgroup at the
    top weight gets nearly all the live use of its lower-weighted siblings; the rest of the
    slice's use stays -- siblings at its own weight share alike, its own use is its own and
    nothing outside its parent yields.  The slice and those siblings are read in one sample
    window, so a burst between two readings cannot erase use another holds.  None at any lower
    own weight, or where the cgroups cannot be read.  Beside injected readings it reads only an
    injected cgroup tree: like `host_readings`, an injected snapshot avoids the real machine.
    """
    if os.environ.get("AK_HOST_READINGS") and not os.environ.get("AK_CGROUP_ROOT"):
        return None
    own = process_cgroup()
    if not own or slice_dir is None:
        return None
    path = cgroup_path(own)
    weight = _cpu_weight(path)
    if weight is None or weight < CPU_WEIGHT_MAX:
        return None
    try:
        siblings = [sibling for sibling in path.parent.iterdir()
                    if sibling.name != path.name and sibling.is_dir()]
    except OSError:
        return None
    lower = [sibling for sibling in siblings
             if (other := _cpu_weight(sibling)) is not None and other < weight]
    rates = _cpu_rates([Path(slice_dir), *lower], delay)
    if Path(slice_dir) not in rates:
        return None
    return max(0.0, rates[Path(slice_dir)] - sum(rates.get(sibling, 0.0) for sibling in lower))


def _slice_memory(cgroup):
    """(used, high, swap) of the cgroup in MB, used without reclaimable cache or swap.

    `memory.high` first, `memory.max` where high sets none;
    None where neither answers.
    """
    if cgroup is None:
        return None
    base = cgroup
    try:
        high = _read_number(base / "memory.high", bytes_to_mb=True)
        if high is None:
            high = _read_number(base / "memory.max", bytes_to_mb=True)
        if high is None:
            return None
        used = held_mb(base)
        swap = _swap_mb(base)
        return None if used is None else (used, high, swap)
    except OSError:
        return None


def held_mb(cgroup, *, swap=False):
    """A cgroup's memory in MB less the file cache reclaim frees, or None where unread; with
    `swap`, what it swapped out too (`_swap_mb`)."""
    raw = _read_number(Path(cgroup) / "memory.current", bytes_to_mb=True)
    cache = _reclaimable_mb(Path(cgroup) / "memory.stat")
    swapped = _swap_mb(cgroup) if swap else 0.0
    return None if raw is None or cache is None else max(0.0, raw - cache) + swapped


def own_cgroup():
    """This process's cgroup where it holds nothing but this process and what it started,
    or None: only there is a change in its memory this process's doing."""
    relative = process_cgroup()
    pids = (cgroup_pids(relative, complete=True) if relative else None) or []
    if os.getpid() not in pids:
        return None
    for pid in pids:
        seen = set()
        while pid != os.getpid():
            stat = proc_stat(pid, PROC)
            if stat is None or pid in seen:
                return None
            seen.add(pid)
            pid = stat.ppid
    return cgroup_path(relative)


def host_readings(source=None, cgroup_file=None, cgroup_root=None, *, slice_dir=None,
                  cpu_dir=None, pressure_window=None, all_limits=False):
    """Host and caller-named cgroup readings; an injected snapshot avoids all reads.

    `slice_dir` may be a directory or a callable locating it after injection is checked.
    `cpu_dir` selects a child for CPU readings only; memory and CPU used outside
    the containing slice still read `slice_dir`, so sibling CPU is reclaimable.
    `pressure_window` samples live CPU stalls on the host, slice and caller's cgroup;
    `all_limits` includes hard memory caps and enclosing groups.
    """
    if source is not None:
        readings = source() if callable(source) else source
        return dict(readings or {})
    injected = os.environ.get("AK_HOST_READINGS")
    if injected:
        try:
            readings = json.loads(injected)
            if isinstance(readings, dict):
                return readings
        except (json.JSONDecodeError, TypeError):
            pass
    meminfo = {}
    try:
        for line in (PROC / "meminfo").read_text().splitlines():
            key, _, value = line.partition(":")
            fields = value.split()
            if fields:
                meminfo[key] = float(fields[0]) / 1024
    except (OSError, ValueError, IndexError):
        pass
    try:
        load = float((PROC / "loadavg").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        load = None
    if callable(slice_dir):
        slice_dir = slice_dir()
    if callable(cpu_dir):
        cpu_dir = cpu_dir()
    if cpu_dir is None:
        cpu_dir = slice_dir
    limits = _unit_memory_limits(cgroup_file, cgroup_root, all_limits=all_limits)
    caps = _unit_memory_limits(cgroup_file, cgroup_root, hard=True)
    readings = {"free_mb": meminfo.get("MemAvailable"), "mem_total_mb": meminfo.get("MemTotal"),
                "load": load, "cpus": cpu_count(), "unit_limits": limits,
                "unit_memory_max_headroom_mb": min((cap - used for used, cap, *_ in caps),
                                                   default=None),
                "slice_cpu_pressure": _slice_pressure(cpu_dir, "cpu"),
                "slice_memory_pressure": _slice_pressure(slice_dir, "memory"),
                "slice_cpu_stat": _slice_cpu_stat(cpu_dir)}
    if limits:
        used, high, raw, name, swap = limits[0]
        readings["unit_memory_swap_mb"] = swap
        readings["unit_memory_current_mb"] = used
        readings["unit_memory_high_mb"] = high
        readings["unit_memory_raw_mb"] = raw
        readings["unit_memory_name"] = name
    try:
        cpu_quota = _slice_cpu_quota(cpu_dir)
        parent_cpu_quota = _slice_cpu_quota(slice_dir) if cpu_dir != slice_dir else None
        if parent_cpu_quota is not None:
            cpu_quota = min(cpu_quota, parent_cpu_quota) if cpu_quota is not None else parent_cpu_quota
    except Exception:
        cpu_quota = None
    cpu_used = outside = None
    if cpu_dir is not None:
        # Sample CPU outside the containing slice alongside both groups, so a burst
        # between readings cannot count a sibling as outside work.
        whole = cgroup_path("", cgroup_root)
        try:
            rates = _cpu_rates(list(dict.fromkeys(
                path for path in (cpu_dir, slice_dir, whole) if path is not None)))
        except Exception:
            rates = {}
        cpu_used = rates.get(cpu_dir)
        # Before its first launch a child has no cgroup and holds no CPU.
        if (cpu_dir != slice_dir and slice_dir is not None and slice_dir.is_dir()
                and not cpu_dir.exists()):
            cpu_used = 0.0
        shared_used = rates.get(slice_dir if slice_dir is not None else cpu_dir)
        if shared_used is not None and whole in rates:
            outside = max(0.0, rates[whole] - shared_used)
    try:
        mem = _slice_memory(slice_dir)
    except Exception:
        mem = None
    readings["slice_cpu_quota"] = cpu_quota
    readings["slice_cpu_used"] = cpu_used
    readings["outside_cpu_used"] = outside
    if mem is not None:
        (readings["slice_memory_used_mb"], readings["slice_memory_high_mb"],
         readings["slice_memory_swap_mb"]) = mem
    else:
        readings["slice_memory_used_mb"] = readings["slice_memory_high_mb"] = None
    if pressure_window is not None:
        paths = {PROC / "pressure/cpu"}
        if cpu_dir is not None:
            paths.add(cpu_dir / "cpu.pressure")
        own = process_cgroup(cgroup_file=cgroup_file)
        if own is not None:
            paths.add(cgroup_path(own, cgroup_root) / "cpu.pressure")
        readings["cpu_pressure"] = _cpu_pressure(paths, pressure_window)
    return readings


def memory_events(path):
    """A cgroup directory's memory.events counters by name, below it included; none where
    it cannot be read."""
    try:
        text = (Path(path) / "memory.events").read_text()
    except OSError:
        return {}
    return {key: int(value) for key, value in (line.split(" ", 1) for line in text.splitlines()
                                               if " " in line) if value.strip().isdigit()}


def _oom_kill_count(cgroup):
    """How many processes the kernel OOM-killed in that cgroup, or 0 if it cannot be read.

    A removed or unreadable cgroup has no count.
    """
    return memory_events(cgroup_path(cgroup)).get("oom_kill", 0) if cgroup else 0


def _scope_readings(scope_dir):
    """(live processes, resident bytes) from a scope's cgroup files, or None.

    `cgroup.procs` names every live process the kernel still holds there, one
    pid a line; `memory.current` is their resident bytes.  Either file missing
    or unreadable is no reading, never a zero.
    """
    try:
        procs = (Path(scope_dir) / "cgroup.procs").read_text().split()
        mem = (Path(scope_dir) / "memory.current").read_text().strip()
    except OSError:
        return None
    try:
        return len([line for line in procs if line.strip().isdigit()]), int(mem)
    except (ValueError, TypeError):
        return None


def frozen_cgroup(pid):
    """The cgroup freezing that process, or None: its own, or any one above it.

    Reads only files, so a frozen process need not answer a command.
    """
    relative = process_cgroup(pid)
    if relative is None:
        return None
    parts = [part for part in relative.split("/") if part]
    for depth in range(len(parts), -1, -1):
        held = cgroup_path().joinpath(*parts[:depth]) / "cgroup.freeze"
        try:
            if held.read_text().strip() == "1":
                return str(held.parent)
        except OSError:
            continue
    return None
