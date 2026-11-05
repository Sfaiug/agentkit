package seat

import (
	"errors"
	"io/fs"
	"os"
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
	going, live, needs bool
	task               *Task
}

func menuRuns(now time.Time) (map[string][]ran, map[string][]ran, bool) {
	entries, err := os.ReadDir(run.Runs())
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return nil, nil, false
	}
	mine := map[string][]ran{}
	projects := map[string][]ran{}
	var records []*run.Object
	for _, entry := range entries {
		dir := filepath.Join(run.Runs(), entry.Name())
		if info, err := os.Stat(dir); err != nil || !info.IsDir() {
			continue
		}
		record, err := run.Read(dir)
		if errors.Is(err, fs.ErrNotExist) {
			continue
		}
		if err != nil || record == nil {
			return nil, nil, false
		}
		if run.SmokeRun(record) {
			continue
		}
		name := run.Seat(record)
		projects[name] = append(projects[name], ran{record: record})
		if record.Truthy("unattended") {
			continue
		}
		records = append(records, record)
		view, known := viewRun(record, now)
		if !known {
			return nil, nil, false
		}
		info, err := os.Stat(filepath.Join(dir, "run.json"))
		if err != nil {
			return nil, nil, false
		}
		mine[name] = append(mine[name], ran{name: entry.Name(), record: record, quiet: now.Sub(info.ModTime()).Seconds(), view: &view})
	}
	index := run.NewIndex(records)
	for _, runs := range mine {
		for _, each := range runs {
			each.view.needs = index.NeedsLook(each.record, now)
		}
	}
	return mine, projects, true
}

func viewRun(record *run.Object, now time.Time) (runView, bool) {
	state := record.Str("state")
	if !run.Active(record) && !run.Ended(record) && state != "waiting" && state != "interrupted" {
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
	// Other parked recovery still needs Python's reader; a parked error is rung 3's (runParked).
	if !view.going && state != "error" && (run.NeedsRecovery(record) || state == "waiting") {
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

func runsAwaitingLive(facts climbing) (*answer, error) {
	if _, err := aRunOfItsOwn(facts); err != nil {
		return nil, err
	}
	if facts.notice != nil {
		return nil, nil
	}
	for _, each := range facts.mine {
		if each.view != nil && each.view.live {
			return &answer{word: "working", reason: "waiting on the live check", since: each.record.Get("finished_at")}, nil
		}
	}
	return nil, nil
}
