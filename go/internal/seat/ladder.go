package seat

import (
	"cmp"
	"fmt"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
)

// climbing is what one seat's ladder is climbed with, each read fresh once its look has asked what
// it kept back; before the look its sight is none, which no rung's refusal hangs on.
type climbing struct {
	state, name, own string
	mine             []ran
	file, notice     *run.Object
	found            sight
	now              float64
	gone             *Seat
	place            int
}

// An answer is a rung's: the seat's word, why and since when, whether that why is the question
// the seat's screen or notice asks, which its bar does not repeat, and when one out of usage comes
// back (`resumes_at`), which its bar says.
type answer struct {
	word, reason string
	since        any
	question     bool
	back         any
}

// A rung decides the seat, nil where it passes the seat on, or says with ErrUnread that Go does not
// read what it hangs on yet. Every rung is pure, so a look can decide before it writes.
type rung func(climbing) (*answer, error)

// ladder is watch._session_state's, top rung first. Python's rung names are in brackets where it
// numbers them.
var ladder = []rung{
	loginOut,          // [1]
	runOnALogin,       // [1a]
	everySeatsNews,    // [1b] gh, [1c] a worker token
	onItsScreen,       // [1d]
	repeatingQuestion, // what questions.unseen sends back
	ownQuestion,
	moveFailed,
	failedRevival,
	runsGoing, // [2]
	waitGoing, // [2a]
	turnRunning,
	runParked, // [3]
	usageWait, // [3b]
	retrying,  // [3c]
	liveCheck, // [3a]
	nobodyIn,  // [4]
	alert,     // [5]
	telling,
	stillOwed,
	planFinished,
}

// climbingOf is what the seat's files say now, with what the home's reading found of its runs.
func climbingOf(state string, seat Seat, found sight, now float64) climbing {
	file, _ := run.ReadJSON(filepath.Join(state, "seat-"+seat.Name+".json"))
	if file == nil {
		file = run.NewObject()
	}
	return climbing{state: state, name: seat.Name, own: seat.own, mine: seat.mine, file: file,
		notice: notify.Last(seat.Name), found: found, now: now}
}

// readable follows the same ladder as the word: a going run already decides the seat
// before its idle plan's send-back, whose reads are still Python's.
func (facts climbing) readable() bool {
	_, err := facts.climb()
	return err == nil
}

// climb is the first rung's answer; at the top of nothing the seat rests.
func (facts climbing) climb() (answer, error) {
	for _, each := range ladder {
		if said, err := each(facts); err != nil || said != nil {
			if err != nil {
				return answer{}, err
			}
			return *said, nil
		}
	}
	return answer{word: "idle", since: facts.found.began}, nil
}

// decided sets the seat's word from its ladder.  Typed text nobody sent is no word of its own: it
// goes beside it, once nobody is in the seat to see it, while its composer is open.
func (seat *Seat) decided(state string, found sight, now float64, attached bool) error {
	said, err := climbingOf(state, *seat, found, now).climb()
	if err != nil {
		return err
	}
	seat.Word, seat.reason, seat.since, seat.question, seat.back = said.word, said.reason, said.since, said.question, said.back
	seat.seen = found
	seat.unsent = ""
	if found.state == "draft" && !attached && found.composerOpen(seat.own) && !found.typedByAk {
		seat.unsent = config.Fold(found.evidence)
	}
	seat.wordFrom = found.wordFrom()
	return nil
}

// wordFrom is what of a sight a seat's word is decided from and kept beside it (watch.word_from).
func (found sight) wordFrom() []any {
	said := ""
	switch {
	case found.state == "asking" || found.state == "draft":
		said = found.evidence
	case found.stall != nil:
		said, _ = found.stall.(string)
	case found.login != nil:
		said, _ = found.login.(string)
	}
	return []any{found.state, found.rule, said}
}

// loginOut: a login its harness needs expired, whose remedy Go does not word yet.
func loginOut(facts climbing) (*answer, error) {
	if loggedOut(facts.state, facts.own) {
		return nil, ErrUnread
	}
	return nil, nil
}

// aRunOfItsOwn: any run of the seat's own, at each of the rungs a run decides.
func aRunOfItsOwn(facts climbing) (*answer, error) {
	if facts.gone == nil {
		for _, each := range facts.mine {
			if each.view == nil {
				return nil, ErrUnread
			}
		}
	}
	return nil, nil
}

func runOnALogin(facts climbing) (*answer, error) { return aRunOfItsOwn(facts) }
func runsGoing(facts climbing) (*answer, error)   { return goneRuns(facts) }
func liveCheck(facts climbing) (*answer, error)   { return runsAwaitingLive(facts) }

// everySeatsNews: the login no harness owns, or a worker token, dead.
func everySeatsNews(facts climbing) (*answer, error) {
	if newsOnEverySeat(facts.state) {
		return nil, ErrUnread
	}
	return nil, nil
}

// onItsScreen: a question on its screen is the owner's even during a turn.
func onItsScreen(facts climbing) (*answer, error) {
	if facts.found.state != "asking" {
		return nil, nil
	}
	return &answer{"needs you", cmp.Or(config.Fold(facts.found.evidence), "waiting for you"), facts.found.began, true, nil}, nil
}

