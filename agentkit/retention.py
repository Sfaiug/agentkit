"""Conservative retention primitives. A name alone never proves temporary ownership."""

from contextlib import contextmanager
import fcntl
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import stat
import time
import tomllib

from . import config

EPHEMERAL_AGE = 86400            # ~/.agentkit/tmp older than a day goes
INTERRUPTED_AGE = 86400          # a dead writer is not a reason to keep yesterday's tmp
PRESSURE_AGE = 86400             # even a full disk keeps yesterday's diagnostics
MARKER = ".agentkit-ephemeral.json"
KINDS = {"smoke", "viewer", "update"}


def present(path):
    """Existence without dereferencing a symlink (even stat-through-link updates its atime)."""
    return os.path.lexists(path)


def safe(path):
    """No symlink ancestors, foreign owners, special files or hard-linked regular files."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        return False
    try:
        for parent in (*reversed(path.parents), path):
            info = parent.lstat()
            if stat.S_ISLNK(info.st_mode):
                return False
        info = path.lstat()
        return (info.st_uid == os.getuid() and
                (stat.S_ISDIR(info.st_mode) or
                 (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)))
    except OSError:
        return False


@contextmanager
def reading(path, directory=False):
    # O_NOATIME makes planning read-only even when callers compare access timestamps.
    # If unavailable/denied we decline collection rather than restore timestamps afterwards.
    if not hasattr(os, "O_NOATIME") or not safe(path):
        raise OSError(f"cannot read without changing metadata: {path}")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME
    if directory:
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        yield fd
    finally:
        os.close(fd)


def children(path):
    try:
        with reading(path, directory=True) as fd:
            return sorted(Path(path) / name for name in os.listdir(fd))
    except OSError:
        return []


def read_bytes(path):
    with reading(path) as fd, os.fdopen(os.dup(fd), "rb") as fh:
        return fh.read()


def read_json(path):
    try:
        value = json.loads(read_bytes(path))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, RecursionError):
        return None


def fingerprint(path):
    info = path.lstat()
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def tree(path, sockets=None, permitted=None):
    """Snapshot a tree without following links. None means ownership is not established."""
    if permitted is not None and not permitted(path):
        return None
    if not safe(path):
        return None
    found = {str(path): fingerprint(path)}
    if path.is_dir():
        try:
            with reading(path, directory=True) as fd:
                entries = os.listdir(fd)
            for name in sorted(entries):
                child = path / name
                if permitted is not None and not permitted(child):
                    return None
                # Links inside a disposable tree are unlinked, never traversed. Their targets
                # may be foreign; only the link itself belongs to this directory.
                if child.is_symlink():
                    if child.lstat().st_uid != os.getuid():
                        return None
                    found[str(child)] = fingerprint(child)
                elif stat.S_ISSOCK(child.lstat().st_mode):
                    # Only a registered smoke tree opts into stale socket removal. Inspect
                    # kernel state without connecting, sending requests or waking a server.
                    if (sockets is None or child.lstat().st_uid != os.getuid()
                            or socket_active(child, sockets)):
                        return None
                    found[str(child)] = fingerprint(child)
                else:
                    sub = tree(child, sockets, permitted)
                    if sub is None:
                        return None
                    found.update(sub)
        except OSError:
            return None
    return found


def unix_sockets():
    """Filesystem sockets still held by the kernel; None means they cannot be proven dead."""
    try:
        lines = Path("/proc/net/unix").read_text().splitlines()
        if not lines or not lines[0].startswith("Num"):
            return None
        return {parts[7] for line in lines[1:] if len(parts := line.split(maxsplit=7)) == 8
                and not parts[7].startswith("@")}
    except OSError:
        return None


def socket_active(path, sockets):
    # Relative bind names have no recorded cwd. Conservatively protect any matching basename.
    return str(path) in sockets or any(not name.startswith("/") and Path(name).name == path.name
                                       for name in sockets)


def git_directory(repo):
    path = repo / ".git"
    if not safe(path):
        raise ValueError("unsafe git directory")
    if path.is_file():
        prefix, sep, value = read_bytes(path).decode().strip().partition(": ")
        if prefix != "gitdir" or not sep:
            raise ValueError("invalid git pointer")
        path = Path(os.path.abspath(repo / value))
    if not safe(path):
        raise ValueError("unsafe git directory")
    return path


def git_ref(common, ref):
    if not ref.startswith("refs/heads/") or ".." in Path(ref).parts:
        return None
    path = common / ref
    if present(path):
        return read_bytes(path).decode().strip()
    packed = common / "packed-refs"
    if safe(packed):
        for line in read_bytes(packed).decode().splitlines():
            sha, _, name = line.partition(" ")
            if name == ref:
                return sha
    return None


def index_entries(path):
    """Read ordinary SHA-1 Git indexes without Git refreshing indexes or access timestamps.

    Split/sparse indexes, submodules, symlinks and unfamiliar index versions are deliberately
    ineligible. Retention must understand every tracked file before removing a checkout.
    """
    import hashlib
    import struct
    data = read_bytes(path)
    magic, version, count = struct.unpack_from("!4sII", data)
    if magic != b"DIRC" or version not in (2, 3) or hashlib.sha1(data[:-20]).digest() != data[-20:]:
        raise ValueError("unsupported index")
    entries, offset = {}, 12
    for _ in range(count):
        start = offset
        mode = struct.unpack_from("!I", data, offset + 24)[0]
        oid = data[offset + 40:offset + 60]
        flags = struct.unpack_from("!H", data, offset + 60)[0]
        offset += 62
        if flags & 0x4000:
            offset += 2
        end = data.index(b"\0", offset)
        name = data[offset:end]
        offset = start + ((end - start + 8) // 8) * 8
        if (flags & 0x3000 or mode not in (0o100644, 0o100755) or not name
                or name.startswith(b"/") or b".." in name.split(b"/") or name in entries):
            raise ValueError("unsupported index entry")
        entries[name] = (mode, oid)
    # Lowercase index extensions are required; in particular `link` is a split index.
    while offset < len(data) - 20:
        signature, size = struct.unpack_from("!4sI", data, offset)
        if not signature[:1].isupper():
            raise ValueError("unsupported index extension")
        offset += 8 + size
    if offset != len(data) - 20:
        raise ValueError("invalid index extent")
    return entries


def git_hash(kind, data):
    import hashlib
    return hashlib.sha1(kind + b" " + str(len(data)).encode() + b"\0" + data).digest()


def index_tree(entries):
    root = {}
    for name, entry in entries.items():
        parts, node = name.split(b"/"), root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = entry
    def digest(node):
        data = b""
        for name, entry in sorted(node.items(), key=lambda pair: pair[0] +
                                  (b"/" if isinstance(pair[1], dict) else b"")):
            mode, oid = (0o40000, digest(entry)) if isinstance(entry, dict) else entry
            data += f"{mode:o} ".encode() + name + b"\0" + oid
        return git_hash(b"tree", data)
    return digest(root).hex()


def clean_worktree(repo, wt, state, junk):
    """Prove checkout ownership and contents using no-atime reads, without running Git."""
    import fnmatch
    import re
    import struct
    import zlib
    try:
        common, private = git_directory(repo), git_directory(wt)
        if (not safe(wt) or private.parent != common / "worktrees"
                or read_bytes(private / "gitdir").decode().strip() != str(wt / ".git")):
            return False
        raw = read_bytes(private / "HEAD").decode().strip()
        if not raw.startswith("ref: "):
            return False
        head = git_ref(common, raw[5:])
        if not head or not re.fullmatch("[0-9a-f]{40}", head):
            return False
        review = state.get("review") or {}
        delivered = state.get("delivery_sha") or review.get("head_sha")
        if delivered:
            if head != delivered:
                return False
        elif head != git_ref(common, "refs/heads/" + (state.get("target") or state.get("base") or "main")):
            return False               # legacy record with no delivery identity needs local proof
        expected_tree = review.get("tree_sha") if review.get("head_sha") == head else None
        if not expected_tree:
            # Legacy records may predate saved review identities. Loose commit objects provide
            # local evidence; packed-only legacy commits remain until evidence is available.
            data = zlib.decompress(read_bytes(common / "objects" / head[:2] / head[2:]))
            if git_hash(b"commit", data.split(b"\0", 1)[1]).hex() != head:
                return False
            expected_tree = data.split(b"\0", 1)[1].splitlines()[0].removeprefix(b"tree ").decode()
        entries = index_entries(private / "index")
        if index_tree(entries) != expected_tree:
            return False
        tracked = {str(wt / os.fsdecode(name)) for name in entries}
        parents = {parent for name in tracked for parent in Path(name).parents if wt in parent.parents}
        def permitted(path):
            return (path == wt or path == wt / ".git" or str(path) in tracked or path in parents
                    or any(fnmatch.fnmatch(part + ("/" if pattern.endswith("/") else ""), pattern)
                           for part in path.relative_to(wt).parts for pattern in junk))
        # Inspect tracked directories before scanning disposable dependencies or hashing
        # blobs. Unknown output makes the checkout ineligible regardless of traversal order.
        for directory in (wt, *sorted(parents)):
            if not safe(directory):
                return False
            with reading(directory, directory=True) as fd:
                if any(not permitted(directory / name) for name in os.listdir(fd)):
                    return False
        snapshot = tree(wt, permitted=permitted)
        if snapshot is None:
            return False
        for name, (mode, oid) in entries.items():
            path = wt / os.fsdecode(name)
            if not safe(path) or not path.is_file() or bool(path.stat().st_mode & 0o111) != (mode == 0o100755):
                return False
            if git_hash(b"blob", read_bytes(path)) != oid:
                return False
        return tree(wt, permitted=permitted) == snapshot
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, struct.error, zlib.error):
        return False


def process_dirs():
    return Path("/proc").iterdir()


def process_paths():
    """Additional protection for orphaned writers holding a path after their owner exits.

    Login daemons may hide descriptors even from their own uid. They are not the recorded
    artifact writers: each candidate separately requires a dead process identity and a free
    writer lease. An unreadable *owner* is always treated as live by process_active. A missing
    process inventory, unlike individual disappearing/privileged descriptors, fails closed.
    """
    paths = set()
    try:
        processes = list(process_dirs())
    except OSError:
        return None
    for proc in processes:
        try:
            if not proc.name.isdigit() or proc.stat().st_uid != os.getuid():
                continue
        except OSError:
            continue
        try:
            handles = list((proc / "fd").iterdir())
        except OSError:
            handles = []
        for link in [proc / "cwd", *handles]:
            try:
                target = os.readlink(link).removesuffix(" (deleted)")
                if target.startswith("/"):
                    paths.add(target)
            except OSError:
                pass
        try:
            for arg in (proc / "cmdline").read_bytes().split(b"\0"):
                if arg.startswith(b"/"):
                    paths.add(os.fsdecode(arg))
        except OSError:
            pass
    return paths


def busy(path, paths):
    prefix = str(path) + "/"
    return paths is None or any(p == str(path) or p.startswith(prefix) for p in paths)


def marker(path):
    return path / MARKER if path.is_dir() else path.with_name(path.name + MARKER)


def begin(path, kind, pid=None):
    """Best-effort ownership registration. Unregistrable artifacts stay outside collection."""
    from . import run
    path = Path(path)
    if kind not in KINDS or path.parent != config.TMP or not safe(path):
        return False
    record = {"version": 1, "kind": kind, "path": str(path), "created_at": time.time(),
              **run.process_owner(pid)}
    try:
        with marker(path).open("x") as fh:
            json.dump(record, fh)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        return False
    return True


def finish(path):
    path = Path(path)
    if not safe(path):
        return False
    record = read_json(marker(path))
    if not record:
        return False
    record["finished_at"] = time.time()
    part = marker(path).with_name(marker(path).name + ".part")
    try:
        with part.open("x") as fh:
            json.dump(record, fh)
        part.replace(marker(path))
    except OSError:
        return False
    return True


@contextmanager
def artifact(path, kind):
    registered, lease = begin(path, kind), None
    if registered:
        try:
            lease = marker(path).open("r")
            fcntl.flock(lease, fcntl.LOCK_EX)
        except OSError:
            if lease:
                lease.close()
            lease = None
    try:
        yield path                     # retention must never prevent the actual operation
    finally:
        if registered:
            finish(path)
        if lease:
            lease.close()


def expired(value, now, age):
    import math
    return (type(value) in (int, float) and math.isfinite(value) and 0 < value <= now - age)


def throwaway(repo):
    """Is a run's repo one of the smoke suite's throwaway checkouts under ~/.agentkit/tmp.

    Those repos are made for one suite and deleted with it; the run records they
    leave behind name a checkout that no longer exists and belong to nobody, so
    gc collects them whole once they are old enough.  A run under ~/code keeps
    today's retention.
    """
    if not isinstance(repo, str) or not repo:
        return False
    try:
        path = Path(repo)
    except (OSError, ValueError):
        return False
    return path == config.TMP or config.TMP in path.parents


def writer_active(record):
    """Malformed or unreadable writer identity is uncertainty, never evidence of an exit."""
    from . import run
    pid, identity = record.get("pid"), record.get("process_identity")
    if pid is not None and (type(pid) is not int or pid <= 0):
        return True
    if identity is not None and (not isinstance(identity, dict) or not identity.get("boot")
                                 or type(identity.get("ticks")) is not int):
        return True
    try:
        return run.process_active(record)
    except (TypeError, ValueError, AttributeError):
        return True


def ephemeral_plan(now, pressure, paths):
    candidates = []
    sockets = unix_sockets()
    for path in children(config.TMP):
        if not safe(path) or path.name.endswith((MARKER, ".part")):
            continue
        receipt = marker(path)
        record = read_json(receipt)
        if (not record or record.get("version") != 1 or not isinstance(record.get("kind"), str) or record.get("kind") not in KINDS
                or record.get("path") != str(path) or "pid" not in record or writer_active(record)):
            continue
        finished = record.get("finished_at")
        age = (PRESSURE_AGE if pressure else EPHEMERAL_AGE) if finished else INTERRUPTED_AGE
        at = finished or record.get("created_at")
        if not expired(at, now, age) or busy(path, paths):
            continue
        snapshot = tree(path, sockets if record["kind"] == "smoke" else None)
        if snapshot is None or any(now - item[6] / 1e9 < age for item in snapshot.values()):
            continue
        # An interrupted receipt write might still be in flight. A later successful writer
        # replaces it; retention never guesses at its contents.
        if present(receipt.with_name(receipt.name + ".part")):
            continue
        try:
            with reading(receipt) as fd:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            continue
        candidates.append({"action": "remove", "kind": record["kind"], "path": str(path),
                           "receipt": str(receipt), "snapshot": snapshot,
                           "receipt_identity": fingerprint(receipt)})
    return candidates


def remove_ephemeral(item):
    """Revalidate under the writer's lease; a stale dry-run plan cannot authorize deletion."""
    path, receipt = Path(item["path"]), Path(item["receipt"])
    paths = process_paths()
    with reading(receipt) as fd:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (fingerprint(receipt) != item["receipt_identity"]
                or tree(path, unix_sockets() if item["kind"] == "smoke" else None) != item["snapshot"]
                or writer_active(read_json(receipt) or {}) or busy(path, paths)):
            return False
        if path.is_dir():
            shutil.rmtree(path)       # fd-based rmtree does not follow swapped directory links
        else:
            path.unlink()
            receipt.unlink()
    return True


