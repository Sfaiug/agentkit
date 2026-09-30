"""A harness is a plugin: `adapters/<name>.sh`, `adapters/<name>.toml`, and nothing else.

`load(name)` answers with every hook a harness can implement, defaulted, so a harness that
brings no Python at all works: the adapter script runs it, the adapter manifest says what its
screen, its quota, its update and its conversation are, and the defaults here answer the rest.
A harness that needs Python puts it in `agentkit/harness/<name>.py` and implements only the
hooks it has something to say about -- `claude.py` the transcript it writes, `codex.py` the
launch receipt its thread is proven by, `grokbuild.py` the session directory it opens,
`muse.py` its launcher build, its own usage probe and the session store its tokens are in,
`opencode.py` the receipt its seat plugin writes its session into and the endpoint that says
how a model is paid.

No module outside this package names a harness: the core asks
`harness.load(config.model(cfg, m)["harness"]).<hook>(...)` and takes the answer.
"""

import importlib
from pathlib import Path
import re

from .. import config

LAUNCHER = "launcher"      # `id_source`: the id in the record is one the launcher handed out
FRESH_WORDS = "no conversation recorded; it starts fresh"   # `[conversation] fresh_words`

# `[update]`: how `ak update` moves this harness, and what it cannot do.  A harness that names
# no `version` and `upgrade` is not one `ak update` touches.  `latest` names its newest release,
# which the tick keeps it on in the background.
UPDATE = {"version": None, "upgrade": None, "revert": None, "latest": None, "env": {},
          "cannot": "", "snapshot_dir": ""}
# `[usage]`: what its usage call needs beyond `<adapter> usage`.  `none` is the harness
# without a meter at all: no reading is a neutral provider, never a failed probe.
# `probe_every` is how often the harness may be asked at all, in seconds: its own fact,
# and None where the manifest names none, which is the host's usual minute.
USAGE = {"capture": False, "strips_timestamp": False, "reset": False, "none": False,
         "probe_every": None}
# `[stall]`: the words no one harness owns, read for every harness beside its manifest's own:
# HTTP's, the shell's, a command line's, a login's and a model name's, which any harness may
# pass on.  An outage's status code counts only beside HTTP, a status or an API error.
STALL = {"refusals": ("API Error", "529", "unexpected status"),
         "outages": ("overloaded", "at capacity", "Internal server error", "Bad Gateway",
                     "Gateway Timeout", "Service unavailable", "idle timeout", "HTTP 5##",
                     "status 5##", "status: 5##", "status=5##", "API Error 5##",
                     "API Error: 5##"),
         "faults": ("command not found", "Argument list too long", "not installed",
                    "unknown flag", "unknown flags", "unknown shorthand flag",
                    "unknown option", "unknown options", "unknown argument",
                    "unknown arguments", "unknown command", "unknown model",
                    "unrecognized option", "unrecognized options", "unrecognized argument",
                    "unrecognized arguments", "unexpected argument", "unexpected arguments",
                    "invalid option", "invalid model", "model … not found",
                    "model … not exist", "model … not supported", "model_not_found",
                    "modelnotfound", "ModelNotFoundError", "not logged in", "please log in",
                    "please login", "please run log in", "please run login",
                    "unauthorized", "unauthorised",
                    "authentication failed", "authentication_failed",
                    "authentication required", "authentication_required",
                    "authentication error", "authentication_error", "invalid api key",
                    "invalid api-key", "invalid apikey", "invalid_api_key", "invalid-api-key",
                    "invalid x-api-key")}
# What a failed turn's own output says, as `Harness.failure` reads it: the account's window is
# spent, the provider declined the turn or is down, or the harness never ran the turn at all.
SPENT, REFUSAL, OUTAGE, FAULT = "spent", "refusal", "outage", "fault"

_LOADED = {}


def says(text, word):
    """Does `text` say `word` on its own: never inside a longer word, nor its digits inside a
    longer number -- a request id, a byte count, a duration?

    A `#` in a word is any one digit (`HTTP 5##`), and `…` joins parts that each stand on
    their own, in that order on one line, at most 80 characters apart (`model … not found`).
    """
    parts = [part.strip() for part in word.split("…")]
    if not all(parts):
        return False
    pattern = ".{0,80}".join(
        (r"(?<!\w)(?<!\d\.)" if re.match(r"[\w#]", part) else "")
        + re.escape(part).replace(r"\#", r"\d")
        + (r"(?!\w)(?!\.\d)" if re.search(r"[\w#]$", part) else "")
        for part in parts)
    return re.search(pattern, text, re.I) is not None


