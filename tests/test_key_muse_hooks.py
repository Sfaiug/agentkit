"""A Muse seat's launch hands Muse ak's hooks, and what Muse hands them becomes the seat's fact.

Muse runs its launch's own session's hooks off its command line, so a Muse seat's word follows its
hooks there only when its launch carries them: the session it opened (`SessionStart`, for its
launch's receipt), its turn's end (`Stop`), its question or approval going up (`Notification`), its
question answered (`PostToolBatch`) and an Esc (`Interrupt`), the last two run beside the turn,
which waits on neither.  A muse whose own schema names no notification event refuses settings it
does not know, so it is given none and its seat is read off the screen.
Muse hands a hook almost none of the seat's environment, so each command carries the seat and
its pane itself.  A tool batch is named for its first tool, so a reminder's batch never reads as
the question answered, and a question's notice names only the folder, so the question is read off
the seat's own pane.  Black-box: seats opened by `ak orch` from a person's terminal on a fake
muse that keeps the line it was started with and shows a real capture of Muse asking
(tests/fixtures/muse-question-pane.txt), each hook fired as Muse fires it with the payload Muse
handed it in a live sweep (tests/fixtures/muse-hook-payloads.jsonl), judged by the fact it writes
(`hook-<seat>.json`); this test fails against `/bin/false`.

A session `/new` opens runs only the hooks of Muse's settings file, so `adapters/muse.sh hooks`,
and each seat's launch, merge the same events into it beside whatever it holds, each running the
adapter `exec`ed; one ak cannot read as Muse's is left as it is.
"""

import json
import os
import shlex
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import PANE
from fixtures.akterm import Terminal
from fixtures.hookdrive import ROOT, adapter

FIXTURES = Path(__file__).resolve().parent / "fixtures"
QUESTION, REMINDED, ANSWERED, STOPPED, ESCAPED, _APPROVAL = (
    json.loads(line) for line in (FIXTURES / "muse-hook-payloads.jsonl").read_text().splitlines())
ASKED = "Which colour should the acme banner use?"    # the question muse-question-pane.txt shows
HOOKED = {"SessionStart", "Stop", "Notification", "PostToolBatch", "Interrupt"}

# muse: the schema this test gives it, and a TUI, the one call made on a terminal, that keeps the
# line it was started with and shows Muse asking its own question.  Anything else (ak's usage
# probe) fails, as offline.
MUSE = """#!/bin/sh
if [ "$1 $2 $3" = "schema generate-json-schema --out" ]; then
  exec cp {root}/schema.json "$4/muse.schema.json"
fi
[ -t 0 ] || exit 1
{python} -c 'import json, sys; json.dump(sys.argv[2:], open(sys.argv[1], "w"))' \\
  {root}/argv-"$AGENTKIT_SESSION".json "$@"
exec {python} {pane} {root}/question.txt {root}/"$AGENTKIT_SESSION".typed
"""
SCHEMA = '{"hook_event": {"enum": ["stop", "notification", "post_tool_batch", "interrupt"]}}'
OLDER = '{"hook_event": {"enum": []}}'    # a muse that runs no lifecycle hooks
FILE = ".config/muse/settings.json"
UNREAD = ("{broken", '{"hooks": null, "threshold": NaN}', "null", '{"hooks": []}',
          '{"hooks": {"Stop": {}}}', '{"hooks": {"Stop": [null]}}',
          '{"hooks": {"Stop": [{"hooks": null}]}}')


def ours(event):
    """The group ak's settings file gives an event: this checkout's adapter, `exec`ed."""
    run = shlex.join(["exec", "bash", str(ROOT / "adapters/muse.sh"), "hook"])
    hook = {"type": "command", "command": run}
    return {"hooks": [{**hook, "async": True} if event in ("PostToolBatch", "Interrupt") else hook]}


def fake(home):
    """Put the muse this test gives a Home on its PATH, its schema naming the events it hooks."""
    home.fake("muse", MUSE.format(root=shlex.quote(str(home.root)),
                                  python=shlex.quote(sys.executable),
                                  pane=shlex.quote(str(PANE))))
    (home.root / "schema.json").write_text(SCHEMA)


