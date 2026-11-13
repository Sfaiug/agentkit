package seat

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

const (
	closedOne = "session closed: press 1 to reopen"
	openLine  = "- [ ] Ship it · check: `true` · acme · written 2026-10-23 09:00\n"
	doneLine  = "- [x] Ship   it · your eye · acme · written 2026-10-23 09:00\n"
)

// paneDied opens a session on the test's own server whose only pane has ended, kept as ak keeps
// a seat's, and answers that pane; each `live` one beside it runs on.
func paneDied(t *testing.T, name string, live ...string) string {
	t.Helper()
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("no tmux installed")
	}
	t.Cleanup(func() { tmux.Ask(tmux.Own(), "kill-server") })
	if err := tmux.Spawn(tmux.Own(), os.Getenv("PATH"), "set-option", "-g", "remain-on-exit", "on", ";", "new-session", "-d", "-s", name, "true"); err != nil {
		t.Fatal(err)
	}
	for _, each := range live {
		if _, err := tmux.Ask(tmux.Own(), "new-session", "-d", "-s", each, "sleep 60"); err != nil {
			t.Fatal(err)
		}
		if _, err := tmux.Ask(tmux.Own(), "set-option", "-t", "="+each+":", tmux.Mark, "1"); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := tmux.Ask(tmux.Own(), "set-option", "-t", "="+name+":", tmux.Mark, "1"); err != nil {
		t.Fatal(err)
	}
	for deadline := time.Now().Add(10 * time.Second); ; time.Sleep(10 * time.Millisecond) {
		if len(tmux.Dead(tmux.Own())) > 0 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("the pane never died")
		}
	}
	pane, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "="+name+":", "#{pane_id}")
	if err != nil {
		t.Fatal(err)
	}
	return pane
}

func TestALookReadsTheSeatGone(t *testing.T) {
	state := func(home string, file string) string { return filepath.Join(home, ".agentkit", "state", file) }
	for name, each := range map[string]struct {
		setup        func(t *testing.T, home string)
		word, reason string
	}{
		"nothing owed rests": {func(*testing.T, string) {}, "idle", closedOne},
		"a plan owing work is the owner's": {func(t *testing.T, home string) {
			write(t, state(home, "plan-acme.md"), openLine)
		}, "needs you", closedOne},
		"a finished plan says what it did": {func(t *testing.T, home string) {
			write(t, state(home, "plan-acme.md"), doneLine)
		}, "done", "Ship it"},
		"one the owner closed rests": {func(t *testing.T, home string) {
			write(t, state(home, "plan-acme.md"), openLine)
			write(t, state(home, "seat-acme.json"), `{"stopped_at": 5, "closed_by_owner": true}`)
			runRecord(t, home, "merged", map[string]any{"state": "pass", "merged": true, "handback_pending": true})
		}, "idle", "session closed by the owner: reopen it from past sessions · 1 hand-backs waiting"},
		"its number counts the seats before it, whatever they hold": {func(t *testing.T, home string) {
			record(t, home, "older", map[string]any{"created": 1_700_000_000, "launched": 3, "rulebook_sha": "x"})
			write(t, state(home, "seat-older.json"), `{"rule": "prompt.composer", "word": "working"}`)
		}, "idle", "session closed: press 2 to reopen"},
		"a question already answered stands no more": {func(t *testing.T, home string) {
			write(t, state(home, "notify-acme.json"), `{"kind": "needs", "text": "which?", "time": 1, "answered_at": 2}`)
		}, "idle", closedOne},
		"no login refused is a seat's news once nobody is in it": {func(t *testing.T, home string) {
			write(t, state(home, "watch.json"), `{"auth_out": {"codex": {"ok": false, "at": 1}, "claude": {"ok": false, "at": 1}}}`)
		}, "idle", closedOne},
		"gh logged out is every seat's news": {func(t *testing.T, home string) {
			write(t, state(home, "watch.json"), `{"gh_out": {"at": 1}}`)
		}, "needs you", "GitHub is logged out: run `gh auth login -p https -w`"},
		"a dead worker token is every seat's news": {func(t *testing.T, home string) {
			write(t, state(home, "watch.json"), `{"worker_tokens": {"claude": {"harness": "claude", "remedy": "replace it", "expired": true, "at": 1}}}`)
		}, "needs you", "claude worker token expired: replace it"},
		"a harness that proves its conversation says what reopening does with no proof": {func(t *testing.T, home string) {
			record(t, home, "acme", map[string]any{"orchestrator": "astra", "workers": []string{"astra"}})
		}, "idle", closedOne + " · starts a new Codex conversation"},
		"a turn that ended well decides nothing": {func(t *testing.T, home string) {
			write(t, state(home, "hook-acme.json"), `{"session": "acme", "event": "Stop", "kind": "", "text": "", "at": 1}`)
		}, "idle", closedOne},
		"a wait that is over waits on nothing": {func(t *testing.T, home string) {
			write(t, state(home, "seat-acme.json"), `{"wait": {"kind": "pr", "on": "x", "over": true}, "usage_wait": null, "stopped_at": null, "closed_by_owner": null}`)
		}, "idle", closedOne},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			paneDied(t, "acme")
			each.setup(t, home)
			seat, _, known := lookedAt(filepath.Join(home, ".agentkit", "state"), "acme", moment)
			if !known || seat.Word != each.word || seat.reason != each.reason {
				t.Fatalf("%v %q %q", known, seat.Word, seat.reason)
			}
		})
	}
}

