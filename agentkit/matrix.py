"""Every model and effort the installed harnesses offer, with the public boards' numbers for each
(`boards`), scored per role.

A row of the matrix is one model at one effort: an effort a board lists for it or the config
runs it at in any role, and a model no board lists at any effort is one row at none.  A board's
model is matched by name, letters and digits alone (`acme-5` is `Acme 5 (max)` at max), else by
the board's name the id extends with a version (`acme-pro` for `acme-pro-1.0`), else by the one
board name that is the id with a qualifier in brackets (`Acme 5 (Default Fallback)`); `benchmark`
on a config entry names the board's model on a board where none fits.  A board's name ending in
an effort word (`acme-5-max`) is the model at that effort, matched the same ways.  A board
naming no effort stands at the model's highest effort Artificial Analysis has an index for, or
at every effort where it has none.  The recommendation is of the models the owner marks
(`assessed`: `[assess]` in config.toml, else the models the config runs), and `rank` of every
configured model as scored.  A row takes each board's rows at its effort, together, else the
nearest above, which loses what Artificial Analysis's intelligence index loses between the
two efforts (`drops`; nothing from that board where the index is missing at either), else the
nearest below as it is: never credited upward.  A price is read only off a board's row at the
row's own effort.

Every row is scored per role, on quality and cost alone: speed is ak's own to fix, and the
subscriptions follow the choice.  Each measure is the points the row is behind the best value
on its whole board (`SCALES`), a measure read off a higher effort adding its drop and one the
board never ran the model on counting as the board's typical gap, and the role's score is 100
less the mean over the role's measures, weighted alike, given at least half of them (`ROLES`
names them and what each tests), said with how many it has (`97 of 3`).  A row
within `within` of the best counts as as good as it, and the cheapest of those is recommended,
the others beside it: by what a task of Artificial Analysis's index run cost on the row, a row
it has not run by LiveBench's cost of a coding task after every priced one, unpriced last, then
the higher quality, the row the config runs in the role, the higher effort, the first by
harness and model name.  ak's own run numbers stand beside, per configured model, the effort its runs recorded and
role, with their count, and never rank (AGENTS.md, Owner rules).
Attribution: Source: Artificial Analysis (artificialanalysis.ai); arena.ai; livebench.ai.
"""

import contextlib
import fcntl
import json
import re
import statistics
import sys
import time

from . import command_help, config, record, terminal
from .boards import EFFORT_ORDER, PREFIX, TASK_COST, collect, lines as board_lines

INTEL = "aa.intelligenceIndex"       # every model has it per effort
COST = "aa.intelligenceIndexCostPerTask.cost.total"      # dollars a task of its index run cost
PRICES = (COST, TASK_COST)          # what a row reads only off a board's row at its own effort
# A row this many points under the best counts as as good: the three boards disagree with each
# other about differences between the top models by more (a median of 6 to 10 points, 17 Oct
# 2026), so no row the boards agree is worse gets in.  `within` in config.toml overrides it;
# it goes to 0 the day the boards publish their intervals.
WITHIN = 5
# How a value is behind its board's best, in points out of 100, per kind of number: (which
# value is the best, the points behind it).  A percent in percentage points, a share from 0 to 1
# in hundredths, and a rating as how far under half its wins against the best would be (35
# behind is 45% of wins, 5 points).
SCALES = {
    "percent": (max, lambda best, value: best - value),
    "share": (max, lambda best, value: 100 * (best - value)),
    "rating": (max, lambda best, value: 100 * (0.5 - 1 / (1 + 10 ** ((best - value) / 400)))),
}
# What each role is scored on: a column (board.field), its kind (`SCALES`) and, in plain words,
# what it tests.  Pinned by tests/test_matrix_measures.py: it changes only with the owner's yes.
ROLES = {
    "orchestrate": (("arena.agent_task_outcome_explicit", "share",
                     "agent sessions the user confirmed did their task"),
                    ("arena.agent_steerability", "share",
                     "how little users had to correct the agent"),
                    ("livebench.long_agentic", "percent",
                     "multi-hour agent tasks that count only if their tests pass"),
                    ("aa.briefcaseBreakdown.overall.elo", "rating",
                     "long business projects of hundreds of turns, delivering files")),
    "execute": (("livebench.coding", "percent", "agent coding tasks"),
                ("livebench.long_agentic", "percent",
                 "multi-hour agent tasks that count only if their tests pass"),
                ("arena.agent_bash_reliability", "share", "how rarely its shell commands fail"),
                ("arena.webdev", "rating", "apps people pick between two built alike"),
                ("aa.terminalBench40", "share",
                 "hard terminal tasks that pass only when all their tests do")),
    "review": (("livebench.reasoning", "percent", "careful reading and deduction"),
               ("arena.text_factuality.coding", "rating",
                "coding answers people pick, a quarter of it their facts checked"),
               ("arena.text_style_control.coding", "rating",
                "coding answers people pick, their length and formatting aside"),
               ("aa.deepsecBench", "share",
                "reviewing files for bugs, each report judged a true or a false finding"),
               ("aa.omniscience", "percent",
                "right answers less wrong guesses, an admitted unknown counting neither")),
}
# the config's word for each role ak scores: `config.ROLE_EFFORTS` keys its efforts by these
CONFIG_ROLES = {"orchestrate": "orchestrator", "execute": "executor", "review": "reviewer"}
HEADERS = ("model", "harness", "id", "orch", "exec", "review", "cost", "$/task")


