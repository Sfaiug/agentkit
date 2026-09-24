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

from .. import config

LAUNCHER = "launcher"      # `id_source`: the id in the record is one the launcher handed out
FRESH_WORDS = "no conversation recorded; it starts fresh"   # `[conversation] fresh_words`

# `[update]`: how `ak update` moves this harness, and what it cannot do.  A harness that names
# no `version` and `upgrade` is not one `ak update` touches.
UPDATE = {"version": None, "upgrade": None, "revert": None, "env": {}, "cannot": "",
          "snapshot_dir": ""}
# `[usage]`: what its usage call needs beyond `<adapter> usage`.  `none` is the harness
# without a meter at all: no reading is a neutral provider, never a failed probe.
USAGE = {"capture": False, "strips_timestamp": False, "reset": False, "none": False}

_LOADED = {}


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


def load(name):
    """The plugin for that harness: its module's hooks where it has them, defaults elsewhere.

    Kept per name, because the module is all it holds: the manifest behind every fact it
    answers is read through `config.manifest`, which rereads a toml the moment it changes.
    """
    key = name if isinstance(name, str) else ""
    if key not in _LOADED:
        _LOADED[key] = Harness(name if isinstance(name, str) else None)
    return _LOADED[key]