def stale_sandboxes(now, paths):
    """`smoke-*` a day old, on the name and the age alone: what `ak run gc` takes.

    `ephemeral_plan` proves a sandbox before it takes it, and a suite's sandbox fails
    that proof on one hard link or foreign file inside it: 598 of 641 sat on the host
    that way.  Here the name is enough, once the rest holds -- under ~/.agentkit/tmp,
    owned, no symlink, its writer gone and nobody in it, and a day since the suite
    signed off, or since it began, or since the directory was written, whichever the
    receipt can say.
    """
    found = []
    for path in children(config.TMP):
        if not path.name.startswith("smoke-") or not safe(path) or not path.is_dir():
            continue
        record = read_json(marker(path)) or {}
        if record.get("pid") is not None and writer_active(record):
            continue
        at = record.get("finished_at") or record.get("created_at") or path.lstat().st_mtime
        if not expired(at, now, EPHEMERAL_AGE) or busy(path, paths):
            continue
        found.append({"action": "remove", "kind": "smoke-sandbox", "path": str(path)})
    return found


def gone_path(value):
    """Does that string name a place inside a `~/.agentkit/tmp/smoke-*` sandbox or a
    `~/.agentkit/wt/*` checkout, and is that sandbox or checkout gone?"""
    if not isinstance(value, str) or not value.startswith("/"):
        return False
    path = Path(value)
    if ".." in path.parts:
        return False
    for root, prefix in ((config.TMP, "smoke-"), (config.WT, "")):
        if root in path.parents:
            top = root / path.relative_to(root).parts[0]
            return top.name.startswith(prefix) and not present(top)
    return False


