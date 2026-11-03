package seat

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestStopsLeftToPython(t *testing.T) {
	for name, build := range map[string]func(t *testing.T, state string){
		"a run still going with a loop to end": func(t *testing.T, state string) {
			runRecord(t, filepath.Dir(filepath.Dir(state)), "r-going", map[string]any{"state": "running", "pid": 4242})
		},
		"a run still going with a checkout to take": func(t *testing.T, state string) {
			runRecord(t, filepath.Dir(filepath.Dir(state)), "r-going", map[string]any{"state": "waiting", "worktree": "/wt/r-going"})
		},
		"a run still going that history records": func(t *testing.T, state string) {
			runRecord(t, filepath.Dir(filepath.Dir(state)), "r-going", map[string]any{"state": "running"})
			write(t, filepath.Join(filepath.Dir(state), "history.db"), "")
		},
		"a run still going under a job's name": func(t *testing.T, state string) {
			runRecord(t, filepath.Dir(filepath.Dir(state)), "r-going", map[string]any{"state": "running"})
			write(t, filepath.Join(filepath.Dir(state), "jobs", "r-going", "job.json"), `{"job_id": "r-going"}`)
		},
		"a finished run whose checkout goes with the seat": func(t *testing.T, state string) {
			runRecord(t, filepath.Dir(filepath.Dir(state)), "r-done", map[string]any{"state": "pass", "worktree": "/wt/r-done"})
		},
		"an error the tick may retry": func(t *testing.T, state string) {
			runRecord(t, filepath.Dir(filepath.Dir(state)), "r-error", map[string]any{"state": "error"})
		},
		"a run stopped to wait on an older run": func(t *testing.T, state string) {
			runRecord(t, filepath.Dir(filepath.Dir(state)), "r-parked", map[string]any{"state": "stopped", "lease_wait": map[string]any{}})
		},
		"a browser tab one of its runs opened": func(t *testing.T, state string) {
			runRecord(t, filepath.Dir(filepath.Dir(state)), "r-done", map[string]any{"state": "pass"})
			write(t, filepath.Join(state, "browser-tabs.json"), `{"T1": {"opener": {"run": "r-done"}}}`)
		},
		"browser tabs recorded as its own": func(t *testing.T, state string) {
			write(t, filepath.Join(state, "browser-tabs.json"), `{"T1": {"opener": {"session": "acme"}}}`)
		},
		"a card a webhook took": func(t *testing.T, state string) {
			write(t, filepath.Join(state, "card-acme.json"), `{"word": "done", "episode": "e1", "sent": true}`)
		},
		"a question's card, which a webhook may have taken": func(t *testing.T, state string) {
			write(t, filepath.Join(state, "card-acme.json"), `{"word": "needs you", "episode": "e1"}`)
		},
		"a question it asked still unseen": func(t *testing.T, state string) {
			write(t, filepath.Join(state, "notify-acme.json"), `{"kind": "needs", "text": "Which branch?"}`)
		},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			state := filepath.Join(home, ".agentkit", "state")
			record(t, home, "acme", nil)
			build(t, state)
			if _, known, err := Stop("acme", moment); known || err != nil {
				t.Fatalf("Go stopped it: known=%v err=%v", known, err)
			}
			if _, err := os.Stat(filepath.Join(state, "seat-acme.json")); !errors.Is(err, fs.ErrNotExist) {
				t.Fatalf("the stop mark went in: %v", err)
			}
		})
	}
}

// What an opening writes into a record no stop of Python's reads; a key nothing here knows may be.
func TestStopReadsARecordAnOpeningWrote(t *testing.T) {
	home := sandbox(t)
	opened := map[string]any{"account": "second", "home_account": "second", "efforts": map[string]any{"opus": map[string]any{"effort": "xhigh"}},
		"reviewers": []any{"opus"}, "rulebook_sha": "ab", "launched": 2.5}
	record(t, home, "acme", opened)
	if _, known, err := Stop("acme", moment); !known || err != nil {
		t.Fatalf("Go left it: known=%v err=%v", known, err)
	}
	if _, err := os.Stat(filepath.Join(home, ".agentkit", "state", "seat-acme.json")); err != nil {
		t.Fatalf("no stop mark: %v", err)
	}
	opened["codex_launch"] = "x"
	record(t, home, "beta", opened)
	if _, known, err := Stop("beta", moment); known || err != nil {
		t.Fatalf("Go stopped a record holding more: known=%v err=%v", known, err)
	}
}

