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
	"agentkit/internal/harness"
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

// stoppable are what a record may hold for Go to stop its seat: all Read follows and the rest an
// opening writes there (Open), none of which Python's stop reads, for a word or anything else.
var stoppable = slices.Concat(recordFields, []string{"reviewers", "account", "home_account", "efforts", "rulebook_sha", "launched"})

// A seen is what a stop finds under Python's watch.state_lock.
type seen struct {
	live, recorded, closed bool     // tmux holds the seat's session; a record keeps it; the owner stopped it
	server                 string   // the server holding its session
	records                []Seat   // every seat's record, which the stop reconciles first (orch.records)
	running                []string // for a name nothing holds, the seats Python's listing offers
	going                  []string // the directories of the runs the seat launched still going
}

// Stop is Python's orch.cmd_stop of the seat by that name, where Go knows the seat: what it says
// once done, or false where the stop is Python's.  Another seat's is refused before anything is
// read of the target (config.check_stop_owner).  The first stop closes the seat and keeps it to
// reopen, then its going runs stop; a stop of one closed already, or of a session no record
// keeps, removes it.  Stopping the seat this runs in says nothing: the terminal went with it.
// Each step takes the locks Python's takes, in its order, so no Python tick or screen meets a
// seat half stopped.
func Stop(arg string, now time.Time) (string, bool, error) {
	name, _, err := config.ResolveSession(arg)
	caller, _, unresolved := config.CurrentSession()
	if err != nil || unresolved != nil {
		return "", false, nil
	}
	if caller != "" && caller != name {
		return "", true, Refusal(fmt.Sprintf("owned by seat %s; a seat stops only its own runs", name))
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
	}
	// outside the lock: nothing a run's stop touches is the seat's state
	said := stopRuns(found.going, now)
	if !removed && !found.recorded { // tmux alone held it: no record to keep, no number to reopen it
		if err := forget(state, name, quietly); err != nil {
			return "", true, err
		}
		removed = true
	}
	notify.ForgetCard(name, quietly)
	if found.live && caller == name {
		return "", true, nil
	}
	if removed {
		said = append(said, "removed "+name)
	} else {
		said = append(said, "stopped "+name+"; its number reopens it")
	}
	return strings.Join(said, "\n"), true, nil
}

// look is what a stop finds of the seat by that name and of every record, as Python's orch.find
// and orch.records find them, or false where the stop is Python's: a session by that name ak did
// not open, a seat needing the owner that other sessions' bars count and would count again
// (statusbar.retell), a record Go does not follow, or something of the seat's own that Python
// ends with it (ownRuns, plain).  A legacy seat's session is on the default server, where no bar
// counts it.
func look(state, name string, now time.Time) (seen, bool) {
	own := tmux.Sessions(tmux.Own())
	_, seats := holdings(state)
	server, held := seats[name]
	found := seen{live: slices.Contains(own, tmux.Session{Name: name, Mark: "1"}) || held && server == tmux.Default, server: server}
	foreign := !found.live && slices.ContainsFunc(own, func(session tmux.Session) bool { return session.Name == name })
	mark, _ := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	counted := found.live && found.server == tmux.Own() && len(own) > 1 && mark != nil && mark.Get("word") == "needs you"
	models, err := config.Models()
	entries, unread := os.ReadDir(state)
	ids, going, known := ownRuns(name)
	if foreign || counted || err != nil || unread != nil || !known || !plain(state, name, ids) {
		return seen{}, false
	}
	found.going = going
	readers := recordReaders{}
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
		seat, known := recorded(state, each, held, models, nil)
		if !known || !only(held, stoppable) {
			return seen{}, false
		}
		found.records = append(found.records, seat)
		readers[each] = seat.reader
		found.recorded = found.recorded || each == name
	}
	found.closed = mark != nil && mark.Truthy("closed_by_owner")
	if found.live || found.recorded {
		return found, true
	}
	// a name nothing holds is refused with the seats the listing offers, once it has written
	// into their records what it reconciles and infers
	home, known := reading(now, false, readRuns, readers)
	found.records = home.records
	for _, each := range home.Seats {
		found.running = append(found.running, each.Name)
	}
	return found, known
}

