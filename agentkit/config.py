"""config.toml loading, model resolution, and every agentkit path."""

from contextlib import contextmanager
import copy
import datetime
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path
from string import Template

from . import host, parsed

REPO = Path(__file__).resolve().parent.parent
STARTED = time.time()   # when this process read its code: every entry imports this module first
HOME = Path.home() / ".agentkit"
PLACES = {"RUNS": "runs", "WT": "wt", "STATE": "state", "SECRETS": "secrets", "TMP": "tmp",
          "ENV": "env", "WORK": "work", "JOBS": "jobs"}
_self = sys.modules[__name__]   # config.STATE and the rest, as this module reads them too


# Python calls __getattr__ for config.STATE and every other place: each follows HOME wherever
# a test or a checkout moves it, so sandboxing HOME alone keeps the owner's real ~/.agentkit out
# of reach.  A test that moved HOME but not STATE once wrote the shipped config's usage reading
# over the owner's, every subscription's reading gone.  Anything patching a place itself keeps
# working, since it shadows this fallback.
def __getattr__(name):
    if name in PLACES:
        return HOME / PLACES[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def tilde(path):
    """`path` as `~/...` under the home directory: what a typed line names stays short
    however deep that directory is."""
    try:
        return f"~/{Path(path).relative_to(Path.home())}"
    except ValueError:
        return str(path)


JOB_DIR_ENV = "AGENTKIT_JOB_DIR"  # the `ak run --bg` job child this receipt belongs to
KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
HARNESS = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")   # a harness name is one path component


RUN_DIR_ENV = "AGENTKIT_RUN_DIR"
ADAPTER_DIR_ENV = "AGENTKIT_ADAPTER_DIR"   # adapters/ elsewhere: the offline smoke checks
SESSION_ENV = "AGENTKIT_SESSION"
RULEBOOK_ENV = "AGENTKIT_RULEBOOK"          # the rulebook a launch has written, for its adapter to take
RULEBOOK_DIR_ENV = "AGENTKIT_RULEBOOK_DIR"  # a dry run's: where rulebook.py writes instead of STATE
SEAT_REPO_ENV = "AGENTKIT_SEAT_REPO"      # a new seat's project, for rulebook.py: no record yet
# where a seat's project rules are read: the full name, since a branch or tag called
# origin/HEAD would win the short one
RULES_REF = "refs/remotes/origin/HEAD"
ACCOUNT_ENV = "AGENTKIT_ACCOUNT"           # which of a provider's `accounts` an adapter call is for
FIRST_PROMPT_ENV = "AGENTKIT_FIRST_PROMPT"  # ... and the line its harness opens on, where it takes one
PROVIDER_ENV = "AGENTKIT_PROVIDER"         # ... and which providers, where a harness runs several's
DEFAULT_ACCOUNT = "default"                # ... the login it has when it lists none: the empty name
UNATTENDED_ENV = "AGENTKIT_UNATTENDED"   # set below a run loop: what it starts is machinery
CODE = Path.home() / "code"                # where the checkouts live, and where a new seat opens
RENAME_HOPS = 8                            # how many renames a session name is followed through
DEFAULT_MODEL = "default"                  # config.toml: the harness runs its own model, no -m
SESSION_STALE = 7 * 86400                  # a record whose session has been gone this long goes
RUN_DEFAULTS = {"max_runs": 0}
CONFIG_NAME = "config.toml"                # the one config file, under HOME: never in the checkout
DEFAULT_CONFIG_NAME = "config.default.toml"   # ... whose shipped default install.sh copies there
# Everything ak keeps at the top of HOME.  Anything else there is a session's own, and the
# collector removes it a week after its last change.  history.db-journal stays: one left by a
# writer that crashed before history.db turned WAL is what puts its file back.
OWN = ("agentkit.git", "bin", CONFIG_NAME, "env", "history.db", "history.db-journal", "history.db-wal",
       "history.db-shm", "history.lock", "history.log", "jobs", "macbridge", "rules.md", "runs", "secrets",
       "state", "tasks", "tmp", "versions", "work", "wt")
EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")   # the effort words for a
                               # harness whose adapter manifest names none of its own
POINTS = 10                    # the most `within` can be: past ten, a point says nothing
CATALOG_TTL = 60               # seconds a harness's model list is reused before it is asked again
CATALOG_NOW = 0.05             # seconds catalog_now waits on catalog() before the answer it has


class Error(Exception):
    """A user-facing error: printed as `ak: <message>` with no traceback."""


def max_runs():
    """Positive host count ceiling; zero means no count cap (or no gates for AK_MAX_RUNS)."""
    override = os.environ.get("AK_MAX_RUNS")
    if override is not None:
        if not override.isascii() or not override.isdigit():
            raise Error("AK_MAX_RUNS must be a non-negative integer (0 disables the cap for tests)")
        return int(override)
    return _count_setting("max_runs")


def max_gates():
    """Pinned heavy-suite turns, or None when the config leaves the count derived.

    An explicit `max_gates` in the home config file pins the host-wide count, 0
    still meaning no cap; a missing file or a missing key means the count is
    derived from the slice's live headroom, never a shipped number.
    """
    path = HOME / CONFIG_NAME
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise Error(f"{path}: {exc}") from exc
    if "max_gates" not in data:
        return None
    value = data["max_gates"]
    if type(value) is not int or value < 0:
        raise Error(f"{path}: max_gates must be a non-negative integer")
    return value


def _count_setting(key):
    """A non-negative integer at the top of the home config file, or the shipped default."""
    path = HOME / CONFIG_NAME
    try:
        with path.open("rb") as fh:
            value = tomllib.load(fh).get(key, RUN_DEFAULTS[key])
    except FileNotFoundError:
        return RUN_DEFAULTS[key]
    except (OSError, ValueError) as exc:
        raise Error(f"{path}: {exc}") from exc
    if type(value) is not int or value < 0:
        raise Error(f"{path}: {key} must be a non-negative integer")
    return value


def _resource_setting(key, environment, default):
    """Read one host gate setting without requiring the model tables in config.toml."""
    override = os.environ.get(environment)
    if override is not None:
        try:
            value = float(override) if "." in override else int(override)
        except ValueError as exc:
            raise Error(f"{environment} must be a non-negative number") from exc
        if isinstance(value, bool) or not math.isfinite(value) or value < 0:
            raise Error(f"{environment} must be a non-negative number")
        return value
    path = HOME / CONFIG_NAME
    try:
        with path.open("rb") as fh:
            value = tomllib.load(fh).get(key, default)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        raise Error(f"{path}: {exc}") from exc
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0):
        raise Error(f"{path}: {key} must be a non-negative number")
    return value


def min_free_mb(mem_total_mb=None):
    """Minimum MemAvailable, defaulting to the larger of 3072 MB and 20% of RAM."""
    if mem_total_mb is None:
        mem_total_mb = host.memory_mb("MemTotal") or 0
    default = max(3072, mem_total_mb * 0.20)
    return _resource_setting("min_free_mb", "AK_MIN_FREE_MB", default)


def max_load(cpus=None):
    """Maximum one-minute load, defaulting to the host's processor count."""
    cpus = host.cpu_count() if cpus is None else cpus
    default = max(1, cpus or 1)
    return _resource_setting("max_load", "AK_MAX_LOAD", default)


def max_load_is_set():
    """True when the owner pinned the host load gate, in the config or the environment.

    Pinned, the old load check still decides admission, with its old meaning;
    unset, nothing gates CPU and the default above goes unread. A corrupt config answers False here and raises where the
    gate itself reads it, as before.
    """
    if os.environ.get("AK_MAX_LOAD") is not None:
        return True
    try:
        with (HOME / CONFIG_NAME).open("rb") as fh:
            return "max_load" in tomllib.load(fh)
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return False


def run_memory_max_mb():
    """The per-run memory cap in MiB, or None when the config leaves it unset.

    Unset is not zero.  The caller then takes 40% of the slice ceiling, or
    4 GB where there is no ceiling to read.  A present value is that cap,
    whatever the ceiling is:
    one leaking run has to be stoppable without waiting to see how large the
    host is.  A bool would pass an ``int`` check, so the type has to be ``int``
    exactly.
    """
    path = HOME / CONFIG_NAME
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise Error(f"{path}: {exc}") from exc
    if "run_memory_max_mb" not in data:
        return None
    value = data["run_memory_max_mb"]
    if type(value) is not int or value <= 0:
        raise Error(f"{path}: run_memory_max_mb must be a positive integer")
    return value


def json_pages(text):
    """Decode gh api --paginate's consecutive JSON documents, without newer gh flags."""
    decoder, pages = json.JSONDecoder(), []
    rest = text.lstrip()
    while rest:
        page, end = decoder.raw_decode(rest)
        pages.append(page)
        rest = rest[end:].lstrip()
    if not pages:
        raise ValueError("gh printed no JSON pages")
    return pages


def child_env():
    """The environment for anything a run spawns.

    AGENTKIT_RUN_DIR marks the `ak run --bg` child.  Left in place it reaches every model
    call and done-when command, where a nested `ak run` adopts this run's directory,
    worktree and task file instead of making its own.  A harness's own seat variables and
    AK_RUN_SCOPE go the same way and for the same reason: they are the launch's, not its
    children's -- see `seat_env_names`.  So does AGENTKIT_ACCOUNT: it names the login one
    adapter call is for, and a turn on one account starts nothing that should run on it unasked.
    """
    dropped = {RUN_DIR_ENV, "AK_RUN_SCOPE", ACCOUNT_ENV, *seat_env_names()}
    return {k: v for k, v in os.environ.items() if k not in dropped}


def owner_env():
    """`child_env` without the seat's name, for a stop the person at the menu's keys asks for --
    the seat the menu is over (Ctrl-b m's popup is inside one) would make every other seat's
    stop a seat's, refused (`check_stop_owner`, the guard for what a seat's own model types) --
    and for a project's features command (`menu.features_run`)."""
    env = child_env()
    env.pop(SESSION_ENV, None)
    return env


