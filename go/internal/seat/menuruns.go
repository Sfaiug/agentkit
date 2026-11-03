package seat

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
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
	going, live bool
	task        *Task
}

func menuRuns(now time.Time) (map[string][]ran, bool) {
	entries, err := os.ReadDir(run.Runs())
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return nil, false
	}
	mine := map[string][]ran{}
	for _, entry := range entries {
		dir := filepath.Join(run.Runs(), entry.Name())
		if info, err := os.Stat(dir); err != nil || !info.IsDir() {
			continue
		}
		record, err := run.Read(dir)
		if err != nil || record == nil {
			return nil, false
		}
		if record.Truthy("unattended") || run.SmokeRun(record) {
			continue
		}
		view, known := viewRun(record, now)
		if !known {
			return nil, false
		}
		info, err := os.Stat(filepath.Join(dir, "run.json"))
		if err != nil {
			return nil, false
		}
		name := run.Seat(record)
		mine[name] = append(mine[name], ran{name: entry.Name(), record: record, quiet: now.Sub(info.ModTime()).Seconds(), view: &view})
	}
	return mine, true
}

func viewRun(record *run.Object, now time.Time) (runView, bool) {
	state := record.Str("state")
	if !slices.Contains([]string{"queued", "running", "waiting", "pass", "fail", "error", "blocked", "stopped", "not_needed", "interrupted"}, state) {
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
	view := runView{going: run.Going(record, now), live: awaitingLive(record, now)}
	// Parked recovery and an ending still owed to the seat need Python's hand-back reader.
	if run.NeedsRecovery(record) && !view.going || record.Truthy("handback_pending") {
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
