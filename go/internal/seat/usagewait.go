package seat

import (
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
	usages "agentkit/internal/usage"
)

// usageAhead is the meters, read with no lock held, where the seat's usage may be waited on as its
// record stands: it ends on its window refusing the turn, as its look would read it, or the one
// subscription of the model it names is spent (spentAlone); nil for none Go reads or for a dry
// look, as collecting them keeps them, false for neither. Health decides again from the model its
// look follows.
func usageAhead(state, name string, models map[string]config.Model) (*usages.Readings, bool) {
	record, _ := run.ReadJSON(filepath.Join(state, "session-"+name+".json"))
	if record == nil {
		return nil, false
	}
	model := record.Str("orchestrator")
	own := models[model].Harness
	reader, known := seatReader(name, record, models)
	said, kept := reader.RecordedError(record)
	if refused, _ := harness.Refusal(own, said); (!known || !kept || !refused) && !spentAlone(model, models[model]) {
		return nil, false
	}
	if drying != nil {
		return nil, true
	}
	readings, err := usages.Collected()
	if err != nil {
		return nil, true
	}
	return readings, true
}

// waitOnUsage is what watch.seat_account does with a seat whose conversation's record ends on its
// window refusing the turn, or whose one subscription is spent, where Go reads all of it, on the
// model its look follows (watch.follow_model), which Health moves the record to before the write: its
// provider lists no accounts, the refusal spends the window, not only limits it for now, the
// seat is neither asking nor done unprompted, nor moving accounts, and no account can take it now --
// it has room only where no wait began and the refusal's own time to try again is still to come,
// and it is spent while one stands.  One refused nothing has no turn its harness wrapped up for the
// limit and no refusal kept unhandled.  Then nothing is typed: the returned write marks the provider
// out until that time where the account had room, keeps the refusal as handled, and puts the seat
// out of usage until its windows come back, to continue there what a limit cut off -- the refused
// turn, or one in flight that is not the owner's own since the wait began.  The caller holds the
// locks the look (found) and the write take, so nothing moves the seat between them.  False, read
// with nothing written, leaves it to Python, as does a wait that would give the seat a word its
// ladder does not read.
func (seat Seat) waitOnUsage(state string, live Live, model string, found sight, readings *usages.Readings, now time.Time, log func(string)) (func() error, bool) {
	models, err := config.Models()
	if err != nil {
		return nil, false
	}
	entry, configured := models[model]
	accounts, err := config.Accounts(entry.Provider)
	refused := live.Refused != ""
	_, limited := harness.Refusal(seat.own, live.Refused)
	waiting, observed, moving := live.File.Dict("usage_wait"), live.File.Dict("usage_refusal"), live.File.Dict("midturn")
	if !configured || err != nil || len(accounts) > 0 ||
		mayRestDone(seat.Name) || refused && limited || !refused && (live.WrappedUp || observed != nil && !observed.Truthy("handled")) ||
		live.State == "asking" || live.File.Truthy("closed_by_owner") || moving != nil && moving.Truthy("account") ||
		live.File.Get("usage_wait") != nil && (waiting == nil || len(waiting.Keys()) == 0) {
		return nil, false
	}
	provider := entry.Provider
	at, line := seconds(now), live.Refused
	until, spent := usages.TryAgainAt(line), readings.Spent(model) != ""
	handled := observed != nil && observed.Get("line") == line && observed.Truthy("handled")
	room := waiting == nil && !spent
	if (waiting != nil || !refused) && !spent || room && (handled || until != 0 && until <= at) {
		return nil, false
	}
	var otherwise, since any = nil, run.Float(at)
	if waiting != nil {
		otherwise, since = waiting.Get("until"), waiting.Get("since")
	}
	// a turn begun since the wait that no limit refused is the owner's, answered by its account
	flight, began := found.turnInFlight(seat.own)
	turned, dated := run.Num(began)
	from, _ := run.Num(since)
	owners := flight && !refused && waiting != nil && dated && turned > from
	continuing := refused || flight && !owners || waiting != nil && waiting.Truthy("continue")
	wait := func(back any) *run.Object {
		when, _ := run.Num(back)
		reason := provider + " out of usage until " + time.Unix(int64(when), 0).Format("2006-01-02 15:04")
		return run.Fields("reason", reason, "until", back, "since", since, "continue", continuing)
	}
	refusal := run.Fields("line", line, "at", run.Float(at), "handled", true)
	// the word the seat takes from the wait is one Go reads, before anything is written
	facts := climbingOf(state, seat, found, at)
	facts.file = facts.file.Copy()
	facts.file.Set("usage_wait", wait(readings.Back(model, nil, otherwise)))
	if refused {
		facts.file.Set("usage_refusal", refusal)
	}
	if _, err := facts.climb(); err != nil {
		return nil, false
	}
	return func() error {
		var marked any
		if room {
			marked = run.Float(usages.MarkExhausted(provider, "", until))
		}
		if refused {
			if err := writeSeat(state, seat.Name, []field{{"usage_refusal", refusal}}); err != nil {
				return err
			}
		}
		waited := wait(readings.Back(model, marked, otherwise))
		if waiting == nil {
			log(seat.Name + ": " + waited.Str("reason"))
		}
		return writeSeat(state, seat.Name, []field{{"usage_wait", waited}})
	}, true
}

// waitingStopped is revivalStopped for a seat whose panes run: a wait on its usage is its
// ladder's to read (usage), not a mark that leaves the seat to Python.
func waitingStopped(file *run.Object) (bool, bool) {
	if file != nil && !file.Truthy("stopped_at") && !file.Truthy("closed_by_owner") {
		file = file.Copy()
		file.Delete("usage_wait")
		file.Delete("usage_refusal")
	}
	return revivalStopped(file)
}