def cache_path():
    return config.STATE / "matrix.json"


@contextlib.contextmanager
def _locked():
    """One writer of `matrix.json`, the matrix as last computed, at a time: `matrix.lock` held
    while its `.tmp` is written and moved in, so two writers never share the `.tmp`."""
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


def normal(text):
    """A model's name as every board and config spells it alike: its letters and digits."""
    return re.sub(r"[^a-z0-9]", "", text.rsplit("/", 1)[-1].lower())


# a model's name ending in an effort word, however the word is joined on (`acme-5-max`,
# `Acme 5 xHigh`, `acme-5-x-high`): the word's letters alone, any separators among them
EFFORT_SUFFIX = re.compile(r"[\s_-]*(" + "|".join(r"[\s_-]*".join(word) for word in EFFORT_ORDER)
                           + ")$", re.IGNORECASE)


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


def indexed(rows):
    """A board's rows by their model's name as `normal` spells it.  A row naming no effort whose
    name ends in an effort word (`EFFORT_SUFFIX`: `acme-5-max`) is under the rest of its name
    too, as that model at that effort, so `found` matches it every way it has."""
    index = {}
    for row in rows:
        index.setdefault(normal(row["model"]), []).append(row)
        cut = EFFORT_SUFFIX.search(row["model"]) if row["effort"] is None else None
        if cut:
            model = row["model"][:cut.start()]
            index.setdefault(normal(model), []).append(
                {**row, "model": model, "effort": normal(cut.group(1))})
    return index


def placed(rows, effort, top, intel):
    """What a board says of a model at `effort`, off its rows for the model (`found`): (its
    rows there as one, the points it adds to every measure, None at the effort itself), else
    None.  A row naming no effort stands at `top`, the model's highest effort with an
    intelligence index, or at every effort where that is None.  The rows at `effort`, else the
    nearest above, adding what the index (`intel`, per effort) loses between the two and None
    where it is missing at either, else the nearest below as it is.  Rows standing at one
    effort say it together (`Acme 5 (max)` beside `acme-5-max`), the first named at it winning
    a column they share."""
    at = {}
    for row in sorted(rows, key=lambda row: row["effort"] is None):    # a named effort first
        there = at.setdefault(row["effort"] or top or effort, dict(row))
        there["values"] = {**row["values"], **there["values"]}
    if effort in at:
        return at[effort], None
    above = [word for word in at if effort_rank(word) > effort_rank(effort)]
    if above:
        word = min(above, key=effort_rank)
        if word not in intel or effort not in intel:
            return None
        return at[word], max(0.0, intel[word] - intel[effort])
    return (at[max(at, key=effort_rank)], 0.0) if at else None


