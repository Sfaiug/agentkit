"""Every model and effort the installed harnesses offer, with the public boards' numbers for each.

Three boards export their numbers.  Artificial Analysis, with the key the owner puts under
`secrets/artificialanalysis_key` (free at artificialanalysis.ai/login): per model and effort,
the intelligence, coding, agentic and capability indexes, prices and output speed its free
endpoint exports (per-benchmark scores are Pro's).  Arena Agent, its leaderboard's Hugging Face
dataset, no key: net improvement over the average agent and steerability, measured on real agent
sessions.  LiveBench 2.0, its CSV files, no key: coding, long-horizon and reasoning scores and
what a successful coding task cost.
`ak models --refresh` asks again before the day is up; a board that cannot answer keeps what it
last said, its error beside it, and waits for the day like one that answered.  Callers at once
share one collection: each writer of `state/matrix.json` holds `matrix.lock` from reading it to
replacing it.  A board's row is one model at one effort (`Acme 5 (max)` is Acme 5 at max, `Acme 5
(Max, Default Fallback)` is Acme 5 (Default Fallback) at max), or at none where the board names no
effort, with every number the board gives as `<board>.<field>`, a table's fields under the table's
name (`aa.evaluations.artificial_analysis_coding_index`).

A row of the matrix is one model at one effort: an effort a board lists for it or the config
runs it at in any role, so a board naming no effort counts for every effort of its model, and a
model no board lists at any effort is one row at none.  A board's model is matched by name,
letters and digits alone (`acme-5` is `Acme 5 (max)` at max), else by the board's name the id
extends with a version (`acme-pro` for `acme-pro-1.0`), else by the one board name that is the
id with a qualifier in brackets (`Acme 5 (Default Fallback)`); `benchmark` on a config entry
names the board's model on a board where none fits.  A board's row at another effort never
stands in.

Every row is scored per role, on quality and cost alone: speed is ak's own to fix, and the
subscriptions follow the choice.  A column is the row's share of the best value among the rows
(100 for the best; zero or below is 0 and still counts: Arena's net improvement can be
negative).  A model's score for a role is the mean share over the role's measures on its row
holding the most of them, and it needs at least half of them; a row's quality is that times what
its effort keeps of it, read off the role's measures that see efforts, else the intelligence
index, which every model has per effort; it is said with the measures the model's score rests on
(`97 of 3`), and `ROLES` names each role's measures and why.  A row within `within` of the best
counts as as good as it, and the cheapest of those is recommended, the others beside it: by what
Artificial Analysis's index run cost on the row, which is its price times how much it talks at
that effort, a row it has not run by LiveBench's cost of a coding task after every priced one,
unpriced last, then the higher quality, the row the config runs in the role, the higher effort,
the first by harness and model name.  ak's own run numbers stand beside, per configured model,
the effort its runs recorded and role, with their count, and never rank (AGENTS.md, Owner rules).
Attribution: artificialanalysis.ai, arena.ai, livebench.ai.
"""

import contextlib
import csv
import fcntl
import io
import json
import re
import sys
import time
import urllib.request

from . import command_help, config, record, terminal

FRESH_FOR = 86400        # a board is asked at most once a day: none moves faster than that
TIMEOUT = 30             # seconds one request may take
AA_URL = "https://artificialanalysis.ai/api/v2/language/models/free"
AA_KEY = "artificialanalysis_key"
ARENA_URL = ("https://datasets-server.huggingface.co/rows?dataset=lmarena-ai/leaderboard-dataset"
             "&config={config}&split=latest&offset={offset}&length=100")