// the same seat with nothing of its own Python ends is Go's to stop
func TestStopClosesARecordTmuxLost(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	if said, known, err := Stop("acme", moment); said != "stopped acme; its number reopens it" || !known || err != nil {
		t.Fatalf("said=%q known=%v err=%v", said, known, err)
	}
}

// a Codex seat, whose record the first stop reconciles, is removed by the second, and the seat
// beside it still reads
func TestStopTwiceRemovesASeatAndLeavesTheRestReadable(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", map[string]any{"orchestrator": "astra", "workers": []string{"astra"}})
	record(t, home, "beta", nil)
	for _, want := range []string{"stopped acme; its number reopens it", "removed acme"} {
		if said, known, err := Stop("acme", moment); said != want || !known || err != nil {
			t.Fatalf("said=%q known=%v err=%v", said, known, err)
		}
	}
	if read, known := Read(moment); !known || len(read.Seats) != 1 || read.Seats[0].Name != "beta" {
		t.Fatalf("known=%v seats=%v", known, read.Seats)
	}
}

// a going run's record, report and log say the user stopped it, and the seat's finished run and
// another seat's stay byte for byte
func TestStopTakesTheSeatsGoingRuns(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	going := runRecord(t, home, "r-going", map[string]any{"state": "waiting", "waiting_on": "r-old", "title": "Fix the API"})
	finished := runRecord(t, home, "r-done", map[string]any{"state": "pass"})
	others := runRecord(t, home, "r-other", map[string]any{"state": "running", "launched_session": "beta"})
	before := map[string]string{finished: contents(t, finished), others: contents(t, others)}
	said, known, err := Stop("acme", moment)
	if want := "stopped r-going\nstopped acme; its number reopens it"; said != want || !known || err != nil {
		t.Fatalf("said=%q known=%v err=%v", said, known, err)
	}
	stopped, err := run.ReadJSON(going)
	if err != nil || stopped == nil {
		t.Fatal(err)
	}
	if stopped.Str("state") != "stopped" || stopped.Str("verdict") != "STOPPED" || stopped.Str("error") != run.Why ||
		stopped.Get("reported") != true || stopped.Get("stop_kept") != true || stopped.Has("waiting_on") {
		t.Fatalf("record: %s", contents(t, going))
	}
	dir := filepath.Dir(going)
	want := "# FAIL — Fix the API\n\nVERDICT: STOPPED\n\n## Why this run stopped\n\nstopped by the user\n\nrelaunch: ak run " + filepath.Join(dir, "task.md") + "\n\n"
	if result := contents(t, filepath.Join(dir, "result.md")); result != want {
		t.Fatalf("result: %q", result)
	}
	if log := contents(t, filepath.Join(dir, "log.txt")); !strings.Contains(log, "ERROR stopped by the user\n") || !strings.HasSuffix(log, "stopped r-going\n") {
		t.Fatalf("log: %q", log)
	}
	for path, held := range before {
		if contents(t, path) != held {
			t.Fatalf("%s changed: %s", path, contents(t, path))
		}
	}
}

// the record of a target is not read past its name: from another seat nothing moves, and a name
// nothing holds is refused the same
func TestStopFromAnotherSeatIsRefused(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	going := runRecord(t, home, "r-going", map[string]any{"state": "running"})
	held := contents(t, going)
	t.Setenv("AGENTKIT_SESSION", "beta")
	for _, name := range []string{"acme", "nobody"} {
		var refused Refusal
		if _, known, err := Stop(name, moment); !known || !errors.As(err, &refused) || string(refused) != "owned by seat "+name+"; a seat stops only its own runs" {
			t.Fatalf("known=%v err=%v", known, err)
		}
	}
	if _, err := os.Stat(filepath.Join(home, ".agentkit", "state", "seat-acme.json")); !errors.Is(err, fs.ErrNotExist) || contents(t, going) != held {
		t.Fatalf("the target moved: %v %s", err, contents(t, going))
	}
}

// a seat whose session tmux lost prints as any other: only a terminal gone with it says nothing
func TestStopOfItsOwnLostSeatStillSpeaks(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	t.Setenv("AGENTKIT_SESSION", "acme")
	if said, known, err := Stop("acme", moment); said != "stopped acme; its number reopens it" || !known || err != nil {
		t.Fatalf("said=%q known=%v err=%v", said, known, err)
	}
}

func contents(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}
