package seat

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"sync"
	"time"

	"agentkit/internal/agent"
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/hookfact"
	"agentkit/internal/lifecycle"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// afterMerge is how long a merge's live check is followed (watch.AFTER_MERGE_WINDOW).
const afterMerge = 3 * 3600

// lookedAt is the seat by that name as a look finds it once its panes have all died, whatever else
// the home holds: its word and reason as watch.announce_state decides them for a seat whose harness
// is gone, its number among every seat the menu offers.  False, for a look that writes nothing,
// where the look does more than that on this path or its word hangs on what Go does not read yet:
// a failed turn to end; a question standing, or kept back, an answer in its conversation may
// answer (notify.answer_written); an account's move or a usage refusal in its seat file; a wait
// or a run of its own short of merged and live; a launch receipt that decides its
// reason; or a number only Python can give. The caller holds the seat's announce lock, so the
// newest facts decide, as watch.announce_state's do.
func lookedAt(state, name string, now time.Time) (Seat, map[string]config.Model, bool) {
	models, err := config.Models()
	offered, unread := config.Offered()
	if err != nil || unread != nil || !slices.Contains(tmux.Dead(tmux.Own()), name) || marked(tmux.Default) {
		return Seat{}, nil, false
	}
	rows, known := places(state, models, now)
	at := slices.IndexFunc(rows, func(row Seat) bool { return row.Name == name })
	if !known || at < 0 {
		return Seat{}, nil, false
	}
	seat := rows[at]
	record, _ := run.ReadJSON(filepath.Join(state, "session-"+name+".json"))
	own := models[record.Str("orchestrator")].Harness
	_, complaint, crewed := recordCrew(record, models)
	if !crewed || failed(name, own) || notify.Standing(name) || record.Truthy(harness.Receipt(own)) {
		return Seat{}, nil, false
	}
	// the follow moves the seat from the model this record names, so both come from one reading
	seat.Orchestrator, seat.own = record.Str("orchestrator"), own
	file, err := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	if err != nil && !errors.Is(err, fs.ErrNotExist) || keptBack(file) {
		return Seat{}, nil, false
	}
	if seat.reader, known = seatReader(name, record, models); !known {
		return Seat{}, nil, false
	}
	if complaint == "" { // a record Python cannot read moves nothing
		if seat.follow, known = follows(record, file, models, offered, seat.reader); !known {
			return Seat{}, nil, false
		}
	}
	if seat.handBacks, known = settled(name, now); !known {
		return Seat{}, nil, false
	}
	seat.closed = file != nil && file.Truthy("closed_by_owner")
	seat.asleep = putToSleep(record, file)
	if err := seat.goneAt(state, at+1, now); err != nil {
		return Seat{}, nil, false
	}
	return seat, models, true
}

// putToSleep is whether the seat was put to sleep since its harness launched, and not closed since
// (sleep.asleep).
func putToSleep(record, file *run.Object) bool {
	asleep, _ := number(record.Get("asleep"))
	launched, _ := number(record.Get("launched"))
	return asleep > launched && (file == nil || !file.Truthy("stopped_at"))
}

// closedReason is why a seat nobody is in reads as it does, and its way back in, that way being
// its number on the menu (watch._session_state's rung 4).
func (seat Seat) closedReason(place int) string {
	reason := fmt.Sprintf("session closed: press %d to reopen", place)
	if seat.asleep {
		reason = fmt.Sprintf("asleep: press %d to wake it", place)
	}
	if seat.closed {
		reason = "session closed by the owner: reopen it from past sessions"
		if seat.handBacks > 0 {
			reason += fmt.Sprintf(" · %d hand-backs waiting", seat.handBacks)
		}
	}
	if seat.restart != "" {
		reason += " · " + seat.restart
	}
	return reason
}

