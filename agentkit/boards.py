"""The public boards whose numbers export, each asked at most once a day and kept in
`state/boards.json`.

Artificial Analysis, its site's pages (`AA_PAGES`), no key: per model and effort, every
benchmark's score, index, price and cost its pages hand their scripts, which its free endpoint
leaves out, and the record's identity (`IDENTITY`) for `catalog`.  Arena, its leaderboard's Hugging Face dataset, no key: each of `ARENA_BOARDS` at its
category, with its 95% interval as `<column>.lower95ci` and `<column>.upper95ci`, no row of a
model run inside another harness.  LiveBench 2.0, its newest release's CSV files, no key: each
suite's score and what a successful coding task cost.  `ak models --refresh` asks again before the day is up; a board
that cannot answer keeps what it last said, its error beside it, and waits for the day like one
that answered.  A board another build of ak read is asked again, once, by a build reading a
column its rows carry none of, or rows lacking the identity this build's reader gives them: its
reader changed, and a day of nothing is stale state; so is a board held from a build before its
reader gave `ADDED`.
Callers at once share one collection: each writer of `state/boards.json` holds
`boards.lock` from reading it to replacing it.  A board's row is one model at one effort (`Acme
5 (max)` is Acme 5 at max, `Acme 5 (Max, Default Fallback)` is Acme 5 (Default Fallback) at
max), or at none where the board names no effort, with every number the board gives as
`<board>.<field>`, a table's fields under the table's name
(`aa.intelligenceIndexCostPerTask.cost.total`), a list's tables under each one's slug
(`aa.intelligenceIndexEvaluations.aa-briefcase.costPerTask`).
Attribution: Source: Artificial Analysis (artificialanalysis.ai); Arena (lmarena-ai), leaderboard-dataset, CC-BY-4.0;
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
# a retired model's page carries every model's record whole; DeepsecBench's carries its score,
# which that one leaves out
AA_PAGES = ("https://artificialanalysis.ai/models/gpt-35-turbo",
            "https://artificialanalysis.ai/evaluations/deepsecbench-aa")
# where a page's script data holds a model's record, and the strings that data comes in
AA_RECORD = re.compile(r'\{"id":"[0-9a-f-]{36}","slug":"[^"]+","name":"')
AA_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
ARENA_URL = ("https://datasets-server.huggingface.co/{endpoint}"
             "?dataset=lmarena-ai/leaderboard-dataset&config={board}&split=latest")
# Arena's boards ak reads, each at one category, a column `arena.<board>` (`.<category>` past
# overall): agent sessions, those that ended in the user's confirmed success, taking a correction
# mid-task, shell commands that run, web apps people pick, and coding answers judged for facts
# and on their own, its style aside
ARENA_BOARDS = (("agent", "overall"), ("agent_task_outcome_explicit", "overall"),
                ("agent_steerability", "overall"), ("agent_bash_reliability", "overall"),
                ("webdev", "overall"), ("text_factuality", "coding"),
                ("text_style_control", "coding"))
# an Arena row's number and the ends of its 95% interval: a rate on the agent boards, a rating
# on the others
ARENA_FIELDS = (("score", "score_ci_lower", "score_ci_upper"),
                ("rating", "rating_lower", "rating_upper"))
# a model run inside another program than Arena's own, which measures that program too: the
# word `harness` between any separators, `_` among them, but not as the word after `arena`
HARNESS = re.compile(r"(?<![a-z0-9])(?<!(?<![a-z0-9])arena[^a-z0-9])harness(?![a-z0-9])",
                     re.IGNORECASE)
LIVEBENCH = "https://livebench.ai/"
BOARDS = ("artificialanalysis.ai", "arena.ai", "livebench.ai")
PREFIX = dict(zip(BOARDS, ("aa", "arena", "livebench")))   # each board's columns start with it
TASK_COST = "livebench.cost_coding"       # dollars per successful coding task, at one effort
EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
# the words a board writes an effort as, each to ak's own
EFFORT_WORDS = {"x-high": "xhigh", "extra high": "xhigh", "non-reasoning": "none"}
# what each board's rows carry beside their numbers, every row all of it: the row's slug, its
# release's slug, name and the release that replaced it (`deprecatedTo`), its maker's name and
# whether it is deprecated
IDENTITY = {"artificialanalysis.ai": {"slug", "release", "maker", "deprecated"}}
# what each board's reader gives since 26 Oct 2026, a table carried where any of its fields is:
# Artificial Analysis's evaluations, and Arena's agent board with its interval
ADDED = {"artificialanalysis.ai": {"aa.intelligenceIndexEvaluations"},
         "arena.ai": {"arena.agent.lower95ci"}}


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


def effort_rank(effort):
    """Where an effort stands among the words ak knows, the highest last; a word ak does not
    know, or no effort, stands below them all."""
    return EFFORT_ORDER.index(effort) if effort in EFFORT_ORDER else -1


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
    """Every number of `entry` as `prefix.field`, a table's fields under the table's name and a
    list's tables under each one's slug."""
    for field, value in entry.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            into[f"{prefix}.{field}"] = value
        elif isinstance(value, dict):
            _numbers(value, f"{prefix}.{field}", into)
        elif isinstance(value, list):
            for table in value:
                if isinstance(table, dict) and isinstance(table.get("slug"), str):
                    _numbers(table, f"{prefix}.{field}.{table['slug']}", into)


def artificial_analysis():
    """Artificial Analysis's rows, one per model and effort, every number its pages give as
    `aa.*` beside the record's `IDENTITY`: each model's record in the data a page hands its scripts, those of all `AA_PAGES`
    merged by the record's slug.  A page with no model's record is a ValueError: the site
    changed, and the board keeps what it last said."""
    records = {}
    for url in AA_PAGES:
        page = fetch_bytes(url).decode("utf-8", "replace")
        data = "".join(json.loads(chunk) for chunk in AA_CHUNK.findall(page))
        found = 0
        for match in AA_RECORD.finditer(data):
            try:
                record = json.JSONDecoder().raw_decode(data, match.start())[0]
            except ValueError:
                continue
            if "release" in record:           # a model's, not its maker's
                records.setdefault(record["slug"], {}).update(
                    {field: value for field, value in record.items() if value is not None})
                found += 1
        if not found:
            raise ValueError(f"no model's record on {url}")
    rows = []
    for record in records.values():
        name, effort = split_effort(str(record["name"]))
        briefcase = record.get("briefcaseBreakdown")
        if isinstance(briefcase, dict) and "overall" not in briefcase:
            # the newest records give Briefcase's overall rating flat, the others under `overall`
            briefcase["overall"] = {field: briefcase.pop(field) for field in
                                    ("elo", "lower95ci", "upper95ci") if field in briefcase}
        values = {}
        _numbers(record, "aa", values)
        rows.append({"model": name, "effort": effort, "values": values, "slug": record["slug"],
                     "release": {field: record["release"].get(field)
                                 for field in ("slug", "name", "deprecatedTo")},
                     "maker": (record.get("creator") or {}).get("name"),
                     "deprecated": record.get("deprecated") is True})
    return rows


def arena():
    """Arena's rows: each of `ARENA_BOARDS` a column with its interval, for every model its latest
    leaderboard lists at that category, but one run inside another harness (`HARNESS`).  A
    board's rows come grouped by category, overall first and the others in their alphabetical
    order, so the dataset's counts per category say where the wanted ones start, and every row
    read is checked to be one of them, all of them read."""
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
            fields = next((fields for fields in ARENA_FIELDS
                           if isinstance(row.get(fields[0]), (int, float))), None)
            if (not fields or not row.get("model_name")
                    or any(HARNESS.search(str(row.get(name) or ""))
                           for name in ("model_name", "model_key"))):
                continue
            model, effort = split_effort(str(row["model_name"]))
            values = rows.setdefault((model, effort), {"model": model, "effort": effort,
                                                       "values": {}})["values"]
            for name, field in zip((column, f"{column}.lower95ci", f"{column}.upper95ci"), fields):
                if isinstance(row.get(field), (int, float)):
                    values[name] = row[field]
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
    """`boards.json` as it is, or while there is none yet the boards as `state/matrix.json` held
    them beside the matrix until 20 Oct 2026, so an install upgraded keeps what they last said
    and its day's pace; {} where the file is unreadable."""
    path = cache_path() if cache_path().exists() else config.STATE / "matrix.json"
    try:
        held = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return {board: held[board] for board in BOARDS if board in held}