// ownQuestion: one it asked with `ak notify needs`, nothing having answered it, once the turn it
// stood through has stopped.  A watcher's own alert waits for its prompt (alert).
func ownQuestion(facts climbing) (*answer, error) {
	if facts.gone != nil || !notify.OwnerQuestion(facts.notice) {
		return nil, nil
	}
	// a seat waiting on its usage was refused mid-turn: no turn is in flight, whatever its screen shows
	if !facts.found.composerOpen(facts.own) {
		if waiting, err := usage(facts); waiting == nil {
			return nil, err
		}
	}
	return &answer{"needs you", config.Fold(facts.notice.Str("text")), facts.notice.Get("time"), true, nil}, nil
}

// usage is the seat's wait on its subscription, which its seat file keeps: none for a seat nobody is
// in or the owner closed.  ErrUnread where its word hangs on what Go does not read: a move to another
// account that failed, a wait no limit cut a turn off for, one its runs or its `ak wait` stand
// beside, a done plan, or a refusal kept with no wait.
func usage(facts climbing) (*run.Object, error) {
	if facts.gone != nil || facts.file.Truthy("closed_by_owner") {
		return nil, nil
	}
	wait := facts.file.Dict("usage_wait")
	if wait == nil && facts.file.Get("usage_wait") == nil && facts.file.Get("usage_refusal") == nil {
		return nil, nil
	}
	if wait == nil {
		return nil, ErrUnread
	}
	finished, err := plan.Finished(facts.name)
	if _, said := wait.Get("reason").(string); !said || !wait.Has("since") || !wait.Truthy("until") || !wait.Truthy("continue") ||
		err != nil || finished || len(facts.mine) > 0 || facts.file.Get("wait") != nil {
		return nil, ErrUnread
	}
	return wait, nil
}

func moveFailed(facts climbing) (*answer, error) {
	_, err := usage(facts)
	return nil, err
}

// usageWait: its subscription ran out, and ak resumes it when the usage comes back.
func usageWait(facts climbing) (*answer, error) {
	wait, err := usage(facts)
	if wait == nil {
		return nil, err
	}
	return &answer{word: "out of usage", reason: wait.Str("reason"), since: wait.Get("since"), back: wait.Get("until")}, nil
}

// waitGoing: it ended its turn on `ak wait`, and what it named is not over (watch.waiting_on).
func waitGoing(facts climbing) (*answer, error) {
	wait := facts.file.Dict("wait")
	if wait == nil || wait.Truthy("over") || wait.Str("kind") != "pr" && wait.Str("kind") != "run" {
		return nil, nil
	}
	on, named := wait.Get("on").(string)
	if !named {
		return nil, nil
	}
	var since any
	if _, dated := wait.Num("at"); dated {
		since = wait.Get("at")
	}
	return &answer{word: "working", reason: "waiting on " + on, since: since}, nil
}

// turnRunning: a turn in flight, past three hours saying so and keeping the word.
func turnRunning(facts climbing) (*answer, error) {
	flight, began := facts.found.turnInFlight(facts.own)
	if waiting, _ := usage(facts); !flight || waiting != nil {
		return nil, nil
	}
	reason := ""
	if at, dated := run.Num(began); dated && facts.now-at > turnSeconds {
		reason = "turn running " + terminal.FormatAge(facts.now-at)
	}
	return &answer{word: "working", reason: reason, since: began}, nil
}

// retrying: its turn stopped on an error the tick types it back past.
func retrying(facts climbing) (*answer, error) {
	if facts.found.stall == nil {
		return nil, nil
	}
	return &answer{word: "working", reason: fmt.Sprintf("retrying: %v", facts.found.stall), since: facts.found.began}, nil
}

// alert: a watcher's alert on the seat, at its prompt with nothing running.
func alert(facts climbing) (*answer, error) {
	if facts.notice == nil {
		return nil, nil
	}
	return &answer{word: "needs you", reason: config.Fold(facts.notice.Str("text")), since: facts.notice.Get("time")}, nil
}

// telling: ak still has to tell it its wait is over (watch.news_owed).  A line a revive owes it stops
// its reading (`stopped`), and an ending of its runs aRunOfItsOwn, before this is reached.
func telling(facts climbing) (*answer, error) {
	wait := facts.file.Dict("wait")
	if wait == nil || !wait.Truthy("over") || wait.Truthy("told") || facts.found.authority == "" ||
		facts.found.state != "at_prompt" && facts.found.state != "draft" {
		return endingNews(facts)
	}
	return &answer{word: "working", reason: fmt.Sprintf("telling it its wait on %v is over", wait.Get("on")), since: facts.found.began}, nil
}

// stillOwed: nothing running, asked or owed it news, it is the owner's while its plan owes a line,
// unless the owner stopped its turn and so knows; and while a question it kept back is unasked.
func stillOwed(facts climbing) (*answer, error) {
	line, owes := "", false
	if !facts.found.interrupted {
		var err error
		if line, owes, err = plan.OwedLine(facts.name); err != nil {
			return nil, ErrUnread
		}
	}
	if back, err := openWork(facts, line); err != nil || back != nil {
		return back, err
	}
	if !owes && !facts.file.Truthy("unasked") {
		return nil, nil
	}
	reason := "stopped with work open"
	if line != "" {
		reason += ": " + line
	}
	return &answer{word: "needs you", reason: reason, since: facts.found.began}, nil
}

// planFinished: a plan whose every line is proven is done, which ak reads and nobody declares; it
// says what it did last.  A run of its own, which could still wait on the owner, aRunOfItsOwn reads.
func planFinished(facts climbing) (*answer, error) {
	finished, err := plan.Finished(facts.name)
	if err != nil {
		return nil, ErrUnread
	}
	if !finished {
		return nil, nil
	}
	return &answer{word: "done", reason: config.Fold(plan.LastDone(facts.name)), since: facts.found.began}, nil
}
