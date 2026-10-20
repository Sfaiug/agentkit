"""The public boards whose numbers export, each asked at most once a day and kept in
`state/boards.json`.

Artificial Analysis, with the key the owner puts under `secrets/artificialanalysis_key` (free at
artificialanalysis.ai/login): per model and effort, the intelligence, coding, agentic and
capability indexes, prices and output speed its free endpoint exports (per-benchmark scores are
Pro's).  Arena, its leaderboard's Hugging Face dataset, no key: each of `ARENA_BOARDS` at its
category.  LiveBench 2.0, its newest release's CSV files, no key: each suite's score and what a
successful coding task cost.  `ak models --refresh` asks again before the day is up; a board
that cannot answer keeps what it last said, its error beside it, and waits for the day like one
that answered.  Callers at once share one collection: each writer of `state/boards.json` holds
`boards.lock` from reading it to replacing it.  A board's row is one model at one effort (`Acme
5 (max)` is Acme 5 at max, `Acme 5 (Max, Default Fallback)` is Acme 5 (Default Fallback) at
max), or at none where the board names no effort, with every number the board gives as
`<board>.<field>`, a table's fields under the table's name
(`aa.evaluations.artificial_analysis_coding_index`).
Attribution: artificialanalysis.ai; Arena (lmarena-ai), leaderboard-dataset, CC-BY-4.0;
livebench.ai, Apache 2.0.
"""

import contextlib
import csv
import fcntl
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config

FRESH_FOR = 86400        # a board is asked at most once a day: none moves faster than that
TIMEOUT = 30             # seconds one request may take
PACE = 1                 # seconds between two asks of one host: a day's asks are a few dozen
RETRIES = (2, 4)         # seconds before asking again after a server error, each in turn
_ASKED = {}              # host -> when it was last asked, on the monotonic clock
AA_URL = "https://artificialanalysis.ai/api/v2/language/models/free"
AA_KEY = "artificialanalysis_key"
ARENA_URL = ("https://datasets-server.huggingface.co/{endpoint}"
             "?dataset=lmarena-ai/leaderboard-dataset&config={board}&split=latest")
# Arena's boards ak reads, each at one category, a column `arena.<board>` (`.<category>` past
# overall): sessions that ended in the user's confirmed success, taking a correction mid-task,
# shell commands that run, web apps people pick, and coding answers judged for facts and on
# their own, its style aside
ARENA_BOARDS = (("agent_task_outcome_explicit", "overall"), ("agent_steerability", "overall"),
                ("agent_bash_reliability", "overall"), ("webdev", "overall"),
                ("text_factuality", "coding"), ("text_style_control", "coding"))
LIVEBENCH = "https://livebench.ai/"
BOARDS = ("artificialanalysis.ai", "arena.ai", "livebench.ai")
TASK_COST = "livebench.cost_coding"       # dollars per successful coding task, at one effort
EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
# the words a board writes an effort as, each to ak's own
EFFORT_WORDS = {"x-high": "xhigh", "extra high": "xhigh", "non-reasoning": "none"}


def fetch_bytes(url, headers=None):
    """One GET and its body: the one place the network is touched, so tests hand bodies in.
    A host is asked at most once a `PACE`, and a server error is asked again after each of
    `RETRIES`: Hugging Face's dataset server answers about one ask in seven with one while it is
    up, and refuses every ask for minutes once asked faster."""
    host = urllib.parse.urlsplit(url).netloc
    for wait in (*RETRIES, None):
        time.sleep(max(0.0, _ASKED.get(host, -PACE) + PACE - time.monotonic()))
        _ASKED[host] = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}),
                                        timeout=TIMEOUT) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if wait is None or exc.code < 500:
                raise
        time.sleep(wait)


def key():
    """The owner's Artificial Analysis key, or "" when the file is not there."""
    try:
        return (config.SECRETS / AA_KEY).read_text().strip()
    except OSError:
        return ""