def strings(value):
    """Every string inside a parsed JSON or TOML value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


JSON_SPACE = re.compile(r"[ \t\n\r]*")
TOML_BLANK = re.compile(r"[ \t]*")
TOML_GAP = re.compile(r"(?:[ \t\r\n]|#[^\n]*)*")
TOML_LINE = re.compile(r"[ \t]*(?:#[^\n]*)?\r?\n?")
TOML_KEY = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'[^\'\n]*\'|[A-Za-z0-9_-]+')
TOML_STRING = re.compile(r'"""(?:[^"\\]|\\.|"(?!""))*""""{0,2}'
                         r"|'''(?:[^']|'(?!''))*''''{0,2}"
                         r'|"(?:[^"\\\n]|\\.)*"|\'[^\'\n]*\'', re.S)
TOML_SCALAR = re.compile(r"[^\s,\]}#]+(?: [0-9]{2}:[^\s,\]}#]*)?")


def cut(members, doomed, opening, closing):
    """The spans that take the doomed members out of the `{...}` between `opening` and
    `closing`, commas and all: a member with what follows it up to the next one, the last
    with what precedes it from the one kept before.  Taking every member leaves `{}`."""
    if not doomed:
        return []
    if len(doomed) == len(members):
        return [(opening + 1, closing)]
    spans = []
    for n, (_, start, end, _) in enumerate(members):
        if n in doomed:
            spans.append((start, members[n + 1][1]) if n + 1 < len(members)
                         else (members[max(set(range(n)) - doomed)][2], end))
    return spans


def splice(raw, spans):
    """`raw` less those character spans, overlapping ones taken once."""
    kept, at = [], 0
    for start, end in sorted(spans):
        kept.append(raw[at:max(at, start)])
        at = max(at, end)
    return "".join(kept) + raw[at:]


def json_members(raw, i):
    """([(key, start, end, value)], closing) of the JSON object whose `{` is at raw[i]: each
    member from its key's quote to the end of its value, and where that value starts."""
    decoder, members = json.JSONDecoder(), []
    i = JSON_SPACE.match(raw, i + 1).end()
    while raw[i] != "}":
        key, colon = json.decoder.scanstring(raw, i + 1)
        value = JSON_SPACE.match(raw, JSON_SPACE.match(raw, colon).end() + 1).end()
        end = decoder.raw_decode(raw, value)[1]
        members.append((key, i, end, value))
        i = JSON_SPACE.match(raw, end).end()
        if raw[i] == ",":
            i = JSON_SPACE.match(raw, i + 1).end()
    return members, i


def toml_key(raw, i):
    """(key, end) of the dotted TOML key at raw[i], each part read by tomllib itself."""
    parts = []
    while (match := TOML_KEY.match(raw, i)):
        parts.append(next(iter(tomllib.loads(match.group(0) + " = 0"))))
        i = TOML_BLANK.match(raw, match.end()).end()
        if not raw.startswith(".", i):
            return tuple(parts), i
        i = TOML_BLANK.match(raw, i + 1).end()
    raise ValueError(f"no TOML key at offset {i}")


def toml_value_end(raw, i):
    """Where the TOML value at raw[i] ends: a string of any quoting, an array over any
    number of lines, an inline table, or a bare scalar."""
    if (match := TOML_STRING.match(raw, i)):
        return match.end()
    if raw.startswith("[", i):
        i = TOML_GAP.match(raw, i + 1).end()
        while not raw.startswith("]", i):
            i = TOML_GAP.match(raw, toml_value_end(raw, i)).end()
            if raw.startswith(",", i):
                i = TOML_GAP.match(raw, i + 1).end()
            elif not raw.startswith("]", i):
                raise ValueError(f"no TOML array end at offset {i}")
        return i + 1
    if raw.startswith("{", i):
        return toml_inline(raw, i)[1] + 1
    if (match := TOML_SCALAR.match(raw, i)):
        return match.end()
    raise ValueError(f"no TOML value at offset {i}")


def toml_inline(raw, i):
    """([(key, start, end, value)], closing) of the inline table whose `{` is at raw[i]."""
    members = []
    i = TOML_GAP.match(raw, i + 1).end()
    while not raw.startswith("}", i):
        key, j = toml_key(raw, i)
        if not raw.startswith("=", j):
            raise ValueError(f"no `=` at offset {j}")
        value = TOML_BLANK.match(raw, j + 1).end()
        end = toml_value_end(raw, value)
        members.append((key, i, end, value))
        i = TOML_GAP.match(raw, end).end()
        if raw.startswith(",", i):
            i = TOML_GAP.match(raw, i + 1).end()
        elif not raw.startswith("}", i):
            raise ValueError(f"no inline table end at offset {i}")
    return members, i


def toml_statements(raw):
    """Every statement of a TOML document in order, as (kind, key, start, end, value): a
    `header` (its key None for an array of tables), a `pair`, or a `note` -- a blank or a
    comment line.  Each runs from its line's start to past its newline."""
    found, i = [], 0
    while i < len(raw):
        j, key, value = TOML_BLANK.match(raw, i).end(), None, None
        if raw.startswith("[", j):
            array = raw.startswith("[[", j)
            key, j = toml_key(raw, TOML_BLANK.match(raw, j + 1 + array).end())
            if not raw.startswith("]]" if array else "]", j):
                raise ValueError(f"no header end at offset {j}")
            kind, j, key = "header", j + 1 + array, None if array else key
        elif j == len(raw) or raw[j] in "#\r\n":
            kind = "note"
        else:
            key, j = toml_key(raw, j)
            if not raw.startswith("=", j):
                raise ValueError(f"no `=` at offset {j}")
            value = TOML_BLANK.match(raw, j + 1).end()
            kind, j = "pair", toml_value_end(raw, value)
        end = TOML_LINE.match(raw, j).end()
        if end <= i or (end < len(raw) and raw[end - 1] != "\n"):
            raise ValueError(f"no line end at offset {end}")
        found.append((kind, key, i, end, value))
        i = end
    return found


def toml_inline_cut(raw, opening, parent, stale):
    """The spans that take stale entries out of an inline table under key `parent`."""
    members, closing = toml_inline(raw, opening)
    doomed = {n for n, (key, *_) in enumerate(members) if (parent + key)[:2] in stale}
    spans = cut(members, doomed, opening, closing)
    for n, (key, _, _, value) in enumerate(members):
        if n not in doomed and len(parent + key) < 2 and raw.startswith("{", value):
            spans += toml_inline_cut(raw, value, parent + key, stale)
    return spans


def codex_pruned(raw):
    """(text, trust entries, MCP servers) of ~/.codex/config.toml without its stale entries.

    Text, not a TOML writer: codex, install.sh and `ak browser` all own keys here, and a round
    trip would lose their comments and their order.  An entry goes however it was written:
    a `[projects."<dir>"]` table from its header to its last key -- comments after that belong
    to what follows, like the agentkit block's end marker -- a key line under `[projects]`,
    or a member of an inline table.  The result must parse to exactly the old file less
    those entries, or it is None.
    """
    data = tomllib.loads(raw)
    stale = set()
    for section, test in (("projects", lambda key, _: gone_path(key)),
                          ("mcp_servers", lambda _, entry: any(map(gone_path, strings(entry))))):
        entries = data.get(section)
        if isinstance(entries, dict):
            stale |= {(section, key) for key, entry in entries.items() if test(key, entry)}
    statements, spans, table = toml_statements(raw), [], ()
    for n, (kind, key, start, end, value) in enumerate(statements):
        if kind == "header":
            table = key
            if key is None or key[:2] not in stale:
                continue
            body = []
            for statement in statements[n + 1:]:
                if statement[0] == "header":
                    break
                body.append(statement)
            last = max((m for m, statement in enumerate(body) if statement[0] == "pair"),
                       default=-1)
            note = next((statement for statement in body[last + 1:]
                         if raw[statement[2]:statement[3]].lstrip().startswith("#")), None)
            spans.append((start, note[2] if note else body[-1][3] if body else end))
        elif kind == "pair" and table is not None:
            path = table + key
            if len(table) < 2 and path[:2] in stale:
                spans.append((start, end))
            elif len(path) < 2 and raw.startswith("{", value):
                spans += toml_inline_cut(raw, value, path, stale)
    text = splice(raw, spans)
    result, expected = tomllib.loads(text), dict(data)
    for section in ("projects", "mcp_servers"):
        if isinstance(data.get(section), dict):
            kept = {k: v for k, v in data[section].items() if (section, k) not in stale}
            if kept or section in result:
                expected[section] = kept
            else:
                del expected[section]
    if result != expected:
        return None
    return (text, sum(section == "projects" for section, _ in stale),
            sum(section == "mcp_servers" for section, _ in stale))


def claude_pruned(raw):
    """(text, trust entries, MCP servers) of ~/.claude.json without its stale entries.

    The members go from the text itself, commas and all, so every other byte stays as the
    harness wrote it, whatever the layout; the result must parse to exactly the old
    document less those members, or it is None.
    """
    data = json.loads(raw)
    if not isinstance(data, dict):
        return None
    top, spans, counts = json_members(raw, JSON_SPACE.match(raw).end())[0], [], []
    for section, test in (("projects", lambda key, _: gone_path(key)),
                          ("mcpServers", lambda _, entry: any(map(gone_path, strings(entry))))):
        entries = data.get(section)
        stale = {key for key, entry in entries.items() if test(key, entry)} \
            if isinstance(entries, dict) else set()
        for key, _, _, value in top:
            if key == section and raw[value] == "{":
                members, closing = json_members(raw, value)
                spans += cut(members, {n for n, member in enumerate(members)
                                       if member[0] in stale}, value, closing)
        for key in stale:
            del entries[key]
        counts.append(len(stale))
    text = splice(raw, spans)
    return (text, *counts) if json.loads(text) == data else None


def harness_files():
    """Where tools/trust.py and `ak browser mcp-register` write trust and MCP entries."""
    home = Path.home()
    return {home / ".claude.json": claude_pruned, home / ".codex" / "config.toml": codex_pruned}


def harness_pruned(path):
    """(identity, text, trust entries, MCP servers) of that harness file less every entry
    naming a gone smoke sandbox or checkout; None when there is none, or the file is a link,
    not ours, or does not parse -- a file this cannot read is left alone."""
    prune = harness_files().get(Path(path))
    if prune is None or not safe(path) or not Path(path).is_file():
        return None
    try:
        identity = fingerprint(Path(path))
        pruned = prune(read_bytes(path).decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, IndexError, RecursionError):
        return None
    return (identity, *pruned) if pruned and (pruned[1] or pruned[2]) else None


def harness_plan():
    found = []
    for path in harness_files():
        pruned = harness_pruned(path)
        if pruned:
            found.append({"action": "prune", "kind": "harness-entries", "path": str(path),
                          "why": f"{pruned[2]} trust entries and {pruned[3]} MCP servers "
                                 "name a gone smoke sandbox or checkout"})
    return found


def prune_harness(path):
    """Rewrite that harness file without its stale entries: atomically, with its own mode,
    and never over a write the harness made since it was read."""
    path = Path(path)
    pruned = harness_pruned(path)
    if not pruned:
        return False
    identity, text = pruned[:2]
    part = path.with_name(f".{path.name}.agentkit-gc")
    part.unlink(missing_ok=True)
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 stat.S_IMODE(identity[2]))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        if fingerprint(path) != identity:
            part.unlink()
            return False
        part.replace(path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return True


def settle(path, passed):
    """The smoke suite's own sandbox at its end: gone when it passed, else kept alone.

    A passed suite has nothing left to show, and its sandbox goes with it.  A failed
    one keeps its sandbox for whoever reads the failure and takes every older sibling
    whose suite is over -- signed off, or its writer gone -- so at most one failed
    sandbox stays, the newest.  A sibling with no receipt, or one still being written,
    is left for `ak run gc` and its day.  The receipt is signed off first either way.
    """
    path = Path(path)
    finish(path)
    if path.parent != config.TMP or not path.name.startswith("smoke-") or not safe(path):
        return False
    try:
        if passed:
            shutil.rmtree(path)
            return True
        for sibling in children(config.TMP):
            if (sibling.name >= path.name or not sibling.name.startswith("smoke-")
                    or not safe(sibling) or not sibling.is_dir()):
                continue
            record = read_json(marker(sibling))
            if not record or not (record.get("finished_at")
                                  or ("pid" in record and not writer_active(record))):
                continue
            shutil.rmtree(sibling)
    except OSError:
        return False
    return True


def same_archive(path):
    """A crash after archive publication may leave two identical copies; neither is guessed."""
    dest = path.with_name(path.name + ".gz")
    try:
        with reading(path) as plain, reading(dest) as packed:
            with os.fdopen(os.dup(plain), "rb") as source, os.fdopen(os.dup(packed), "rb") as archive:
                with gzip.GzipFile(fileobj=archive) as decoded:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if chunk != decoded.read(1024 * 1024):
                            return False
                        if not chunk:
                            return True
    except (OSError, EOFError):
        return False


def compress(path, expected):
    """Lossless log archival, with an atomic destination and restartable interrupted writes."""
    if not safe(path) or fingerprint(path) != expected:
        return False
    dest, part = path.with_name(path.name + ".gz"), path.with_name(path.name + ".gz.part")
    if dest.is_symlink() or part.is_symlink():
        return False
    if present(dest):
        if same_archive(path) and fingerprint(path) == expected:
            path.unlink()              # recover publication followed by an interrupted unlink
            return True
        return False                   # never overwrite another archive
    # A prior interrupted compressor's .part is reusable only if it is an ordinary owned file.
    if present(part) and not safe(part):
        return False
    with reading(path) as fd, os.fdopen(os.dup(fd), "rb") as source:
        with part.open("wb") as output:
            with gzip.GzipFile(filename=path.name, mode="wb", fileobj=output, mtime=0) as packed:
                shutil.copyfileobj(source, packed)
            output.flush()
            os.fsync(output.fileno())
        if fingerprint(path) != expected:
            part.unlink()
            return False
        os.link(part, dest)             # publish only if nobody created an archive meanwhile
        part.unlink()
        with reading(path.parent, directory=True) as parent:
            os.fsync(parent)           # the archive name is durable before the source goes
        # If we crash here both copies remain; the next pass checks both before unlinking.
        if fingerprint(path) != expected:
            return False
        path.unlink()
    return True


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["collect"]:
        from . import run
        run.gc(print, automatic=True)
    elif sys.argv[1] == "begin":
        begin(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]))
    elif sys.argv[1] == "finish":
        finish(Path(sys.argv[2]))
    elif sys.argv[1] == "settle":
        settle(Path(sys.argv[2]), sys.argv[3] == "0")
    else:
        raise SystemExit(2)