def harness_binary(name):
    """The binary the way its adapter finds it: PATH first, its own bin dir as fallback.

    ~/.opencode/bin and ~/.grok/bin are on no fresh shell's PATH, so a lookup by PATH
    alone misses a working install -- the adapter would reinstall over it, and `ak
    update` would call it missing.  The fallback answers only where PATH has none: an
    explicit placement first on PATH -- a test fake, a version manager, /usr/local --
    keeps its precedence and is never shadowed by the installer's own dir.  Every
    adapter does the same check in shell; this is the same answer in Python.  An
    absolute path answers itself when it is executable, and anything unanswered is "",
    the way shutil.which says it with None.
    """
    if "/" in name:
        path = Path(name)
        return name if path.is_file() and os.access(path, os.X_OK) else ""
    found = shutil.which(name)
    if found:
        return found
    home = Path.home()
    grok_bin = Path(os.environ.get("GROK_BIN_DIR") or home / ".grok/bin")
    for directory in (home / ".opencode/bin", grok_bin,
                      home / ".local/bin", home / ".npm-global/bin"):
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return ""


def harness_present(harness):
    """Whether that harness is present to run a turn: its adapter here and its program found,
    the one its `[update] version` runs, else the adapter's own name, as `orch.agent_programs`
    reads them.  The one answer for a pick, a seat's move, the config screen and `ak models`."""
    try:
        adapter(harness)
    except Error:
        return False
    return bool(harness_binary(harness_program(harness)))


def harness_program(harness):
    """The program of that harness `harness_present` finds."""
    block = manifest(harness).get("update")
    version = block.get("version") if isinstance(block, dict) else None
    named = isinstance(version, list) and version and isinstance(version[0], str) and version[0]
    return version[0] if named else harness


def seatless_env():
    """child_env() without the seat's name: nothing below the loop speaks for a seat.

    The loop process keeps $AGENTKIT_SESSION, because that is where a run's `launched_session`
    comes from at launch.  A model call and a done-when command below it do not: an `ak run` or
    a smoke suite they start would otherwise count as launched from the seat that launched the
    loop -- reported to it, typed into it, and counted in its row.

    $AGENTKIT_UNATTENDED says what the missing name cannot.  A run launched by hand has no seat
    either, but it has the terminal it was started from, and the menu still offers it; a run
    started below another run has neither, so it is machinery and belongs on no menu at all.
    """
    return {**{k: v for k, v in child_env().items() if k != SESSION_ENV}, UNATTENDED_ENV: "1"}


def unattended():
    """Whether this process was started below a run loop rather than by a person."""
    return bool(os.environ.get(UNATTENDED_ENV))


def repo_env(repo):
    """The KEY=value pairs of ~/.agentkit/env/<repo-basename>.env, or {} if there is none.

    A repo's test secrets live on the machine, never in the repo.  A line the file gets wrong
    ends the run: a typo that silently dropped one variable would surface as a test failure the
    executor cannot fix, so it is reported here, by line number and without its value.
    """
    path = _self.ENV / f"{Path(repo).name}.env"
    if not path.exists():
        return {}
    try:
        text = path.read_text()
    except OSError as exc:
        raise Error(f"cannot read {path}: {exc}")
    env = {}
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not KEY.match(key):
            raise Error(f"{path}:{n}: not a KEY=value line")
        value = value.strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key] = value
    return env


def _read_toml(path):
    """Parse one TOML file, or None when there is no such file."""
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise Error(f"cannot read {path}: {exc}")
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise Error(f"{path}: {exc}")


def load():
    """The config: ~/.agentkit/config.toml, else the default shipped in the checkout.

    install.sh copies that default to the home file once and never again, so a config the
    owner has edited survives every later install, and a checkout nobody has installed from
    still reads -- silently, because there is nothing to fix.

    It is the same file max_runs() reads, and an install from before the models moved into it
    left only that key there.  A file that configures no models at all is not a broken config:
    the shipped default answers for the models, and the home file still answers for max_runs.

    Every model is offered as orchestrator and as worker; `[defaults]` names the orchestrator
    and the workers a new seat starts with, the last created seat's (remember_defaults): a
    model removed since is passed over here, and in the file once saved.  A file from before it said
    that with two tier lists, and reads as what they meant outside a session: the first of A
    orchestrating for B without it.  Nothing writes it back until the config is next saved,
    which then writes `[defaults]` and the top-level `pace_margin` in their place.
    """
    tables = ("defaults", "tiers", "models", "providers")
    path = HOME / CONFIG_NAME
    cfg = _read_toml(path)
    if cfg is None or not any(table in cfg for table in tables):
        path = REPO / DEFAULT_CONFIG_NAME
        cfg = _read_toml(path)
        if cfg is None:
            raise Error(f"missing {path}")
    for key in ("models", "providers"):
        if not isinstance(cfg.get(key), dict):
            raise Error(f"{path}: missing [{key}] table")
    drop_bare_free(cfg)     # one an older removal of its last model left behind
    names = offered(cfg)
    if not names:
        raise Error(f"{path}: no [models.*] entry names a provider with a [providers.*] table")
    tiers = cfg.pop("tiers", None)
    if isinstance(tiers, dict):
        if "pace_margin" in tiers:
            cfg.setdefault("pace_margin", tiers["pace_margin"])
        first, rest = tiers.get("A"), tiers.get("B")
        if "defaults" not in cfg and isinstance(first, list) and first and isinstance(rest, list):
            cfg["defaults"] = {"orchestrator": first[0],
                               "workers": [name for name in rest if name != first[0]]}
    defaults = cfg.setdefault("defaults", {})
    if not isinstance(defaults, dict):
        raise Error(f"{path}: [defaults] must be a table")
    if "within" in cfg and (isinstance(cfg["within"], bool) or not isinstance(cfg["within"], (int, float))
                            or not 0 <= cfg["within"] <= POINTS):
        raise Error(f"{path}: within must be a number of points from 0 to {POINTS} "
                    f"(got {cfg['within']!r})")
    marks = cfg.get("compare")
    if marks is not None and (not isinstance(marks, list)
                              or any(not isinstance(slug, str) for slug in marks)):
        raise Error(f"{path}: compare must list release slugs (compare = [\"acme-pro-5\"]) "
                    f"(got {marks!r})")
    if not isinstance(defaults.setdefault("orchestrator", names[0]), str):
        raise Error(f"{path}: [defaults].orchestrator must be a model name "
                    f"(got {defaults['orchestrator']!r})")
    written = "workers" in defaults        # an empty group nobody wrote is no choice of one
    workers = defaults.setdefault("workers", [])
    if (not isinstance(workers, list) or any(not isinstance(name, str) for name in workers)
            or len(set(workers)) != len(workers)):
        raise Error(f"{path}: [defaults].workers must list distinct model names "
                    f"(got {workers!r})")
    if "reviewers" in defaults:
        reviewers = defaults["reviewers"]
        if (not isinstance(reviewers, list) or not reviewers
                or any(not isinstance(name, str) for name in reviewers)
                or len(set(reviewers)) != len(reviewers)):
            raise Error(f"{path}: [defaults].reviewers must list distinct model names "
                        f"(got {reviewers!r})")
    # [defaults] may name a model removed since by hand: passed over here, as a default nobody
    # named is, and the first model takes a place it empties, so a seat can still start with
    # Enter.
    _fall_back(defaults, names, written)
    hosts = provider_hosts()
    for name, entry in cfg["providers"].items():
        if name in hosts and isinstance(entry, dict):
            # the harness's own provider (listed_providers), whatever an older `+ add` named
            # it: `OpenCode Console` reads `OpenCode`, and the next save writes it so
            entry["name"] = hosts[name]
        listed = entry.get("accounts", []) if isinstance(entry, dict) else []
        # each name is a path component: the adapters keep that account's login under it
        if (not isinstance(listed, list)
                or not all(isinstance(one, str) and HARNESS.fullmatch(one) for one in listed)
                or len(set(listed)) != len(listed)):
            raise Error(f"{path}: [providers.{name}].accounts must list distinct names of "
                        f"letters, digits, '.', '_' and '-' (got {listed!r})")
    return cfg


def offered(cfg):
    """Every model the config offers, each under its harness: each one can orchestrate, and
    each can work.

    A `[models.*]` entry is offered once it names a harness and its provider has a
    `[providers.*]` table; any other stays in the file and out of every choice.  Every list of models reads
    this order -- a harness where its first model is in the file, its models in file order
    under it -- so a model added last still sits with its harness's others on every screen.
    """
    names = [name for name, entry in cfg["models"].items()
             if isinstance(entry, dict) and isinstance(entry.get("harness"), str)
             and isinstance(entry.get("provider"), str) and entry["provider"] in cfg["providers"]]
    harnesses = dict.fromkeys(cfg["models"][name]["harness"] for name in names)
    return [name for harness in harnesses for name in names
            if cfg["models"][name]["harness"] == harness]


def remove_provider(cfg, name):
    """Take one provider out of `cfg`: its table and its models.

    [defaults] passes over its models (passed_over), in the file too once saved.  The last
    provider cannot go, since a config with no model has nothing to start a seat on.  Its usage
    row goes with its table: the menu and `ak usage` list, and probe, only the providers the
    config has.  The caller saves.
    """
    if name not in cfg["providers"]:
        raise Error(f"no provider {name!r}; the config has {', '.join(cfg['providers'])}")
    left = [model for model in offered(cfg) if cfg["models"][model]["provider"] != name]
    if not left:
        raise Error(f"{name} is the last provider with a model; add another before removing it")
    del cfg["providers"][name]
    for model in [model for model, entry in cfg["models"].items()
                  if isinstance(entry, dict) and entry.get("provider") == name]:
        del cfg["models"][model]
    if "defaults" in cfg:
        cfg["defaults"] = passed_over(cfg["defaults"], cfg)
    return cfg


def remove_model(cfg, name):
    """Take one model out of `cfg`, the way remove_provider takes one provider's: [defaults]
    passes over it (passed_over), and the last model cannot go.  Its provider stays, settings
    and all, so another of its models can be added, but a free one, which goes with its last
    (drop_bare_free); a `usage_model` naming it goes, and that usage call falls to the
    provider's first model.  The caller saves.
    """
    left = [model for model in offered(cfg) if model != name]
    if not left:
        raise Error(f"{name} is the last model; add another before removing it")
    provider = cfg["providers"][cfg["models"].pop(name)["provider"]]
    if provider.get("usage_model") == name:
        del provider["usage_model"]
    drop_bare_free(cfg)
    if "defaults" in cfg:
        cfg["defaults"] = passed_over(cfg["defaults"], cfg)
    return cfg


