package seat

import (
	"errors"
	"maps"
	"os"
	"path/filepath"
	"regexp"
	"slices"
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
// conversation a hook whose parent is pid reported, with its transcript and id_source.  Only from
// the seat's own client (agent.OwnsHook), with the transcript that conversation's own file for the
// seat, while the seat owns the one it is on and no other
// seat's record names the new one, as its own or one it left.  The one left stays the seat's for
// its done check (`left`); one it goes back to is its current one again, read once.  One a harness
// learns from its own evidence (harness.Learns) goes into the record first, whether the seat moves
// or not.  To keep one (Followed.Keep) is to add it to those the seat left, unless it is among them
// already, and move nothing.  The seat's
// lock, which a delivery holds while it types the very prompt a hook may report, is never taken:
// its name holds under `claims`.  False where Go does not carry it, with nothing written.
func Claim(launched string, to harness.Followed, pid int) bool {
	id, named := to.Conversation.(string)
	file, filed := to.Transcript.(string)
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
		carried = claim(state, launched, to, id, file, pid)
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
func claim(state, launched string, to harness.Followed, id, transcript string, pid int) bool {
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
	if model, err := config.ModelNamed(record.Str("orchestrator")); err != nil || model.Harness != to.Harness ||
		!record.Truthy("cwd") || record.Get("conversation") == id {
		return true
	}
	if harness.Learns(to.Harness) {
		// the one its harness's evidence says the seat is in, which that evidence may not have
		// written into its record yet; a seat in none, or only in another seat's, is Python's
		current := harness.Current(to.Harness, fields)
		if current == "" || spoken(name, current) {
			return false
		}
		if record.Get("conversation") != current {
			if err := update(state, name, set([]field{{"conversation", current}})); err != nil {
				return !errors.Is(err, run.ErrLoneSurrogate)
			}
			record.Set("conversation", current)
		}
		if current == id {
			return true
		}
	} else if owned, known := harness.Owns(to.Harness, record, record.Str("conversation")); !owned {
		return known
	}
	filed := ""
	if to.Filed != nil {
		filed = to.Filed(id)
	} else {
		there := map[string]any{}
		maps.Copy(there, fields)
		there["conversation"] = id
		named, known := harness.Conversation(to.Harness, there)
		if !known {
			return false
		}
		filed = named
	}
	if config.Resolve(transcript) != config.Resolve(filed) || spoken(name, id) {
		return true
	}
	held, exited, known := find(name, fields)
	if !known {
		return false
	}
	if !held || exited || !agent.OwnsHook(tmux.Own(), name, pid, to.Client) {
		return true
	}
	now := record.Get("conversation")
	if to.Keep {
		now = id
	}
	gone, readable := left(record, to.Harness, id, now)
	if !readable || to.Keep && slices.ContainsFunc(record.List("left"), func(was any) bool {
		return was.(*run.Object).Get("conversation") == id
	}) {
		return true // kept already: a report that comes late or twice undoes no move
	}
	changes := []field{{"conversation", id}, {"left", gone}, {"id_source", to.Source}}
	if to.Keep {
		changes = []field{{"left", gone}}
	}
	moved := set(changes)
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
		if other.Get("conversation") == id || slices.Contains(harness.Recorded(other), id) {
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

// left is the record's `left` with now added last, of that harness, each beside the account and
// directory it was written under, which the record's own go on to name the seat's next ones
// (notify.left): the conversation it is on, which it leaves, or one it keeps.  The one the seat
// goes on in is its current one again.  False where an entry is none Python's claim reads.
func left(record *run.Object, kind, id string, now any) ([]any, bool) {
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
	added := run.NewObject()
	added.Set("harness", kind)
	added.Set("conversation", now)
	return append(gone, then(added)), true
}
