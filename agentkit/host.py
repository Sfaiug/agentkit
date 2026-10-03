"""Read-only host and cgroup counters, with no agentkit imports or policy."""

import json
import os
import time
from pathlib import Path

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


def process_identity(pid):
    """Linux process birth, including the boot so a reboot cannot recycle an identity."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] in ("Z", "X"):
            return None
        ticks = int(fields[19])
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        btime = next(line.split()[1] for line in Path("/proc/stat").read_text().splitlines()
                     if line.startswith("btime "))
        return {"boot": boot, "ticks": ticks,
                "started_at": int(btime) + ticks / os.sysconf("SC_CLK_TCK")}
    except (OSError, ValueError, IndexError, StopIteration):
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


def _unit_memory(readings):
    """(used, high, raw, name) for the cgroup the gate reads, or None.

    ``used`` excludes reclaimable file cache; ``raw`` includes it or is None
    where the readings predate it. A list carries the nearest
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
                    return (used, high, None, None)
            elif len(entry) >= 3:
                used, high, raw = entry[0], entry[1], entry[2]
                name = entry[3] if len(entry) > 3 else None
                if (_number(used) is None or _number(high) is None
                        or high < 0):
                    continue
                raw = _number(raw)
                name = name if isinstance(name, str) and name else None
                return (used, high, raw, name)
    current = _reading(readings, "unit_memory_current_mb", "memory_current_mb")
    high = _reading(readings, "unit_memory_high_mb", "memory_high_mb")
    if current is not None and high is not None and high >= 0:
        raw = _reading(readings, "unit_memory_raw_mb", "unit_memory_with_cache_mb",
                       "memory_raw_mb")
        name = readings.get("unit_memory_name", readings.get("unit_name"))
        name = name if isinstance(name, str) and name else None
        return (current, high, raw, name)
    return None


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


def _reclaimable_mb(path):
    """Reclaimable file cache in MB from a cgroup's memory.stat, or None.

    The kernel can reclaim file cache under pressure. Older kernels name
    the counter inactive_file where newer ones say file.
    """
    try:
        text = path.read_text()
    except OSError:
        return None
    values = {}
    for line in text.splitlines():
        key, _, rest = line.partition(" ")
        if key in ("file", "inactive_file"):
            try:
                values[key] = float(rest.split()[0])
            except (ValueError, IndexError):
                continue
    if "file" in values:
        return values["file"] / (1024 * 1024)
    if "inactive_file" in values:
        return values["inactive_file"] / (1024 * 1024)
    return None


def _unit_memory_limits(cgroup_file=None, cgroup_root=None, *, all_limits=False, hard=False):
    """The nearest ancestor with a finite memory.high, as one (used, high, raw, name).

    The used figure excludes reclaimable file cache. An empty list means
    no finite limit or no reading of its use. With `all_limits`, include each
    enclosing limit, memory.max too: a child cannot spend its parent's headroom.
    With `hard`, read only enclosing memory.max caps and count file cache too,
    since those bytes count toward OOM.
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
            cache = 0 if hard else _reclaimable_mb(current / "memory.stat")
            if raw is not None and cache is not None:
                limits.append((max(0.0, raw - cache), high, raw,
                               current.name if current != root else "/"))
            if not (all_limits or hard):
                return limits
        if current == root:
            break
        current = current.parent
    return limits


def _pressure_avg10(text):
    """The `some avg10` percentage in a cpu.pressure body, or None when it says none."""
    for line in text.splitlines():
        if line.startswith("some "):
            for part in line.split():
                if part.startswith("avg10="):
                    try:
                        return float(part.split("=", 1)[1])
                    except ValueError:
                        return None
    return None


def _slice_cpu_pressure(slice_dir):
    """The cgroup's CPU pressure, or None where nothing answers.

    The `some avg10` counter measures processes waiting on CPU.
    """
    if slice_dir is None:
        return None
    try:
        return _pressure_avg10((slice_dir / "cpu.pressure").read_text())
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


def _slice_cpu_used(cgroup, delay=0.1):
    """The cgroup's current CPU use in cores, or None when it cannot be read.

    Two samples of `cpu.stat`'s `usage_usec` around a tenth of a second of sleep:
    the rate over the measured window.  A single sample is cumulative since the
    cgroup was made, which says nothing live; dividing by the measured elapsed
    rather than the requested sleep keeps a delayed wakeup from overestimating.
    """
    if cgroup is None:
        return None
    path = cgroup / "cpu.stat"
    def _usage():
        try:
            for line in path.read_text().splitlines():
                if line.startswith("usage_usec"):
                    return float(line.split()[1])
        except (OSError, ValueError, IndexError):
            return None
        return None
    first = _usage()
    if first is None:
        return None
    start = time.monotonic()
    time.sleep(delay)
    second = _usage()
    if second is None:
        return None
    elapsed = time.monotonic() - start
    if elapsed <= 0:
        return None
    return max(0.0, (second - first) / (elapsed * 1000000))


def _slice_memory(cgroup):
    """(used, high) of the cgroup in MB, used without reclaimable cache.

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
        raw = _read_number(base / "memory.current", bytes_to_mb=True)
        if raw is None:
            return None
        cache = _reclaimable_mb(base / "memory.stat")
        if cache is None:
            return None
        return (max(0.0, raw - cache), high)
    except OSError:
        return None


