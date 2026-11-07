package seat

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// fakeTmux puts a tmux on PATH holding that session, its only pane dead or not, that refuses a
// respawn unless $HOME/respawns is there.
func fakeTmux(t *testing.T, home, session string, dead bool) {
	t.Helper()
	bin := filepath.Join(home, "fake")
	flag := map[bool]string{true: "1", false: "0"}[dead]
	write(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *respawn-pane*) [ -e "$HOME/respawns" ] || { echo "can't find pane" >&2; exit 1; } ;;
  *list-sessions*) printf '`+session+`\t1\n' ;;
  *list-panes*) printf '`+session+`\t`+flag+`\n' ;;
  *show-options*) echo %1 ;;
  *display-message*) echo acme ;;
esac
`)
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
}

func TestARefusedRespawnLeavesTheSeatAsItWas(t *testing.T) {
	home := sandbox(t)
	fakeTmux(t, home, "acme", true)
	state := filepath.Join(home, ".agentkit", "state")
	path := filepath.Join(state, "session-acme.json")
	kept := `{"orchestrator": "opus", "conversation": "conv-acme", "id_source": "launcher", "rulebook_read": {"sha": "old"}, "session_title": "acme"}`
	write(t, path, kept)
	write(t, filepath.Join(state, "hook-acme.json"), `{"event": "Stop"}`)
	rulebook := filepath.Join(state, "rulebook-acme.md")
	write(t, rulebook, "new rules\n")
	seat := reopening{name: "acme", held: true}
	_, err := seat.launch(state, rulebook, []string{"claude"}, "new-conversation")
	var refused Refusal
	if !errors.As(err, &refused) || string(refused) != "cannot resume the session acme: can't find pane" {
		t.Fatalf("refused with %v", err)
	}
	record, _ := run.ReadJSON(path)
	if record.Str("conversation") != "conv-acme" || record.Has("rulebook_sha") || record.Dict("rulebook_read") == nil || record.Has("launched") || record.Has("seen") {
		t.Errorf("the record is left %s", run.Encode(record))
	}
	if read, _ := os.ReadFile(rulebook); string(read) != "new rules\n" {
		t.Errorf("the rulebook is left %q", read)
	}
	if read, _ := os.ReadFile(filepath.Join(state, "hook-acme.json")); !strings.Contains(string(read), "Stop") {
		t.Error("the last harness's facts did not come back")
	}
	if left, _ := filepath.Glob(filepath.Join(state, "*.last")); len(left) > 0 {
		t.Errorf("left %v", left)
	}
	if left, _ := filepath.Glob(filepath.Join(state, "launch-*")); len(left) > 0 {
		t.Errorf("left %v", left)
	}
}

// With no session and no record there is nothing to come back; a session whose record is gone
// does not say which model held it.
func TestReopenRefusals(t *testing.T) {
	home := sandbox(t)
	fakeTmux(t, home, "acme", true)
	var refused Refusal
	known, err := Reopen("beta", How{}, io.Discard, io.Discard)
	if !known || !errors.As(err, &refused) || string(refused) != "no session 'beta' to resume and no record of one" {
		t.Errorf("no seat answers %v, %v", known, err)
	}
	path, _ := config.SessionPath("acme")
	known, err = Reopen("acme", How{}, io.Discard, io.Discard)
	if !known || !errors.As(err, &refused) || string(refused) != path+" does not say which model held 'acme'" {
		t.Errorf("a session with no record answers %v, %v", known, err)
	}
}

// The launch hands over the rulebook on disk as it starts: its digest is the record's, and nothing
// has told or read it yet.
func TestALaunchRecordsTheRulebookOnDisk(t *testing.T) {
	home := sandbox(t)
	fakeTmux(t, home, "acme", true)
	write(t, filepath.Join(home, "respawns"), "")
	state := filepath.Join(home, ".agentkit", "state")
	path := filepath.Join(state, "session-acme.json")
	write(t, path, `{"orchestrator": "opus", "rulebook_sha": "old", "rulebook_told": {"code": "c"}}`)
	rulebook := filepath.Join(state, "rulebook-acme.md")
	write(t, rulebook, "rules\n")
	seat := reopening{name: "acme", held: true}
	if _, err := seat.launch(state, rulebook, []string{"claude"}, "conv-acme"); err != nil {
		t.Fatal(err)
	}
	record, _ := run.ReadJSON(path)
	if record.Str("rulebook_sha") != digest([]byte("rules\n")) || record.Has("rulebook_told") || !record.Has("launched") {
		t.Errorf("the record is %s", run.Encode(record))
	}
}

func TestReopensLeftToPython(t *testing.T) {
	home := sandbox(t)
	state := filepath.Join(home, ".agentkit", "state")
	cwd := filepath.Join(home, "code")
	if err := os.MkdirAll(cwd, 0o700); err != nil {
		t.Fatal(err)
	}
	record := func(extra map[string]any) map[string]any {
		fields := map[string]any{"orchestrator": "opus", "workers": []any{"opus"}, "cwd": cwd,
			"conversation": "conv-acme", "id_source": "launcher"}
		for key, value := range extra {
			fields[key] = value
		}
		return fields
	}
	if _, known := comingBack(state, "acme", record(nil), false, false); !known {
		t.Fatal("Go does not reopen a seat that holds nothing it leaves to Python")
	}
	for name, extra := range map[string]map[string]any{
		"an account's login":     {"account": "work"},
		"a seat naming itself":   {"unnamed": true},
		"a folder gone":          {"cwd": filepath.Join(home, "gone")},
		"a model no longer run":  {"orchestrator": "gone"},
		"duplicate workers":      {"workers": []any{"opus", "opus"}},
		"an id nothing vouches":  {"id_source": "guess"},
		"efforts Python refuses": {"efforts": map[string]any{"opus": "high"}},
	} {
		if _, known := comingBack(state, "acme", record(extra), false, false); known {
			t.Errorf("Go reopens %s", name)
		}
	}
	for name, file := range map[string]string{
		"an account's line":           `{"owed_lines": [{"line": "go on", "switch": true}]}`,
		"a seat cut off asking":       `{"state": "asking"}`,
		"background work":             `{"holds": ["a watch"]}`,
		"an unknown screen":           `{"rule": "none"}`,
		"a queued line during a turn": `{"state": "working", "owed_lines": [{"line": "go on"}]}`,
	} {
		write(t, filepath.Join(state, "seat-acme.json"), file)
		// a seat cut off is the revival's to tell, Python's: only the owner's reopen tells it here
		if seat, known := comingBack(state, "acme", record(nil), false, false); known {
			if _, known = seat.goesOn(How{}); known {
				t.Errorf("Go relaunches %s", name)
			}
		}
		if _, known := comingBack(state, "acme", record(nil), false, true); !known {
			t.Errorf("a dry run hangs on %s", name)
		}
	}
	write(t, filepath.Join(state, "seat-acme.json"), `{"state": "asking"}`)
	seat, _ := comingBack(state, "acme", record(nil), false, false)
	if line, known := seat.goesOn(How{Owner: true}); !known || line != QuestionContinue {
		t.Errorf("the owner's reopen of a seat cut off asking tells it %q", line)
	}
	write(t, filepath.Join(state, "seat-acme.json"), `{"state": "asking", "closed_by_owner": true}`)
	for _, how := range []How{{}, {Owner: true}} {
		seat, known := comingBack(state, "acme", record(nil), false, false)
		if line, told := seat.goesOn(how); !known || !told || line != "" {
			t.Error("a seat the owner closed ended on purpose, and is told nothing")
		}
	}
	os.Remove(filepath.Join(state, "seat-acme.json"))
	write(t, filepath.Join(cwd, ".git", "HEAD"), "ref: refs/heads/main\n")
	if _, known := comingBack(state, "acme", record(nil), false, false); known {
		t.Error("Go relaunches in a checkout, whose git ak keeps from collecting")
	}
}
