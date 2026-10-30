"""Every current model on the boards, a row per release and effort with the installed harnesses'
models that are it (`lineup`), answered per role on quality and cost alone (`answer`), the
cheapest within `within` of the best the pick; `rank` places each configured model off it.  ak's
own run numbers stand beside, per configured model, the effort its runs recorded and role, with
their count, and never rank (AGENTS.md, Owner rules).
Attribution: Source: Artificial Analysis (artificialanalysis.ai); arena.ai.
"""

import contextlib
import fcntl
import functools
import json
import re
import sys
import time

from . import catalog, command_help, config, quality, record, terminal
from .boards import PREFIX, cached, collect, effort_rank

# A row this many points under the best counts as as good: the three boards disagree with each
# other about differences between the top models by more (a median of 6 to 10 points, 17 Oct
# 2026), so no row the boards agree is worse gets in.  `within` in config.toml overrides it;
# it goes to 0 the day the boards publish their intervals.
WITHIN = 5
# the config's word for each role ak answers: `config.ROLE_EFFORTS` keys its efforts by these
CONFIG_ROLES = {"orchestrate": "orchestrator", "execute": "executor", "review": "reviewer"}


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
                   *(config.role_effort(cfg["models"][name], role) for role in config.ROLE_EFFORTS)]
                  for name in config.offered(cfg))


def normal(text):
    """A model's name as every board and config spells it alike: its letters and digits."""
    return re.sub(r"[^a-z0-9]", "", text.rsplit("/", 1)[-1].lower())


def found(index, model):
    """A board's rows for one model: under its exact name, else under a board's name naming no
    version of its own that `model` extends with one (`Acme Pro` for `acme-pro-1.0`, never
    `Acme 5` for `acme-5-5`), else under the one board name that is `model` with a qualifier in
    brackets (`Acme 5 (Default Fallback)`; two such names stand for nothing), else under each
    board name that adds a version or date to a `model` naming none (`Acme Flash 1017` for
    `acme-flash`, `lineup` taking only one release), else the same matches without a trailing
    `-free` pricing tier; none where the board has nothing for it."""
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
    extended = [hit for stem, hits in index.items() for hit in hits
                if not wanted[-1:].isdigit() and stem.startswith(wanted)
                and stem[len(wanted):].isdigit()]
    if extended:
        return extended
    if model.endswith("-free"):
        # Free is a pricing tier, so use the underlying model's board rows.
        return found(index, model.removesuffix("-free"))
    return []


def lineup(boards, offers):
    """A row per current release (`catalog.current`) and effort, with its `values` as the
    catalog joins them and `yours`: each model of `offers` ({harness: config.catalog(harness)})
    that `found` matches to this release alone, as {"harness", "model"}, at each effort it
    lists and at a row naming no effort, which is the model however it is run, or at the
    release's default where it lists none but `none`."""
    releases = catalog.current(boards)
    index = {}
    for release in releases:
        # the name first: `found` reads the first hit's for a bracketed qualifier; either may lack
        for name in filter(None, (release["name"], release["slug"])):
            index.setdefault(normal(name), []).append({"model": name, "release": release})
    yours = {}
    for harness, models in offers.items():
        for model in models:
            hits = {hit["release"]["slug"]: hit["release"] for hit in found(index, model["id"])}
            if len(hits) != 1:
                continue
            [release] = hits.values()
            words = (None, *model["efforts"]) if set(model["efforts"]) - {"none"} else None
            for effort in release["efforts"]:
                if effort["effort"] in words if words else effort["default"]:
                    yours.setdefault((release["slug"], effort["effort"]), []).append(
                        {"harness": harness, "model": model["id"]})
    return [{"release": release["slug"], "name": release["name"], "maker": release["maker"],
             "effort": effort["effort"], "values": effort["values"],
             "yours": yours.get((release["slug"], effort["effort"]), [])}
            for release in releases for effort in release["efforts"]]