def passed_over(defaults, cfg):
    """`defaults` as load() reads them over `cfg`'s models, the first model left taking a place
    one gone empties; as given while every model they name is there.  save writes them so: a
    removed model's place moves on every screen and in the file alike."""
    left = offered(cfg)
    named = [defaults.get("orchestrator"), *(defaults.get("workers") or []),
             *(defaults.get("reviewers") or [])]
    if not left or all(name in left for name in named):
        return defaults
    defaults = dict(defaults)     # _fall_back puts new lists in, never changing one given
    _fall_back(defaults, left, "workers" in defaults)
    return defaults


def drop_bare_free(cfg):
    """`cfg` without each `mode = "free"` provider no model names: a free provider is nothing
    but its models -- no meter, login or price -- so with none it would be a table no screen
    shows or removes."""
    named = {cfg["models"][name]["provider"] for name in offered(cfg)}
    for name in [name for name, entry in cfg["providers"].items()
                 if isinstance(entry, dict) and entry.get("mode") == "free" and name not in named]:
        del cfg["providers"][name]
    return cfg


def provider_harnesses(cfg, provider):
    """The harnesses `provider` runs on, for the `c` screen's `Models`: the ones its
    models in `cfg` run on, then the ones the shipped default runs it on, each once.  A
    provider neither names a harness for is offered none, never a guess."""
    return list(dict.fromkeys(harness for named, harness in _runs_on(cfg) if named == provider))


def _runs_on(cfg):
    """(provider, harness) of each model in `cfg`, then of each the shipped default has."""
    models = shipped().get("models")
    entries = [*cfg["models"].values(), *(models.values() if isinstance(models, dict) else ())]
    return [(entry.get("provider"), entry["harness"]) for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("harness"), str)]


def provider_hosts():
    """{harness: its name} for each harness that runs any provider it can log in to, as its
    manifest's `[providers] label` says: `+ add a subscription` offers it by that name, then
    each provider its adapter lists (listed_providers)."""
    hosts = {}
    for harness, found in manifests():
        block = found.get("providers")
        if isinstance(block, dict) and isinstance(block.get("label"), str):
            hosts.setdefault(harness, block["label"])
    return hosts


def one_login(harness):
    """True where that harness keeps one login for each provider, as its manifest's `[auth]
    accounts = false` says: no other subscription of a provider can be logged in on it."""
    return (manifest(harness).get("auth") or {}).get("accounts") is False


def signs_in_again(harness, account):
    """False for that harness's usual login (`account` None or DEFAULT_ACCOUNT) where its
    manifest says `[auth] again = false`: its adapter's `login again` cannot sign that one in
    afresh over a login that still stands, so nothing offers it."""
    return (account not in (None, DEFAULT_ACCOUNT)
            or (manifest(harness).get("auth") or {}).get("again") is not False)


def listed_providers(harness):
    """Every provider that harness can log in to, as its adapter's `providers` verb lists them:
    (id, name, mode), the logged-in ones first with their mode, `subscription`, `free` or
    `payg`, and the rest with none.  The one with the harness's own id is the harness's own, named as `+
    add` offers the harness (provider_hosts): OpenCode's is OpenCode, whatever OpenCode calls
    it.  Error, in the adapter's own last words, when it lists none."""
    try:
        proc = run_adapter([str(adapter(harness)), "providers"], timeout=75, env=child_env())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Error(f"{harness} providers: {exc}") from exc
    own = provider_hosts().get(harness)
    rows = [(fields[0], own if own and fields[0] == harness else fields[1], fields[2])
            for fields in (line.split("\t") for line in proc.stdout.splitlines())
            if len(fields) == 3 and fields[0]]
    if proc.returncode or not rows:
        raise Error((proc.stderr.strip().splitlines() or [f"{harness} lists no provider"])[-1])
    return rows


def shipped():
    """The shipped config.default.toml as it parses, {} when it does not: the providers the
    `c` screen's `+ add` offers, each added as it is here."""
    try:
        return _read_toml(REPO / DEFAULT_CONFIG_NAME) or {}
    except Error:
        return {}


def _fall_back(defaults, left, written=True):
    """Keep defaults to models `left`; executors written empty beside reviewers stay empty,
    and a `[defaults]` that never named its executors falls back to the first model."""
    if defaults.get("orchestrator") not in left:
        defaults["orchestrator"] = left[0]
    named = defaults.get("workers") or []
    defaults["workers"] = [model for model in named if model in left] or (
        [] if not named and written and "reviewers" in defaults else [left[0]])
    if "reviewers" in defaults:
        defaults["reviewers"] = [model for model in defaults["reviewers"]
                                if model in left] or [left[0]]


_CATALOGS = {}    # (harness, account): (when that login was asked, what it listed)


def catalog_table(harness):
    """The `[catalog]` table of that harness's manifest, as catalog() returns a list.

    Keyed by model id, in file order, each with its `label` and its `efforts` strongest last;
    written from the harness's own docs or `--help` for one that cannot list its models.
    `efforts = ["none"]` is a model that runs at no effort, and is configured `effort = "none"`;
    an entry that names no efforts is a model whose efforts nobody has said.
    """
    table = manifest(harness).get("catalog")
    if not isinstance(table, dict):
        return []
    return [{"id": model, "label": str(entry.get("label") or model),
             "efforts": [word for word in entry.get("efforts") or [] if isinstance(word, str)]}
            for model, entry in table.items() if isinstance(entry, dict)]


def forget_catalog(harness):
    """Ask that harness's logins for their models afresh next time: a login has just changed
    them."""
    for key in [key for key in _CATALOGS if key[0] == harness]:
        _CATALOGS.pop(key, None)


def _logins(cfg, harness):
    """{account: its providers} for each login whose models are that harness's: every
    subscription (`accounts`) of each provider `cfg` runs there, the usual login of one listing
    none.  The usual login alone without `cfg`, where it runs no provider there, or where the
    harness keeps one login (one_login)."""
    logins = {}
    if cfg and not one_login(harness):
        on = {provider for provider, runs in _runs_on(cfg) if runs == harness}
        for provider in (provider for provider in cfg["providers"] if provider in on):
            for account in accounts(cfg, provider) or [DEFAULT_ACCOUNT]:
                logins.setdefault(account, []).append(provider)
    return logins or {DEFAULT_ACCOUNT: []}


def _listed(harness, account, providers):
    """What one login of that harness lists (catalog), [] for nothing usable."""
    try:
        proc = run_adapter([str(adapter(harness)), "models"], timeout=15,
                           env={**child_env(), **account_env(account), **provider_env(providers)})
        out = proc.stdout if proc.returncode == 0 else ""
    except (Error, OSError, subprocess.TimeoutExpired):
        out = ""
    return [{"id": fields[0], "label": fields[1] or fields[0], "efforts": fields[2].split()}
            for fields in (line.split("\t") for line in out.splitlines())
            if len(fields) == 3 and fields[0]]


def catalog(harness, cfg=None):
    """The models that harness can run: dicts of `id`, `label` and `efforts`, strongest last.

    Each model once, as the first login (_logins: of `cfg`'s subscriptions there) to list it
    says it.  `adapters/<h>.sh models` answers, told the login (account_env, provider_env), one
    `id<TAB>label<TAB>efforts` line per model: live where the harness lists its own, else --
    and when that listing fails or outlasts ten seconds -- from the `[catalog]` table of its
    manifest.  `none` is the one effort of a model that runs at no effort; an empty efforts
    field, a model whose efforts its harness does not say.  Where no login's adapter says
    anything usable, failing or still going after fifteen seconds, that table too.  The logins
    are asked at once, and each answer cached a minute, because a live listing asks the
    harness's server.
    """
    now, logins = time.monotonic(), _logins(cfg, harness)
    asked = [account for account in logins if now - _CATALOGS.get(
        (harness, account), (-CATALOG_TTL, []))[0] >= CATALOG_TTL]

    def ask(account):
        _CATALOGS[harness, account] = (now, _listed(harness, account, logins[account]))
    # threads of its own, never concurrent.futures: importing that registers an exit hook, and
    # config is imported at exit too (a fake adapter writing its hand-in), where that raises
    asking = [threading.Thread(target=ask, args=(account,), daemon=True) for account in asked]
    for thread in asking:
        thread.start()
    for thread in asking:
        thread.join()
    return catalog_held(harness, cfg)


_ASKING = {}      # catalog_now's: the thread asking catalog(), by harness


def catalog_now(harness, cfg=None):
    """catalog(harness, cfg) for a key that is drawn at once: catalog_held once it answers
    within CATALOG_NOW seconds, as a cached one does, or before it has.

    A listing asks the harness itself and can take fifteen seconds, so it goes on in the
    background and the next key reads it.  Only a step on the `c` screen reads this way;
    `ak doctor`, a model id's step and `Models` wait for catalog() as before.
    """
    asking = _ASKING.get(harness)
    if asking is None or not asking.is_alive():
        asking = _ASKING[harness] = threading.Thread(target=_ask_catalog, args=(harness, cfg),
                                                     daemon=True)
        asking.start()
    asking.join(CATALOG_NOW)
    return catalog_held(harness, cfg)


def _ask_catalog(harness, cfg):
    try:
        catalog(harness, cfg)
    except Error:
        pass            # catalog_now falls back to the table, which says the same error


def catalog_held(harness, cfg=None):
    """catalog(harness, cfg) as its logins last listed it, however old, else its manifest's
    table: for a draw, which asks no harness and waits on none."""
    held = {account: listed for (on, account), (_, listed) in list(_CATALOGS.items())
            if on == harness}         # a list: a thread may be adding one
    models = {}
    for account in _logins(cfg, harness) if held else ():    # a draw reads no config for none
        for model in held.get(account, ()):
            models.setdefault(model["id"], model)
    return list(models.values()) or catalog_table(harness)


def efforts(harness, model=None, listing=None):
    """That harness's effort words, in the order the `c` screen cycles them -- or that model's.

    A model's are the first of these to say them: its harness's `listing` (catalog() unless
    given: catalog_now for a key, catalog_held for a draw), its adapter's `[catalog]` row --
    `none` alone for one that runs at no effort -- its adapter's `[effort] levels`, the fixed
    list, which holds every word the shipped defaults use.  Without a model nothing is listed.
    """
    if model is not None:
        for table in ((listing or catalog)(harness), catalog_table(harness)):
            said = next((entry["efforts"] for entry in table
                         if entry["id"] == model and entry["efforts"]), None)
            if said:
                return list(said)
    block = manifest(harness).get("effort")
    levels = block.get("levels") if isinstance(block, dict) else None
    if isinstance(levels, list) and levels and all(
            isinstance(word, str) and word for word in levels):
        return list(levels)
    return list(EFFORTS)