def _write(cache):
    tmp = cache_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(cache))
    tmp.replace(cache_path())


def collect(*, refresh=False, now=None, needs=None, build=None):
    """The boards' rows, each board asked once a day (`refresh` asks now), as the cache holds
    them: {board: {"asked_at", "fetched_at", "rows", "error", "build"}}.  The day counts from
    `asked_at`, answered or not; a board that fails keeps its last rows and their `fetched_at`.
    `needs`, {board: columns} the caller reads, and `build`, ak's build asking: a board held
    from another build whose rows carry none of a needed column, or lack its `IDENTITY` or
    `ADDED`, is asked again before the day is up, once, since its reader changed.  One caller
    collects at a time, under `boards.lock`, and the next reads what it wrote."""
    now = time.time() if now is None else now
    with _locked():
        cache = _held()
        asks = {"artificialanalysis.ai": artificial_analysis, "arena.ai": arena,
                "livebench.ai": livebench}
        for board, ask in asks.items():
            held = cache.get(board) or {}
            fresh = held.get("asked_at") and now - held["asked_at"] < FRESH_FOR
            if fresh and build is not None and held.get("build") != build:
                carried = {".".join(parts[:n]) for row in held.get("rows") or []
                           for column in (*row, *row["values"])
                           for parts in [column.split(".")] for n in range(1, len(parts) + 1)}
                fresh = not (((needs or {}).get(board, set()) | IDENTITY.get(board, set())
                              | ADDED.get(board, set())) - carried)
            if not refresh and fresh:
                continue
            try:
                cache[board] = {"asked_at": now, "fetched_at": now, "rows": ask(), "error": None,
                                "build": build}
            except Exception as exc:          # noqa: BLE001 -- a board down is a note, not a crash
                cache[board] = {**held, "asked_at": now, "build": build,
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