func TestALookThatWouldDoMoreWritesNothing(t *testing.T) {
	state := func(home string, file string) string { return filepath.Join(home, ".agentkit", "state", file) }
	seatFile := func(content string) func(t *testing.T, home string) {
		return func(t *testing.T, home string) { write(t, state(home, "seat-acme.json"), content) }
	}
	for name, setup := range map[string]func(t *testing.T, home string){
		"a question standing, which its conversation may answer": func(t *testing.T, home string) {
			write(t, state(home, "notify-acme.json"), `{"kind": "needs", "text": "which?", "time": 1}`)
		},
		"a question kept back": seatFile(`{"unasked": ["which?"]}`),
		"an account's move":    seatFile(`{"usage_wait": {"reason": "spent", "since": 1}}`),
		"a usage refusal":      seatFile(`{"usage_refusal": {"line": "spent", "at": 1}}`),
		"a wait not yet over":  seatFile(`{"wait": {"kind": "pr", "on": "x", "at": 1}}`),
		"a failed turn to end": func(t *testing.T, home string) {
			write(t, state(home, "hook-acme.json"), `{"session": "acme", "event": "StopFailure", "kind": "", "text": "", "at": 1}`)
		},
		"a run going": func(t *testing.T, home string) {
			runRecord(t, home, "going", map[string]any{"state": "running"})
		},
		"a merge awaiting its live check": func(t *testing.T, home string) {
			runRecord(t, home, "merged", map[string]any{"state": "pass", "merged": true, "repo": "/r", "finished_at": float64(time.Now().Unix()),
				"health": map[string]any{"command": "true"}})
		},
		"a launch receipt, which may give it back its conversation": func(t *testing.T, home string) {
			record(t, home, "acme", map[string]any{"orchestrator": "astra", "workers": []string{"astra"}, "codex_launch": "receipt"})
		},
		"a session with no record": func(t *testing.T, home string) {
			if _, err := tmux.Ask(tmux.Own(), "new-session", "-d", "-s", "stray", "sleep 60", ";", "set-option", "-t", "=stray:", tmux.Mark, "1"); err != nil {
				t.Fatal(err)
			}
		},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			pane := paneDied(t, "acme")
			setup(t, home)
			path := state(home, "seat-acme.json")
			before, _ := os.ReadFile(path)
			looked(t, pane, "acme")
			if after, _ := os.ReadFile(path); string(after) != string(before) {
				t.Fatalf("the seat's file became %s", after)
			}
			if got, _ := tmux.Ask(tmux.Own(), "show-options", "-v", "-t", "=acme:", barTop); got != "" {
				t.Fatalf("its bar became %s", got)
			}
		})
	}
}

// looked runs the look as the seat's wrapper started it, from that pane.
func looked(t *testing.T, pane, name string) {
	t.Helper()
	socket, err := tmux.Ask(tmux.Own(), "display-message", "-p", "#{socket_path}")
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("TMUX", socket+",1,0")
	t.Setenv("TMUX_PANE", pane)
	t.Setenv("AGENTKIT_SESSION", name)
	Look(name, "", nil)
}

