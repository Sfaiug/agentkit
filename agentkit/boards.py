"""The public boards ak rates models on (`quality`), each asked at most once a day and kept in
`state/boards.json`.

Artificial Analysis, its models list and the own page of each release they name, no key: per model
and effort, every benchmark's score, index, price and cost those pages hand their scripts,
which its free endpoint leaves out, and the record's identity (`IDENTITY`) for `catalog`.
Arena, its leaderboard's Hugging Face dataset, no key: each board `quality` rates on at its
category (`arena_boards`), with its 95% interval as `<column>.lower95ci` and
`<column>.upper95ci`, no row of a model run inside another harness.  `ak models --refresh` asks
again before the day is up; a board that cannot answer keeps what it last said, its error
beside it, and waits for the day like one that answered.  A board another build of ak read is
asked again, once, by a build reading a column its rows carry none of, or rows lacking the
identity this build's reader gives them: its reader changed, and a day of nothing is stale
state; so is a board held from a build before its reader gave `ADDED`.  A board ak no longer
reads leaves the cache at its next write.
Callers at once share one collection: each writer of `state/boards.json` holds
`boards.lock` from reading it to replacing it.  A board's row is one model at one effort (`Acme
5 (max)` is Acme 5 at max, `Acme 5 (Max, Default Fallback)` is Acme 5 (Default Fallback) at
max), or at none where the board names no effort, with every number the board gives as
`<board>.<field>`, a table's fields under the table's name
(`aa.intelligenceIndexCostPerTask.cost.total`), a list's tables under each one's slug
(`aa.intelligenceIndexCostPerTask.evaluations.aa-briefcase.weightedCostPerTask`), and each index
evaluation's score and cost a task as `aa.intelligenceIndexEvaluations.<slug>.score` and
`.costPerTask` (`EVALUATIONS`).
Attribution: Source: Artificial Analysis (artificialanalysis.ai); Arena (lmarena-ai),
leaderboard-dataset, CC-BY-4.0.
"""

import contextlib
import fcntl
import json
import os
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
AA_SITE = "https://artificialanalysis.ai"      # `AK_AA_URL` stands in for it
# where a page's script data holds a model's record, and the strings that data comes in
AA_RECORD = re.compile(r'\{"id":"[0-9a-f-]{36}","slug":"[^"]+","name":"')
AA_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
ARENA_URL = ("https://datasets-server.huggingface.co/{endpoint}"
             "?dataset=lmarena-ai/leaderboard-dataset&config={board}&split=latest")
# an Arena row's number and the ends of its 95% interval: a rate on the agent boards, a rating
# on the others
ARENA_FIELDS = (("score", "score_ci_lower", "score_ci_upper"),
                ("rating", "rating_lower", "rating_upper"))
# a model run inside another program than Arena's own, which measures that program too: the
# word `harness` between any separators, `_` among them, but not as the word after `arena`
HARNESS = re.compile(r"(?<![a-z0-9])(?<!(?<![a-z0-9])arena[^a-z0-9])harness(?![a-z0-9])",
                     re.IGNORECASE)
BOARDS = ("artificialanalysis.ai", "arena.ai")
PREFIX = dict(zip(BOARDS, ("aa", "arena")))   # each board's columns start with it
EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
# the words a board writes an effort as, each to ak's own
EFFORT_WORDS = {"x-high": "xhigh", "extra high": "xhigh", "non-reasoning": "none"}
# what each board's rows carry beside their numbers, every row all of it: the row's slug, its
# release's slug, name and the release that replaced it (`deprecatedTo`), its maker's name and
# whether it is deprecated
IDENTITY = {"artificialanalysis.ai": {"slug", "release", "maker", "deprecated"}}
# Each evaluation of Artificial Analysis's Intelligence Index, as its methodology page
# (/methodology/intelligence-benchmarking) said of v5.0.1 on 16 Nov 2026: the record's field of
# its score and its weight in the index.  Since 15 Nov 2026 a record gives an evaluation's score
# only as that field and its cost a task only times that weight
# (`intelligenceIndexCostPerTask.evaluations`).
EVALUATIONS = {"aa-briefcase": ("briefcaseBreakdown.overall.elo", 0.15),
               "automationbench-aa": ("automationBenchPartialScore", 0.05),
               "gdp-pdf": ("gdpPdfAllPass", 0.05),
               "frontiercode-2-0": ("frontierCode20", 0.15),
               "terminalbench-4-0": ("terminalBench40", 0.10),
               "terminal-bench-science": ("terminalBenchScience", 0.15),
               "critpt-v2-hard": ("critptAgenticHard", 0.10),
               "omniscience": ("omniscience", 0.15),
               "hle-diamond": ("hleDiamond", 0.10)}
