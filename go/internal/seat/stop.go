package seat

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// A Refusal is a stop Python's orch.cmd_stop refuses, in its words (its config.Error).
type Refusal string

func (refusal Refusal) Error() string { return string(refusal) }

// waits are what Python's orch.mark_owner_closed clears with the owner's stop mark: the seat's
// wait on usage and the lines owed its harness, which the reopening after it goes on without.
var waits = []string{"usage_wait", "usage_refusal", "midturn", "owed_lines"}

// watchKeys are the maps Python's watch.load_state reads watch.json into, in its order.
var watchKeys = []string{"reviewed", "own", "stalls", "seen_at", "after_merge"}

// A seen is what a stop finds under Python's watch.state_lock.
type seen struct {
	live, recorded, closed bool     // tmux holds the seat's session; a record keeps it; the owner stopped it
	records                []Seat   // every seat's record, which the stop reconciles first (orch.records)
	running                []string // for a name nothing holds, the seats Python's listing offers
}

// Stop is Python's orch.cmd_stop of the seat by that name, run from outside any seat, where Go
// knows the seat: what it says once done, or false where the stop is Python's.  The first stop
// closes the seat and keeps it to reopen; a stop of one closed already, or of a session no record
// keeps, removes it.  Each step takes the locks Python's takes, in its order, so no Python tick
// or screen meets a seat half stopped.
func Stop(arg string, now time.Time) (string, bool, error) {
	name, _, err := config.ResolveSession(arg)
	if err != nil {
		return "", false, nil
	}
	if err := config.EnsureDirs(); err != nil {
		return "", true, err
	}
	state := filepath.Join(config.Home(), "state")
	var found seen
	known, removed := true, false
	// every lifecycle change's lock: a stop and boot recovery agree on whether the seat exists
	err = under(filepath.Join(state, "watch.lock"), func() (err error) {
		if found, known = look(state, name, now); known {
			removed, err = found.close(state, name, now)
		}
		return err
	})
	if !known || err != nil {
		return "", known, err
	}
	if !removed {
		if err := forgetSeen(state, name, now); err != nil {
			return "", true, err
		}
		if !found.recorded { // tmux alone held it: no record to keep, no number to reopen it
			if err := forget(state, name); err != nil {
				return "", true, err
			}
			removed = true
		}
	}
	if err := forgetCard(state, name); err != nil {
		return "", true, err
	}
	if removed {
		return "removed " + name, true, nil
	}
	return "stopped " + name + "; its number reopens it", true, nil
}

// look is what a stop finds of the seat by that name and of every record, as Python's orch.find
// and orch.records find them, or false where the stop is Python's: tmux holding another seat,
// whose bar would count this one again (statusbar.retell), a record Go does not follow, or
// something of the seat's own that Python ends with it (plain).
func look(state, name string, now time.Time) (seen, bool) {
	own := tmux.Sessions(tmux.Own())
	found := seen{live: len(own) == 1 && own[0] == tmux.Session{Name: name, Mark: "1"}}
	models, err := config.Models()
	entries, unread := os.ReadDir(state)
	if len(own) > 0 && !found.live || marked(tmux.Default) || err != nil || unread != nil || !plain(state, name) {
		return seen{}, false
	}
	for _, entry := range entries {
		each, ok := sessionFile(entry.Name())
		if !ok {
			continue
		}
		held, err := run.ReadJSON(filepath.Join(state, entry.Name()))
		if err != nil || held == nil {
			return seen{}, false
		}
		if held.Has(config.Renamed) {
			continue
		}
		seat, known := recorded(state, each, held, models)
		if !known {
			return seen{}, false
		}
		found.records = append(found.records, seat)
		found.recorded = found.recorded || each == name
	}
	mark, _ := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	found.closed = mark != nil && mark.Truthy("closed_by_owner")
	if found.live || found.recorded {
		return found, true
	}
	// a name nothing holds is refused with the seats the listing offers, once it has written
	// into their records what it reconciles and infers
	home, known := Read(now)
	found.records = home.records
	for _, each := range home.Seats {
		found.running = append(found.running, each.Name)
	}
	return found, known
}

