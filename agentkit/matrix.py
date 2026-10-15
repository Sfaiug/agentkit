"""The public boards ak reads models' numbers from, each asked once a day into `state/matrix.json`.

Three boards export their numbers.  Artificial Analysis, with the key the owner puts under
`secrets/artificialanalysis_key` (free at artificialanalysis.ai/login): per model and effort,
the intelligence, coding, agentic and capability indexes, prices and output speed its free
endpoint exports (per-benchmark scores are Pro's).  Arena Agent, its leaderboard's Hugging Face
dataset, no key: net improvement over the average agent and steerability, measured on real agent
sessions.  LiveBench 2.0, its CSV
files, no key: coding, long-horizon and reasoning scores and what a successful coding task cost.
`ak models --refresh` asks again before the day is up; a board that cannot answer keeps what it
last said, its error beside it, and waits for the day like one that answered.  Callers at once
share one collection: `collect` holds `state/matrix.lock` from reading the cache to replacing it.
A board's row is one model at one effort (`Acme 5 (max)` is Acme 5 at max), or at none where the
board names no effort, with every number the board gives as `<board>.<field>`, a table's fields
under the table's name (`aa.evaluations.artificial_analysis_coding_index`).  Attribution:
artificialanalysis.ai, arena.ai, livebench.ai.
"""

import csv
import fcntl
import io
import json
import re
import sys
import time
import urllib.request

from . import command_help, config

FRESH_FOR = 86400        # a board is asked at most once a day: none moves faster than that
TIMEOUT = 30             # seconds one request may take
AA_URL = "https://artificialanalysis.ai/api/v2/language/models/free"
AA_KEY = "artificialanalysis_key"
ARENA_URL = ("https://datasets-server.huggingface.co/rows?dataset=lmarena-ai/leaderboard-dataset"
             "&config={config}&split=latest&offset={offset}&length=100")
ARENA_CONFIGS = ("agent", "agent_steerability")
LIVEBENCH = "https://livebench.ai/"
BOARDS = ("artificialanalysis.ai", "arena.ai", "livebench.ai")
COST = "livebench.cost_coding"           # dollars per successful coding task
EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
# the words a board writes an effort as, each to ak's own
EFFORT_WORDS = {"x-high": "xhigh", "extra high": "xhigh", "non-reasoning": "none"}


def fetch_bytes(url, headers=None):
    """One GET and its body: the one place the network is touched, so tests hand bodies in."""
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def key():
    """The owner's Artificial Analysis key, or "" when the file is not there."""
    try:
        return (config.SECRETS / AA_KEY).read_text().strip()
    except OSError:
        return ""


def split_effort(name):
    """(the model's name without its effort, the effort or None) off a board's model name:
    `Acme 5 (max)` is Acme 5 at max, `Acme 5 (max) (0813)` is Acme 5 (0813) at max; a bracket
    naming no effort stays on the name."""
    for found in re.finditer(r"\s*\(([^()]*)\)", name):
        word = found.group(1).strip().lower()
        word = EFFORT_WORDS.get(word, word)
        if word in EFFORT_ORDER or word in ("thinking", "reasoning"):   # the latter name none
            rest = (name[:found.start()] + name[found.end():]).strip()
            return rest, word if word in EFFORT_ORDER else None
    return name, None


def _numbers(entry, prefix, into):
    """Every number of `entry` as `prefix.field`, a table's fields under the table's name."""
    for field, value in entry.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            into[f"{prefix}.{field}"] = value
        elif isinstance(value, dict):
            _numbers(value, f"{prefix}.{field}", into)


def artificial_analysis(secret):
    """Artificial Analysis's rows, one per model and effort, every number it gives as `aa.*`,
    off every page of its free endpoint."""
    rows, page = [], 1
    while True:
        payload = json.loads(fetch_bytes(f"{AA_URL}?page={page}", {"x-api-key": secret}))
        for entry in payload.get("data") or []:
            name, effort = split_effort(str(entry.get("name") or entry.get("slug") or ""))
            values = {}
            _numbers(entry, "aa", values)
            rows.append({"model": name, "effort": effort, "values": values})
        if not payload.get("data") or not (payload.get("pagination") or {}).get("has_more"):
            return rows
        page += 1


def arena():
    """Arena Agent's rows: the net improvement and the steerability signal, each a column, for
    every model its latest leaderboard lists."""
    rows = {}
    for name in ARENA_CONFIGS:
        offset = 0
        while True:
            page = json.loads(fetch_bytes(ARENA_URL.format(config=name, offset=offset)))
            for item in page.get("rows") or []:
                row = item.get("row") or {}
                score = row.get("score")
                if not isinstance(score, (int, float)) or not row.get("model_name"):
                    continue
                model, effort = split_effort(str(row["model_name"]))
                rows.setdefault((model, effort), {"model": model, "effort": effort, "values": {}})
                rows[(model, effort)]["values"][f"arena.{name}"] = score
            offset += len(page.get("rows") or [])
            if not page.get("rows") or offset >= (page.get("num_rows_total") or 0):
                break
    return list(rows.values())