def settings(argv):
    """Each `-c hooks.<event>=<value>` Muse was started with, its value as JSON."""
    found = {}
    for flag, value in zip(argv, argv[1:]):
        if flag == "-c" and value.startswith("hooks."):
            event, _, given = value.removeprefix("hooks.").partition("=")
            found[event] = json.loads(given)
    return found


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MuseHooks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        fake(cls.home)
        (cls.home.root / "question.txt").write_text(
            (FIXTURES / "muse-question-pane.txt").read_text())
        cls.hooks = settings(cls.launch("acme", SCHEMA))

    @classmethod
    def launch(cls, name, schema):
        """Open a Muse seat as a person does, and the line its muse was started with; with
        no `schema`, its muse has no schema to write."""
        (cls.home.root / "schema.json").unlink(missing_ok=True)
        if schema is not None:
            (cls.home.root / "schema.json").write_text(schema)
        argv = cls.home.root / f"argv-{name}.json"
        term = Terminal(cls.home, "orch", name, "--model", "spark", "--workers", "spark",
                        size=(120, 40))
        deadline = time.monotonic() + 60
        while not argv.exists() or not argv.read_text().endswith("]"):
            if time.monotonic() > deadline:
                raise AssertionError(f"no muse started for {name}; the terminal shows:\n"
                                     f"{term.screen()}")
            time.sleep(0.05)
        return json.loads(argv.read_text())

    def setUp(self):
        self.fact_file = self.home.path / ".agentkit/state/hook-acme.json"
        self.fact_file.unlink(missing_ok=True)

    def fire(self, payload):
        """Run each command the launch gave Muse for the event, as Muse runs one: `sh -c`, the
        event's JSON on stdin, and none of the seat's environment."""
        for group in self.hooks[payload["hook_event_name"]]:
            for hook in group["hooks"]:
                done = self.home.run("sh", "-c", hook["command"], input=json.dumps(payload))
                self.assertEqual(done.code, 0, done.err)

    def fact(self):
        return json.loads(self.fact_file.read_text()) if self.fact_file.exists() else None

    def test_a_muse_seat_starts_with_a_hook_for_each_event_its_word_follows(self):
        self.assertEqual(set(self.hooks), HOOKED)
        for event, groups in self.hooks.items():
            with self.subTest(event=event):
                hooks = [hook for group in groups for hook in group["hooks"]]
                self.assertTrue(hooks)
                self.assertTrue(all(hook["type"] == "command" and hook["command"]
                                    for hook in hooks))
        for event in ("PostToolBatch", "Interrupt"):
            with self.subTest(event=event, runs="beside the turn"):
                self.assertTrue(all(hook.get("async") is True for group in self.hooks[event]
                                    for hook in group["hooks"]))

    def test_a_muse_that_names_no_notification_event_is_started_with_no_hooks(self):
        for name, schema in (("beta", OLDER), ("gamma", None)):
            with self.subTest(schema=schema):
                argv = self.launch(name, schema)
                self.assertFalse([arg for arg in argv if "hooks." in arg], argv)

    def test_its_launch_makes_sure_of_the_settings_file_and_starts_past_one_it_cannot_read(self):
        written = json.loads((self.home.path / FILE).read_text())
        self.assertEqual(written["hooks"], {event: [ours(event)] for event in HOOKED})
        unread = self.home.write(FILE, '{"hooks": {"Stop": [null]}}')
        self.assertTrue(settings(self.launch("delta", SCHEMA)))
        self.assertEqual(unread.read_text(), '{"hooks": {"Stop": [null]}}')

    def test_its_question_going_up_is_written_down_in_the_words_on_its_own_pane(self):
        self.fire(QUESTION)
        fact = self.fact()
        self.assertEqual(fact, {"session": "acme", "event": "Notification",
                                "kind": "question_prompt", "text": ASKED, "at": fact["at"]})

    def test_its_question_answered_is_the_batch_its_question_tool_leads(self):
        batch = dict(ANSWERED, tool_calls=[*ANSWERED["tool_calls"], {"tool_name": "shell"}])
        self.fire(batch)
        fact = self.fact()
        self.assertEqual((fact["session"], fact["event"], fact["kind"]),
                         ("acme", "PostToolBatch", "request_user_input"))

    def test_a_reminders_batch_leaves_its_question_standing(self):
        self.fire(QUESTION)
        asked = self.fact()
        self.assertEqual(asked["kind"], "question_prompt")
        self.fire(REMINDED)
        self.assertEqual(self.fact(), asked)

    def test_an_esc_and_a_turns_end_are_each_written_down(self):
        for payload in (ESCAPED, STOPPED):
            with self.subTest(event=payload["hook_event_name"]):
                self.fire(payload)
                fact = self.fact()
                self.assertEqual((fact["session"], fact["event"]),
                                 ("acme", payload["hook_event_name"]))

    def test_outside_any_seat_its_hook_writes_nothing(self):
        for payload in (QUESTION, ANSWERED, STOPPED):
            with self.subTest(event=payload["hook_event_name"]):
                fired = adapter(self.home, "muse", "hook", payload=payload, seat=None)
                self.assertEqual(fired.code, 0, fired.err)
                self.assertEqual(sorted((self.home.path / ".agentkit/state").glob("hook-*.json")),
                                 [])


