package seat

import (
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/lifecycle"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/screen"
)

// nudgeQuestion is watch.stop_nudge, where its stop is typed at the seat, for a question its closing
// message left out of the chat (questions.unseen): the reminder goes back, once a stop, past the
// question standing and with no turn watched to its end, and a reply of the owner's answers it
// first.  A dry look asks and answers nothing, reads what the seat kept back as asked, as the real
// look's askKeptBack has asked it by then, and says the reminder it would type where the seat file
// as saved passes its guards (savedStop), Python's dry tick's to say otherwise.  Under Health's
// announce lock, as nudgeOpenWork; the confirmed send rechecks the composer under the typing lock.
func (seat Seat) nudgeQuestion(state string, found sight, log func(string)) (sight, error) {
	flight, _ := found.turnInFlight(seat.own)
	if nudged, err := lifecycle.Nudged(seat.own); err != nil || !nudged || flight || found.interrupted || found.stall != nil || found.login != nil {
		return found, err
	}
	facts := climbingOf(state, seat, found, 0)
	if drying != nil { // asked by now (askKeptBack): at its prompt, no turn in flight
		facts.file.Delete("unasked")
	}
	if back, err := facts.goesBack(); err != nil || !back {
		return found, err
	}
	if drying == nil {
		if _, _, err := answerWritten(state, seat.Name, seconds(time.Now()), 0); err != nil {
			return found, err
		}
	}
	reminder, err := questionUnseen(seat.Name, seat.own, found, notify.Last(seat.Name))
	if err != nil || reminder == "" {
		return found, err
	}
	episode, err := stopEpisode(seat.own, facts.file)
	if err != nil {
		return found, err
	}
	const why = "left its question out of the chat"
	if drying != nil {
		if !seat.savedStop(state) {
			return found, errDry
		}
		log("would resume " + seat.Name + ", " + why + ", with " + commandhelp.Quote(reminder))
		return found, nil
	}
	at := seatAt{seat.Name, seat.own, "=" + seat.Name + ":"}
	stale := func(current string) bool {
		pane := at.capture()
		latest := climbingOf(state, seat, at.sight(pane), 0)
		if latest.found.state == "draft" && latest.found.typedByAk {
			latest.found.state = "at_prompt" // the confirmed send rechecks with our line in the composer
		}
		back, err := latest.goesBack()
		now, unread := stopEpisode(seat.own, latest.file)
		return current != seat.Name || err != nil || unread != nil || !back || !run.Equal(now, episode) ||
			latest.found.interrupted || stopWords(eyeOf(seat.own).rules, screen.Tail(pane)) != facts.file.Str("stop_said")
	}
	if !typeInto(seat.Name, reminder, log, stale) {
		return found, nil
	}
	if err := Write(seat.Name, "stop_nudged", episode); err != nil {
		return found, err
	}
	log(seat.Name + ": " + why + "; typed " + commandhelp.Quote(reminder))
	return seat.look(state, seconds(time.Now()))
}
