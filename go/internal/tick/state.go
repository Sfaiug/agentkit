package tick

import (
	"context"
	"errors"
	"math"
	"os"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// What ticks remember between them is Python's watch.json, in Python's format, under its lock.

// kept are the tables every watch.json holds, and each names what a home has to act on.
var kept = []string{"reviewed", "own", "stalls", "seen_at", "after_merge"}

// loadState is watch.json as Python's load_state reads it; false where a read fails on what Go
// cannot write back as it was, or where Python's would write over what cannot be written over.
func loadState() (*run.Object, bool) {
	state := run.NewObject()
	data, err := os.ReadFile(statePath("watch.json"))
	if err != nil && !missing(statePath("watch.json")) {
		return nil, false
	}
	value, err := run.DecodeLimited(data)
	if errors.Is(err, run.ErrLoneSurrogate) || errors.Is(err, run.ErrLimit) {
		return nil, false
	}
	if object, ok := value.(*run.Object); ok {
		state = object
	}
	for _, key := range kept {
		if state.Dict(key) == nil {
			state.Set(key, run.NewObject())
		}
	}
	seen := state.Dict("seen_at")
	for _, name := range seen.Keys() {
		seen.Set(name, generation(seen.Get(name)))
	}
	return state, true
}

// generation is a stamp on disk as Python's reads one: numeric, nonnegative and safely
// incrementable, else 0.
func generation(value any) any {
	if stamp, ok := run.Num(value); ok && stamp >= 0 && !math.IsInf(math.Nextafter(stamp, math.Inf(1)), 1) {
		return value
	}
	return run.Number("0")
}

// quiet is whether watch.json holds only what a home Go carries holds: no PR followed, login or
// worker token kept, and no stall but one nothing is typed past yet, which the health row keeps.
// Alert generations are bookkeeping, kept even after an open; the heads reviewed are the incoming
// pass's own, and a merge's break the merge checks', both of which Go carries.
func quiet(state *run.Object) bool {
	for _, key := range kept {
		if key != "seen_at" && key != "reviewed" && key != "after_merge" && len(state.Dict(key).Keys()) > 0 &&
			!(key == "stalls" && seat.PlainStalls(state.Dict(key))) {
			return false
		}
	}
	return !state.Truthy("auth_out") && !state.Truthy("worker_tokens")
}

// locked holds watch.json's lock around the read before a write, as Python's state_lock does.
func locked(change func() error) error {
	if err := config.EnsureDirs(); err != nil {
		return err
	}
	held, err := lock.Wait(context.Background(), statePath("watch.lock"))
	if err != nil {
		return err
	}
	defer held.Close()
	return change()
}

func writeState(state *run.Object) error {
	tmp := statePath("watch.tmp")
	if err := os.WriteFile(tmp, []byte(run.Encode(state)+"\n"), 0o666); err != nil {
		return err
	}
	return os.Rename(tmp, statePath("watch.json"))
}

var errUnwritable = errors.New("watch.json holds what Go cannot write back")

// saveState writes the tick's state as Python's save_state does: a seat's newer generation, and a
// stall already told, win over what the tick kept in memory, and a menu's boot recovery stands.
func saveState(state *run.Object) error {
	return locked(func() error {
		current, ok := loadState()
		if !ok {
			return errUnwritable
		}
		syncSeen(state, current)
		for _, key := range []string{"boot_id", "boot_resume"} {
			if current.Has(key) {
				state.Set(key, current.Get(key))
			}
		}
		return writeState(state)
	})
}

// syncSeen is Python's sync_seen.
func syncSeen(state, current *run.Object) {
	seen, stalls, theirs := state.Dict("seen_at"), state.Dict("stalls"), current.Dict("stalls")
	for _, name := range current.Dict("seen_at").Keys() {
		stamp := current.Dict("seen_at").Get(name)
		now, _ := run.Num(stamp)
		if before, _ := run.Num(seen.Get(name)); now > before {
			stalls.Delete(name)
			if theirs.Has(name) {
				stalls.Set(name, theirs.Get(name))
			}
			seen.Set(name, stamp)
		}
	}
	for _, name := range theirs.Keys() {
		if entry, ok := theirs.Get(name).(*run.Object); ok && entry.Truthy("told") {
			stalls.Set(name, entry)
		}
	}
}
