package seat

import (
	"path/filepath"
	"time"

	"agentkit/internal/run"
)

// Task is a run still in flight: build, review or land, and whether a model works on it.
type Task struct {
	Stage  int
	Moving bool
}

// runView is what a full record says to the row's ladder and to its open line together.
type runView struct {
	going, live, needs, parked, undecided bool
	task                                  *Task
}

// screenRuns is what the open screen knows of the runs between its reads: a run at rest is as its
// last full read found it, on the rows and in what a frame's looks decide from them (Home.runs).
// Every other reader decides on what it reads, and looks at every run.
var screenRuns run.Reader

// judging judges the runs one read of a run.Reader found, at whatever moment it is given.
func judging(held []run.Held) judges {
	return func(now time.Time) (map[string][]ran, bool) {
		mine, _, known := menuRuns(held, now)
		return mine, known
	}
}

// menuRuns is each seat's runs as those records give them at that moment, and every run by the
// seat it files under.
func menuRuns(held []run.Held, now time.Time) (map[string][]ran, map[string][]ran, bool) {
	mine := map[string][]ran{}
	projects := map[string][]ran{}
	var records []*run.Object
	census := make([]*run.Object, len(held))
	for i, each := range held {
		census[i] = each.Record
	}
	seats := run.Seats()
	for _, each := range held {
		if each.Smoke {
			continue
		}
		record, name := each.Record, seats(each.Record)
		projects[name] = append(projects[name], ran{record: record})
		if record.Truthy("unattended") {
			continue
		}
		records = append(records, record)
		view, known := viewRun(record, now)
		if !known {
			return nil, nil, false
		}
		mine[name] = append(mine[name], ran{name: each.Name, record: record, quiet: silence(filepath.Join(run.Runs(), each.Name), record, now), view: &view, census: census})
	}
	index := run.NewIndex(records)
	for _, runs := range mine {
		for _, each := range runs {
			each.view.needs = index.NeedsLook(each.record, now)
			each.view.undecided = index.Unfinished(each.record)
			each.view.parked = parked(each.record, *each.view, index, now)
		}
	}
	return mine, projects, true
}

func viewRun(record *run.Object, now time.Time) (runView, bool) {
	state := record.Str("state")
	if !run.Active(record) && !run.Ended(record) && state != "waiting" && state != "interrupted" && state != "stalled" && state != "exhausted" {
		return runView{}, false
	}
	for _, field := range []string{"waiting_on", "gate_turn", "transient_wait", "process_identity", "lease_wait", "health"} {
		if record.Truthy(field) && record.Dict(field) == nil {
			return runView{}, false
		}
	}
	for _, field := range []string{"started_at", "finished_at", "error_retry_at"} {
		if _, known := number(record.Get(field)); !known {
			return runView{}, false
		}
	}
	if view, known := decisionRun(record); known {
		return view, true
	}
	view := runView{going: run.Going(record, now), live: awaitingLive(record, now)}
	// Other parked recovery still needs Python's reader; a parked error, exhausted run or merge wait is rung 3's (runParked).
	if !view.going && state != "error" && state != "exhausted" && run.NeedsRecovery(record) {
		return runView{}, false
	}
	stage := map[string]int{"executor": 0, "done-when": 0, "reviewer": 1, "merge": 2}[record.Str("step")]
	if state == "waiting" && record.Dict("waiting_on") != nil && record.Dict("waiting_on").Truthy("line") || view.live {
		view.task = &Task{Stage: 2}
	} else if view.going {
		moving := state == "running" && run.GateTurnNote(record) == ""
		if wait := record.Dict("transient_wait"); wait != nil && run.Equal(wait.Get("pid"), record.Get("pid")) && run.FirstNumber(wait, "until") > seconds(now) {
			moving = false
		}
		if record.Truthy("delivery_wait") && run.Equal(record.Get("delivery_wait"), record.Get("pid")) && run.ProcessActive(record) {
			moving = false
		}
		view.task = &Task{Stage: stage, Moving: moving}
	}
	return view, true
}

func awaitingLive(record *run.Object, now time.Time) bool {
	finished, known := record.Num("finished_at")
	health := record.Dict("health")
	age := seconds(now) - finished
	return record.Truthy("merged") && !record.Truthy("live_at") && record.Truthy("repo") && known &&
		age >= 0 && age <= 3*3600 && health != nil && health.Truthy("command")
}

// runsAwaitingLive is rung 3a: only where nothing below is the owner's either, so a run of its own
// undecided (the stop hook's `unfinished`, which it puts first) or a watcher's alert keeps the word
// a lower rung gives it.  A parked one rung 3 has already answered.
func runsAwaitingLive(facts climbing) (*answer, error) {
	if _, err := aRunOfItsOwn(facts); err != nil {
		return nil, err
	}
	if facts.notice != nil {
		return nil, nil
	}
	for _, each := range facts.mine {
		if each.view != nil && each.view.undecided {
			return nil, nil
		}
	}
	var pending []ran
	for _, each := range facts.mine {
		if each.view != nil && each.view.live {
			pending = append(pending, each)
		}
	}
	if len(pending) == 0 {
		return nil, nil
	}
	return waitingOnLive(pending), nil
}