ARENA_CONFIGS = ("agent", "agent_steerability")
LIVEBENCH = "https://livebench.ai/"
BOARDS = ("artificialanalysis.ai", "arena.ai", "livebench.ai")
INTEL = "aa.evaluations.artificial_analysis_intelligence_index"   # every model has it per effort
COST = "aa.artificial_analysis_intelligence_index_cost.total_cost"   # dollars its index run cost
TASK_COST = "livebench.cost_coding"       # dollars per successful coding task, at one effort
# A row this many points under the best counts as as good: the three boards disagree with each
# other about differences between the top models by more (a median of 6 to 10 points, 17 Oct
# 2026), so no row the boards agree is worse gets in.  `within` in config.toml overrides it;
# it goes to 0 the day the boards publish their intervals.
WITHIN = 5
EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
# the words a board writes an effort as, each to ak's own
EFFORT_WORDS = {"x-high": "xhigh", "extra high": "xhigh", "non-reasoning": "none"}
# What each role is scored on: a column (board.field) and, in plain words, why it stands for
# that role.  Pinned by tests/test_matrix_measures.py: it changes only with the owner's yes.
# Artificial Analysis's free endpoint carries its three indexes, never one benchmark's score.
ROLES = {
    "orchestrate": (("arena.agent", "real agent sessions: net improvement over the average"),
                    ("arena.agent_steerability", "taking a correction mid-task"),
                    ("aa.evaluations.artificial_analysis_agentic_index",
                     "agentic work end to end, across Artificial Analysis's agent suites"),
                    ("livebench.long_horizon", "work that runs for hours")),
    "execute": (("aa.evaluations.artificial_analysis_coding_index", "coding across evaluations"),
                ("aa.evaluations.artificial_analysis_agentic_index", "agentic work end to end"),
                ("livebench.coding", "bug fixes and apps that must run"),
                ("livebench.long_horizon", "work that runs for hours")),
    "review": (("aa.evaluations.artificial_analysis_intelligence_index",
                "general strength: no public review board exports its numbers"),
               ("aa.evaluations.artificial_analysis_coding_index", "reading code"),
               ("livebench.reasoning", "reasoning")),
}
# the config's word for each role ak scores: `config.ROLE_EFFORTS` keys its efforts by these
CONFIG_ROLES = {"orchestrate": "orchestrator", "execute": "executor", "review": "reviewer"}
HEADERS = ("model", "harness", "id", "orch", "exec", "review", "cost", "$/task")


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
                row["values"][TASK_COST] = round(float(line["coding"]) / passed, 2)
        except (KeyError, TypeError, ValueError):
            continue
    return list(rows.values())


def cache_path():
    return config.STATE / "matrix.json"


@contextlib.contextmanager
def _locked():
    """One writer of `matrix.json` at a time: `matrix.lock` held from reading it to replacing
    it, so callers at once share one collection and no write loses another's."""
    cache_path().parent.mkdir(parents=True, exist_ok=True)
    with cache_path().with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _held():
    """`matrix.json` as it is, {} where it is not or unreadable."""
    try:
        return json.loads(cache_path().read_text())
    except (OSError, ValueError):
        return {}


def _write(cache):
    tmp = cache_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(cache))
    tmp.replace(cache_path())


def present():
    """Every harness present to run a turn, the ones whose models the matrix rows."""
    return sorted({name for name, _ in config.manifests() if config.harness_present(name)})


def config_key(cfg):
    """What of the config the matrix is computed from: a change here recomputes it."""
    return sorted([name, cfg["models"][name]["harness"], cfg["models"][name]["model"],
                   *(config.role_effort(cfg["models"][name], role) for role in config.ROLE_EFFORTS),
                   cfg["models"][name].get("benchmark") or ""]
                  for name in config.offered(cfg))


def collect(*, refresh=False, now=None):
    """The boards' rows, each board asked once a day (`refresh` asks now), as the cache holds
    them: {board: {"asked_at", "fetched_at", "rows", "error"}}.  The day counts from `asked_at`,
    answered or not; a board that fails keeps its last rows and their `fetched_at`.  One caller
    collects at a time, under `matrix.lock`, and the next reads what it wrote."""
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
    return {board: cache[board] for board in BOARDS}      # the matrix computed from them aside


def normal(text):
    """A model's name as every board and config spells it alike: its letters and digits."""
    return re.sub(r"[^a-z0-9]", "", text.rsplit("/", 1)[-1].lower())


def found(index, model, benchmark=None):
    """A board's rows for one model: under its exact name, else under a board's name naming no
    version of its own that `model` extends with one (`Acme Pro` for `acme-pro-1.0`, never
    `Acme 5` for `acme-5-5`), else under the one board name that is `model` with a qualifier in
    brackets (`Acme 5 (Default Fallback)`; two such names stand for nothing), else the same
    matches without a trailing `-free` pricing tier, else under `benchmark`, the config entry's
    name for it on a board where none fits; none where the board has nothing for it."""
    wanted = normal(model)
    if wanted in index:
        return index[wanted]
    stems = [stem for stem in index if stem and not stem[-1].isdigit()
             and wanted.startswith(stem) and wanted[len(stem):].isdigit()]
    if stems:
        return index[max(stems, key=len)]
    qualified = [stem for stem, hits in index.items()
                 if normal(re.sub(r"\([^()]*\)", "", hits[0]["model"])) == wanted]
    if len(qualified) == 1:
        return index[qualified[0]]
    if model.endswith("-free"):
        # Free is a pricing tier, so use the underlying model's board rows.
        return found(index, model.removesuffix("-free"), benchmark)
    return index.get(normal(benchmark), []) if benchmark else []


