package seat

import (
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// AskedWord is the seat's word once notice is the question it asks, as Python's shaped reads it
// after recording one (watch.session_state): the ladder climbed at now on what its last look kept,
// with notice in place of the one on record, since when as its file dates it, and whether the word
// is the question.  A seat nothing is left of has no harness to read, so the question is its word.
// "" where Go does not climb it so: a seat no harness of its own is read for, whose word is its
// reading's, or a rung Go does not read.
func AskedWord(name string, notice *run.Object, now time.Time) (word string, since any, question bool) {
	state := filepath.Join(config.Home(), "state")
	file, _ := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	if file == nil {
		file = run.NewObject()
	}
	if Unheld(name) {
		return "needs you", begun(file, "needs you", config.Fold(notice.Str("text")), notice.Get("time"), now), true
	}
	home, known := seated(now)
	at := slices.IndexFunc(home.Seats, func(each Seat) bool { return each.Name == name })
	if !known || at < 0 || !home.Seats[at].looked() {
		return "", nil, false
	}
	facts := climbingOf(state, home.Seats[at], keptSight(file), seconds(now))
	facts.notice = notice
	said, err := facts.climb()
	if err != nil {
		return "", nil, false
	}
	return said.word, begun(file, said.word, said.reason, said.since, now), said.question
}
