package seat

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"agentkit/internal/run"
)

func TestTheScreenReadsFullRunsAndLeavesTheirRecordsAlone(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	var files []string
	var before [][]byte
	for id, fields := range []map[string]any{
		{"state": "running", "step": "reviewer", "round_summaries": []any{}, "pid": 123},
		{"state": "running", "step": "done-when"},
		{"state": "waiting", "waiting_on": map[string]any{"line": "acme"}},
		{"state": "queued"},
		{"state": "pass", "step": "merge"},
	} {
		file := runRecord(t, home, string(rune('a'+id)), fields)
		write(t, filepath.Join(filepath.Dir(file), "log.txt"), "worker output")
		data, _ := os.ReadFile(file)
		files, before = append(files, file), append(before, data)
	}
	found, known := Menu(moment)
	if !known || len(found.Seats) != 1 || found.Seats[0].Word != "working" {
		t.Fatalf("known %v: %+v", known, found.Seats)
	}
	want := []Task{{Stage: 0, Moving: true}, {Stage: 0}, {Stage: 1, Moving: true}, {Stage: 2}}
	if got := found.Seats[0].Tasks(); !reflect.DeepEqual(got, want) {
		t.Fatalf("tasks %v, want %v", got, want)
	}
	for i, file := range files {
		if data, _ := os.ReadFile(file); string(data) != string(before[i]) {
			t.Fatalf("screen changed %s", file)
		}
	}
	write(t, files[0], `{"state":"running","title":"\ud800"}`)
	if _, known := Menu(moment); known {
		t.Fatal("a record only Python can keep must hand the screen back")
	}
}

func TestOnlyTheLoopThatWaitedDimsItsTask(t *testing.T) {
	for name, fields := range map[string]*run.Object{
		"gate":       run.Fields("gate_turn", run.Fields("pid", 123)),
		"transient":  run.Fields("transient_wait", run.Fields("pid", 123, "until", seconds(moment)+60)),
		"other loop": run.Fields("transient_wait", run.Fields("pid", 456, "until", seconds(moment)+60)),
		"expired":    run.Fields("transient_wait", run.Fields("pid", 123, "until", seconds(moment)-1)),
	} {
		record := run.Fields("state", "running", "pid", 123, "step", "reviewer")
		for _, key := range fields.Keys() {
			record.Set(key, fields.Get(key))
		}
		view, known := viewRun(record, moment)
		moving := name == "other loop" || name == "expired"
		if !known || !view.going || view.task == nil || view.task.Stage != 1 || view.task.Moving != moving {
			t.Errorf("%s: %+v, known %v", name, view, known)
		}
	}
}

func TestTheScreenReadsLiveSeatsWithRuns(t *testing.T) {
	home := sandbox(t)
	write(t, filepath.Join(home, ".agentkit", "config.toml"), testConfig+"\n[models.spark]\nharness='muse'\nmodel='spark'\neffort='high'\nprovider='test'\n")
	record(t, home, "acme", map[string]any{"workers": []string{"spark"}, "reviewers": []string{"opus"}})
	drawn(t, home, "acme", spinning)
	runRecord(t, home, "going", map[string]any{"state": "running", "step": "executor"})
	if got, known := Menu(moment); !known || len(got.Seats) != 1 || got.Seats[0].Word != "working" {
		t.Fatalf("known %v: %+v", known, got.Seats)
	}
}

func TestADoneSeatOpensItsPlanEvenWhileAsleep(t *testing.T) {
	home := sandbox(t)
	write(t, stateFile(home, "plan-acme.md"), "- [x] The parser is shipped\n")
	seat := Seat{Name: "acme", Word: "done", reason: "asleep: press 1 to wake it"}
	if said := seat.Said(); said != "The parser is shipped" {
		t.Fatal(said)
	}
}

func TestALineGoCannotOrderHandsTheScreenBack(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	runRecord(t, home, "fix-api", map[string]any{"state": "waiting", "waiting_on": map[string]any{"line": "acme/api", "joined": 1, "fix": "failure"}})
	runRecord(t, home, "green-web", map[string]any{"state": "waiting", "waiting_on": map[string]any{"line": "acme/api", "joined": 2, "land": "abc1234"}})
	if _, known := Menu(moment); !known {
		t.Fatal("no seat was told to go first: Go orders the line")
	}
	write(t, stateFile(home, "live-checks/abc1234-1800000000/handed"), `{"seat":"acme"}`)
	if got, known := Menu(moment); known {
		t.Fatalf("a fix that may go first was ranked: %q", got.Seats[0].reason)
	}
}
