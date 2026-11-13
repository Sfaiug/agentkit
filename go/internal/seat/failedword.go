package seat

import (
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// failedWord is the word of a seat nobody is in once notice, its failed revival, stands, as Python's
// shaped reads session_state after recording it: the ladder climbed without a screen, as the reading
// climbs such a seat, with notice in place of the one on record, since when as its file dates it.
// "" where that word is not the failure's own, whose text a failure's card would not carry (a
// login's news outranks it, say), and where Go does not read the seat.  A failure is never the
// question.
func failedWord(name string, notice *run.Object, now time.Time) (string, any, bool) {
	home, known := seated(now)
	at := slices.IndexFunc(home.Seats, func(each Seat) bool { return each.Name == name })
	if !known || at < 0 || home.Seats[at].live {
		return "", nil, false
	}
	state := filepath.Join(config.Home(), "state")
	seat := home.Seats[at]
	facts := climbingOf(state, seat, sight{}, seconds(now))
	facts.gone, facts.place, facts.notice = &seat, at+1, notice
	said, err := facts.climb()
	if err != nil || said.reason != config.Fold(notice.Str("text")) {
		return "", nil, false
	}
	file, _ := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	if file == nil {
		file = run.NewObject()
	}
	return said.word, begun(file, said.word, said.since, said.anew, now), false
}
