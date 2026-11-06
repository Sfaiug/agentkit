//go:build unix

package tick

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestTheRunRowsLeaveWhatNobodyOwesAlone(t *testing.T) {
	for row, record := range map[string]string{
		// a line under no lander's name of runs/ has no lander to start
		"waiting resume": `{"state":"waiting","waiting_on":{"line":"acme/api"}}`,
		"endings":        `{"state":"pass","verdict":"PASS"}`,
	} {
		t.Run(row, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			path := filepath.Join(ak, "runs", "fix-api", "run.json")
			put(t, path, record)
			tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
			if !tick.through(rows(tick, row)) || read(t, path) != record {
				t.Fatalf("%s: %s", row, read(t, path))
			}
		})
	}
}

// A gone seat's wait ends on its run's fact, marked on the wait the moment it is seen; what Go
// does not carry past that is left to Python with the mark standing.
func TestTheEndedWaitsRowMarksAGoneSeatsWait(t *testing.T) {
	ended := `{"on": "r-build", "kind": "run", "at": 1, "over": "run r-build ended PASS", "run": "r-build"}`
	for _, each := range []struct {
		name, kind, record, file, plan, wait string
		carried, told                        bool
	}{
		{"going", "run", `{"state":"running"}`, "", "", `{"on": "r-build", "kind": "run", "at": 1}`, true, false},
		{"awaiting live", "run", fmt.Sprintf(`{"state":"pass","merged":true,"repo":"/acme","finished_at":%d,"health":{"command":"true"}}`, time.Now().Unix()), "", "",
			`{"on": "r-build", "kind": "run", "at": 1}`, true, false},
		{"closed", "run", `{"state":"pass","verdict":"PASS"}`, `,"closed_by_owner":true,"stopped_at":1`, "", ended, true, false},
		{"work done", "run", `{"state":"running"}`, "", "- [x] Last\n",
			`{"on": "r-build", "kind": "run", "at": 1, "over": "your plan is done and its changes are live", "run": null}`, true, true},
		{"cannot open", "run", `{"state":"pass","verdict":"PASS"}`, "", "", ended, false, false},
		{"own run", "run", `{"state":"pass","verdict":"PASS","launched_session":"acme"}`, "", "", ended, false, false},
		{"pull request", "pr", `{"state":"running"}`, "", "", `{"on": "r-build", "kind": "pr", "at": 1}`, false, false},
	} {
		t.Run(each.name, func(t *testing.T) {
			ak, _ := goneHome(t)
			put(t, filepath.Join(ak, "runs", "r-build", "run.json"), each.record)
			path := filepath.Join(ak, "state", "seat-acme.json")
			put(t, path, fmt.Sprintf(`{"wait":{"on":"r-build","kind":%q,"at":1}%s}`, each.kind, each.file))
			if each.plan != "" {
				put(t, filepath.Join(ak, "state", "plan-acme.md"), each.plan)
			}
			tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
			if carried := tick.through(rows(tick, "ended waits")); carried != each.carried {
				t.Fatalf("carried=%v", carried)
			}
			file, _ := run.ReadJSON(path)
			wait := file.Dict("wait")
			if told := wait.Truthy("told"); told != each.told {
				t.Fatalf("told=%v", told)
			}
			wait.Delete("told")
			if run.Line(wait) != each.wait {
				t.Fatal(run.Line(wait))
			}
		})
	}
}

// Its wait reopens it once that ends, and one that could not be reopened then is the owner's it
// was paged as; a turn its end cut off is still the revival's.
func TestTheRevivalRowLeavesASeatGoneWhileItsWaitStands(t *testing.T) {
	ak, _ := goneHome(t)
	put(t, filepath.Join(ak, "runs", "r-build", "run.json"), `{"state":"running"}`)
	told := `,"over":"run r-build ended PASS","run":"r-build","told":2`
	for _, each := range []struct {
		wait, file, source string
		carried            bool
	}{
		{"", "", "", true},
		{"", `,"state":"working"`, "", false},
		{told, "", "wait:acme:1", true},
		{told, `,"state":"working"`, "wait:acme:1", false},
		{told, "", "revive:acme:turn:1", false},
	} {
		put(t, filepath.Join(ak, "state", "seat-acme.json"), `{"wait":{"on":"r-build","kind":"run","at":1`+each.wait+"}"+each.file+"}")
		notice := filepath.Join(ak, "state", "notify-acme.json")
		os.Remove(notice)
		if each.source != "" {
			put(t, notice, run.Line(run.Fields("session", "acme", "kind", "needs", "text", "Its orchestrator session acme is gone", "source", each.source, "watcher", true, "time", 1.0)))
		}
		tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
		if tick.through(rows(tick, "seat revival")) != each.carried {
			t.Fatalf("%+v: carried=%v", each, !each.carried)
		}
	}
}

// A seat its wait's end could not reopen is the owner's, paged once: that tick's card follows the
// word the page gave it, not the one published before it.
func TestAFailedWaitReopenIsCardedThatTick(t *testing.T) {
	ak := revivalHome(t)
	put(t, filepath.Join(ak, "runs", "r-build", "run.json"), `{"state":"pass","verdict":"PASS"}`)
	path := filepath.Join(ak, "state", "seat-acme.json")
	put(t, path, `{"word":"working","reason":"waiting on r-build","word_since":1,"wait":{"on":"r-build","kind":"run","at":1}}`)
	tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
	if !tick.through(append(rows(tick, "ended waits"), rows(tick, "card transitions")...)) {
		t.Fatal("the failed reopen was left to Python")
	}
	file, _ := run.ReadJSON(path)
	notice, _ := run.ReadJSON(filepath.Join(ak, "state", "notify-acme.json"))
	if !file.Dict("wait").Truthy("told") || file.Str("word") != "needs you" || notice.Str("source") != "wait:acme:1" {
		t.Fatalf("seat=%s notice=%s", run.Line(file), run.Line(notice))
	}
}

func rows(tick *ticking, name string) []pass {
	for _, each := range table(tick) {
		if each.name == name {
			return []pass{each}
		}
	}
	return nil
}
