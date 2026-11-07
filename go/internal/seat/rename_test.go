package seat

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// live opens a session on ak's server as a seat's, ak's mark on it.
func live(t *testing.T, name string) {
	t.Helper()
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("no tmux installed")
	}
	t.Cleanup(func() { tmux.Ask(tmux.Own(), "kill-server") })
	if err := tmux.Spawn(tmux.Own(), os.Getenv("PATH"), "new-session", "-d", "-s", name, "sleep 60", ";", "set-option", "-t", "="+name+":", tmux.Mark, "1"); err != nil {
		t.Fatal(err)
	}
}

func TestRenameWhatTheKeysDoNotReach(t *testing.T) {
	home := sandbox(t)
	state := filepath.Join(home, ".agentkit", "state")
	live(t, "acme")
	record(t, home, "acme", map[string]any{"title_superseded": []string{"beta", "old-title"},
		"title_sync": map[string]any{"name": "pending", "tries": 1}})
	write(t, filepath.Join(state, "watch.json"), `{"stalls": {"acme": {"at": 1}}, "seen_at": {"other": 9000000000.5}}`)
	write(t, filepath.Join(state, "handover-acme.md"), "handed over\n")
	write(t, filepath.Join(state, "seat-acme.json"), `{"word": "working", "reason": ""}`)
	// a gone seat's plan under the free name is not this seat's
	write(t, filepath.Join(state, "plan-beta.md"), "- [ ] a gone seat's\n")
	said, known, err := Rename("acme", "Beta", false, time.Now())
	if said != "renamed acme -> beta" || !known || err != nil {
		t.Fatal(said, known, err)
	}
	moved, _ := run.ReadJSON(filepath.Join(state, "session-beta.json"))
	if got := run.Line(moved.Get("title_superseded")); got != `["old-title", "pending"]` {
		t.Error(got)
	}
	if moved.Str("title_conversation") != "conv-acme" {
		t.Error(run.Line(moved))
	}
	watch, _ := run.ReadJSON(filepath.Join(state, "watch.json"))
	if watch.Dict("stalls").Has("acme") || !watch.Dict("stalls").Has("beta") {
		t.Error(run.Line(watch))
	}
	newest, _ := watch.Dict("seen_at").Num("other")
	for _, name := range []string{"acme", "beta"} {
		if at, _ := watch.Dict("seen_at").Num(name); at <= newest {
			t.Errorf("%s's generation %v is not past every one before", name, at)
		}
	}
	// the rulebook the running seat was started on names the handover under its old name
	for _, name := range []string{"handover-acme.md", "handover-beta.md"} {
		if contents(t, filepath.Join(state, name)) != "handed over\n" {
			t.Error(name)
		}
	}
	if exists(filepath.Join(state, "plan-beta.md")) {
		t.Error("the gone seat's plan is read as this seat's")
	}
	if bar, _ := tmux.Ask(tmux.Own(), "show-options", "-v", "-t", "=beta:", barTop); !strings.Contains(bar, "beta") || !strings.Contains(bar, "working") {
		t.Errorf("the bar reads %q", bar)
	}
}

func TestRenameBackKeepsWhatTheSeatWroteUnderThatName(t *testing.T) {
	home := sandbox(t)
	state := filepath.Join(home, ".agentkit", "state")
	live(t, "acme")
	record(t, home, "acme", nil)
	write(t, filepath.Join(state, "session-beta.json"), `{"renamed": "acme"}`)
	write(t, filepath.Join(state, "plan-beta.md"), "written under beta\n")
	write(t, filepath.Join(state, "plan-acme.md"), "written under acme\n")
	if said, known, err := Rename("beta", "beta", false, time.Now()); said != "renamed acme -> beta" || !known || err != nil {
		t.Fatal(said, known, err)
	}
	if contents(t, filepath.Join(state, "plan-beta.md")) != "written under beta\n" || !exists(filepath.Join(state, "plan-acme.md")) {
		t.Error("the plan under the name it went back to was moved over")
	}
	if got, _ := run.ReadJSON(filepath.Join(state, "session-beta.json")); got.Has("renamed") || got.Str("conversation") != "conv-acme" {
		t.Error(run.Line(got))
	}
}

// A session no record keeps has no record to move, and the pointer still leads to it.
func TestRenameOfASeatWithNoRecordLeavesItsPointer(t *testing.T) {
	home := sandbox(t)
	state := filepath.Join(home, ".agentkit", "state")
	live(t, "acme")
	if said, known, err := Rename("acme", "beta", false, time.Now()); said != "renamed acme -> beta" || !known || err != nil {
		t.Fatal(said, known, err)
	}
	if exists(filepath.Join(state, "session-beta.json")) {
		t.Error("a record was invented for it")
	}
	if got, _ := run.ReadJSON(filepath.Join(state, "session-acme.json")); got.Str("renamed") != "beta" {
		t.Error(run.Line(got))
	}
}