def matching(index, model, effort, benchmark=None):
    """The board's row for that model at that effort, else its row naming no effort, else None:
    a row at another effort never stands in."""
    hits = found(index, model, benchmark)
    return next((row for row in hits if row["effort"] == effort),
                next((row for row in hits if row["effort"] is None), None))


def rows(cfg, boards, harnesses):
    """One row per model and effort `harnesses` (`present`) offer, with the config name that
    runs it and the roles it runs it in, every board's numbers it matches and which board model
    and effort each came from."""
    indexes = {}
    for board, held in boards.items():
        for row in held.get("rows") or []:
            indexes.setdefault(board, {}).setdefault(normal(row["model"]), []).append(row)
    names = {}        # (harness, model, effort) -> the config name some role runs it at
    roles = {}        # (harness, model, effort) -> the roles the config runs it in
    for name in config.offered(cfg):
        entry = cfg["models"][name]
        for role, config_role in CONFIG_ROLES.items():
            key = (entry["harness"], entry["model"], config.role_effort(entry, config_role))
            names[key] = name
            roles.setdefault(key, set()).add(role)
    table = []
    for harness in harnesses:
        listed = {item["id"]: item["efforts"] for item in config.catalog(harness)}
        for (h, model, effort), name in names.items():
            if h == harness:
                listed.setdefault(model, [])
        for model, offered in listed.items():
            own = [name for (h, m, _), name in names.items() if (h, m) == (harness, model)]
            benchmark = next((cfg["models"][name]["benchmark"] for name in own
                              if cfg["models"][name].get("benchmark")), None)
            # the efforts worth a row: the boards' for this model, among those the harness
            # offers, and the config's
            efforts = {row["effort"] for index in indexes.values()
                       for row in found(index, model, benchmark)
                       if row["effort"] and (not offered or row["effort"] in offered)}
            efforts |= {effort for (h, m, effort) in names if (h, m) == (harness, model)}
            for effort in sorted(efforts, key=lambda word: -effort_rank(word)) or [None]:
                row = {"harness": harness, "model": model, "effort": effort,
                       "name": names.get((harness, model, effort)),
                       "roles": [role for role in ROLES
                                 if role in roles.get((harness, model, effort), ())],
                       "values": {}, "matched": {}}
                for board, index in indexes.items():
                    hit = matching(index, model, effort, benchmark)
                    if hit is not None:
                        row["values"].update(hit["values"])
                        row["matched"][board] = {"model": hit["model"], "effort": hit["effort"]}
                table.append(row)
    return table


def effort_rank(effort):
    """Where an effort stands among the words ak knows, the highest last; a word ak does not
    know, or no effort, stands below them all."""
    return EFFORT_ORDER.index(effort) if effort in EFFORT_ORDER else -1


def scored(table):
    """Each row's `scores`: per role, {"score", "measures"}, or None where its model has under
    half the role's measures or nothing tells its effort apart while another of the model's is.
    A column is a share of the best value among the rows: 100 for the best, 0 at zero or below
    (still a measure).  The model's score is the mean share over the role's measures on its row
    holding the most of them (then the highest); the row's is that times what its effort keeps
    (`kept`), said with the measures the model's rests on."""
    best = {}
    for row in table:
        for column, value in row["values"].items():
            best[column] = max(best.get(column, 0), value)
    shares = [{column: 100 * max(value, 0) / best[column] if best[column] > 0 else 0.0
               for column, value in row["values"].items()} for row in table]
    models = {}
    for number, row in enumerate(table):
        row["scores"] = {}
        models.setdefault((row["harness"], row["model"]), []).append(number)
    for role, columns in ROLES.items():
        columns = [column for column, _ in columns]
        for siblings in models.values():
            own = [[shares[number][c] for c in columns if c in shares[number]]
                   for number in siblings]
            top = max(((len(have), sum(have) / len(have)) for have in own
                       if 2 * len(have) >= len(columns)), default=None)
            keeps = kept([shares[number] for number in siblings], columns)
            for number, keep in zip(siblings, keeps):
                table[number]["scores"][role] = (
                    {"score": top[1] * keep, "measures": top[0]}
                    if top is not None and keep is not None else None)
    return table