// plain is whether nothing the seat owns is Python's to end with it: no browser tab it or one of
// its runs opened (browser.close_owned), no question it asked still unseen (notify.clear), and no
// card a webhook took or a question's, which an outbox may hold, nor one Python could not read
// (notify.forget_card).
func plain(state, name string, runs []string) bool {
	if asked, _ := run.ReadJSON(filepath.Join(state, "notify-"+name+".json")); asked != nil {
		if _, text := asked.Get("text").(string); asked.Get("kind") == "needs" && text && !asked.Truthy("seen") {
			return false
		}
	}
	card, err := run.ReadJSON(filepath.Join(state, "card-"+name+".json"))
	if err != nil && !errors.Is(err, fs.ErrNotExist) || card != nil && (card.Truthy("sent") || card.Get("word") == "needs you") {
		return false
	}
	if tabs, _ := run.ReadJSON(filepath.Join(state, "browser-tabs.json")); tabs != nil {
		for _, key := range tabs.Keys() {
			if tab, _ := tabs.Get(key).(*run.Object); tab != nil && tab.Dict("opener") != nil {
				opener := tab.Dict("opener")
				if opener.Get("session") == name || slices.Contains(runs, opener.Str("run")) {
					return false
				}
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
		return true, forget(state, name, quietly)
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
		if err := tmux.Kill(found.server, name); err != nil {
			return Refusal(fmt.Sprintf("could not stop the session %s: %v", name, err))
		}
		return nil
	})
}

// forgetSeen is Python's watch.forget for a seat the owner stopped or a person opened: its next
// alert generation, then under the seat's typing lock the question its turn's end kept back
// (notify.clear).
func forgetSeen(state, name string, now time.Time) error {
	if err := nextGeneration(state, name, now); err != nil {
		return err
	}
	return notify.Held(context.Background(), name, func(current string) error {
		return writeSeat(state, current, []field{{"unasked", nil}})
	})
}

// nextGeneration is watch.forget of a seat a person is opening (`opening`): in watch.json, under
// its lock, the seat's alert generation past every one before and its stall record gone.
func nextGeneration(state, name string, now time.Time) error {
	return put(filepath.Join(state, "watch.json"), filepath.Join(state, "watch.lock"), run.Encode, true, func(data *run.Object) bool {
		generations := watched(data)
		previous, _ := run.Num(generations.Get(name))
		generations.Set(name, math.Max(seconds(now), math.Nextafter(previous, math.Inf(1))))
		data.Dict("stalls").Delete(name)
		return true
	})
}

// watched is watch.json as Python's watch.load_state reads it, each map there, and its alert
// generations.
func watched(data *run.Object) *run.Object {
	for _, key := range watchKeys {
		if data.Dict(key) == nil {
			data.Set(key, run.NewObject())
		}
	}
	generations, before := run.NewObject(), data.Dict("seen_at")
	for _, each := range before.Keys() {
		generations.Set(each, generation(before.Get(each)))
	}
	data.Set("seen_at", generations)
	return generations
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
// hold or wait on, and its card, which notify takes, saying so to log; then the stop mark back in
// its seat file where there was one, for a hand-back of its runs to read.  Its own are its
// regular files, never a link; the rest retention.safe asks holds for all of ~/.agentkit, where ak
// makes no hard link and only its owner writes.
func forget(state, name string, log func(string)) error {
	mark, _ := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	record, _ := run.ReadJSON(filepath.Join(state, "session-"+name+".json"))
	own := config.SeatHarness(name)
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
	notify.ForgetCard(name, log)
	if record != nil {
		if drop, carried := harness.Forgetting(own, record); carried {
			drop() // what its harness kept for it, as Python's plugin `forget`
		}
	}
	return nil
}

// quietly is a stop's log of the card forgetting a seat closes or leaves for a retry, which Go's
// stop leaves unsaid where Python's cmd_stop prints it to stderr.
func quietly(string) {}

// stopped is whether a seat file holds the owner's stop mark, as Read knows one: none, or the
// mark whole, nothing it clears left; false where it holds anything else.
func stopped(seat *run.Object) (bool, bool) {
	if seat == nil {
		return false, true
	}
	for _, key := range waits {
		if key == "owed_lines" && owedReadable(seat) {
			continue
		}
		if seat.Get(key) != nil {
			return false, false
		}
	}
	// a reopening leaves its mark null
	if !seat.Truthy("stopped_at") && !seat.Truthy("closed_by_owner") {
		return false, true
	}
	at, finite := number(seat.Get("stopped_at"))
	return true, finite && at != 0 && seat.Get("closed_by_owner") == true
}

// quiet is whether watch.json holds nothing a seat's word reads but what Go reads: what
// watch.forget leaves where the watch kept nothing else, every map but the alert generations, the
// heads the tick reviewed, a merge's break and stalls nothing is typed past yet empty, beside the
// boot the tick last saw, the record of how the last tick went, when the last tick ended whole
// and worker tokens none of which is dead.
func quiet(path string) bool {
	data, err := run.ReadJSON(path)
	if err != nil || data == nil {
		return false
	}
	data.Delete("boot_resume") // the seats the tick reopened after the boot it last saw
	for _, key := range data.Keys() {
		if key == "boot_id" || key == "tick" || key == "tick_completed_at" || key == "worker_tokens" && !newsOnEverySeat(filepath.Dir(path)) {
			continue
		}
		held := data.Dict(key)
		if !slices.Contains(watchKeys, key) || held == nil || key != "seen_at" && key != "reviewed" && key != "after_merge" && len(held.Keys()) > 0 &&
			!(key == "stalls" && PlainStalls(held)) {
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