// Each is refused, or left to Python, before anything moves.
func TestRenameThatMovesNothing(t *testing.T) {
	spoken := "the name 'beta' is already spoken for"
	for name, c := range map[string]struct {
		build   func(t *testing.T, home, state string)
		known   bool
		refused string
	}{
		"a seat tmux lost": {func(t *testing.T, home, state string) {
			record(t, home, "beta", nil)
		}, true, spoken},
		"a seat the owner stopped": {func(t *testing.T, home, state string) {
			record(t, home, "beta", map[string]any{"conversation": nil})
			write(t, filepath.Join(state, "seat-beta.json"), `{"stopped_at": 1.5, "closed_by_owner": true}`)
		}, true, spoken},
		"a pointer to a record": {func(t *testing.T, home, state string) {
			write(t, filepath.Join(state, "session-beta.json"), `{"renamed": "gamma"}`)
			record(t, home, "gamma", nil)
		}, true, spoken},
		"a pointer leading nowhere": {func(t *testing.T, home, state string) {
			write(t, filepath.Join(state, "session-beta.json"), `{"renamed": "gamma"}`)
		}, true, "'beta' points at another session; pick a name that is not a rename"},
		"a record only Python's listing can place": {func(t *testing.T, home, state string) {
			record(t, home, "beta", map[string]any{"conversation": nil})
		}, false, ""},
		"a rename chain that loops": {func(t *testing.T, home, state string) {
			write(t, filepath.Join(state, "session-beta.json"), `{"renamed": "gamma"}`)
			write(t, filepath.Join(state, "session-gamma.json"), `{"renamed": "beta"}`)
		}, false, ""},
		"a run in a landing line": {func(t *testing.T, home, state string) {
			runRecord(t, home, "r-line", map[string]any{"state": "running", "line_since": 1})
		}, false, ""},
		"a watch.json Go cannot keep": {func(t *testing.T, home, state string) {
			write(t, filepath.Join(state, "watch.json"), `{"own": {"\ud800": 1}}`)
		}, false, ""},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			state := filepath.Join(home, ".agentkit", "state")
			live(t, "acme")
			record(t, home, "acme", nil)
			c.build(t, home, state)
			_, known, err := Rename("acme", "beta", false, time.Now())
			var refused Refusal
			errors.As(err, &refused)
			if known != c.known || string(refused) != c.refused {
				t.Fatalf("known %v, %v", known, err)
			}
			if got, _ := tmux.Ask(tmux.Own(), "list-sessions", "-F", "#{session_name}"); got != "acme" {
				t.Errorf("tmux holds %q", got)
			}
			if got, _ := run.ReadJSON(filepath.Join(state, "session-acme.json")); got.Str("conversation") != "conv-acme" {
				t.Error(run.Line(got))
			}
		})
	}
}

// A run launched after the look names the old name too.
func TestRenameCarriesARunLaunchedAfterItsLook(t *testing.T) {
	home := sandbox(t)
	state := filepath.Join(home, ".agentkit", "state")
	live(t, "acme")
	record(t, home, "acme", nil)
	runRecord(t, home, "r-late", map[string]any{"state": "running", "launched_session": "acme", "session": "acme"})
	if known, err := (carry{state, tmux.Own(), "acme", "beta", false}).do(time.Now()); !known || err != nil {
		t.Fatal(known, err)
	}
	moved, _ := run.Read(filepath.Join(home, ".agentkit", "runs", "r-late"))
	if moved.Str("launched_session") != "beta" || moved.Str("session") != "beta" {
		t.Error(run.Line(moved))
	}
}

// A record that came to hold what Go cannot keep after the look is Python's, with nothing moved.
func TestRenameUndoesTmuxForARecordItCannotKeep(t *testing.T) {
	home := sandbox(t)
	state := filepath.Join(home, ".agentkit", "state")
	live(t, "acme")
	held := `{"unnamed": true, "conversation": "conv-acme", "cwd": "/code/acme-\ud800"}`
	write(t, filepath.Join(state, "session-acme.json"), held)
	write(t, filepath.Join(state, "plan-beta.md"), "- [ ] a gone seat's\n")
	if known, err := (carry{state, tmux.Own(), "acme", "beta", false}).do(time.Now()); known || err != nil {
		t.Fatal(known, err)
	}
	if got, _ := tmux.Ask(tmux.Own(), "list-sessions", "-F", "#{session_name}"); got != "acme" {
		t.Errorf("tmux holds %q", got)
	}
	if got := contents(t, filepath.Join(state, "session-acme.json")); got != held {
		t.Error(got)
	}
	if exists(filepath.Join(state, "session-beta.json")) || !exists(filepath.Join(state, "plan-beta.md")) {
		t.Error("something moved")
	}
}

func TestRenameLeavesARecordItCannotRead(t *testing.T) {
	home := sandbox(t)
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(state, "session-acme.json"), "{broken")
	if err := (carry{state: state, old: "acme", new: "beta"}).record(); err == nil {
		t.Error("no error")
	}
	if got := contents(t, filepath.Join(state, "session-acme.json")); got != "{broken" {
		t.Error(got)
	}
	if exists(filepath.Join(state, "session-beta.json")) {
		t.Error("a record was invented")
	}
}