def kept(shares, columns):
    """What each of one model's rows (their shares, one dict per effort) keeps of the model's
    best effort, 0 to 1: its mean share over the `columns` whose values differ between its
    efforts, else over the intelligence index, against the highest among them; 1 where nothing
    tells them apart, None for a row that lacks what tells the others apart."""
    basis = [c for c in columns if len({row[c] for row in shares if c in row}) > 1] or [INTEL]
    each = [([row[c] for c in basis if c in row] or None) for row in shares]
    means = [sum(have) / len(have) if have else None for have in each]
    top = max((mean for mean in means if mean is not None), default=None)
    return [1.0 if top is None else None if mean is None else mean / top if top > 0 else 1.0
            for mean in means]


def best(row):
    """A row's best quality in any role, -1 where no role scores it: what orders rows."""
    return max((found["score"] for found in (row.get("scores") or {}).values() if found),
               default=-1)


def within(cfg):
    """How many points under the best still counts as as good: `within` in the config, else
    `WITHIN`."""
    return cfg.get("within", WITHIN)


def cost_key(row):
    """What ordering by cost sorts a row on: Artificial Analysis's index run cost, a row it has
    not run after every priced one, by LiveBench's cost of a coding task, unpriced last."""
    values = row["values"]
    return ((0, values[COST]) if COST in values else (1, values[TASK_COST])
            if TASK_COST in values else (2, 0.0))


def tops(table):
    """Per role, the row of the highest quality, the one `recommended` measures the band from;
    a role no row has a score for is left out."""
    return {role: max(rows, key=lambda row: row["scores"][role]["score"])
            for role in ROLES if (rows := [row for row in table if row["scores"][role]])}


def recommended(table, within=WITHIN):
    """Per role, the rows as good as the best (`tops`), cheapest first (`cost_key`), one per
    model at its cheapest such effort, the first the recommendation; {} for a role no row has a
    score for.  Rows alike on cost go by the higher quality, then the row the config runs in the
    role, then the higher effort, then the first by harness and model name, so the pick is the
    same however the table is ordered."""
    picks = {}
    for role, top in tops(table).items():
        found = [row for row in table if row["scores"][role]]
        best = top["scores"][role]["score"]
        seen, picks[role] = set(), []
        for row in sorted((row for row in found if row["scores"][role]["score"] >= best - within),
                          key=lambda row: (*cost_key(row), -row["scores"][role]["score"],
                                           role not in row["roles"], -effort_rank(row["effort"]),
                                           row["harness"], row["model"])):
            if (row["harness"], row["model"]) not in seen:
                seen.add((row["harness"], row["model"]))
                picks[role].append(row)
    return picks


LIVE_HEADERS = ("model", "orch", "exec", "review")
# the run's column holding the effort the role ran it at (None where it was not recorded); a
# review's effort is its review row's
EFFORT_OF = {"orchestrate": "own_orchestrator_effort", "execute": "executor_effort"}


def live(cfg, now=None):
    """ak's own numbers per configured model, the effort it ran at and role, which never rank.
    Off the history's runs that ended with a verdict of the work (`record.JUDGED`): of the runs
    it executed, how many and the share merged in round 1 (`history.merged`); of the pull
    requests its seat wrote (the row's `own_orchestrator`), how many and the share merged in
    round 1.  Of the runs it finished a review of, by its harness and model id, whatever became
    of them since, how many and the share it let through in round 1 (`history.reviewed_runs`).
    {label: {role: {"runs", "round_1"} or None}}: a label per effort the model's runs recorded
    (`acme @ max`, the strongest first), the bare name for runs that recorded none and for a
    model that ran nothing."""
    from . import history     # here, not at the top: the boards and the table need no database
    now = time.time() if now is None else now
    rows = [row for row in history.ended_runs(0, now) if row.get("final_state") in record.JUDGED]
    first = {row["run_id"] for row in rows
             if (row.get("rounds_used") or 0) <= 1 and history.merged(row)}
    found = {}
    for name in config.offered(cfg):
        counts = {}     # {effort: {role: (runs, of them in round 1)}}
        for role, column in (("orchestrate", "own_orchestrator"), ("execute", "executor")):
            for row in rows:
                if row.get(column) == name:
                    mine = counts.setdefault(row.get(EFFORT_OF[role]) or None, {})
                    runs, in_first = mine.get(role, (0, 0))
                    mine[role] = (runs + 1, in_first + (row["run_id"] in first))
        entry = cfg["models"][name]
        for effort, reviewed in history.reviewed_runs(entry["harness"], entry["model"]).items():
            counts.setdefault(effort or None, {})["review"] = reviewed
        for effort in sorted(counts, key=lambda word: (word is None, -effort_rank(word))) or [None]:
            found[f"{name} @ {effort}" if effort else name] = {
                role: share(*counts.get(effort, {}).get(role, (0, 0))) for role in ROLES}
    return found