// failed is whether the last event the seat's harness reported ended a turn in failure, which
// watch.hook_look settles before it tells a word.
func failed(name, own string) bool {
	_, event, err := lifecycle.State(own, hookfact.Standing(name))
	return err != nil || event != "" && slices.Contains(lifecycle.Marked(own, "failed"), event)
}

// keptBack is whether the seat file holds what the look leaves for later: a question kept back, an
// account's move, a usage refusal, a line owed, or a wait not yet over.
func keptBack(file *run.Object) bool {
	if file == nil {
		return false
	}
	for _, key := range append([]string{"unasked"}, waits...) {
		if file.Truthy(key) {
			return true
		}
	}
	wait := file.Dict("wait")
	return wait != nil && !wait.Truthy("over")
}

// settled is how many of the seat's own runs wait to hand back, every one merged and past its live
// check; false where one is anything else, which its word would hang on.
func settled(name string, now time.Time) (int, bool) {
	waiting := 0
	for _, dir := range run.Dirs() {
		record, err := run.Read(dir)
		if err != nil && !errors.Is(err, fs.ErrNotExist) {
			return 0, false
		}
		if record == nil || run.SmokeRun(record) || run.Seat(record) != name {
			continue
		}
		if record.Str("state") != "pass" || !record.Truthy("merged") || AwaitingLive(record, now) {
			return 0, false
		}
		if run.Waits(record) {
			waiting++
		}
	}
	return waiting, true
}

// AwaitingLive is whether a merged run's project has yet to prove itself live (watch.awaiting_live).
func AwaitingLive(record *run.Object, now time.Time) bool {
	finished, dated := record.Num("finished_at")
	age := seconds(now) - finished
	health := record.Dict("health")
	return record.Truthy("merged") && !record.Truthy("live_at") && record.Truthy("repo") && dated && 0 <= age && age <= afterMerge &&
		health != nil && health.Truthy("command")
}

// places is every seat the menu offers, in its order (orch.listing with no reconciling): the ones
// tmux holds and the ones only their record does; false where only Python can say which a record
// is, or tmux holds one that has none.
func places(state string, models map[string]config.Model, now time.Time) ([]Seat, bool) {
	entries, err := os.ReadDir(state)
	if err != nil {
		return nil, false
	}
	own := tmux.Sessions(tmux.Own())
	stands := sync.OnceValue(listed)
	var rows []Seat
	var recorded []string
	for _, entry := range entries {
		name, ok := sessionFile(entry.Name())
		if !ok {
			continue
		}
		record, _ := run.ReadJSON(filepath.Join(state, entry.Name()))
		if record == nil || record.Has(config.Renamed) {
			continue
		}
		recorded = append(recorded, name)
		restart, known := harness.Reopens(models[record.Str("orchestrator")].Harness)
		created, dated := number(record.Get("created"))
		held := slices.ContainsFunc(own, func(session tmux.Session) bool { return session.Name == name })
		if !known || !dated || held && created == 0 {
			return nil, false
		}
		if created == 0 {
			created = float64(now.Unix())
		}
		file, _ := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
		stopped := file != nil && file.Truthy("stopped_at")
		if !held && !stopped && restart == "" {
			owned := record.Str("conversation") != "" && record.Str("id_source") == "launcher"
			if _, asked := os.Stat(filepath.Join(state, "notify-"+name+".json")); !owned && (asked == nil || record.Str("conversation") != "") {
				return nil, false // a harness's own evidence, or a question unread, may keep its row
			}
			if !owned {
				continue
			}
		}
		rows = append(rows, Seat{Name: name, Created: created, closed: stopped, held: held, restart: restart, home: homeKey(record.Str("repo"), stands)})
	}
	var strangers []string
	for _, session := range own {
		if !slices.Contains(recorded, session.Name) {
			if session.Mark == "1" {
				return nil, false
			}
			strangers = append(strangers, session.Name)
		}
	}
	if !agent.Agentless(tmux.Own(), strangers) {
		return nil, false
	}
	order(rows)
	return rows, true
}