def rows(cfg, boards, harnesses):
    """One row per model and effort `harnesses` (`present`) offer, with the config name that
    runs it and the roles it runs it in, the numbers each board says of it there, each measure
    placed on its own (`placed`; a price only off a board's row at the effort itself), the
    points a measure read off a higher effort adds (`drops`) and which board model and effort
    each board's measures came from, the first naming an effort before one naming none."""
    indexes = {board: indexed(held.get("rows") or []) for board, held in boards.items()}
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
            found_rows = {board: found(index, model, benchmark) for board, index in indexes.items()}
            # the efforts worth a row: the boards' for this model, among those the harness
            # offers, and the config's
            efforts = {row["effort"] for rows_of in found_rows.values() for row in rows_of
                       if row["effort"] and (not offered or row["effort"] in offered)}
            efforts |= {effort for (h, m, effort) in names if (h, m) == (harness, model)}
            intel = {row["effort"]: row["values"][INTEL] for rows_of in found_rows.values()
                     for row in rows_of if row["effort"] and INTEL in row["values"]}
            top = max(intel, key=effort_rank, default=None)
            for effort in sorted(efforts, key=lambda word: -effort_rank(word)) or [None]:
                row = {"harness": harness, "model": model, "effort": effort,
                       "name": names.get((harness, model, effort)),
                       "roles": [role for role in ROLES
                                 if role in roles.get((harness, model, effort), ())],
                       "values": {}, "drops": {}, "matched": {}}
                for board, rows_of in found_rows.items():
                    # each measure on its own: a board may test a model on a measure at one
                    # effort alone
                    for column in dict.fromkeys(c for source in rows_of for c in source["values"]):
                        hit = placed([source for source in rows_of if column in source["values"]],
                                     effort, top, intel)
                        if hit is None or hit[1] is not None and column in PRICES:
                            continue
                        source, drop = hit
                        row["values"][column] = source["values"][column]
                        if drop:
                            row["drops"][column] = drop
                        if row["matched"].get(board, {}).get("effort") is None:
                            row["matched"][board] = {"model": source["model"],
                                                     "effort": source["effort"]}
                table.append(row)
    return table


def effort_rank(effort):
    """Where an effort stands among the words ak knows, the highest last; a word ak does not
    know, or no effort, stands below them all."""
    return EFFORT_ORDER.index(effort) if effort in EFFORT_ORDER else -1


def bests(boards):
    """Per measure a role is scored on, {"best": the best value on its whole board (`SCALES`),
    "typical": the median points behind it over the board's rows}."""
    found = {}
    for held in boards.values():
        for row in held.get("rows") or []:
            for column, kind, _ in (measure for measures in ROLES.values() for measure in measures):
                if column in row["values"]:
                    found.setdefault(column, []).append(row["values"][column])
    return {column: {"best": SCALES[kind][0](values),
                     "typical": statistics.median(SCALES[kind][1](SCALES[kind][0](values), value)
                                                  for value in values)}
            for column, kind, _ in (measure for measures in ROLES.values() for measure in measures)
            for values in [found.get(column)] if values}


def behind(row, column, kind, best):
    """The points `row` is behind `best` (`bests`) on one measure: its own value's, a measure read
    off a higher effort adding its `drops`, else the board's typical gap, as a model the board
    never tested on it is as likely above as below the ones it did."""
    if column not in row["values"]:
        return best[column]["typical"]
    return (SCALES[kind][1](best[column]["best"], row["values"][column])
            + (row.get("drops") or {}).get(column, 0))


def scored(table, best):
    """Each row's `scores`: per role, {"score", "measures"}: 100 less the mean of the points it
    is `behind` the best on each of the role's measures, with how many of them it has; None
    under half of them."""
    for row in table:
        row["scores"] = {}
        for role, measures in ROLES.items():
            points = [behind(row, column, kind, best) for column, kind, _ in measures if column in best]
            have = sum(column in row["values"] for column, _, _ in measures)
            row["scores"][role] = ({"score": 100 - sum(points) / len(points), "measures": have}
                                   if points and 2 * have >= len(measures) else None)
    return table


def assessed(cfg):
    """The models the recommendation is of, {(harness, model)}: `[assess]` in config.toml, each
    harness's list of model ids, else every model the config runs."""
    marks = cfg.get("assess")
    if marks is not None:
        return {(harness, model) for harness, models in marks.items() for model in models}
    return {(cfg["models"][name]["harness"], cfg["models"][name]["model"])
            for name in config.offered(cfg)}


def assessment(cfg, table):
    """The rows of `table` the recommendation is of (`assessed`)."""
    marks = assessed(cfg)
    return [row for row in table if (row["harness"], row["model"]) in marks]


def best(row):
    """A row's best quality in any role, -1 where no role scores it: what orders rows."""
    return max((found["score"] for found in (row.get("scores") or {}).values() if found),
               default=-1)