def _toml_key(key):
    if isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _toml_value(value):
    # bool before int: isinstance(True, int) is true and TOML spells them differently.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise Error(f"cannot write {value!r} to {CONFIG_NAME}: not a TOML number")
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        inner = ", ".join(f"{_toml_key(key)} = {_toml_value(item)}"
                          for key, item in value.items())
        return "{" + inner + "}"
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    raise Error(f"cannot write {value!r} to {CONFIG_NAME}: not a TOML value")


def _ordered(items, first):
    """Those pairs in a canonical key order, then whatever else the dict held, in place."""
    led = [pair for key in first for pair in items if pair[0] == key]
    return led + [pair for pair in items if pair[0] not in set(first)]


SAVE_HEADER = ("# agentkit's config, written by the menu's `c` screen. It is rewritten whole on "
               "every change,",
               "# so a comment left here would not survive it; unknown keys are kept as they are.")
_TOP_ORDER = ("max_runs", "max_gates", "min_free_mb", "max_load", "run_memory_max_mb", "pace_margin",
              "within")
_DEFAULTS_ORDER = ("orchestrator", "workers", "reviewers")
_MODEL_ORDER = ("harness", "model", "effort", "exec_effort", "review_effort", "provider",
                "meter", "mode")
_PROVIDER_ORDER = ("mode", "usage_model", "usage_effort")


def _dump_table(path, value, chunks):
    """One TOML table and whatever it holds, appended to chunks; unknown shapes included.

    Tables the schema knows are ordered canonically by the caller; anything else -- a new
    top-level table, a nested table, an array of tables -- is written in place, so a setting
    this writer never heard of still survives a menu edit with its value unchanged.
    """
    if isinstance(value, dict):
        head = "[" + ".".join(_toml_key(part) for part in path) + "]"
        pairs = [(key, item) for key, item in value.items() if not isinstance(item, dict)
                 and not (isinstance(item, list) and any(isinstance(bit, dict) for bit in item))]
        chunks.append([head] + [f"{_toml_key(key)} = {_toml_value(item)}" for key, item in pairs])
        for key, item in value.items():
            if isinstance(item, dict):
                _dump_table([*path, key], item, chunks)
            elif isinstance(item, list) and any(isinstance(bit, dict) for bit in item):
                for bit in item:
                    if not isinstance(bit, dict):
                        raise Error(f"cannot write {CONFIG_NAME}: [{key}] mixes tables and values")
                    head = "[[" + ".".join(_toml_key(part) for part in [*path, key]) + "]]"
                    chunks.append([head] + [f"{_toml_key(k)} = {_toml_value(v)}"
                                            for k, v in bit.items()])
    elif isinstance(value, list) and all(isinstance(bit, dict) for bit in value):
        for bit in value:
            head = "[[" + ".".join(_toml_key(part) for part in path) + "]]"
            chunks.append([head] + [f"{_toml_key(k)} = {_toml_value(v)}"
                                    for k, v in bit.items()])
    else:
        raise Error(f"cannot write {CONFIG_NAME}: [{path[-1]}] is not a table")


def dump(cfg):
    """This config as TOML text: the known tables canonically ordered, the rest in place."""
    for table in ("defaults", "models", "providers"):
        if table in cfg and not isinstance(cfg[table], dict):
            raise Error(f"cannot write {CONFIG_NAME}: [{table}] is not a table")
    chunks = [list(SAVE_HEADER)]
    scalars = [(key, value) for key, value in cfg.items() if not isinstance(value, dict)]
    if scalars:
        chunks.append([f"{_toml_key(key)} = {_toml_value(value)}"
                       for key, value in _ordered(scalars, _TOP_ORDER)])
    if "defaults" in cfg:
        chunks.append(["[defaults]"] + [f"{_toml_key(key)} = {_toml_value(value)}"
                                        for key, value in _ordered(list(cfg["defaults"].items()),
                                                                   _DEFAULTS_ORDER)])
    for table, order in (("models", _MODEL_ORDER), ("providers", _PROVIDER_ORDER)):
        for name, entry in (cfg.get(table) or {}).items():
            if not isinstance(entry, dict):
                raise Error(f"cannot write {CONFIG_NAME}: [{table}.{name}] is not a table")
            chunks.append(["[" + table + "." + _toml_key(name) + "]"] +
                          [f"{_toml_key(key)} = {_toml_value(value)}"
                           for key, value in _ordered(list(entry.items()), order)])
    for key, value in cfg.items():
        if key not in ("defaults", "models", "providers") and isinstance(value, dict):
            _dump_table([key], value, chunks)
    return "\n\n".join("\n".join(chunk) for chunk in chunks) + "\n"


def save(cfg, defaults=None):
    """Write the config back to ~/.agentkit/config.toml, atomically.

    The standard library parses TOML but does not write it, so this is the small writer for
    this schema: the known keys canonically ordered, every unknown key copied through with its
    value unchanged.  The text is built whole before anything is touched, then moved into
    place, so a value that will not write leaves the file it found behind.  The file keeps
    the 0600 install.sh gave it: a replace inherits the temp file's mode, not the old one's.
    `[defaults]` is written as `defaults`, a creation's (remember_defaults), and otherwise as
    the file has it, whatever `cfg` holds, since a menu open for hours holds an older one: a
    model `cfg` no longer has passed over (passed_over).  Every seat first holds the efforts
    the entries load gives it, the shipped default's for a file with none (keep_efforts), so
    none moves with them.
    """
    path = HOME / CONFIG_NAME
    if defaults is None:
        try:
            defaults = (_read_toml(path) or {}).get("defaults")
        except Error:
            defaults = None       # nothing readable to keep: `cfg`'s are written
        if isinstance(defaults, dict):
            defaults = passed_over(defaults, cfg)
    text = dump(cfg if defaults is None else {**cfg, "defaults": defaults})
    try:
        before = load()
    except Error:
        before = None       # no entries readable: no seat had efforts off them to keep
    for name in session_records() if before else ():
        keep_efforts(before, name)
    ensure_dirs()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def model(cfg, name):
    """Resolve a config.toml key to its harness/model/effort/provider dict."""
    entry = cfg["models"].get(name)
    if entry is None:
        known = ", ".join(sorted(cfg["models"]))
        raise Error(f"unknown model {name!r}; ~/.agentkit/config.toml defines: {known}")
    for field in ("harness", "model", "effort", "provider"):
        if field not in entry:
            raise Error(f"~/.agentkit/config.toml: [models.{name}] is missing {field!r}")
    if entry["provider"] not in cfg["providers"]:
        raise Error(f"~/.agentkit/config.toml: [models.{name}].provider={entry['provider']!r} "
                    "has no [providers.*] entry")
    return entry


# The key each role's effort is read from: a seat's is `effort`, which also answers for a model
# that sets neither of the other two
ROLE_EFFORTS = {"orchestrator": "effort", "executor": "exec_effort", "reviewer": "review_effort"}


def role_effort(entry, role):
    """The effort one model entry runs at in a role: `orchestrator`, `executor` (a fixer's turn
    too) or `reviewer`."""
    return entry.get(ROLE_EFFORTS[role], entry["effort"])


def worker_effort(cfg, name, role):
    """The effort the model entry `name` runs `role` at, or None where `name` is no entry."""
    try:
        return role_effort(model(cfg, name), role) if name else None
    except (Error, KeyError):       # no such entry, or a config that configures no models
        return None


def efforts_of(entry):
    """The effort keys (ROLE_EFFORTS) an entry sets, as a record's `efforts` holds a model's."""
    return {key: entry[key] for key in ROLE_EFFORTS.values() if key in entry}


def held_efforts(entry, keys):
    """`entry` with each of `keys` (ROLE_EFFORTS) that follows its effort set to that effort,
    every key it sets kept: a new effort then leaves those where they stood."""
    return {**dict.fromkeys(keys, entry["effort"]), **entry}


def orchestrating_at(models, data, model, effort):
    """Seat record `data`'s efforts with `model`'s orchestrator effort at `effort`, every other
    key kept and one that followed it set where it stood, so its builds and reviews stay as they
    were; a model it holds none for starts from its entry's in `models`."""
    efforts = dict(data.get("efforts") or {})
    own = efforts.get(model) or efforts_of(models[model])
    return {**efforts, model: {**held_efforts(own, ROLE_EFFORTS.values()), "effort": effort}}


def at_efforts(cfg, record):
    """`cfg` as the seat or run `record` runs it: each model its `efforts` names (own_efforts, a
    receipt's every model's as launched) at those, every other at its entry's own."""
    held = (record or {}).get("efforts") or {}
    if not held:
        return cfg      # nothing to run at, and a config of no models stays as it is
    return {**cfg, "models": {
        name: {**{key: value for key, value in entry.items() if key not in ROLE_EFFORTS.values()},
               **held[name]} if name in held and isinstance(entry, dict) else entry
        for name, entry in cfg["models"].items()}}


def run_efforts(cfg, record):
    """What a run's receipt records as `efforts`: every model's, at the seat `record`'s."""
    return {name: efforts_of(entry) for name, entry in at_efforts(cfg, record)["models"].items()
            if isinstance(entry, dict)}


def model_name(cfg, name):
    """The full name every screen shows the configured model `name` by: `Opus 5.5` for one
    running `claude-opus-5-5` -- its harness's catalog label for its id, read off the manifest's
    table so no draw waits on a listing -- else its id, a provider's prefix off
    (`acme-flash-free`).  `name` itself where it is no entry or names no id of its
    own (`default`: the harness picks).
    """
    entry = (cfg.get("models") or {}).get(name)
    if not isinstance(entry, dict) or entry.get("model") in (None, "", DEFAULT_MODEL):
        return name
    return (catalog_label(entry.get("harness") or "", entry["model"])
            or entry["model"].rsplit("/", 1)[-1])


def catalog_label(harness, model):
    """A model's full name, its harness's catalog label for its id, read off the manifest's
    table so no draw waits on a listing; None where the table names it no other way."""
    label = next((row["label"] for row in catalog_table(harness) if row["id"] == model), None)
    return label if label != model else None


def normalize_session(name):
    """Whitespace has the same spelling at creation, lookup and in rename pointers."""
    return " ".join(name.split()) if isinstance(name, str) else name


