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

// fakeTmux puts a tmux on PATH holding acme, its only pane dead, that refuses a respawn.
func fakeTmux(t *testing.T, home string) {
	t.Helper()
	bin := filepath.Join(home, "fake")
	write(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *respawn-pane*) echo "can't find pane" >&2; exit 1 ;;
  *list-sessions*) printf 'acme\t1\n' ;;
  *list-panes*) printf 'acme\t1\n' ;;
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
	fakeTmux(t, home)
	state := filepath.Join(home, ".agentkit", "state")
	path := filepath.Join(state, "session-acme.json")
	kept := `{"orchestrator": "opus", "conversation": "conv-acme", "id_source": "launcher", "rulebook_read": {"sha": "old"}, "session_title": "acme"}`
	write(t, path, kept)
	write(t, filepath.Join(state, "hook-acme.json"), `{"event": "Stop"}`)
	rulebook := filepath.Join(state, "rulebook-acme.md")
	write(t, rulebook, "rules\n")
	seat := reopening{name: "acme", held: true}
	err := seat.launch(state, rulebook, []string{"claude"}, "new-conversation")
	var refused Refusal
	if !errors.As(err, &refused) || string(refused) != "cannot resume the session acme: can't find pane" {
		t.Fatalf("refused with %v", err)
	}
	record, _ := run.ReadJSON(path)
	if record.Str("conversation") != "conv-acme" || record.Has("rulebook_sha") || record.Dict("rulebook_read") == nil || record.Has("launched") || record.Has("seen") {
		t.Errorf("the record is left %s", run.Encode(record))
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
	fakeTmux(t, home)
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
	if _, known := planned(state, "acme", record(nil), false, false); !known {
		t.Fatal("Go does not reopen a seat that holds nothing it leaves to Python")
	}
	for name, extra := range map[string]map[string]any{
		"an account's login":     {"account": "work"},
		"a filed seat's launch":  {"repo": cwd},
		"a seat naming itself":   {"unnamed": true},
		"a folder gone":          {"cwd": filepath.Join(home, "gone")},
		"a model no longer run":  {"orchestrator": "gone"},
		"duplicate workers":      {"workers": []any{"opus", "opus"}},
		"an id nothing vouches":  {"id_source": "guess"},
		"efforts Python refuses": {"efforts": map[string]any{"opus": "high"}},
	} {
		if _, known := planned(state, "acme", record(extra), false, false); known {
			t.Errorf("Go reopens %s", name)
		}
	}
	for name, file := range map[string]string{
		"lines owed":            `{"owed_lines": [{"line": "go on"}]}`,
		"a seat cut off asking": `{"state": "asking"}`,
		"background work":       `{"holds": ["a watch"]}`,
	} {
		write(t, filepath.Join(state, "seat-acme.json"), file)
		if _, known := planned(state, "acme", record(nil), false, false); known {
			t.Errorf("Go relaunches %s", name)
		}
		if _, known := planned(state, "acme", record(nil), false, true); !known {
			t.Errorf("a dry run hangs on %s", name)
		}
	}
	write(t, filepath.Join(state, "seat-acme.json"), `{"state": "asking", "closed_by_owner": true}`)
	if _, known := planned(state, "acme", record(nil), false, false); !known {
		t.Error("a seat the owner closed ended on purpose, and is told nothing")
	}
	os.Remove(filepath.Join(state, "seat-acme.json"))
	write(t, filepath.Join(cwd, ".git", "HEAD"), "ref: refs/heads/main\n")
	if _, known := planned(state, "acme", record(nil), false, false); known {
		t.Error("Go relaunches in a checkout, whose git ak keeps from collecting")
	}
}