def within(cfg):
    """How many points under the best still counts as as good: `within` in the config, else
    `WITHIN`."""
    return cfg.get("within", WITHIN)


def cost_key(row):
    """What ordering by cost sorts a row on: what a task of Artificial Analysis's index run
    cost, a row it has not run after every priced one, by LiveBench's cost of a coding task, unpriced last."""
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
    """The matrix as last computed, {"computed_at", "config", "harnesses", "build", "bests",
    "rows"}, or {}, its rows scored afresh against the boards' bests it saved: the catalogs `rows`
    asks are what the file saves, and scoring is cheap, so a scoring rule changed since the
    matrix was computed holds at once."""
    held = _held().get("matrix") or {}
    scored(held.get("rows") or [], held.get("bests") or {})
    return held


def needed():
    """The columns scoring reads, by board, for `collect`: a board whose cached rows carry none
    of one is read again by a new build, since its reader changed."""
    columns = {COST, INTEL, TASK_COST} | {column for role in ROLES.values()
                                          for column, _, _ in role}
    return {board: {column for column in columns if column.split(".")[0] == prefix}
            for board, prefix in PREFIX.items()}


def refresh(cfg, *, refresh=False, now=None):
    """The boards (`collect`) and the matrix computed from them and the config, written to
    `state/matrix.json` so every pick reads one computed truth; computed again
    only once a board answered anew, the config's models changed, the harnesses installed are
    not the ones it rowed or ak's own build is not the one that computed it (a matching rule
    that landed holds at the next tick, not a day later), since the harness catalogs it asks
    take time.  Returns (boards, the scored rows); `recommended` reads off the rows."""
    from . import update        # here, not at the top: update reaches this module through orch
    now = time.time() if now is None else now
    harnesses, build = present(), update.agentkit_version()
    boards = collect(refresh=refresh, now=now, needs=needed(), build=build)
    held = stored()
    fetched = max((board.get("fetched_at") or 0 for board in boards.values()), default=0)
    if (held.get("rows") is not None and held.get("computed_at", -1) >= fetched
            and held.get("config") == config_key(cfg) and held.get("harnesses") == harnesses
            and held.get("build") == build):
        return boards, held["rows"]
    best = bests(boards)
    table = scored(rows(cfg, boards, harnesses), best)
    with _locked():
        _write({"matrix": {"computed_at": now, "config": config_key(cfg), "harnesses": harnesses,
                           "build": build, "bests": best, "rows": table}})
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


def render(table, boards, own=None, band=WITHIN):
    """The scored rows as a table, the best first, the recommendation per role and the rows as
    good as it, what each role is scored on, ak's own numbers per configured model (`own`),
    then what each board said and when."""
    table = sorted(table, key=lambda row: (-best(row), row["harness"], row["model"]))
    lines_of = [HEADERS] + [
        (row["name"] or "-", row["harness"],
         row["model"] + (f" @ {row['effort']}" if row["effort"] else ""),
         *(cell(row["scores"][role]) for role in ROLES),
         _num(row["values"].get(COST), 2), _num(row["values"].get(TASK_COST), 2))
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
    notes = ["a row's quality for a role is 100 less the mean of the points it is behind the best "
             "on each board over the role's measures, half of them at least: percentage points, "
             "a share in hundredths, a rating as how far under half its wins against the best "
             "would be; a board row at a higher effort adds what Artificial Analysis's "
             "intelligence index loses down to the row's, one naming no effort stands at the "
             "model's highest, and a measure the board never ran the model on counts as the "
             f"board's typical gap; a row within {band:g} of the best counts as as good "
             "(`within` in config.toml), and the cheapest of those is recommended: by `cost`, "
             "what a task of Artificial Analysis's index run cost on it, then `$/task`, "
             "LiveBench's cost "
             "of a coding task, unpriced last, then the higher quality, the one the config runs "
             "in the role, the higher effort, the first by name",
             *(f"{role}, {len(measures)} measures: "
               + ", ".join(f"{column} ({why})" for column, _, why in measures)
               for role, measures in ROLES.items())]
    # wrapped before styling: wrap returns plain text, which would print the notes undimmed
    lines += [terminal.styled(part, "dim") for note in notes for part in fit(note)]
    if own:
        lines += live_lines(own)
    lines += board_lines(boards)
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
    table, own = assessment(cfg, table), live(cfg)
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
