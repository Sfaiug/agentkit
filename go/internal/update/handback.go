package update

import (
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/run"
)

// A Deliver types a line ak owes into a seat on the repository the clone URL origin names,
// Python's watch.after_merge_deliver with no run: the tick's, which this package cannot import.
// The seat its mark typed names while that one is up, else the newest seat up whose merged runs'
// pull requests are on that repository; only at that seat's prompt, receipt keeping the mark of a
// line typed now.  The seat told, "" for none; an error, before anything is done, where Go does
// not carry it.
type Deliver func(origin, line string, typed *run.Object, receipt func(*run.Object) error) (string, error)

// handBack tells each red's line still owed, as Python's update.keep_current does under the
// upgrade lock: each harness's second red in a row or more, by name, then the fresh-install gate's
// standing faults.
func handBack(deliver Deliver, say func(string)) error {
	state := filepath.Join(config.Home(), "state")
	checks, _ := filepath.Glob(filepath.Join(state, "harness-gates", "*", "handed"))
	for _, path := range checks {
		record, _ := run.ReadJSON(path)
		if record == nil {
			continue
		}
		if reds, _ := record.Num("reds"); reds < 2 {
			continue
		}
		name := filepath.Base(filepath.Dir(path))
		if err := tellOnce(path, record, deliver, "handed "+name+"'s failed harness upgrade back to fix", say); err != nil {
			return err
		}
	}
	faults := filepath.Join(state, "fresh-gate-faults", "handed")
	record, _ := run.ReadJSON(faults)
	return tellOnce(faults, record, deliver, "handed the fresh-install gate's standing faults back to fix", say)
}

// tellOnce delivers the line a hand-back record at path keeps, keyed by ~/agentkit's origin, as
// Python's update._gate_hand_back: the whole record rewritten with its mark the moment the line is
// typed, so a later tick only presses its Enter, and told once it is sent, saying so.  A record
// told, or holding no line, owes none.
func tellOnce(path string, record *run.Object, deliver Deliver, done string, say func(string)) error {
	if record == nil || record.Truthy("told") || record.Str("line") == "" {
		return nil
	}
	keep := func(key string, value any) error {
		record.Set(key, value)
		return put(path, []byte(run.Line(record)))
	}
	// one that cannot be read keys no repository, as Python's _git answers ""
	origin, _ := gitcall.Git{Repo: filepath.Join(config.UserHome(), "agentkit"), Env: pins, Cap: gitCap}.Try("remote", "get-url", "origin")
	seat, err := deliver(origin, record.Str("line"), record.Dict("typed"), func(mark *run.Object) error { return keep("typed", mark) })
	if err != nil || seat == "" {
		return err
	}
	if err := keep("told", true); err != nil {
		return err
	}
	say(done)
	return nil
}