def share(runs, in_round_1):
    """`{"runs", "round_1"}`: how many runs, and the share of them in round 1; None with none."""
    return {"runs": runs, "round_1": round(100 * in_round_1 / runs)} if runs else None


def live_cell(found):
    """`55% of 320`: the share merged in round 1 and the runs it rests on; `-` where it ran none."""
    return "-" if found is None else f"{found['round_1']}% of {found['runs']}"


def live_lines(own):
    """The second table: each configured model's own numbers per role, `55% of 320`."""
    lines_of = [LIVE_HEADERS] + [
        (name, *(live_cell(found[role]) for role in ROLES)) for name, found in own.items()]
    widths = [max(terminal.cells(line[i]) for line in lines_of) for i in range(len(LIVE_HEADERS))]
    lines = [" ".join(terminal.pad(text, w) for text, w in zip(line, widths)).rstrip()
             for line in lines_of]
    lines[0] = terminal.styled(lines[0], "dim")
    return [terminal.styled("ak's own runs, never ranking: merged in round 1 of the runs it "
                            "executed, let through in round 1 of those it reviewed, merged in "
                            "round 1 of its seat's own pull requests", "dim"), *lines]


def cell(found):
    """`97 of 3`: the score and the measures it rests on; `-` where the role has none."""
    return "-" if found is None else f"{found['score']:.0f} of {found['measures']}"


def stored():
    """The matrix as last computed, {"computed_at", "config", "harnesses", "build", "rows"}, or {}, its
    rows scored afresh: the catalogs `rows` asks are what the file saves, and scoring is cheap,
    so a scoring rule changed since the matrix was computed holds at once."""
    held = _held().get("matrix") or {}
    scored(held.get("rows") or [])
    return held


def refresh(cfg, *, refresh=False, now=None):
    """The boards (`collect`) and the matrix computed from them and the config, written beside
    the boards in `state/matrix.json` so every pick reads one computed truth; computed again
    only once a board answered anew, the config's models changed, the harnesses installed are
    not the ones it rowed or ak's own build is not the one that computed it (a matching rule
    that landed holds at the next tick, not a day later), since the harness catalogs it asks
    take time.  Returns (boards, the scored rows); `recommended` reads off the rows."""
    from . import update        # here, not at the top: update reaches this module through orch
    now = time.time() if now is None else now
    boards = collect(refresh=refresh, now=now)
    held = stored()
    fetched = max((board.get("fetched_at") or 0 for board in boards.values()), default=0)
    harnesses, build = present(), update.agentkit_version()
    if (held.get("rows") is not None and held.get("computed_at", -1) >= fetched
            and held.get("config") == config_key(cfg) and held.get("harnesses") == harnesses
            and held.get("build") == build):
        return boards, held["rows"]
    table = scored(rows(cfg, boards, harnesses))
    with _locked():
        cache = _held()
        cache["matrix"] = {"computed_at": now, "config": config_key(cfg), "harnesses": harnesses,
                           "build": build, "rows": table}
        _write(cache)
    return boards, table


def _at(entry, role):
    """The row a configured model runs in `role`: its harness and model, at the effort the
    config runs it at there."""
    return (entry["harness"], entry["model"], config.role_effort(entry, CONFIG_ROLES[role]))


def rank(cfg, role, names=None):
    """Each of the configured models `names` (all of them unless given) sorted on this for
    `role`, off the matrix as last computed, at the effort the config runs it at in that role:
    those within `within` of the best of them first, the cheaper first (`cost_key`), then the
    others by quality; None for a model the boards have nothing on or a matrix nobody computed
    yet.  A pick reads this and never the boards."""
    held = stored()
    rows_by = {(row["harness"], row["model"], row["effort"]): row for row in held.get("rows") or []}
    found = {}
    for name in config.offered(cfg) if names is None else names:
        row = rows_by.get(_at(cfg["models"][name], role))
        score = (row.get("scores") or {}).get(role) if row else None
        found[name] = (score["score"], cost_key(row)) if score else None
    best = max((place[0] for place in found.values() if place), default=None)
    return {name: None if place is None else (0, *place[1], -place[0])
            if place[0] >= best - within(cfg) else (1, 0, 0.0, -place[0])
            for name, place in found.items()}


