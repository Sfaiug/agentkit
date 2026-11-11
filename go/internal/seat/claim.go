package seat

import (
	"errors"
	"maps"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"agentkit/internal/agent"
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// plainID is a conversation id a hook may report: nothing a path or an option can be made of.
var plainID = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)

// Claim is Python's harness.claim: the seat launched as launched, on that harness, goes on in the
// conversation a hook whose parent is pid reported with its transcript, with source as its
// id_source.  Only from the seat's own client (agent.OwnsHook, by client), with the transcript
// that conversation's own file for the seat, while the seat owns the one it is on and no other
// seat's record names the new one, as its own or one it left.  The one left stays the seat's for
// its done check (`left`); one it goes back to is its current one again, read once.  The seat's
// lock, which a delivery holds while it types the very prompt a hook may report, is never taken:
// its name holds under `claims`.  False where Go does not carry it, with nothing written.
func Claim(launched, kind string, conversation, transcript any, pid int, client func([]string) bool, source string) bool {
	id, named := conversation.(string)
	file, filed := transcript.(string)
	if !named || !filed || !plainID.MatchString(id) || strings.HasPrefix(id, "-") {
		return true
	}
	// the seat's already: decided without waiting on a rename
	if _, record, err := config.ResolveSession(launched); err != nil || record["conversation"] == id {
		return true
	}
	state := filepath.Join(config.Home(), "state")
	carried := true
	claims(state, func() error {
		carried = claim(state, launched, kind, id, file, pid, client, source)
		return nil
	})
	return carried
}

// claims runs fn holding the lock held while a seat claims a conversation and while a seat is
// renamed (harness.claims): two claiming one would each see it free, and a claim names its seat.
func claims(state string, fn func() error) error {
	return under(filepath.Join(state, "conversations.lock"), fn)
}

// claim is Claim's decision and its write, under `claims`.
func claim(state, launched, kind, id, transcript string, pid int, client func([]string) bool, source string) bool {
	name, fields, err := config.ResolveSession(launched)
	if err != nil {
		return true
	}
	record, err := run.ReadJSON(filepath.Join(state, "session-"+name+".json"))
	if errors.Is(err, run.ErrLoneSurrogate) {
		return false
	}
	if record == nil {
		return true
	}
	if model, err := config.ModelNamed(record.Str("orchestrator")); err != nil || model.Harness != kind ||
		!record.Truthy("cwd") || record.Get("conversation") == id {
		return true
	}
	if owned, known := harness.Owns(kind, record, record.Str("conversation")); !owned {
		return known
	}
	there := map[string]any{}
	maps.Copy(there, fields)
	there["conversation"] = id
	filed, known := harness.Conversation(kind, there)
	if !known {
		return false
	}
	if config.Resolve(transcript) != config.Resolve(filed) || spoken(name, id) {
		return true
	}
	held, exited, known := find(name, fields)
	if !known {
		return false
	}
	if !held || exited || !agent.OwnsHook(tmux.Own(), name, pid, client) {
		return true
	}
	gone, readable := left(record, kind, id)
	if !readable {
		return true
	}
	moved := set([]field{{"conversation", id}, {"left", gone}, {"id_source", source}})
	for {
		found := false
		err := update(state, name, func(data *run.Object) bool {
			found = true
			return moved(data)
		})
		next, _, unresolved := config.ResolveSession(name)
		if found || err != nil || unresolved != nil || next == name {
			return !errors.Is(err, run.ErrLoneSurrogate)
		}
		name = next // moved meanwhile: written where it went
	}
}

// spoken is whether a seat's record but that one names the conversation, as its own or one it
// left, or holds a `left` Python's claim cannot read, which leaves the seat where it is.
func spoken(name, id string) bool {
	for _, path := range config.SeatFiles() {
		data, _ := os.ReadFile(path)
		value, _ := run.DecodeShown(data)
		other, _ := value.(*run.Object)
		if seat, _ := sessionFile(filepath.Base(path)); seat == name || other == nil || other.Has(config.Renamed) {
			continue
		}
		if other.Get("conversation") == id {
			return true
		}
		was, listed := other.Get("left").([]any)
		if other.Has("left") && !listed {
			return true
		}
		for _, each := range was {
			entry, _ := each.(*run.Object)
			if entry == nil || entry.Get("conversation") == id {
				return true
			}
		}
	}
	return false
}

// left is the record's `left` with the conversation it is on added last, of that harness, each
// beside the account and directory it was written under, which the record's own go on to name
// the seat's next ones (notify.left); the one the seat goes on in is its current one again.
// False where an entry is none Python's claim reads.
func left(record *run.Object, kind, id string) ([]any, bool) {
	kept, listed := record.Get("left").([]any)
	if record.Has("left") && !listed {
		return nil, false
	}
	then := func(entry *run.Object) *run.Object {
		entry.Set("account", record.Get("account"))
		entry.Set("cwd", record.Get("cwd"))
		return entry
	}
	var gone []any
	for _, each := range kept {
		was, _ := each.(*run.Object)
		if was == nil || !was.Has("conversation") {
			return nil, false
		}
		if was.Get("conversation") == id {
			continue
		}
		entry := then(run.NewObject())
		for _, key := range was.Keys() {
			entry.Set(key, was.Get(key))
		}
		gone = append(gone, entry)
	}
	now := run.NewObject()
	now.Set("harness", kind)
	now.Set("conversation", record.Get("conversation"))
	return append(gone, then(now)), true
}