# Every file a seat owns under STATE is `<kind>-<seat>.<ext>`, named here and nowhere else: a
# rename moves them, a stop and the daily collector find them by this table.  Its locks and
# temporaries share the stem.
SEAT_FILES = {
    "log": "txt",        # left by the retired prose-question reader; goes with its seat
    "session": "json",   # the seat's record, or a pointer a rename left at an old name
    "notify": "json",    # the last notification it sent, for the menu's state column
    "card": "json",      # its notification transition latch
    "seat": "json",      # its last classified live state and since when
    "hook": "json",      # what its harness's own lifecycle hooks say it is doing
    "plan": "md",        # its plan, which the menu row reads its bar from
    "stop": "json",      # this turn's start, for the stop hook's rule
    "live": "txt",       # when its own ssh last reached the live host (`guard.live_reach`)
    "title": "json",     # the title last read from its conversation
    "input": "jsonl",    # each line ak typed, with its source and conversation
    "rulebook": "md",    # the rulebook its orchestrator was started on
    "verify": "lock",    # held by one verification of its plan at a time (`plan.verifying`)
    "nextverify": "lock",    # held by the delivered run next in line for it (`plan.verify_delivered`)
    # left by the prompts that named a rulebook to read, before they carried it: goes with its
    # seat, and a change may still be told against it (`orch.rulebook_change`)
    "rules": "md",
    "change": "md",      # rulebook news too long for its prompt, which names it (`orch.rulebook_pointer`)
    "held": "md",        # the rulebook its conversation was last handed
    "launch": "sh",      # the command a pane runs, until it starts: one per launch, `.sh` a token (`orch.seat_command`)
    "refused": "txt",    # its screen when it read at its prompt yet took no line (`watch.untyped`)
    "handover": "md",    # what moves to another harness handed it of its conversation (`orch.handover`)
    # written by nothing since seats stopped messaging one another: named so a stop and the daily collector still
    # take the queues a host holds from before, as they take every other file of a gone seat
    "tell": "json",
}


def session_path(name):
    """The state file for one tmux session, whose name must stay a single path component."""
    name = normalize_session(name)
    if not isinstance(name, str) or not name or Path(name).name != name or name in (".", ".."):
        raise Error(f"invalid {SESSION_ENV} name {name!r}")
    return _self.STATE / f"session-{name}.json"


def seat_file(kind, name):
    """The seat's file of one SEAT_FILES kind; raises Error for a name session_path refuses."""
    return session_path(name).with_name(f"{kind}-{normalize_session(name)}.{SEAT_FILES[kind]}")


def seat_files(kind):
    """(seat, path) for every file of one SEAT_FILES kind, in name order."""
    head, tail = f"{kind}-", f".{SEAT_FILES[kind]}"
    try:
        names = parsed.read(_self.STATE, os.listdir)
    except OSError:
        return []       # no state yet, or none to list
    return [(name[len(head):-len(tail)], _self.STATE / name) for name in sorted(names)
            if name.startswith(head) and name.endswith(tail)]


def seat_file_owner(path):
    """(kind, seat) for a `<kind>-<seat>.<anything>` file of a SEAT_FILES kind, None otherwise."""
    stem, dot, ext = Path(path).name.rpartition(".")
    kind, sep, name = stem.partition("-")
    return (kind, name) if dot and ext and sep and name and kind in SEAT_FILES else None


def notify_path(name):
    """Where the last notification a session sent is kept, for the menu's state column."""
    return seat_file("notify", name)