// plain is whether nothing the seat owns is Python's to end with it: no run it launched
// (stop.release_session), no browser tab it opened (browser.close_owned), no question it asked
// still unseen (notify.clear), and no card of a question, which an outbox may hold, nor one
// Python could not read (notify.forget_card).
func plain(state, name string) bool {
	if asked, _ := run.ReadJSON(filepath.Join(state, "notify-"+name+".json")); asked != nil {
		if _, text := asked.Get("text").(string); asked.Get("kind") == "needs" && text && !asked.Truthy("seen") {
			return false
		}
	}
	card, err := run.ReadJSON(filepath.Join(state, "card-"+name+".json"))
	if err != nil && !errors.Is(err, fs.ErrNotExist) || card != nil && card.Get("word") == "needs you" {
		return false
	}
	if tabs, _ := run.ReadJSON(filepath.Join(state, "browser-tabs.json")); tabs != nil {
		for _, key := range tabs.Keys() {
			if tab, _ := tabs.Get(key).(*run.Object); tab != nil && tab.Dict("opener") != nil && tab.Dict("opener").Get("session") == name {
				return false
			}
		}
	}
	entries, _ := os.ReadDir(run.Runs())
	for _, entry := range entries {
		record, _ := run.Read(filepath.Join(run.Runs(), entry.Name()))
		if record == nil {
			continue
		}
		key := "launched_session" // `session` in a run.json from before its rename
		if !record.Truthy(key) {
			key = "session"
		}
		if launched := record.Str(key); launched != "" {
			if seat, _, err := config.ResolveSession(launched); err == nil && seat == name {
				return false
			}
		}
	}
	return true
}

// close is the half of a stop under the state lock: each record reconciled, then a name nothing
// holds refused, a seat stopped already removed, or else the stop mark written and the session
// ended; whether it removed the seat.
func (found seen) close(state, name string, now time.Time) (bool, error) {
	nothing := !found.live && !found.recorded
	if err := reconcile(state, found.records, nothing); err != nil {
		return false, err
	}
	if nothing {
		running := cmp.Or(strings.Join(found.running, ", "), "none")
		return false, Refusal(fmt.Sprintf("no orchestrator session %s (running: %s)", commandhelp.Quote(name), running))
	}
	if !found.live && found.closed { // stopped already: off the list now rather than when the sweep comes
		return true, forget(state, name)
	}
	// Under the seat's typing lock, the one a rename takes: a line under way finishes into the
	// seat before it closes, and one waiting finds it closed.  The mark goes in ahead of the
	// kill, so whatever meets the session gone finds the seat closed.
	return false, notify.Held(context.Background(), name, func(string) error {
		fields := []field{{"stopped_at", run.Float(seconds(now))}, {"closed_by_owner", true}}
		for _, key := range waits {
			fields = append(fields, field{key, nil})
		}
		if err := writeSeat(state, name, fields); err != nil || !found.live {
			return err
		}
		if err := tmux.Kill(tmux.Own(), name); err != nil {
			return Refusal(fmt.Sprintf("could not stop the session %s: %v", name, err))
		}
		return nil
	})
}

// forgetSeen is Python's watch.forget for a seat the owner stopped: in watch.json, under its
// lock, the seat's alert generation past every one before and its stall record gone; then under
// the seat's typing lock the question its turn's end kept back (notify.clear).
func forgetSeen(state, name string, now time.Time) error {
	err := put(filepath.Join(state, "watch.json"), filepath.Join(state, "watch.lock"), run.Encode, true, func(data *run.Object) bool {
		for _, key := range watchKeys {
			if data.Dict(key) == nil {
				data.Set(key, run.NewObject())
			}
		}
		generations, before := run.NewObject(), data.Dict("seen_at")
		for _, each := range before.Keys() {
			generations.Set(each, generation(before.Get(each)))
		}
		previous, _ := run.Num(generations.Get(name))
		generations.Set(name, math.Max(seconds(now), math.Nextafter(previous, math.Inf(1))))
		data.Set("seen_at", generations)
		data.Dict("stalls").Delete(name)
		return true
	})
	if err != nil {
		return err
	}
	return notify.Held(context.Background(), name, func(current string) error {
		return writeSeat(state, current, []field{{"unasked", nil}})
	})
}

// generation is an alert generation as Python's watch.generation keeps one: a number no less
// than zero whose next is still finite, else 0.
func generation(value any) any {
	if at, ok := run.Num(value); ok && at >= 0 && !math.IsInf(math.Nextafter(at, math.Inf(1)), 0) {
		return value
	}
	return 0
}

