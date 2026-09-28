"""Read-only Linux process inventory, also runnable with isolated Python under sudo.

Keep this helper independent of agentkit imports: inspecting a hidden descriptor
needs privilege; loading the application or removing files does not.
"""

from itertools import chain
import json
import os
from pathlib import Path
import sys


def collect(processes):
    """Readable processes and unresolved pids; an exited process holds nothing."""
    rows, hidden = {}, []
    for proc in processes:
        if not proc.name.isdigit():
            continue
        try:
            fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
            # PF_KTHREAD identifies kernel threads; an empty userspace argv does not.
            if fields[0] in ("Z", "X") or int(fields[6]) & 0x200000:
                continue
            start = fields[19]
            uid = int(next(line for line in (proc / "status").read_text().splitlines()
                           if line.startswith("Uid:")).split()[1])
            args = [os.fsdecode(arg) for arg in (proc / "cmdline").read_bytes().split(b"\0")
                    if arg]
            paths = set(arg for arg in args if arg.startswith("/"))
            # Iterate while the descriptor is open: our own fd inventory includes it.
            with os.scandir(proc / "fd") as handles:
                for link in chain([proc / "cwd"], (proc / "fd" / entry.name for entry in handles)):
                    try:
                        target = os.readlink(link)
                    except FileNotFoundError:
                        if link == proc / "cwd":
                            raise
                        continue                # this descriptor has already closed
                    if target.startswith("/"):
                        paths.update((target, target.removesuffix(" (deleted)")))
            if (proc / "stat").read_text().rsplit(")", 1)[1].split()[19] != start:
                raise ValueError("pid was reused during the scan")
            rows[int(proc.name)] = {"uid": uid, "start": start, "args": args,
                                    "paths": sorted(paths)}
        except (OSError, ValueError, IndexError, StopIteration):
            try:
                proc.stat()
            except FileNotFoundError:
                continue
            except OSError:
                pass
            hidden.append(int(proc.name))
    return rows, hidden


if __name__ == "__main__":
    # Only numeric pids, never caller-supplied paths or application configuration.
    if not sys.argv[1:] or not all(pid.isdigit() for pid in sys.argv[1:]):
        raise SystemExit(2)
    print(json.dumps(collect(Path("/proc") / pid for pid in sys.argv[1:])))
