package plan

import (
	"errors"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Ending is Go's one stop, `ak run stop`'s, which loop gives here: of the run in dir as its record
// reads under its lock, the stop carried out for why whatever the home reads by then, or nil where
// the stop is Python's, as every stop is without loop.
var Ending = func(dir string, record *run.Object) func(why string) { return nil }

// A tick is a line this verification ticks on the commit its check passes on, in its repository.
type tick struct {
	line         entry
	repo, commit string
}

// retire is Python's plan.retire of ticks, around write, their write onto the plan: each run that
// only repeats a line ticked ends as a stop ends it, naming the line and the commit.  Such a run is
// queued in the line's repository with the line's check as its follow-up's and never held a slot
// (`slot_started_at`, which a requeue keeps), so never started: it would keep its seat working until
// a slot frees, hours in a busy queue.  Every stop is decided before write, each such run held under
// its lock until the last stop is written, so nothing after write hands over: where one is Python's,
// or a record Go cannot read may be one, it is ErrUnread and nothing is written.
func retire(ticks []tick, write func() error) error {
	var dirs []string
	if len(ticks) > 0 {
		dirs = run.Dirs()
	}
	for i := range ticks {
		if resolved, err := filepath.EvalSymlinks(ticks[i].repo); err == nil {
			ticks[i].repo = resolved // as Python's resolve() names it, which a run's record holds
		}
	}
	var stops []func()
	for _, dir := range dirs {
		if record, err := run.Read(dir); errors.Is(err, run.ErrLoneSurrogate) {
			return ErrUnread
		} else if repeated(record, ticks) == "" {
			continue
		}
		release, err := run.Hold(dir)
		if err != nil {
			return err
		}
		defer release()
		record, err := run.Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) {
			return ErrUnread
		}
		why := repeated(record, ticks)
		if why == "" {
			continue // it moved on before its lock was held
		}
		stop := Ending(dir, record)
		if stop == nil {
			return ErrUnread
		}
		stops = append(stops, func() { stop(why) })
	}
	if err := write(); err != nil {
		return err
	}
	for _, stop := range stops {
		stop()
	}
	return nil
}

// repeated is why a run that only repeats a line of ticks ends, the first it repeats; "" for any
// other run.
func repeated(record *run.Object, ticks []tick) string {
	if record == nil || record.Str("state") != "queued" || !record.Truthy("slot_waiting") || record.Truthy("slot_started_at") {
		return ""
	}
	check := ""
	if followup := record.Dict("followup"); followup != nil {
		check = strings.TrimFunc(followup.Str("check"), config.Space)
	}
	for _, each := range ticks {
		if record.Str("repo") == each.repo && check == strings.TrimFunc(each.line.Check, config.Space) {
			return "plan line \"" + each.line.What + "\" ticked on " + each.commit + ": its check passes there"
		}
	}
	return ""
}
