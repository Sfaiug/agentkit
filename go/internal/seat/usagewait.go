package seat

import (
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	usages "agentkit/internal/usage"
)

// usageAhead is the meters, read with no lock held, where the seat's record ends on its window
// refusing the turn, as its look would read it; nil for none Go reads, false for no refusal.
func usageAhead(state, name string, models map[string]config.Model) (*usages.Readings, bool) {
	record, _ := run.ReadJSON(filepath.Join(state, "session-"+name+".json"))
	if record == nil {
		return nil, false
	}
	own := models[record.Str("orchestrator")].Harness
	reader, known := harness.For(own).Reconciled(name, record)
	said, kept := reader.RecordedError(record)
	if refused, _ := harness.Refusal(own, said); !known || !kept || !refused {
		return nil, false
	}
	readings, err := usages.Collected()
	if err != nil {
		return nil, true
	}
	return readings, true
}

// waitOnUsage is what watch.seat_account does with a seat whose conversation's record ends on its
// window refusing the turn, where Go reads all of it: its last answer ran on the model its record
// names once Health has followed it (watch.follow_model), its provider lists no accounts,
// the refusal spends the window, not only limits it for now, the seat is neither asking nor done,
// nor moving accounts, and no account can take it now -- it has room only where no wait began and
// the refusal's own time to try again is still to come, and it is spent while one stands.  Then
// nothing is typed: the returned write marks the provider out until that time where the account
// had room, keeps the refusal as handled, and puts the seat out of usage until its windows come
// back.  The caller holds the locks the look and the write take, so nothing moves the seat between
// them.  False, read with nothing written, leaves it to Python.
func (seat Seat) waitOnUsage(state string, live Live, readings *usages.Readings, now time.Time, log func(string)) (func() error, bool) {
	models, err := config.Models()
	if err != nil {
		return nil, false
	}
	model := live.Record.Str("orchestrator")
	entry, configured := models[model]
	accounts, err := config.Accounts(entry.Provider)
	finished, unplanned := plan.Finished(seat.Name)
	_, limited := harness.Refusal(seat.own, live.Refused)
	waiting, observed, moving := live.File.Dict("usage_wait"), live.File.Dict("usage_refusal"), live.File.Dict("midturn")
	if !configured || seat.follow.chosen != "" && seat.follow.chosen != model || err != nil || len(accounts) > 0 ||
		unplanned != nil || finished || limited ||
		live.State == "asking" || live.File.Truthy("closed_by_owner") || moving != nil && moving.Truthy("account") ||
		live.File.Get("usage_wait") != nil && (waiting == nil || len(waiting.Keys()) == 0) {
		return nil, false
	}
	provider := entry.Provider
	at, line := seconds(now), live.Refused
	until, spent := usages.TryAgainAt(line), readings.Spent(model) != ""
	handled := observed != nil && observed.Get("line") == line && observed.Truthy("handled")
	room := waiting == nil && !spent
	if waiting != nil && !spent || room && (handled || until != 0 && until <= at) {
		return nil, false
	}
	return func() error {
		var marked any
		if room {
			marked = run.Float(usages.MarkExhausted(provider, until))
		}
		if err := writeSeat(state, seat.Name, []field{{"usage_refusal", run.Fields("line", line, "at", run.Float(at), "handled", true)}}); err != nil {
			return err
		}
		var otherwise, since any = nil, run.Float(at)
		if waiting != nil {
			otherwise, since = waiting.Get("until"), waiting.Get("since")
		}
		back := readings.Back(model, marked, otherwise)
		when, _ := run.Num(back)
		reason := provider + " out of usage until " + time.Unix(int64(when), 0).Format("2006-01-02 15:04")
		if waiting == nil {
			log(seat.Name + ": " + reason)
		}
		return writeSeat(state, seat.Name, []field{{"usage_wait", run.Fields("reason", reason, "until", back, "since", since, "continue", true)}})
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