// forget is Python's orch.forget_seat, the second half of ending a seat: every file of its own,
// under its name or one a rename left leading to it, off the host, but its locks, which writers
// hold or wait on, and its card, which forgetCard takes; then the stop mark back in its seat
// file where there was one, for a hand-back of its runs to read.  Its own are its regular files,
// never a link; the rest retention.safe asks holds for all of ~/.agentkit, where ak makes no hard
// link and only its owner writes.
func forget(state, name string) error {
	mark, _ := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	entries, err := os.ReadDir(state)
	if err != nil {
		return err
	}
	names := []string{name}
	for _, entry := range entries {
		old, ok := sessionFile(entry.Name())
		if !ok {
			continue
		}
		if held, _ := run.ReadJSON(filepath.Join(state, entry.Name())); held != nil && held.Has(config.Renamed) {
			if target, _, err := config.ResolveSession(old); err == nil && target == name {
				names = append(names, old)
			}
		}
	}
	for _, entry := range entries {
		owner, owned := config.SeatFileOwner(entry.Name())
		if !owned || !slices.Contains(names, owner) || !entry.Type().IsRegular() || entry.Name() == "card-"+name+".json" ||
			strings.HasSuffix(entry.Name(), ".lock") {
			continue
		}
		if err := os.Remove(filepath.Join(state, entry.Name())); err != nil && !errors.Is(err, fs.ErrNotExist) {
			return err
		}
	}
	if mark != nil && mark.Truthy("closed_by_owner") {
		if err := writeSeat(state, name, []field{{"stopped_at", mark.Get("stopped_at")}, {"closed_by_owner", true}}); err != nil {
			return err
		}
	}
	return forgetCard(state, name)
}

// forgetCard is Python's notify.forget_card of a card no outbox holds (plain): gone under the
// seat's typing lock, which stays for whoever holds or waits on it.  A card under an old name
// leading to a renamed seat is not this one's.
func forgetCard(state, name string) error {
	path := filepath.Join(state, "card-"+name+".json")
	if info, err := os.Lstat(path); err != nil || !info.Mode().IsRegular() {
		return nil
	}
	return notify.Held(context.Background(), name, func(current string) error {
		if current != name {
			return nil
		}
		if err := os.Remove(path); err != nil && !errors.Is(err, fs.ErrNotExist) {
			return err
		}
		return nil
	})
}

// stopped is whether a seat file holds the owner's stop mark, as Read knows one: none, or the
// mark whole, nothing it clears left; false where it holds anything else.
func stopped(seat *run.Object) (bool, bool) {
	if seat == nil {
		return false, true
	}
	for _, key := range append([]string{"unasked"}, waits...) {
		if seat.Get(key) != nil {
			return false, false
		}
	}
	if !seat.Has("stopped_at") && !seat.Has("closed_by_owner") {
		return false, true
	}
	at, finite := number(seat.Get("stopped_at"))
	return true, finite && at != 0 && seat.Get("closed_by_owner") == true
}

// quiet is whether watch.json holds nothing a seat's word reads: what watch.forget leaves where
// the watch kept nothing else, every map but the alert generations empty.
func quiet(path string) bool {
	data, err := run.ReadJSON(path)
	if err != nil || data == nil {
		return false
	}
	for _, key := range data.Keys() {
		held := data.Dict(key)
		if !slices.Contains(watchKeys, key) || held == nil || key != "seen_at" && len(held.Keys()) > 0 {
			return false
		}
	}
	return true
}

// sessionFile is the seat a state file is the record or rename pointer of: `session-<seat>.json`.
func sessionFile(file string) (string, bool) {
	seat, prefixed := strings.CutPrefix(file, "session-")
	seat, suffixed := strings.CutSuffix(seat, ".json")
	return seat, prefixed && suffixed
}

// writeSeat merges fields into the seat file under its lock, as Python's watch.seat_write does.
func writeSeat(state, name string, fields []field) error {
	return put(filepath.Join(state, "seat-"+name+".json"), filepath.Join(state, "seat-"+name+".lock"), run.Line, true,
		set(fields, field{"session", name}))
}

// under runs fn holding the lock at path.
func under(path string, fn func() error) error {
	held, err := lock.Wait(context.Background(), path)
	if err != nil {
		return err
	}
	defer held.Close()
	return fn()
}