def runs(cfg, row, role):
    """The configured model that runs `row` in `role`, off the config as it stands and matched
    as `rank` matches a model to its row; None where none does."""
    return next((name for name in config.offered(cfg)
                 if _at(cfg["models"][name], role) == (row["harness"], row["model"], row["effort"])),
                None)


def row_label(row):
    """`acme` for a configured row, else `acme-5-5`, and `@ max` where an effort is."""
    return (row["name"] or row["model"]) + (f" @ {row['effort']}" if row["effort"] else "")


def _num(value, places=0):
    return "-" if value is None else f"{value:.{places}f}"


def boards_lines(boards):
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


def render(table, boards, own=None, band=WITHIN):
    """The scored rows as a table, the best first, the recommendation per role and the rows as
    good as it, what each role is scored on, ak's own numbers per configured model (`own`),
    then what each board said and when."""
    table = sorted(table, key=lambda row: (-best(row), row["harness"], row["model"]))
    lines_of = [HEADERS] + [
        (row["name"] or "-", row["harness"],
         row["model"] + (f" @ {row['effort']}" if row["effort"] else ""),
         *(cell(row["scores"][role]) for role in ROLES),
         _num(row["values"].get(COST)), _num(row["values"].get(TASK_COST), 2))
        for row in table]
    width = terminal.width()

    def fit(line):
        return ([line] if terminal.cells(terminal.plain(line)) <= width else
                terminal.wrap(line, width))
    widths = [max(terminal.cells(line[i]) for line in lines_of) for i in range(len(HEADERS))]
    lines = [" ".join(terminal.pad(text, w) for text, w in zip(line, widths)).rstrip()
             for line in lines_of]
    lines[0] = terminal.styled(lines[0], "dim")
    picks = recommended(table, band)
    lines.append("recommended: " + " · ".join(
        f"{role} {row_label(rows[0])} ({cell(rows[0]['scores'][role])})"
        + (f", as good: {', '.join(row_label(row) for row in rows[1:])}" if rows[1:] else "")
        for role, rows in picks.items())
        if picks else "no recommendation yet: no board has a row ak can run")
    notes = ["a row's quality is its model's score for the role, the mean share of the best row "
             "over the role's measures on the model's row holding the most of them (half of "
             "them at least), times what its effort keeps of it on the measures that see "
             "efforts, else the intelligence index; a board naming no effort counts for every "
             f"effort of its model; a row within {band:g} of the best counts as as good "
             "(`within` in config.toml), and the cheapest of those is recommended: by `cost`, "
             "what Artificial Analysis's index run cost on it, then `$/task`, LiveBench's cost "
             "of a coding task, unpriced last, then the higher quality, the one the config runs "
             "in the role, the higher effort, the first by name",
             *(f"{role}, {len(columns)} measures: "
               + ", ".join(f"{column} ({why})" for column, why in columns)
               for role, columns in ROLES.items())]
    # wrapped before styling: wrap returns plain text, which would print the notes undimmed
    lines += [terminal.styled(part, "dim") for note in notes for part in fit(note)]
    if own:
        lines += live_lines(own)
    lines += boards_lines(boards)
    unmatched = [row_label(row) for row in table if not row["values"]]
    if unmatched:
        lines.append(f"no board row: {', '.join(unmatched)}")
    return "\n".join(part for line in lines for part in fit(line))


def main(argv):
    if command_help.show("models", argv):
        return 0
    flags = set(argv)
    if flags - {"--json", "--refresh"}:
        raise config.Error(f"usage: ak models [--json] [--refresh]  (got {argv!r})")
    cfg = config.load()
    boards, table = refresh(cfg, refresh="--refresh" in flags)
    own = live(cfg)
    if "--json" in flags:
        json.dump({"rows": table, "within": within(cfg),
                   "recommended": {role: [row_label(row) for row in rows]
                                   for role, rows in recommended(table, within(cfg)).items()},
                   "live": own,
                   "boards": {board: {k: v for k, v in held.items() if k != "rows"}
                              for board, held in boards.items()}}, sys.stdout, indent=2)
        print()
    else:
        print(render(table, boards, own, within(cfg)))
    return 0