# what each board's reader gives that an older one's rows lack, a table carried where any of
# its fields is: Artificial Analysis's evaluations (26 Oct 2026), which no reader before 16 Nov
# 2026 gave off a record of 15 Nov or later, and records' efforts, which no record on the one
# page read until 15 Nov 2026 gave, and Arena's agent board with its interval
ADDED = {"artificialanalysis.ai": {"aa.intelligenceIndexEvaluations", "aa.effort"},
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


def _evaluations(record, values):
    """Into `values`, which hold `record`'s numbers (`_numbers`), each of `EVALUATIONS`' score
    and cost a task where the record holds a number there and `values` no such column yet: the
    score its field holds, the cost its weighted cost over its weight.  A record weighing an
    evaluation the table lacks fails: the index changed, and its weights with it, so dividing by
    an old one would say a wrong price as if it were read."""
    named = {str(table.get("slug")) for table in
             (record.get("intelligenceIndexCostPerTask") or {}).get("evaluations") or ()}
    if unknown := sorted(named - EVALUATIONS.keys()):
        raise ValueError(f"{record['slug']} weighs an Intelligence Index evaluation ak has no "
                         f"weight for: {', '.join(unknown)}")
    for slug, (field, weight) in EVALUATIONS.items():
        column = f"aa.intelligenceIndexEvaluations.{slug}."
        weighted = values.get(f"aa.intelligenceIndexCostPerTask.evaluations.{slug}"
                              ".weightedCostPerTask")
        if f"aa.{field}" in values:
            values.setdefault(column + "score", values[f"aa.{field}"])
        if weighted is not None:
            values.setdefault(column + "costPerTask", weighted / weight)


def _records(url, into):
    """Each model's record in the data the page at `url` hands its scripts into `into`, by slug,
    every field it gives a value over what another page gave; their releases' slugs, in order."""
    page = fetch_bytes(url).decode("utf-8", "replace")
    data = "".join(json.loads(chunk) for chunk in AA_CHUNK.findall(page))
    releases = {}
    for match in AA_RECORD.finditer(data):
        try:
            record = json.JSONDecoder().raw_decode(data, match.start())[0]
        except ValueError:
            continue
        if "release" in record:           # a model's, not its maker's
            into.setdefault(record["slug"], {}).update(
                {field: value for field, value in record.items() if value is not None})
            releases[record["release"]["slug"]] = None
    return list(releases)


def artificial_analysis():
    """Artificial Analysis's rows, one per model and effort, every number its pages give as
    `aa.*` and its index's evaluations (`_evaluations`) beside the record's `IDENTITY`: one per
    slug of the records `/models` hands its scripts, a release each at its top effort, and those
    each release's own page hands, that release at every effort and others, for every release a
    page read names, each page once.  A page that will not load, `/models` with no model's
    record, a release's page with none of that release or a record weighing an evaluation
    `EVALUATIONS` lacks fails the whole read: the board keeps what it last said, since one
    missing some models would look whole."""
    site, records = os.environ.get("AK_AA_URL", AA_SITE), {}
    found = _records(f"{site}/models", records)
    if not found:
        raise ValueError(f"no model's record on {site}/models")
    for release in found:             # `found` grows as pages name releases not yet in it
        named = _records(f"{site}/models/{release}", records)
        if release not in named:
            raise ValueError(f"no record of {release} on {site}/models/{release}")
        found += [other for other in named if other not in found]
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
        _evaluations(record, values)
        rows.append({"model": name, "effort": effort, "values": values, "slug": record["slug"],
                     "release": {field: record["release"].get(field)
                                 for field in ("slug", "name", "deprecatedTo")},
                     "maker": (record.get("creator") or {}).get("name"),
                     "deprecated": record.get("deprecated") is True})
    return rows


def arena_boards():
    """Arena's boards `quality` rates on, each (board, category): `arena.<board>` at overall,
    `arena.<board>.<category>` at that category."""
    from . import quality        # here, not at the top: quality reads `effort_rank` off this module
    return sorted({(*parts, "overall")[:2] for role in quality.ROLES.values()
                   for column, *_ in role
                   for prefix, *parts in [column.split(".")] if prefix == "arena"})


def arena():
    """Arena's rows: each of `arena_boards()` a column with its interval, for every model its latest
    leaderboard lists at that category, but one run inside another harness (`HARNESS`).  A
    board's rows come grouped by category, overall first and the others in their alphabetical
    order, so the dataset's counts per category say where the wanted ones start, and every row
    read is checked to be one of them, all of them read."""
    rows = {}
    for board, category in arena_boards():
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


def cached():
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
        cache = cached()
        asks = {"artificialanalysis.ai": artificial_analysis, "arena.ai": arena}
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