def _module(name):
    """`agentkit/harness/<name>.py`, or None where that harness brings no Python.

    Only a plain file beside this one, named exactly for the harness, is imported: a harness
    name is a path component and never a dotted import path, so nothing else can be reached
    from here.
    """
    if not isinstance(name, str) or not config.HARNESS.fullmatch(name):
        return None
    if not (Path(__file__).resolve().parent / f"{name}.py").is_file() or not name.isidentifier():
        return None
    try:
        return importlib.import_module(f".{name}", __name__)
    except ImportError:
        return None


class Harness:
    """One harness's hooks, each answered by its module or by the default beside it.

    The manifest is read on every access rather than remembered, because `config.manifest`
    already caches it by mtime and an adapter toml that changes must show up on the next draw.
    """

    def __init__(self, name):
        self.name = name
        self.module = _module(name)

    def _section(self, table, defaults):
        block = config.manifest(self.name).get(table)
        return {**defaults, **(block if isinstance(block, dict) else {})}

    def _hook(self, name):
        return getattr(self.module, name, None)

    # --- the adapter manifest's own words ---------------------------------

    @property
    def update(self):
        """Its `[update]` table: the commands that move it, and what it cannot put back."""
        return self._section("update", UPDATE)

    @property
    def usage(self):
        """Its `[usage]` table: a captured probe, a stripped timestamp, a spendable reset."""
        facts = self._section("usage", USAGE)
        facts["none"] = bool(facts.get("none"))
        return facts

    def failure(self, said, ran=True):
        """What a failed turn's own output says, in its `[stall]` words: (outcome, word).

        `said` is the harness's own -- its stderr, its failure events, a final.md nothing
        answered (`run.harness_said`) -- never the model's answer, and a word counts only
        standing on its own (`says`).  A spent window (`quotas`) outranks a refusal
        (`refusals`), and a refusal an outage (`outages`).  In a turn that never `ran` -- it
        left no answer at all -- a `faults` word says the harness could not run it, and that
        outranks the rest, unless an outage word says the provider was down beside it.
        (None, None) where it said none of them.
        """
        block = config.manifest(self.name).get("stall")
        block = block if isinstance(block, dict) else {}

        def first(key):
            listed = block.get(key)
            words = (listed if isinstance(listed, list) else []) + list(STALL.get(key, ()))
            return next((word for word in words if isinstance(word, str) and says(said, word)),
                        None)

        outage = first("outages")
        fault = None if ran or outage else first("faults")
        for outcome, word in ((FAULT, fault), (SPENT, first("quotas")),
                              (REFUSAL, first("refusals")), (OUTAGE, outage)):
            if word:
                return outcome, word
        return None, None

    @property
    def conversation_facts(self):
        return self._section("conversation", {"fresh_words": "", "always_offered": False})

    @property
    def fresh_words(self):
        """What a seat starting without a past is said to be doing, in this harness's words."""
        return self.conversation_facts.get("fresh_words") or FRESH_WORDS

    @property
    def always_offered(self):
        """Whether a seat of this harness keeps its row after tmux has lost it.

        True where ownership is decided by evidence outside the record -- a launch receipt --
        so a row has to be recomputed rather than read, and a seat that owns nothing is still
        offered, under its own name, starting fresh.
        """
        return bool(self.conversation_facts.get("always_offered"))

    @property
    def hooks_from_config(self):
        """Whether its hooks come from a config file its launch reads, rather than per launch.

        A seat older than the last install is then missing whatever that install added, and
        says so; one whose launch installs its own hooks, or which has none, never is.
        """
        return (config.manifest(self.name).get("hooks") or {}).get("installed") == "config"

    # --- the conversation a seat holds ------------------------------------

    def seat_auth(self, account):
        """Whether this account can open a seat, including logins only seats support."""
        hook = self._hook("seat_auth")
        if hook:
            return hook(account)
        from .. import worker
        return worker.auth_ok(self.name, seat=True, account=account)

    def conversation(self, record, cwd=None):
        """The conversation this seat owns: by default the one its record was launched with."""
        hook = self._hook("conversation")
        return hook(record, cwd) if hook else record.get("conversation")

    def resumable(self, record, cwd, conversation):
        """Whether that conversation may be resumed: by default only a launcher-issued id."""
        hook = self._hook("resumable")
        if hook:
            return bool(hook(record, cwd, conversation))
        return bool(conversation) and record.get("id_source") == LAUNCHER

    def restart_word(self, record):
        """Why a row restarts instead of resuming, or None where it has no words for it."""
        hook = self._hook("restart_word")
        return hook(record) if hook else None

    def reconcile(self, record):
        """The record fields to write down before anything claims this seat is resumable.

        By default a conversation the launcher did not hand out is not this seat's to resume,
        and is dropped rather than offered.
        """
        hook = self._hook("reconcile")
        if hook:
            return hook(record)
        return ({"conversation": None, "resumable": False}
                if record.get("conversation") and record.get("id_source") != LAUNCHER else {})

    def launched(self, name, cwd, conversation):
        """Write down what this launch owns; the env pairs its command has to carry.

        By default the launcher's own id is the record, and the command needs nothing.
        """
        hook = self._hook("launched")
        if hook:
            return hook(name, cwd, conversation)
        config.update_session(name, conversation=conversation, resumable=bool(conversation),
                              id_source=LAUNCHER if conversation else None, before=None)
        return {}

    def title_command(self, name):
        """The line that changes a seat's launch title, or None for a harness without one."""
        hook = self._hook("title_command")
        return hook(name) if hook else None

    def sync_title(self, name, record):
        """Set a title without typing: True once confirmed, False pending, None unsupported."""
        hook = self._hook("sync_title")
        return hook(name, record) if hook else None

    @property
    def title_facts(self):
        """The original title-hook contract; adapters can require a stored receipt instead."""
        return self._section("title", {"at_launch": True, "unreadable": True})

    def title_ready(self, record, state):
        """May this owned conversation accept a title now, including a retry?"""
        hook = self._hook("title_ready")
        return hook(record, state) if hook else True

    def session_title(self, record):
        """The latest custom title, empty if absent, or None if the record cannot be read."""
        hook = self._hook("session_title")
        return hook(record) if hook else None

    def forget(self, record):
        """Drop whatever else this harness kept for a seat that is ending."""
        hook = self._hook("forget")
        if hook:
            hook(record)

    def opened(self, cwd, conversation):
        """Has the harness written that conversation down yet?

        Not a question of whose conversation it is -- the launcher settled that -- only of
        whether there is one to resume.  A store nothing here knows is taken at its word.
        """
        hook = self._hook("opened")
        return bool(hook(cwd, conversation)) if hook else True

    def transcript(self, record, cwd, conversation):
        """Where that conversation's transcript is, for a model taking the seat over.

        A path the new orchestrator can read the last exchange from, or None where this
        harness keeps no file to read -- its session lives in a store, or it starts fresh.
        """
        hook = self._hook("transcript")
        return hook(record, cwd, conversation) if hook else None

    # --- what its own installation and usage call know --------------------

    def identity(self, text, argv):
        """Its `[update] version` output as a build identity, refined where it has more to say."""
        hook = self._hook("identity")
        return hook(text, argv) if hook else text

    def usage_extra(self, out, data, state_dir):
        """After a usage probe: whatever else this harness knows about what it just said."""
        hook = self._hook("usage_extra")
        if hook:
            hook(out, data, state_dir)

    def usage_recorded(self, state_dir, now):
        """Meters this harness wrote down itself -- a refused run's quota -- still standing, or []."""
        hook = self._hook("usage_recorded")
        return hook(state_dir, now) if hook else []

    def usage_policy(self, entry, effort):
        """Whether that config.toml entry is a probe of this harness's own to run.

        False by default: a harness with no probe of its own has no policy to satisfy.
        """
        hook = self._hook("usage_policy")
        return bool(hook(entry, effort)) if hook else False

    def mode(self, entry):
        """`subscription` or `payg` where the harness's own config says how that model is paid.

        None by default: config.toml's `[providers.*] mode` stands.
        """
        hook = self._hook("mode")
        return hook(entry) if hook else None

    # --- what one headless turn spent ----------------------------------------

    def tokens(self, out):
        """The tokens the turn written to `out` spent, or None where this harness said nothing.

        By default they are in the event log its adapter wrote there; a harness that keeps
        them elsewhere reads them from there.
        """
        hook = self._hook("tokens")
        if hook:
            return hook(Path(out))
        from .. import history   # here, not at the top: history is what reads this
        return history.event_tokens(Path(out) / "events.jsonl")

    def turn_meters(self, out):
        """The meters the turn in `out` reported about its own account, or [].

        By default a harness reports none: only one that prints its account's limits in
        its stream has anything to say, and what it says is endpoint-shaped meters.
        """
        hook = self._hook("turn_meters")
        if hook:
            return hook(Path(out))
        return []


def load(name):
    """The plugin for that harness: its module's hooks where it has them, defaults elsewhere.

    Kept per name, because the module is all it holds: the manifest behind every fact it
    answers is read through `config.manifest`, which rereads a toml the moment it changes.
    """
    key = name if isinstance(name, str) else ""
    if key not in _LOADED:
        _LOADED[key] = Harness(name if isinstance(name, str) else None)
    return _LOADED[key]