def livebench():
    """LiveBench 2.0's rows off its newest release: each suite's score as `livebench.<suite>`,
    and the cost of a successful coding task.  The releases' dates are in its page's script;
    the newest whose table answers is the one, and its costs are part of the answer."""
    index = fetch_bytes(LIVEBENCH).decode("utf-8", "replace")
    script = re.search(r'src="\./?([^"]+\.js)"', index)
    if not script:
        raise ValueError("livebench.ai: no script on its page")
    code = fetch_bytes(LIVEBENCH + script.group(1)).decode("utf-8", "replace")
    for date in sorted(set(re.findall(r"\d{4}-\d{2}-\d{2}", code)), reverse=True):
        stamp = date.replace("-", "_")
        try:
            table = fetch_bytes(f"{LIVEBENCH}table_{stamp}.csv").decode("utf-8", "replace")
        except OSError:
            continue
        cost = fetch_bytes(f"{LIVEBENCH}cost_{stamp}.csv").decode("utf-8", "replace")
        break
    else:
        raise ValueError("livebench.ai: no release's table answers")
    rows = {}
    for line in csv.DictReader(io.StringIO(table)):
        model = line.pop("model", "")
        values = {f"livebench.{suite}": float(value) for suite, value in line.items()
                  if value not in ("", None)}
        rows[model] = {"model": model, "effort": None, "values": values, "release": date}
    for line in csv.DictReader(io.StringIO(cost)):
        row = rows.get(line.get("model", ""))
        try:          # the suite's spend over the tasks it passed
            passed = float(line["nq_coding"]) * row["values"]["livebench.coding"] / 100
            if passed > 0:
                row["values"][COST] = round(float(line["coding"]) / passed, 2)
        except (KeyError, TypeError, ValueError):
            continue
    return list(rows.values())


def cache_path():
    return config.STATE / "matrix.json"


def collect(*, refresh=False, now=None):
    """The boards' rows, each board asked once a day (`refresh` asks now), as the cache holds
    them: {board: {"asked_at", "fetched_at", "rows", "error"}}.  The day counts from `asked_at`,
    answered or not; a board that fails keeps its last rows and their `fetched_at`.  One caller
    collects at a time, under `matrix.lock`, and the next reads what it wrote."""
    now = time.time() if now is None else now
    cache_path().parent.mkdir(parents=True, exist_ok=True)
    with cache_path().with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            cache = json.loads(cache_path().read_text())
        except (OSError, ValueError):
            cache = {}
        secret = key()
        asks = {"artificialanalysis.ai": (lambda: artificial_analysis(secret)) if secret else None,
                "arena.ai": arena, "livebench.ai": livebench}
        for board, ask in asks.items():
            held = cache.get(board) or {}
            if ask is None:
                cache[board] = {**held, "error": f"no key: put one in {config.SECRETS / AA_KEY}"}
                continue
            if not refresh and held.get("asked_at") and now - held["asked_at"] < FRESH_FOR:
                continue
            try:
                cache[board] = {"asked_at": now, "fetched_at": now, "rows": ask(), "error": None}
            except Exception as exc:          # noqa: BLE001 -- a board down is a note, not a crash
                cache[board] = {**held, "asked_at": now,
                                "error": " ".join(str(exc).split()) or type(exc).__name__}
        tmp = cache_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(cache))
        tmp.replace(cache_path())
    return cache


def render(boards):
    """One line per board: how many rows it gave and when, and its error where it has one."""
    lines = []
    for board in BOARDS:
        held = boards.get(board) or {}
        when = held.get("fetched_at")
        line = (f"{board}: {len(held.get('rows') or [])} rows as of "
                f"{time.strftime('%d %b %H:%M', time.localtime(when))}" if when
                else f"{board}: no rows yet")
        lines.append(line + (f" · note: {held['error']}" if held.get("error") else ""))
    return "\n".join(lines)


def main(argv):
    if command_help.show("models", argv):
        return 0
    flags = set(argv)
    if flags - {"--json", "--refresh"}:
        raise config.Error(f"usage: ak models [--json] [--refresh]  (got {argv!r})")
    boards = collect(refresh="--refresh" in flags)
    if "--json" in flags:
        json.dump(boards, sys.stdout, indent=2)
        print()
    else:
        print(render(boards))
    return 0