func TestALookIsOnlyAtASeatInItsOwnPane(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	record(t, home, "other", map[string]any{"created": 1_700_000_000})
	pane := paneDied(t, "acme", "other")
	path := filepath.Join(home, ".agentkit", "state", "seat-")
	// another seat's pane
	looked(t, pane, "other")
	for _, name := range []string{"acme", "other"} {
		if _, err := os.Stat(path + name + ".json"); err == nil {
			t.Fatalf("%s was written", name)
		}
	}
	// a live seat beside it only counts in its number
	looked(t, pane, "acme")
	got, _ := run.ReadJSON(path + "acme.json")
	if got == nil || got.Str("reason") != "session closed: press 2 to reopen" {
		t.Fatalf("%v", got)
	}
}

// Whatever another announcer publishes while a look queues for its lock is what the look decides from.
func TestALookDecidesUnderTheAnnounceLock(t *testing.T) {
	for name, each := range map[string]struct{ file, content, word, reason string }{
		"a question asked": {"notify-acme.json", `{"kind": "needs", "text": "which?", "time": 2}`, "needs you", "which?"},
		"a plan finished":  {"plan-acme.md", doneLine, "done", "Ship it"},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", nil)
			pane := paneDied(t, "acme")
			state := filepath.Join(home, ".agentkit", "state")
			path := filepath.Join(state, "seat-acme.json")
			held, err := lock.Wait(context.Background(), filepath.Join(state, "seat-acme.announce"))
			if err != nil {
				t.Fatal(err)
			}
			finished := make(chan struct{})
			socket, _ := tmux.Ask(tmux.Own(), "display-message", "-p", "#{socket_path}")
			t.Setenv("TMUX", socket+",1,0")
			t.Setenv("TMUX_PANE", pane)
			t.Setenv("AGENTKIT_SESSION", "acme")
			go func() {
				defer close(finished)
				Look("acme", "", nil)
			}()
			// long enough for a look that decides first to have decided; a slow one only passes
			time.Sleep(300 * time.Millisecond)
			write(t, filepath.Join(state, each.file), each.content)
			write(t, path, `{"word": "`+each.word+`", "reason": "`+each.reason+`", "word_since": 2}`)
			held.Close()
			<-finished
			got, _ := run.ReadJSON(path)
			since, _ := got.Num("word_since")
			if got.Str("word") != each.word || got.Str("reason") != each.reason || since != 2 {
				t.Fatal(run.Line(got))
			}
		})
	}
}

// A merge recorded while a look queues is younger than the look's start, and still awaits its check.
func TestALookReadsAMergeMadeWhileItQueuedByTheClockOfItsDecision(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	pane := paneDied(t, "acme")
	state := filepath.Join(home, ".agentkit", "state")
	path := filepath.Join(state, "seat-acme.json")
	write(t, filepath.Join(state, "plan-acme.md"), doneLine)
	held, err := lock.Wait(context.Background(), filepath.Join(state, "seat-acme.announce"))
	if err != nil {
		t.Fatal(err)
	}
	finished := make(chan struct{})
	socket, _ := tmux.Ask(tmux.Own(), "display-message", "-p", "#{socket_path}")
	t.Setenv("TMUX", socket+",1,0")
	t.Setenv("TMUX_PANE", pane)
	t.Setenv("AGENTKIT_SESSION", "acme")
	go func() {
		defer close(finished)
		Look("acme", "", nil)
	}()
	// long enough for a look to have read its clock; a slow one only passes
	time.Sleep(300 * time.Millisecond)
	runRecord(t, home, "merged", map[string]any{"state": "pass", "merged": true, "repo": "/r",
		"finished_at": float64(time.Now().UnixNano()) / 1e9, "health": map[string]any{"command": "true"}})
	want := `{"word": "working", "reason": "waiting on the live check", "word_since": 2}`
	write(t, path, want)
	held.Close()
	<-finished
	if got, _ := os.ReadFile(path); string(got) != want {
		t.Fatalf("the seat's file became %s", got)
	}
}

