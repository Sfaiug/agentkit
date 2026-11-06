package seat

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// CardWord is the seat's word as its card takes it, Python's transition: the ladder climbed now on
// what its last look kept, with its runs, notices and plan as they stand, nothing captured or
// written, and since when as its file dates it.  A seat nothing is left of has no harness to read,
// so its own question is its word (watch.session_state of a name no listing holds).  "" where Go
// does not read the seat.
func CardWord(name string) (string, any) {
	word, _, since := CardAnswer(name)
	return word, since
}

// CardAnswer is CardWord with the reason the ladder gives that word, the text a need's card goes
// out with (notify.needs_transition's answer).
func CardAnswer(name string) (word, reason string, since any) {
	now := time.Now()
	home, known := seated(now)
	if !known {
		return "", "", nil
	}
	state := filepath.Join(config.Home(), "state")
	file, _ := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	if file == nil {
		file = run.NewObject()
	}
	at := slices.IndexFunc(home.Seats, func(each Seat) bool { return each.Name == name })
	var seat Seat
	switch {
	case at >= 0:
		seat = home.Seats[at]
	case Unheld(name):
		mine, read := lookRuns(nil, time.Now()) // judged as they are read, as the reading judges its own
		if !read {
			return "", "", nil
		}
		seat = Seat{Name: name, mine: mine[name]}
	default:
		return "", "", nil
	}
	// a seat nobody is in, or one no harness is read for, was worded by the reading itself
	if (at < 0 || seat.looked()) && seat.decided(state, keptSight(file), seconds(now), false) != nil {
		return "", "", nil
	}
	return seat.Word, seat.reason, begun(file, seat.Word, seat.since, now)
}

// Unheld is whether nothing of that seat is left on the host but what it said (watch.seat_closed of
// a seat orch.find does not find): no record keeps it, no tmux server holds a session by its name,
// and no close of its owner's waits for its reopening.
func Unheld(name string) bool {
	path, err := config.SessionPath(name)
	if _, missing := os.Lstat(path); err != nil || !errors.Is(missing, fs.ErrNotExist) {
		return false
	}
	file, _ := run.ReadJSON(filepath.Join(config.Home(), "state", "seat-"+name+".json"))
	return (file == nil || !file.Truthy("closed_by_owner")) &&
		tmux.Absent(tmux.Own(), "="+name) && tmux.Absent(tmux.Default, "="+name)
}

// keptSight is what the seat's last look kept in its file, the sight Python's card reads it by.
func keptSight(file *run.Object) sight {
	hooked, _ := file.Get("hooked").(string)
	event, _ := file.Get("hooked_event").(string)
	return sight{state: file.Str("state"), authority: file.Str("authority"), rule: file.Str("rule"), evidence: file.Str("evidence"),
		since: file.Get("since"), began: file.Get("began"), stall: file.Get("stall"), login: file.Get("login"),
		hooked: hooked, hookedEvent: event, hookedAt: file.Get("hooked_at"), interrupted: file.Truthy("interrupted")}
}

// begun is since when a word stands (watch.session_state): from where the seat's file dates it, for
// the word it holds; from now, for another; and from the rung's own evidence where it held none.
func begun(previous *run.Object, word string, since any, now time.Time) any {
	switch {
	case run.Equal(previous.Get("word"), word):
		if previous.Has("word_since") {
			return previous.Get("word_since")
		}
	case previous.Get("word") != nil:
		return run.Float(seconds(now))
	}
	return since
}