def split_effort(name):
    """(the model's name without its effort, the effort or None) off a board's model name:
    `Acme 5 (max)` is Acme 5 at max, `Acme 5 (max) (0813)` is Acme 5 (0813) at max, and a
    bracket of several words keeps the others (`Acme 5 (Max, Default Fallback)` is Acme 5
    (Default Fallback) at max); a bracket naming no effort stays on the name."""
    for found in re.finditer(r"\s*\(([^()]*)\)", name):
        parts = [part.strip() for part in found.group(1).split(",")]
        for part in parts:
            word = EFFORT_WORDS.get(part.lower(), part.lower())
            if word in EFFORT_ORDER or word in ("thinking", "reasoning"):   # the latter name none
                others = [other for other in parts if other != part]
                kept = f" ({', '.join(others)})" if others else ""
                rest = (name[:found.start()] + kept + name[found.end():]).strip()
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
    """Arena's rows: each of `ARENA_BOARDS` a column, for every model its latest leaderboard
    lists at that category.  A board's rows come grouped by category, overall first and the
    others in their alphabetical order, so the dataset's counts per category say where the
    wanted ones start, and every row read is checked to be one of them, all of them read."""
    rows = {}
    for board, category in ARENA_BOARDS:
        statistics = json.loads(fetch_bytes(ARENA_URL.format(endpoint="statistics", board=board)))
        counts = next((column["column_statistics"]["frequencies"]
                       for column in statistics["statistics"]
                       if column["column_name"] == "category"), {})
        if category not in counts:
            raise ValueError(f"arena.ai: {board} has no {category} rows")
        order = sorted(counts, key=lambda name: (name != "overall", name))
        offset = sum(counts[name] for name in order[:order.index(category)])
        column = f"arena.{board}" + (f".{category}" if category != "overall" else "")
        found = []
        while len(found) < counts[category]:
            page = json.loads(fetch_bytes(ARENA_URL.format(endpoint="rows", board=board)
                                          + f"&offset={offset + len(found)}"
                                          f"&length={min(100, counts[category] - len(found))}"))
            if not page.get("rows"):
                break
            found += [item.get("row") or {} for item in page["rows"]]
        if len(found) != counts[category] or any(row.get("category") != category for row in found):
            raise ValueError(f"arena.ai: {board}'s {category} rows are not where its counts "
                             "put them")
        for row in found:
            score = row.get("score", row.get("rating"))     # a rate, or a rating
            if not isinstance(score, (int, float)) or not row.get("model_name"):
                continue
            model, effort = split_effort(str(row["model_name"]))
            rows.setdefault((model, effort), {"model": model, "effort": effort, "values": {}})
            rows[(model, effort)]["values"][column] = score
    return list(rows.values())


def livebench():
    """LiveBench 2.0's rows off its newest release: each suite's score as `livebench.<suite>`,
    and the cost of a successful coding task.  The releases are named by their date in its
    page's script (`"20261014"`), each one's files under `data/<release>/`; the newest whose
    table answers is the one, and its costs are part of the answer."""
    index = fetch_bytes(LIVEBENCH).decode("utf-8", "replace")
    script = re.search(r'src="\./?([^"]+\.js)"', index)
    if not script:
        raise ValueError("livebench.ai: no script on its page")
    code = fetch_bytes(LIVEBENCH + script.group(1)).decode("utf-8", "replace")
    for release in sorted(set(re.findall(r'"(20\d{6})"', code)), reverse=True):
        try:
            table = fetch_bytes(f"{LIVEBENCH}data/{release}/table.csv").decode("utf-8", "replace")
        except OSError:
            continue
        cost = fetch_bytes(f"{LIVEBENCH}data/{release}/cost.csv").decode("utf-8", "replace")
        date = f"{release[:4]}-{release[4:6]}-{release[6:]}"
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
                row["values"][TASK_COST] = round(float(line["coding"]) / passed, 2)
        except (KeyError, TypeError, ValueError):
            continue
    return list(rows.values())


def cache_path():
    return config.STATE / "boards.json"


@contextlib.contextmanager
def _locked():
    """One writer of `boards.json` at a time: `boards.lock` held from reading it to replacing
    it, so callers at once share one collection and no write loses another's."""
    cache_path().parent.mkdir(parents=True, exist_ok=True)
    with cache_path().with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _held():
    """`boards.json` as it is, {} where it is not or unreadable."""
    try:
        return json.loads(cache_path().read_text())
    except (OSError, ValueError):
        return {}


def _write(cache):
    tmp = cache_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(cache))
    tmp.replace(cache_path())


def collect(*, refresh=False, now=None):
    """The boards' rows, each board asked once a day (`refresh` asks now), as the cache holds
    them: {board: {"asked_at", "fetched_at", "rows", "error"}}.  The day counts from `asked_at`,
    answered or not; a board that fails keeps its last rows and their `fetched_at`.  One caller
    collects at a time, under `boards.lock`, and the next reads what it wrote."""
    now = time.time() if now is None else now
    with _locked():
        cache = _held()
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
        _write(cache)
    return {board: cache[board] for board in BOARDS}


def lines(boards):
    """One line per board: how many rows it gave and when, and its error where it has one."""
    lines = []
    for board in BOARDS:
        held = boards.get(board) or {}
        when = held.get("fetched_at")
        line = (f"{board}: {len(held.get('rows') or [])} rows as of "
                f"{time.strftime('%d %b %H:%M', time.localtime(when))}" if when
                else f"{board}: no rows yet")
        lines.append(line + (f" · note: {held['error']}" if held.get("error") else ""))
    return lines