func TestALookWritesOnlyAChangeAndTellsTheBar(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	record(t, home, "needy", map[string]any{"created": 1_900_000_000})
	pane := paneDied(t, "acme", "needy")
	path := filepath.Join(home, ".agentkit", "state", "seat-acme.json")
	write(t, filepath.Join(home, ".agentkit", "state", "seat-needy.json"), `{"word": "needs you"}`)
	// Python's own keys stay, and the word it had stands from when it began
	write(t, path, `{"word": "idle", "reason": "", "word_since": 123.5, "rule": "prompt.composer", "state": "at_prompt"}`)
	looked(t, pane, "acme")
	got, err := run.ReadJSON(path)
	if err != nil {
		t.Fatal(err)
	}
	if got.Str("word") != "idle" || got.Str("reason") != closedOne || got.Str("rule") != "prompt.composer" || got.Str("state") != "at_prompt" {
		t.Fatal(run.Line(got))
	}
	if since, _ := got.Num("word_since"); since != 123.5 {
		t.Fatalf("word_since %v", since)
	}
	for option, want := range map[string]string{barKey: "Ctrl-b m", "status": "2", barNeed: "! 1 other seat needs you", "set-titles-string": "acme · idle"} {
		if said, _ := tmux.Ask(tmux.Own(), "show-options", "-v", "-t", "=acme:", option); !strings.Contains(said, want) {
			t.Errorf("%s: %q", option, said)
		}
	}
	// a changed word reaches every other seat's bar at once
	if said, _ := tmux.Ask(tmux.Own(), "show-options", "-v", "-t", "=needy:", barHit); said != "" {
		t.Errorf("a seat counts itself: %q", said)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	before, _ := os.ReadFile(path)
	if err := os.Chtimes(path, moment, moment); err != nil {
		t.Fatal(err)
	}
	looked(t, pane, "acme")
	after, _ := os.ReadFile(path)
	again, _ := os.Stat(path)
	if string(after) != string(before) || !again.ModTime().Equal(moment) || info.Size() != again.Size() {
		t.Fatalf("an unchanged word was written: %s", after)
	}
}

// A seat whose last answer ran on another model closes on that model, and its bar names it.
func TestALookFollowsTheLastAnswersModel(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	transcript(t, home, "acme", `{"type":"assistant","message":{"model":"claude-fable"}}`+"\n")
	pane := paneDied(t, "acme")
	looked(t, pane, "acme")
	got, _ := run.ReadJSON(filepath.Join(home, ".agentkit", "state", "session-acme.json"))
	if got == nil || got.Str("orchestrator") != "fable" {
		t.Fatalf("%v", got)
	}
	if said, _ := tmux.Ask(tmux.Own(), "show-options", "-v", "-t", "=acme:", barTop); !strings.Contains(said, "Fable xhigh") {
		t.Fatalf("its bar: %q", said)
	}
}

func TestABarIsToldOnlyWhereThisProcessPublishes(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	pane := paneDied(t, "acme")
	if err := os.MkdirAll(filepath.Join(home, "agentkit"), 0o700); err != nil { // a live checkout, not this one
		t.Fatal(err)
	}
	if config.Publishes() {
		t.Fatal("another checkout's code publishes")
	}
	looked(t, pane, "acme")
	got, _ := run.ReadJSON(filepath.Join(home, ".agentkit", "state", "seat-acme.json"))
	if got == nil || got.Str("reason") != closedOne {
		t.Fatalf("the seat's own file is written all the same: %v", got)
	}
	if said, _ := tmux.Ask(tmux.Own(), "show-options", "-v", "-t", "=acme:", barTop); said != "" {
		t.Fatalf("its bar became %s", said)
	}
}

func TestReadReadsASeatWhosePanesHaveAllDiedAsGone(t *testing.T) {
	home := sandbox(t)
	// no conversation of its own: tmux holding it is what gives it a row
	record(t, home, "acme", map[string]any{"conversation": nil})
	paneDied(t, "acme")
	write(t, filepath.Join(home, ".agentkit", "state", "seat-acme.json"), `{"rule": "prompt.composer"}`)
	found, known := Read(moment)
	if !known || len(found.Seats) != 1 || found.Seats[0].Word != "idle" || found.Seats[0].reason != closedOne || !found.Seats[0].held {
		t.Fatalf("%v %+v", known, found.Seats)
	}
	if err := found.Announce(moment); err != nil {
		t.Fatal(err)
	}
	got, _ := run.ReadJSON(filepath.Join(home, ".agentkit", "state", "seat-acme.json"))
	if got.Str("rule") != "prompt.composer" || got.Str("reason") != closedOne {
		t.Fatal(run.Line(got))
	}
	if _, known := Read(moment); !known {
		t.Fatal("Read does not know a home its own look wrote")
	}
	if said, _ := tmux.Ask(tmux.Own(), "show-options", "-v", "-t", "=acme:", barKey); !strings.Contains(said, "Ctrl-b m") {
		t.Fatalf("its bar: %q", said)
	}
}

func TestReadDoesNotReadALiveSeatBesideAGoneOne(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	record(t, home, "other", nil)
	paneDied(t, "acme", "other")
	if _, known := Read(moment); known {
		t.Fatal("Read knows a seat whose pane runs")
	}
}