def answer(lineup, within, compared=None):
    """Per role, `rated`: `quality.rated` over every row of `lineup`, so a row's quality never
    changes with what is compared; then over the rows of the releases in `compared` (slugs, None
    for every one), `best` quality, `pick` at `within`, `front`: those with a cost, cheapest
    first, each better than every cheaper one, and `take`: the cheapest of them that is yours
    within `within` of `best`, the pick itself when it is yours."""
    out = {}
    for role in quality.ROLES:
        rated = quality.rated(lineup, role)
        them = [row for row in rated if compared is None or row["release"] in compared]
        best = max((row["quality"] for row in them), default=None)
        priced = sorted((row for row in them if row["cost"] is not None),
                        key=lambda row: (row["cost"], -row["quality"]))
        front = []
        for row in priced:
            if not front or row["quality"] > front[-1]["quality"]:
                front.append(row)
        take = next((row for row in priced
                     if row["yours"] and row["quality"] >= best - within), None)
        out[role] = {"rated": rated, "best": best, "pick": quality.pick(them, within),
                     "front": front, "take": take}
    return out


def compared(cfg, current):
    """The releases of `current` (slugs) that `compare` in the config marks, one replaced since
    as its successor (catalog.successor), so a mark never holds a replaced model, and one that
    is neither as nothing; None, every one, where nothing is marked."""
    marked = cfg.get("compare") or []
    boards = cached() if set(marked) - current else {}    # the boards only for a replaced one
    found = {slug if slug in current else (catalog.successor(boards, slug) or {}).get("slug")
             for slug in marked} & current
    return found or None


def within(cfg):
    """How many points under the best still counts as as good: `within` in the config, else
    `WITHIN`."""
    return cfg.get("within", WITHIN)


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
                role: share(*counts.get(effort, {}).get(role, (0, 0))) for role in quality.ROLES}
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
        (name, *(live_cell(found[role]) for role in quality.ROLES))
        for name, found in own.items()]
    widths = [max(terminal.cells(line[i]) for line in lines_of) for i in range(len(LIVE_HEADERS))]
    head, *lines = [" ".join(terminal.pad(text, w) for text, w in zip(line, widths)).rstrip()
                    for line in lines_of]
    room = terminal.layout_width()

    def fit(text):
        # a row wider than the terminal wraps rather than run past its edge
        return [text] if terminal.cells(text) <= room else terminal.wrap(text, room)
    said = ("ak's own runs, never ranking: merged in round 1 of the runs it executed, let "
            "through in round 1 of those it reviewed, merged in round 1 of its seat's own pull "
            "requests")
    return [terminal.styled(part, "dim") for part in (*terminal.wrap(said, room), *fit(head))] \
        + [part for line in lines for part in fit(line)]


def stored():
    """The matrix as last computed, {"computed_at", "config", "harnesses", "build", "lineup",
    "fetched_at"} (`lineup` over the boards and harnesses it read, the newest board's
    `fetched_at`), or {}."""
    return _held().get("matrix") or {}


def needed():
    """The columns `quality` reads, by board, for `collect`: each role's measures and the cost
    of its task, the index and what each measure's error cannot be had without.  A board whose
    cached rows carry none of one is read again by a new build, since its reader changed."""
    columns = {quality.INTEL, *quality.COSTS.values()} | {
        name for role in quality.ROLES.values() for column, *_ in role
        for name in (column, *quality.reads(column))}
    return {board: {column for column in columns if column.split(".")[0] == prefix}
            for board, prefix in PREFIX.items()}