class SettingsFile(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fake(self.home)

    def hooks(self, code=0, **env):
        done = adapter(self.home, "muse", "hooks", seat=None, env=env)
        self.assertEqual(done.code, code, done.out + done.err)
        return done

    def read(self, relative=FILE):
        return json.loads((self.home.path / relative).read_text())

    def test_a_home_with_none_gets_one_of_muses_shape_with_each_event_its_launch_hooks(self):
        self.hooks()
        self.assertEqual(self.read(), {"schema_version": 1,
                                       "hooks": {event: [ours(event)] for event in HOOKED}})
        # Muse runs them as it runs any, handed none of a seat's environment: they move no seat
        for event, [group] in self.read()["hooks"].items():
            done = self.home.run("sh", "-c", group["hooks"][0]["command"],
                                 input=json.dumps({"hook_event_name": event}))
            self.assertEqual(done.code, 0, done.err)
        self.assertEqual(list((self.home.path / ".agentkit/state").glob("hook-*.json")), [])

    def test_they_run_from_a_checkout_whose_path_is_not_ascii(self):
        # Muse runs a hook with sh, which reads no bash quoting such as $'...'
        checkout = self.home.root / "caf\u00e9"
        checkout.symlink_to(ROOT, target_is_directory=True)
        done = self.home.run("bash", str(checkout / "adapters/muse.sh"), "hooks",
                             env={"LC_ALL": "C"})
        self.assertEqual(done.code, 0, done.err)
        for event, [group] in self.read()["hooks"].items():
            fired = self.home.run("/bin/sh", "-c", group["hooks"][0]["command"],
                                  input=json.dumps({"hook_event_name": event}), env={"LC_ALL": "C"})
            self.assertEqual(fired.code, 0, fired.err)

    def test_the_owners_settings_and_hooks_stay_and_another_checkouts_give_way(self):
        mine = [{"type": "command", "command": "notify-send done"},
                {"type": "command", "command": "exec bash /acme/adapters/muse.sh.local hook"}]
        old = {"type": "command", "command": "exec bash /old/acme/adapters/muse.sh hook"}
        greet = {"matcher": "x", "hooks": [{"type": "command", "command": "echo hi"}]}
        self.home.write(FILE, {"schema_version": 1, "tui": {"theme": "dark"}, "hooks": {
            "Stop": [{"hooks": [*mine, old]}, {"hooks": [old]}],
            "SessionStart": [greet], "PreCompact": [greet]}})
        self.hooks()
        hooks = {event: [ours(event)] for event in HOOKED}
        hooks.update(Stop=[{"hooks": mine}, ours("Stop")], PreCompact=[greet],
                     SessionStart=[greet, ours("SessionStart")])
        self.assertEqual(self.read(), {"schema_version": 1, "tui": {"theme": "dark"},
                                       "hooks": hooks})

    def test_hooks_of_null_are_none_and_get_aks(self):
        self.home.write(FILE, '{"tui": {"theme": "dark"}, "hooks": null}')
        self.hooks()
        self.assertEqual(self.read(), {"schema_version": 1, "tui": {"theme": "dark"},
                                       "hooks": {event: [ours(event)] for event in HOOKED}})

    def test_a_file_not_of_muses_shape_is_left_as_it_is_and_said_in_one_line(self):
        for unread in UNREAD:
            with self.subTest(unread):
                path = self.home.write(FILE, unread)
                done = self.hooks(code=1)
                self.assertEqual(path.read_text(), unread)
                self.assertEqual(len(done.err.strip().splitlines()), 1, done.err)

    def test_a_logins_link_stays_a_link_and_takes_them_where_it_leads(self):
        own, usual = self.home.path / ".muse-be/muse", (self.home.path / FILE).parent
        own.mkdir(parents=True)
        for name in ("settings.json", ".settings.json.lock"):    # as the login's home links them
            (own / name).symlink_to(usual / name)    # not there yet, nor their folder
        self.hooks(AGENTKIT_ACCOUNT="be")
        for name in ("settings.json", ".settings.json.lock"):
            self.assertEqual(os.readlink(own / name), str(usual / name))
        self.assertEqual(self.read()["hooks"], {event: [ours(event)] for event in HOOKED})

    def test_a_second_run_leaves_the_file_as_it_is(self):
        self.home.write(FILE, {"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "exec bash /old/acme/adapters/muse.sh hook"},
            {"type": "command", "command": "notify-send done"}]}]}})
        self.hooks()
        path = self.home.path / FILE
        before, held = os.stat(path), path.read_bytes()
        self.hooks()
        after = os.stat(path)
        self.assertEqual(path.read_bytes(), held)
        self.assertEqual((after.st_ino, after.st_mtime_ns), (before.st_ino, before.st_mtime_ns))


if __name__ == "__main__":
    unittest.main()
