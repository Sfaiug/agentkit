package seat

import (
	"fmt"
	"regexp"
	"slices"
	"strings"

	"agentkit/internal/lifecycle"
	"agentkit/internal/notify"
)

// An owed is what a gone seat owes once back: the line it is told, "" for nothing, and whether its
// end cut off a turn or a question rather than only background work.
type owed struct {
	line string
	turn bool
}

// owing is watch.cut_off, the one read of what a seat owes once back, which a reboot, every tick's
// revival and the idle sleep ask: by what it was doing when its process went, asking or in a turn,
// a Stop on background agents among them, and by the background work it held, named after that
// line or alone, which alone owes nothing where it is only a watch (lifecycle.Watch).  False where
// its harness's manifest cannot be read.
func (seat Seat) owing() (owed, bool) {
	found, err := seat.lastSeen()
	if err != nil {
		return owed{}, false
	}
	work := holding(seat.Name)
	cut := ""
	flight, _ := found.turnInFlight(seat.own)
	switch {
	case found.state == "asking" || notify.OwnerQuestion(notify.Last(seat.Name)):
		cut = QuestionContinue
	case flight:
		cut = MidturnContinue
	}
	if cut == "" && !slices.ContainsFunc(work, func(kind string) bool { return kind != lifecycle.Watch }) {
		return owed{}, true
	}
	if len(work) == 0 {
		return owed{cut, true}, true
	}
	return owed{strings.TrimSpace(cut + " " + fmt.Sprintf(heldContinue, strings.Join(work, ", "))), cut != ""}, true
}

// about is what the revival says of the seat it reopens, as watch.revive_seats words it: what it
// owed, for the event the owner is paged on where it does not come back, what it was cut off in,
// for that page, and what it was asked to do.
func (cut owed) about() (event, when, ask string) {
	if cut.turn {
		return "turn", "in the middle of a turn or a question to you", "go on with its turn"
	}
	return "work", "while it held background work", "pick up its background work"
}

// owedLine is every line owing gives, the fresh note after it or not, which the revival alone
// types.
var owedLine = func() *regexp.Regexp {
	held := strings.Replace(regexp.QuoteMeta(heldContinue), "%s", ".+", 1)
	cut := regexp.QuoteMeta(QuestionContinue) + "|" + regexp.QuoteMeta(MidturnContinue)
	return regexp.MustCompile("^(?:(?:" + cut + ")(?: " + held + ")?|" + held + ")(?:" + regexp.QuoteMeta(freshContinue) + ")?$")
}()