def refresh(cfg, *, refresh=False, now=None):
    """The boards (`collect`) and the matrix computed from them and the config, written to
    `state/matrix.json` so every pick reads one computed truth; computed again
    only once a board answered anew, the config's models changed, the harnesses installed are
    not the ones it rowed or ak's own build is not the one that computed it (a matching rule
    that landed holds at the next reading, not a day later), since the harness catalogs it asks
    take time.  Asked as the models screen opens and by `ak models`, never the tick: the owner
    wants the assessment as a feature opened, not a process running all day (22 Oct 2026).
    The matrix is the lineup (`lineup`), so the models screen reads it and asks no catalog.
    Returns (boards, the lineup)."""
    from . import update        # here, not at the top: update reaches this module through orch
    now = time.time() if now is None else now
    harnesses, build = present(), update.agentkit_version()
    boards = collect(refresh=refresh, now=now, needs=needed(), build=build)
    held = stored()
    fetched = max((board.get("fetched_at") or 0 for board in boards.values()), default=0)
    if (held.get("lineup") is not None and held.get("computed_at", -1) >= fetched
            and held.get("config") == config_key(cfg) and held.get("harnesses") == harnesses
            and held.get("build") == build):
        return boards, held["lineup"]
    offers = {harness: config.catalog(harness, cfg) for harness in harnesses}
    rows = lineup(boards, offers)
    with _locked():
        _write({"matrix": {"computed_at": now, "config": config_key(cfg), "harnesses": harnesses,
                           "build": build, "lineup": rows, "fetched_at": fetched}})
    return boards, rows


@functools.lru_cache(maxsize=1)
def _answered(text):
    """`answer` over the lineup `text`, `state/matrix.json` as read, holds: rated once per
    stored lineup, however often a run picks.  `rated` reads no `within`."""
    return answer((json.loads(text).get("matrix") or {}).get("lineup") or [], WITHIN)


def rank(cfg, role, names):
    """Each of the configured models `names` sorted on this for `role`, off the lineup as last
    stored and `answer` rated it: the row whose `yours` holds its harness and model at the
    effort the config runs it at there.  Those within `within` of the best of them first, the
    cheaper first and one without a cost last, then the others by quality; None for a model no
    row is, or a lineup nobody stored.  A pick reads this and never the boards."""
    try:
        rated = _answered(cache_path().read_text())[role]["rated"]
    except (OSError, ValueError):
        rated = []
    rows = {(one["harness"], one["model"], row["effort"]): row
            for row in rated for one in row["yours"]}
    found = {name: rows.get((cfg["models"][name]["harness"], cfg["models"][name]["model"],
                             config.role_effort(cfg["models"][name], CONFIG_ROLES[role])))
             for name in names}
    best = max((row["quality"] for row in found.values() if row), default=None)
    return {name: None if row is None else
            (0, row["cost"] is None, row["cost"] or 0.0, -row["quality"])
            if row["quality"] >= best - within(cfg) else (1, False, 0.0, -row["quality"])
            for name, row in found.items()}


def notes(row, said):
    """What the models screen notes beside a front row of `said`, `answer`'s for a role."""
    missing = sum(one["how"] == "missing" for one in row["measures"].values())
    return [word for word, true in (
        ("pick", row is said["pick"]),
        ("tie", row is not said["pick"] and said["pick"] and quality.tie(row, said["pick"])),
        (f"{missing} missing", missing), ("no harness", not row["yours"])) if true]


def main(argv):
    if command_help.show("models", argv):
        return 0
    flags = set(argv)
    if flags - {"--json", "--refresh"}:
        raise config.Error(f"usage: ak models [--json] [--refresh]  (got {argv!r})")
    from . import menu      # here, not at the top: the menu reaches this module as it loads
    cfg = config.load()
    _, rows = refresh(cfg, refresh="--refresh" in flags)
    current = {row["release"] for row in rows}
    marked = compared(cfg, current)
    found, own = answer(rows, within(cfg), marked), live(cfg)
    if "--json" in flags:
        json.dump({**{role: {"best": said["best"], "front": [
            {**{key: row[key] for key in ("release", "name", "effort", "quality", "se", "cost")},
             "notes": notes(row, said)} for row in said["front"][::-1]]}
            for role, said in found.items()}, "live": own}, sys.stdout, indent=2)
        print()
        return 0
    body, _ = menu.models_body(menu.models_said(found, rows), within(cfg), marked, len(current),
                               stored().get("fetched_at"))
    print("\n".join([*body, *(["", *live_lines(own)] if own else [])]))
    return 0