def host_readings(source=None, cgroup_file=None, cgroup_root=None, *, slice_dir=None,
                  pressure_window=None, all_limits=False):
    """Host and caller-named cgroup readings; an injected snapshot avoids all reads.

    `slice_dir` may be a directory or a callable locating it after injection is checked.
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
    limits = _unit_memory_limits(cgroup_file, cgroup_root, all_limits=all_limits)
    caps = _unit_memory_limits(cgroup_file, cgroup_root, hard=True)
    readings = {"free_mb": meminfo.get("MemAvailable"), "mem_total_mb": meminfo.get("MemTotal"),
                "load": load, "cpus": cpu_count(), "unit_limits": limits,
                "unit_memory_max_headroom_mb": min((cap - used for used, cap, _, _ in caps),
                                                   default=None),
                "slice_cpu_pressure": _slice_cpu_pressure(slice_dir),
                "slice_cpu_stat": _slice_cpu_stat(slice_dir)}
    if limits and isinstance(limits[0], (tuple, list)) and len(limits[0]) >= 4:
        used, high, raw, name = limits[0][:4]
        readings["unit_memory_current_mb"] = used
        readings["unit_memory_high_mb"] = high
        readings["unit_memory_raw_mb"] = raw
        readings["unit_memory_name"] = name
    try:
        cpu_quota = _slice_cpu_quota(slice_dir)
    except Exception:
        cpu_quota = None
    try:
        cpu_used = _slice_cpu_used(slice_dir) if cpu_quota is not None else None
    except Exception:
        cpu_used = None
    try:
        mem = _slice_memory(slice_dir)
    except Exception:
        mem = None
    readings["slice_cpu_quota"] = cpu_quota
    readings["slice_cpu_used"] = cpu_used
    if mem is not None:
        readings["slice_memory_used_mb"], readings["slice_memory_high_mb"] = mem
    else:
        readings["slice_memory_used_mb"] = readings["slice_memory_high_mb"] = None
    if pressure_window is not None:
        paths = {PROC / "pressure/cpu"}
        if slice_dir is not None:
            paths.add(slice_dir / "cpu.pressure")
        own = process_cgroup(cgroup_file=cgroup_file)
        if own is not None:
            paths.add(cgroup_path(own, cgroup_root) / "cpu.pressure")
        readings["cpu_pressure"] = _cpu_pressure(paths, pressure_window)
    return readings


def _oom_kill_count(cgroup):
    """How many processes the kernel OOM-killed in that cgroup, or 0 if it cannot be read.

    A removed or unreadable cgroup has no count.
    """
    if not cgroup:
        return 0
    path = cgroup_path(cgroup) / "memory.events"
    try:
        text = path.read_text()
    except OSError:
        return 0
    for line in text.splitlines():
        key, _, value = line.partition(" ")
        if key == "oom_kill" and value.strip().isdigit():
            return int(value.strip())
    return 0


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