def card_path(name):
    """Where the per-session notification transition latch is kept."""
    return seat_file("card", name)


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json(path, shared=False):
    """The file's JSON, None for no file; `shared` is what it held when last parsed while it
    has not changed since (`parsed`), every reader's, so its caller only reads it."""
    try:
        return parsed.read(path, _json) if shared else _json(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise Error(f"cannot read {path}: {exc}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Error(f"{path}: {exc}")


def resolve_session(name):
    """The name a session goes by now.

    `ak orch rename` leaves `{"renamed": "<new>"}` behind in the old state file, because the
    orchestrator that was started under the old name still carries it in $AGENTKIT_SESSION and
    hands it to every `ak` it runs.  Following the chain here means those calls keep landing on
    the right selection, and the right menu row, after the rename.
    """
    name = normalize_session(name)
    # User-entered names are slugged by the seat launcher. Keep existing literal names,
    # including legacy tmux seats, but accept the same whitespace at lookup as at creation.
    if isinstance(name, str) and " " in name and not session_path(name).exists():
        from . import orch
        name = orch.session_name(name)
    seen = [name]
    for _ in range(RENAME_HOPS + 1):    # RENAME_HOPS renames, then the name after the last
        data = _read_json(session_path(name), shared=True)
        if not isinstance(data, dict) or not isinstance(data.get("renamed"), str):
            return name
        name = normalize_session(data["renamed"])
        if name in seen:
            raise Error(f"{session_path(seen[0])}: the rename chain loops through {' -> '.join(seen)}")
        seen.append(name)
    raise Error(f"{session_path(seen[0])}: more than {RENAME_HOPS} renames deep")


def current_session():
    """The session this process runs in, by its current name, or None outside a seat."""
    name = os.environ.get(SESSION_ENV)
    return resolve_session(name) if name else None


INBOX_ENV = "AGENTKIT_INBOX_SESSION"


def inbox():
    """The seat other people's PRs are offered in and merged from (`ak watch`); a test points it
    elsewhere.  One home: the gh shim lets this seat's `gh pr merge` through, and watch asks it."""
    return os.environ.get(INBOX_ENV) or "inbox"


def check_stop_owner(owner):
    """A seat stops only its own work; the owner outside a seat may stop anything."""
    caller = current_session()
    if caller and isinstance(owner, str) and owner:
        owner = resolve_session(owner)
        if owner != caller:
            raise Error(f"owned by seat {owner}; a seat stops only its own runs")


def _validate_session(cfg, name, data, prune=False):
    if not isinstance(data, dict):
        raise Error(f"{session_path(name)}: expected a JSON object")
    orchestrator = data.get("orchestrator")
    if not isinstance(orchestrator, str):
        raise Error(f"{session_path(name)}: orchestrator must be a model name")
    # A record read back passes over a model the config no longer has, the way `load`
    # passes over one in [defaults]: models are renamed and removed while seats built on
    # them are still open, and the seat goes on with what is left.  The orchestrator's
    # name is kept as recorded -- an open seat is still running it, and picking another
    # moves the seat -- and a group emptied by the passing over takes the first model
    # left, as an emptied default does.  A name still in [models.*] is not removed, so
    # its entry is judged here, and the lists as recorded are judged before any passing
    # over: a record already invalid stays invalid.  A session being saved is checked whole.
    left = offered(cfg) if prune else []
    if not prune or orchestrator in cfg["models"]:
        try:
            model(cfg, orchestrator)
        except Error as exc:
            raise Error(f"{session_path(name)}: {exc}") from None
    groups = {}
    for role in ("workers", "reviewers"):
        if role == "reviewers" and role not in data:
            continue
        listed = data.get(role)
        # no executor is a choice once reviewers are named: the orchestrator builds everything
        empty_ok = role == "workers" and "reviewers" in data
        if (not isinstance(listed, list) or not (listed or empty_ok)
                or any(not isinstance(worker, str) for worker in listed)):
            raise Error(f"{session_path(name)}: {role} must be a non-empty list of model names")
        for worker in listed:
            if prune and worker not in cfg["models"]:
                continue
            try:
                model(cfg, worker)
            except Error as exc:
                raise Error(f"{session_path(name)}: {exc}") from None
        if len(set(listed)) != len(listed):
            raise Error(f"{session_path(name)}: {role} contains duplicates")
        groups[role] = listed
    if prune:
        if left:
            normalized = {"orchestrator": orchestrator, **groups}
            _fall_back(normalized, left)
            groups = {role: normalized[role] for role in groups}
        # judge what is handed back: a fallen-back name was not listed above, and with
        # nothing left a gone name has nowhere to fall back to
        for listed in groups.values():
            for worker in listed:
                try:
                    model(cfg, worker)
                except Error as exc:
                    raise Error(f"{session_path(name)}: {exc}") from None
    efforts = data.get("efforts", {})
    if not isinstance(efforts, dict) or any(not isinstance(held, dict) or not isinstance(
            held.get("effort"), str) for held in efforts.values()):
        raise Error(f"{session_path(name)}: efforts must give each model its effort")
    # the orchestrator's own model may work for it too: nothing here excludes one from the other
    # Whatever else the record carries -- where the seat ran, when, and the conversation the
    # harness kept -- is handed back untouched: only the model fields are this file's to judge.
    return {**data, "orchestrator": orchestrator, **groups}


def record_lock_path(path):
    """The file a seat record's writers lock (`_record_lock`)."""
    return path.with_name(f".{path.stem}.lock")


@contextmanager
def _record_lock(path):
    """One writer at a time for a record, a seat's or the logins kept: each reads, merges and
    replaces the whole file, and they share the one temporary file beside it.  Always taken
    last, inside any other lock, and held only for that write (the logins' across their asks,
    which take none), so it orders with nothing."""
    with record_lock_path(path).open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _write_json(path, data, prepare=True):
    if prepare:
        ensure_dirs()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def save_session(cfg, name, orchestrator, workers, extra=None):
    """Atomically record the models selected for a newly created session, and where it runs.

    `extra` is what the seat is besides its models -- its directory, the moment it was created,
    the harness conversation it holds -- because a record has to say enough to open the seat
    again once tmux is no longer holding it. New seats inherit explicit default reviewers;
    loading an older record never adds them.
    """
    reviewers = cfg.get("defaults", {}).get("reviewers")
    selection = _validate_session(cfg, name, {"orchestrator": orchestrator, "workers": workers,
                                              **({"reviewers": list(reviewers)}
                                                 if reviewers is not None else {}),
                                              **(extra or {})})
    selection = own_efforts(cfg["models"], name, selection)
    ensure_dirs()
    with _record_lock(session_path(name)):
        _write_json(session_path(name), selection, prepare=False)
    return selection


def discard_session(name, created):
    """Remove `name`'s record only while it is still the one saved at `created`: a launch that
    failed takes back its own record, never one another launch saved under the name since."""
    path = session_path(name)
    if not path.parent.is_dir():
        return
    with _record_lock(path):
        try:
            data = _read_json(path)
        except Error:
            return      # unreadable is not known to be its own
        if isinstance(data, dict) and data.get("created") == created:
            path.unlink(missing_ok=True)


def remember_defaults(record, models=None):
    """[defaults] as `record` has them: what the next `n` starts from, and the one write of
    them (save), the `[models.*]` tables as `models` has them in the same write where given.
    The file is read again first, so nothing else changed in it since is written back over, and
    one holding them already is not written; a failed write keeps it as it was and says why,
    else ""."""
    defaults = {key: record[key] for key in _DEFAULTS_ORDER if key in record}

    def meant(table):     # reviewers it leaves out are its workers
        return {"reviewers": table.get("workers"), **table} if isinstance(table, dict) else None
    try:
        if models is None and meant((_read_toml(HOME / CONFIG_NAME) or {}).get(
                "defaults")) == meant(defaults):
            return ""
        cfg = load()
        # a file from before it held the models (max_runs alone) loads as the shipped one: its
        # own keys are written back over the shipped ones, as they were
        cfg.update((key, value) for key, value in (_read_toml(HOME / CONFIG_NAME) or {}).items()
                   if key not in ("defaults", "tiers", "models", "providers"))
        if models is not None:
            cfg["models"] = models
        save(cfg, defaults)
    except (Error, OSError) as exc:
        return str(exc)     # a seat is made all the same
    return ""


def update_session(name, **fields):
    """Merge fields into an existing session record; a session with no record is left alone.

    A seat somebody made by hand (`tmux new`) has no record and gets none here: it is listed
    from tmux, not from this directory, and inventing a file for it would only claim to know
    things -- which models, which conversation -- that nobody ever chose.  A field given as
    None is removed rather than written, except for repo: null records a deliberate lack of
    project, so old-record inference does not run again.
    """
    path = session_path(name)
    if not path.parent.is_dir():
        return None
    # read and written under the record's lock: a concurrent writer of other fields
    # never writes back the record as it was before this one
    with _record_lock(path):
        data = _read_json(path)
        if not isinstance(data, dict) or "renamed" in data:
            return None
        if all(data.get(key) == value and (key != "repo" or key in data)
               for key, value in fields.items()):
            return data
        for key, value in fields.items():
            if value is None and key != "repo":
                data.pop(key, None)
            else:
                data[key] = value
        if fields.keys() & {"orchestrator", "workers", "reviewers"}:
            try:        # a model the seat takes on runs at its entry's efforts as of now
                data = own_efforts(load()["models"], name, data)
            except Error:
                pass
        # The record's directory already exists. In particular, project inference while
        # listing seats must not prepare or change metadata on run/worktree directories.
        _write_json(path, data, prepare=False)
    return data


def change_efforts(name, change):
    """Seat `name`'s `efforts` as `change` makes them of its record as it stands, read, changed
    and written under the record's lock, so no other writer's step is lost or undone: the
    record as written, or None for a seat with no record."""
    path = session_path(name)
    with _record_lock(path):
        data = _read_json(path)
        if not isinstance(data, dict) or "renamed" in data:
            return None
        efforts = change(data)
        if efforts != data.get("efforts"):
            data["efforts"] = efforts
            _write_json(path, data, prepare=False)
    return data


def own_efforts(models, name, data):
    """Seat `name`'s record `data` holding the efforts of each model it runs: one it holds none
    for takes its entry's in `models`, the defaults, once -- at the seat's creation, a model
    added to it, or before the entries change (save), a read holding them for itself alone --
    so an entry changed since moves no seat.  The weekly audit's seat, whose models are
    [audit]'s, goes on with the entries'."""
    from . import audit     # here, not at the top: audit imports this module
    held = data.get("efforts") or {}
    runs = [data.get("orchestrator"), *(data.get("workers") or ()), *(data.get("reviewers") or ())]
    taken = {model: efforts_of(models[model]) for model in runs if isinstance(model, str)
             and isinstance(models.get(model), dict) and model not in held}
    if not taken or normalize_session(name) == resolve_session(audit.NAME):
        return data
    return {**data, "efforts": {**held, **taken}}


def keep_efforts(cfg, name):
    """own_efforts of `cfg` for seat `name`'s record as it stands, read as load_session reads
    it (a fallen-back worker's too), under its lock (change_efforts)."""
    def kept(data):
        try:
            return own_efforts(cfg["models"], name, _validate_session(
                cfg, name, data, prune=True)).get("efforts")
        except Error:
            return data.get("efforts")      # a record that will not read is left as it is
    return change_efforts(name, kept)


def _session_file(path, record):
    """What a session file holds where it is a record (`record`) or else a rename pointer, None
    for no file, the other kind or neither; shared (`_read_json`): only read."""
    try:
        data = _read_json(path, shared=True)
    except Error:
        return None
    return data if isinstance(data, dict) and ("renamed" not in data) == record else None


def _session_files(record):
    """(name, contents) for every session file that is a record (`record`) or a rename pointer."""
    for name, path in seat_files("session"):
        data = _session_file(path, record)
        if data is not None:
            yield name, data


def session_records():
    """{name: record} for every session file that is a record rather than a rename pointer."""
    return dict(_session_files(record=True))


def session_record(name):
    """`session_records().get(name)`, read from that seat's file alone."""
    try:
        path = session_path(name)
    except Error:
        return None             # a name no session file has
    return _session_file(path, record=True)


def session_aliases():
    """{old name: where it leads} for the pointers `ak orch rename` left behind.

    An alias is not a free name while it leads anywhere: the orchestrator renamed under it still
    carries the old name in $AGENTKIT_SESSION and hands it to every `ak` it runs, so a new seat
    taking that name would take those calls with it.  A chain that loops or runs too deep leads
    to itself here, which is the caller's cue that it is no name to hand out either.
    """
    found = {}
    for name, _ in _session_files(record=False):
        try:
            found[name] = resolve_session(name)
        except Error:
            found[name] = name
    return found


def load_session(cfg, name, required=True):
    """Read a session selection, following renames; optionally tolerate no file.

    A model the config no longer has is passed over in what comes back
    (_validate_session), so a seat whose models changed under it still reads; the file
    itself is left as it was, each model read here at the efforts it holds or else its entry's
    (own_efforts): a dry run or a tick's read writes nothing.
    """
    name = resolve_session(name)
    path = session_path(name)
    data = copy.deepcopy(_read_json(path, shared=True))     # its caller's own to change
    if data is None:
        if not required:
            return None
        raise Error(f"{SESSION_ENV}={name!r}, but {path} does not exist")
    return own_efforts(cfg["models"], name, _validate_session(cfg, name, data, prune=True))


def rename_session(old, new):
    """Move the selection to its new name and leave a pointer at the old one."""
    target = resolve_session(new)
    if target not in (old, new):
        raise Error(f"{new!r} points at another session; pick a name that is not a rename")
    ensure_dirs()
    if target == new:
        # a free name: the plan a gone seat left there, or under a name still leading there,
        # is not this seat's
        from . import plan
        plan.forget(new)
    # under both records' locks: a field written to the old one meanwhile moves with it
    with _record_lock(session_path(old)), _record_lock(session_path(new)):
        selection = _read_json(session_path(old))
        if isinstance(selection, dict) and "renamed" not in selection:
            _write_json(session_path(new), selection, prepare=False)
        elif target == old:
            # A legacy seat has no selection to overwrite its former pointer with.
            session_path(new).unlink(missing_ok=True)
        _write_json(session_path(old), {"renamed": new}, prepare=False)
    # Every older name of this seat leads to `old`, straight or through its other old names: it
    # points at `new` now, so no chain passes one rename however often a seat is renamed (its
    # title follows the conversation), and a chain left deeper than a walk follows recovers.
    pointers = {name: normalize_session(data["renamed"])
                for name, data in _session_files(record=False)
                if isinstance(data.get("renamed"), str)}
    for name, leads in pointers.items():
        seen, step = {name}, leads
        while step != old and step in pointers and step not in seen:
            seen.add(step)
            step = pointers[step]
        if step != old:
            continue
        with _record_lock(session_path(name)):
            try:
                pointer = _read_json(session_path(name))
            except Error:
                continue
            if isinstance(pointer, dict) and normalize_session(pointer.get("renamed")) == leads:
                _write_json(session_path(name), {"renamed": new}, prepare=False)
    # The running orchestrator keeps reading the rulebook it was started on, its hooks keep the
    # turn's latch and its ssh shim the turn's live reach under the name it was started with,
    # and a pane still starting reads the launch file it was given.  Back to a name it had, what the
    # seat wrote under it since is kept rather than moved over: a seat renamed still writes its
    # plan under the name it was launched with, and `plan.path` reads the plan under every name
    # the seat had, the newest one winning.
    for kind in SEAT_FILES.keys() - {"session", "rulebook", "stop", "live", "launch"}:
        was, now = seat_file(kind, old), seat_file(kind, new)
        if kind == "handover" and was.exists():
            # the rulebook it runs on names it under the old name, and a move only adds to it:
            # a copy keeps that one readable, the newest whole under the new name
            copied = now.with_name(f"{now.name}.{os.getpid()}.tmp")
            copied.write_bytes(was.read_bytes())
            copied.replace(now)
        elif was.exists() and not (target == old and now.exists()):
            was.replace(now)


def active_session(cfg):
    """The active session selection, or None outside an orchestrator's environment."""
    name = current_session()
    if not name:
        return None
    selection = load_session(cfg, name, required=False)
    return {"name": name, **selection} if selection else None


def server_alias():
    """The ssh alias of the server, which install.sh records on a client and nowhere else."""
    try:
        return (_self.STATE / "server").read_text().strip() or None
    except OSError:
        return None


def live_host():
    """The ssh alias of the live product host a seat must not write to by hand, from `live_host` in
    config.toml, or None when the owner has set none.  The deploy host is each owner's own -- ak ships
    with no alias for it, so it guards none until the owner names theirs; this is not `server_alias`
    (the ak coordination server), and a file reaches the live host through the repo, never a seat's
    scp/rsync/sftp."""
    try:
        with (HOME / CONFIG_NAME).open("rb") as fh:
            alias = tomllib.load(fh).get("live_host")
    except (OSError, ValueError):
        return None
    return alias or None


def suite_helper():
    """The ssh alias of the machine that runs suite pieces beside this one (agentkit/helper.py),
    from `suite_helper` in config.toml, or None when the owner has named none."""
    try:
        with (HOME / CONFIG_NAME).open("rb") as fh:
            alias = tomllib.load(fh).get("suite_helper")
    except (OSError, ValueError):
        return None
    return alias if isinstance(alias, str) and alias else None


def workers(cfg):
    """The session's selection, else the default workers."""
    session = active_session(cfg)
    return session["workers"] if session else list(cfg["defaults"]["workers"])


def reviewers(cfg):
    """An omitted reviewer selection uses that same record's workers, never another seat's."""
    selection = active_session(cfg) or cfg["defaults"]
    return list(selection.get("reviewers", selection["workers"]))


def audit(cfg):
    """The weekly audit's setting, `[audit]` in config.toml: whether it runs (`on`, true until
    written false) and the models its seat takes, `orchestrator`, `workers` and `reviewers`,
    each `[defaults]`'s where the table leaves it out.  A name no `[models.*]` entry offers,
    or an empty reviewer list, is an Error naming it, so the `c` row and the tick say the same
    thing."""
    table = cfg.get("audit", {})
    if not isinstance(table, dict):
        raise Error(f"~/.agentkit/{CONFIG_NAME}: [audit] must be a table")
    defaults = cfg["defaults"]
    on = table.get("on", True)
    if not isinstance(on, bool):
        raise Error(f"~/.agentkit/{CONFIG_NAME}: [audit].on must be true or false (got {on!r})")
    setting = {"on": on, "orchestrator": table.get("orchestrator", defaults["orchestrator"]),
               "workers": table.get("workers", defaults["workers"]),
               "reviewers": table.get("reviewers", defaults.get("reviewers", defaults["workers"]))}
    for role in ("workers", "reviewers"):
        names = setting[role]
        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
            raise Error(f"~/.agentkit/{CONFIG_NAME}: [audit].{role} must list model names "
                        f"(got {names!r})")
        setting[role] = list(names)
    if not isinstance(setting["orchestrator"], str):
        raise Error(f"~/.agentkit/{CONFIG_NAME}: [audit].orchestrator must be a model name "
                    f"(got {setting['orchestrator']!r})")
    if not setting["reviewers"]:
        raise Error(f"~/.agentkit/{CONFIG_NAME}: [audit].reviewers must name a model")
    for name in (setting["orchestrator"], *setting["workers"], *setting["reviewers"]):
        model(cfg, name)
    return setting


def role_groups(cfg, workers=None, reviewers=None):
    """Bind unbound picks only for explicit reviewers; preserve absence for legacy overrides."""
    if workers is None:
        selection = active_session(cfg) or cfg["defaults"]
        if "reviewers" in selection:
            workers = selection["workers"]
            if reviewers is None:
                reviewers = selection["reviewers"]
    return workers, reviewers


def adapter(harness):
    """adapters/<harness>.sh, the script that runs one harness: the adapter contract.

    A harness is that script, adapters/<harness>.toml beside it (`manifest`), a `[models.<name>]`
    naming it and its `[providers.<name>]`; Python it needs goes in agentkit/harness/<harness>.py.
    tests/fixtures/adapters/echo.sh and echo.toml are a working pair, and $AGENTKIT_ADAPTER_DIR
    names another directory of adapters, which is how the offline suites run with no model.

    It has three duties: hand the worker the prompt as written, let it close its turn with
    `ak hand-in done`, and return `final.md` and a `session_id` a second turn resumes; ak ends
    whatever a turn leaves running.  `python3 tests/check_harness_contract.py [harness]` proves
    them on each harness installed with a login, at the model and effort its `[check]` names.
    The verbs:

    run <model> <effort> <workspace> <prompt> <out> [<session>]
        one headless turn; the prompt goes from its file or stdin, never as one argument, which
        Linux caps at 128 KiB; writes final.md (the turn's last message), session_id,
        stderr.log and events.jsonl.
    interactive <model> <effort> [<session> [new]]
        the seat's command line, with the harness's own bypass flag.  It hands the harness the
        rulebook $AGENTKIT_RULEBOOK names, else the file `python3 tools/rulebook.py
        "$AGENTKIT_SESSION"` writes and prints, adding no instructions of its own, so an
        orchestrator behaves one way whatever runs it; anything else it writes goes beside that
        file.  With `[launch] first_prompt = true` it puts a non-empty $AGENTKIT_FIRST_PROMPT
        on that line as one single-quoted word, for a new conversation and a resumed one alike.
    usage
        one JSON object of meters, `error` set rather than a non-zero exit, and `credits`, the
        bought credits left where the provider has them, in `currency` where they are money.
    auth [seat]
        one line and never a network call: exit 0 with a token, ending `; logged in as <who>`
        where it can tell, or 1 with why not.
    models
        an `id<TAB>label<TAB>efforts` line per model, efforts strongest last, `none` for one
        that runs at no effort, empty where the harness does not say; `[catalog]` stands in for
        a harness that lists none, fails, or takes ten seconds.
    hooks / install / login [again] / logout
        install its lifecycle hooks idempotently; install it and log in on a fresh box, `again`
        signing in afresh over a login that still stands; sign that login out on this machine,
        0 at once where it holds none, touching no other login nor a store they share.
    forget
        a harness that keeps more than one login: every file of $AGENTKIT_ACCOUNT's own removed,
        a link among them but never what it leads to; the usual login refused.
    login-end
        one JSON object: `email`, and `ends`, the epoch second the login stops serving, or null.
    lend <home>
        a copy of that login where a turn run with HOME=<home> reads it, holding nothing whose
        use renews the login (`tools/lend.py` places it); prints the epoch second it stops
        authenticating, nothing where it never does, or exits 1 with why there is none.
    providers
        a harness that runs any provider it can log in to: an `id<TAB>name<TAB>mode` line each,
        those it can run first with `subscription` or `payg`, the rest with no mode.
    reset-status / reset
        optional, where the provider hands out usage-limit resets.

    `usage`, `auth`, `login` and `lend` are told the providers they answer for in
    $AGENTKIT_PROVIDER, space-separated; a harness that runs one provider may ignore it.  Each
    manifest table is explained at the code that reads it.
    """
    path = adapter_path(harness)
    if not path.exists():
        raise Error(f"no adapter for harness {harness!r}: {path} does not exist")
    if not os.access(path, os.X_OK):
        raise Error(f"adapter {path} is not executable; chmod +x it")
    return path


def adapter_path(harness):
    """Where `adapter` looks for that harness's script, there or not."""
    return Path(os.environ.get(ADAPTER_DIR_ENV) or REPO / "adapters").expanduser() / f"{harness}.sh"


def run_adapter(argv, timeout, env=None):
    """`subprocess.run` of one adapter call, its output captured as text and its stdin empty,
    except that the call runs in a process group of its own, in ak's session, and that past
    `timeout`, or on anything else that ends the wait, `_end` kills what it runs."""
    with subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env, process_group=0, encoding="utf-8",
                          errors="replace") as proc:
        try:
            out, err = proc.communicate(timeout=timeout)
        except BaseException:
            _end(proc.pid)
            raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def _end(pid):
    """KILL that adapter call, every process below it still in ak's session and each group one
    of those leads -- `timeout` makes one for itself, and a CLI under it may catch TERM --
    then wait up to a second for them to go.

    No process below the call leads ak's own group, which the menu shares with its terminal, so
    no group kill reaches it; one below the call that joined it is killed on its own.  A process
    in a session of its own is never killed: that is a harness's own service, which an adapter
    call starts on purpose, and everything below it is in that session too.  What has left the
    call's tree and its groups by now is the leftover sweep's.
    """
    parents, below = host.parents(), {}
    for child, parent in parents.items():
        below.setdefault(parent, []).append(child)
    tree, stack = [], [pid]
    while stack:
        if (current := stack.pop()) not in tree:
            tree.append(current)
            stack.extend(below.get(current, ()))
    ours = [member for member in tree if _session(member) == os.getsid(0)]
    groups = {member for member in ours if _group(member) == member}
    for kill, targets in ((os.killpg, groups), (os.kill, ours)):
        for target in targets:
            try:
                kill(target, signal.SIGKILL)
            except OSError:
                pass
    killed = {*ours, *(other for other in parents if _group(other) in groups)}
    deadline = time.monotonic() + 1
    while killed & host.parents().keys() and time.monotonic() < deadline:
        time.sleep(.01)


def _session(pid):
    try:
        return os.getsid(pid)
    except OSError:
        return None   # gone


def _group(pid):
    try:
        return os.getpgid(pid)
    except OSError:
        return None   # gone


_MANIFESTS = {}


def manifest(harness):
    """adapters/<harness>.toml: everything agentkit knows about that harness's screen.

    Beside the adapter script, and read the same way -- $AGENTKIT_ADAPTER_DIR first -- except
    that a directory of fake adapters replaces the model calls, not the screen knowledge, so a
    missing file there falls back to this checkout's own.  A harness with no manifest reads as
    an empty one: nothing is recognised on its screen, and nothing is typed into it.
    Cached by path and mtime, because it is read on every menu draw and every watch tick.
    """
    if not isinstance(harness, str) or not HARNESS.fullmatch(harness):
        return {}
    override = os.environ.get(ADAPTER_DIR_ENV)
    roots = [Path(override).expanduser(), REPO / "adapters"] if override else [REPO / "adapters"]
    for root in roots:
        path = root / f"{harness}.toml"
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            continue
        cached = _MANIFESTS.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        try:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise Error(f"{path}: {exc}")
        _MANIFESTS[path] = (stamp, data)
        return data
    return {}


def seat_env_names():
    """The variables a launch sets for its seat alone, as the adapter manifests declare them.

    `[launch] seat_env` in adapters/<h>.toml names what a harness is told when its seat opens
    and what nothing that seat starts may be told -- where this seat's rulebook is, say.  A
    worker, a done-when command, or a second harness started from that seat would otherwise be
    working to the orchestrator's rules instead of its own role's.  The names come from the
    manifests because nothing here knows one harness from another, let alone what it calls its
    own variables; the manifests themselves are cached by mtime.
    """
    names = set()
    for _, data in manifests():
        block = data.get("launch")
        if isinstance(block, dict):
            names.update(n for n in block.get("seat_env") or [] if isinstance(n, str))
    return names


def state_env_names():
    """State roots declared by any adapter follow the caller into a seat and its menu."""
    names = set()
    for _, data in manifests():
        block = data.get("worker") or {}
        for field in ("state", "logins"):
            for path in block.get(field) or []:
                found = re.match(r"^\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))", path)
                if found:
                    names.add(found[1] or found[2])
    return names


def manifests():
    """Every adapter manifest, as (harness, manifest), from the same places `manifest` reads."""
    override = os.environ.get(ADAPTER_DIR_ENV)
    roots = [Path(override).expanduser(), REPO / "adapters"] if override else [REPO / "adapters"]
    for root in roots:
        try:
            paths = sorted(root.glob("*.toml"))
        except OSError:
            continue
        for path in paths:
            yield path.stem, manifest(path.stem)


def harness_name(harness):
    """What a screen calls that harness: its manifest's `name`, else its id."""
    try:
        name = manifest(harness).get("name")
    except Error:
        name = None
    return name if isinstance(name, str) and name else harness


def harness_colour(harness):
    """What a screen draws that harness's name in: its manifest's `colour`, `#RRGGBB`, else
    None."""
    try:
        own = manifest(harness).get("colour")
    except Error:
        own = None
    return own if isinstance(own, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", own) else None


def instruction_ceiling():
    """The most of a project's AGENTS.md every harness reads on its own, and whose limit it is.

    `[instructions] read_limit` in adapters/<h>.toml is how many bytes that harness reads of
    the file before it drops the rest unannounced.  The smallest wins: a project's file has to
    reach every harness whole, ak's prompts and a harness opened in the checkout alike.  None
    when no manifest declares one, and then nothing limits the file's size.
    """
    limits = []
    for harness, data in manifests():
        block = data.get("instructions")
        limit = block.get("read_limit") if isinstance(block, dict) else None
        if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
            limits.append((limit, harness))
    return min(limits) if limits else None


def manifest_paths(names, env, cwd=None):
    """Manifest paths resolved for `env`, the environment the harness runs in: `~/` is its home,
    `$VARIABLE` and `${VARIABLE:-default}` its variables, and an unset or empty one with no
    default skips that path; a relative path is under `cwd`."""
    values = {key: value for key, value in env.items() if value}
    values.setdefault("HOME", str(Path.home()))
    for name in names:
        name = re.sub(r"\$\{(\w+):-([^}]*)\}", lambda m: values.get(m[1]) or m[2], name)
        if name.startswith("~/"):
            name = "$HOME/" + name[2:]
        try:
            path = Path(Template(name).substitute(values))
        except KeyError:
            continue
        yield path if path.is_absolute() else Path(cwd or os.getcwd()) / path


def unswitched_files(harness, env):
    """The files and folders under the home that this harness reads on its own and that its
    adapter cannot switch off: `[instructions] unswitched` in adapters/<h>.toml, resolved for
    `env` as `manifest_paths` does, so an account's own home is looked in where the adapter
    keeps one.  An `env` naming no account looks in the usual homes too: there an adapter drops
    an account's home a seat handed down.  A seat opens only while none of them exists, since
    nothing but its rulebook may instruct it; a worker's box hides each from its turn, and the
    live contract check plants a word to prove it."""
    block = manifest(harness).get("instructions")
    paths = block.get("unswitched") if isinstance(block, dict) else None
    paths = [p for p in paths or [] if isinstance(p, str) and p[:1] in "~$"]
    found = list(manifest_paths(paths, env))
    if not env.get(ACCOUNT_ENV):
        found += [p for p in manifest_paths(paths, {"HOME": env.get("HOME")}) if p not in found]
    return found


def workspace_rules(harness):
    """The instruction files and folders this harness loads from the checkout it works in, with
    no switch to stop it: `[instructions] workspace` in adapters/<h>.toml, named relative to the
    checkout.  Such a harness never reviews: it would judge a branch by the rules the branch
    itself wrote (`staffing.barred_reviewer`)."""
    block = manifest(harness).get("instructions")
    names = block.get("workspace") if isinstance(block, dict) else None
    return [name for name in names or [] if isinstance(name, str) and name]


def seat_state_path(name):
    """Where the seat's last classified live state and its `since` are kept."""
    return seat_file("seat", name)


def hook_facts_path(name):
    """Where a harness's own lifecycle hooks write what that seat is doing."""
    return seat_file("hook", name)


def record_hook_fact(name, fact, keep=lambda standing: False):
    """Put that lifecycle fact in place of the seat's last one, unless the one standing was
    heard later or `keep(standing)` keeps it.

    Both hooks writing one -- hooks/seat-state.sh, and hooks/orchestrator-stop.sh for the Stop
    it judges -- read, decide and replace under the record's lock: an event its harness does not
    wait on can finish after a newer one, and a decision made outside the lock would put it back
    over that one.
    """
    path = hook_facts_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _record_lock(path):
        try:
            standing = _read_json(path)
        except Error:
            standing = None
        standing = standing if isinstance(standing, dict) else {}
        at = standing.get("at")
        if (isinstance(at, (int, float)) and not isinstance(at, bool) and at > fact["at"]
                or keep(standing)):
            return
        from . import lifecycle     # here: it reads this module's paths
        _write_json(path, lifecycle.carried(standing, fact), prepare=False)


def plan_path(name):
    """The session's plan, a markdown list the menu row reads its bar from."""
    return seat_file("plan", name)


def runs_moved_path():
    """Touched whenever a seat's run moves -- a step, a round, an ending -- so an open menu, which
    watches it, reads its rows again."""
    return _self.STATE / "runs-moved"


def stop_path(name):
    """Where hooks/seat-state.sh leaves this turn's start for the stop hook's rule."""
    return seat_file("stop", name)


def title_path(name):
    """Where the seat's conversation title and how far it was read are kept between ticks."""
    return seat_file("title", name)


def rulebook_path(name):
    """The rulebook file for a seat of any name: whatever cannot be a file name becomes `-`."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", " ".join(str(name).split())).strip("-.") or "seat"
    return seat_file("rulebook", name)


def rulebook_text():
    """The rulebook a session receives: ak's rules, then this host's own.

    Only a host that has written no rules of its own has none: a rules.md that is there and
    cannot be read is an error, never an empty one, because a session opened without rules the
    owner did write is a session working to rules nobody chose.
    """
    body = (REPO / "orchestrator.md").read_text()
    try:
        local = (HOME / "rules.md").read_text()
    except FileNotFoundError:
        return body
    return f"{body.rstrip()}\n\n{local}" if local.strip() else body


NAME_LINE = ("This seat is unnamed. Before your turn ends, name it with `ak orch rename --auto "
             "<name>`: the shortest possible name, at most three words, saying what the work is.")


def name_owed(name):
    """NAME_LINE while that seat is unnamed, else None: its rulebook carries the line, and the
    end-of-turn rule sends its stops back with it (`stop.recorded_ending`)."""
    return NAME_LINE if session_records().get(name, {}).get("unnamed") else None


def seat_rulebook(session, repo=None):
    """What `session`'s rulebook file holds when it opens now: `rulebook_text`, the AGENTS.md of
    the project it is filed under -- `repo`, else its record's -- as on that project's default
    branch: what its workers get, as its launch or the tick last fetched it
    (`orch.fetch_project`); an unnamed seat's instruction to name itself; and, last, where the
    conversations it moved from are (`orch.handover`)."""
    from . import gitcall     # here, not at the top: gitcall imports this module
    record = session_records().get(session, {})
    repo = record.get("repo") if repo is None else repo
    project = gitcall.agents_body(repo, RULES_REF)
    body = rulebook_text()
    if project:
        body = (f"{body.rstrip()}\n\n# The project's AGENTS.md\n\nThe rules of {Path(repo).name}, "
                "the project this session is filed under, as on its default branch: its workers "
                f"get the same.\n\n{project}\n")
    if record.get("unnamed"):
        body = f"{body.rstrip()}\n\n{NAME_LINE}\n"
    handed = seat_file("handover", session) if record else None    # only a seat moves
    if handed and handed.is_file():
        # where, not what: a harness may take its rulebook as one argument, which Linux caps
        # at 128 KiB, and a conversation has no such bound
        body = (f"{body.rstrip()}\n\n# Where this seat's work stands\n\nThis seat moved to you "
                "from another model under the same name. Its runs go on and report to you (`ak "
                "run status`), and its plan is `ak plan`. What was said in its conversation so "
                f"far, oldest first, is in {handed}: read its end before anything else.\n")
    return body


def rulebook_digest(data):
    """sha256 of a rulebook's text or bytes: what a seat's record keeps of the one it read."""
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def accounts(cfg, provider):
    """The subscriptions one provider lists as `accounts`, in the order they are tried.

    [] for a provider that lists none, which is one login, exactly as a provider always was.
    """
    entry = cfg["providers"].get(provider)
    listed = entry.get("accounts") if isinstance(entry, dict) else None
    return list(listed) if isinstance(listed, list) else []


def account_label(cfg, provider, account, name):
    """What a person reads for one of a provider's subscriptions: `name`, the provider's own,
    and for one of several its place in `accounts` in roman numerals -- `Claude II`.  The
    account's name in `accounts` is ak's own and is never shown; one no longer listed there
    keeps it, since no place would say which one it is."""
    listed = accounts(cfg, provider)
    if account not in listed:
        return name if account in (None, DEFAULT_ACCOUNT) else f"{name} {account}"
    if len(listed) < 2:
        return name
    number, numeral = listed.index(account) + 1, ""
    for value, digits in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
                          (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"),
                          (4, "IV"), (1, "I")):
        count, number = divmod(number, value)
        numeral += digits * count
    return f"{name} {numeral}"


def account_env(account):
    """What an adapter call for that account is told: its name in AGENTKIT_ACCOUNT, and for
    `default` the empty name -- the login the adapter uses when no account is named at all."""
    return {ACCOUNT_ENV: "" if account in (None, DEFAULT_ACCOUNT) else account}


def provider_env(providers):
    """What an adapter call is told about the providers it is for: their names in
    AGENTKIT_PROVIDER, space-separated.  A harness that runs several providers' models
    (OpenCode) answers for those, and every other harness has only one to answer for."""
    return {PROVIDER_ENV: " ".join(providers)}


def harness_providers(cfg, harness):
    """The providers whose offered models `cfg` runs on that harness, each once: what a
    question about the harness as a whole is a question about (worker.auth_ok)."""
    return list(dict.fromkeys(cfg["models"][name]["provider"] for name in offered(cfg)
                              if cfg["models"][name].get("harness") == harness))


def provider_harness(cfg, provider):
    """The harness of the first model of a provider -- that adapter owns its usage call."""
    for name, entry in cfg["models"].items():
        if entry.get("provider") == provider:
            return entry["harness"], name
    raise Error(f"~/.agentkit/config.toml: [providers.{provider}] has no model")


def ensure_dirs():
    for d in (HOME, *(getattr(_self, name) for name in PLACES)):
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(d, 0o700)   # a dir someone else created stays 0700 too
