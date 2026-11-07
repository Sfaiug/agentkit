package seat

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestAnOwedReceiptSurvivesBeforeEnterAndLeavesTheOwnersEditsAlone(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	bin := filepath.Join(home, "bin")
	write(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *list-sessions*) printf 'acme\t1\n' ;;
  *list-panes*) echo '%1 0' ;;
  *capture-pane*) cat "$HOME/shown" ;;
  *display-message*'#{pane_id}'*) printf '%%1\t1000\n' ;;
  *send-keys*)
    for last do :; done
    printf '%s\n' "$last" >> "$HOME/keys"
    if [ "$last" = Enter ]; then cp "$HOME/prompt" "$HOME/shown"; fi ;;
esac
`)
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	write(t, filepath.Join(home, "prompt"), prompting)
	write(t, filepath.Join(home, "shown"), prompting)
	line := "run r-build is still going"
	if err := OweLine("acme", line); err != nil {
		t.Fatal(err)
	}
	file, _ := run.ReadJSON(seatFile("acme"))
	owed := file.List("owed_lines")[0].(*run.Object)
	// The send stops just after its durable receipt, as a killed tick would.
	if TypeAtPrompt("acme", line, nil, func(mark *run.Object) error {
		owed.Set("typed", mark)
		if err := Write("acme", "owed_lines", []any{owed}); err != nil {
			t.Fatal(err)
		}
		return errors.New("tick ended before Enter")
	}, func(string) {}) {
		t.Fatal("an interrupted send was confirmed")
	}
	tell := func() {
		t.Helper()
		if carried, err := TellOwed("acme", func(string) {}); !carried || err != nil {
			t.Fatal(carried, err)
		}
	}
	write(t, filepath.Join(home, "shown"), drafted)
	tell()
	keys, _ := os.ReadFile(filepath.Join(home, "keys"))
	if string(keys) != line+"\n" {
		t.Fatalf("typed onto the owner's edits: %q", keys)
	}
	write(t, filepath.Join(home, "shown"), strings.Replace(prompting, "❯", "❯ "+line, 1))
	tell() // only Enter; its confirmation is the next tick's
	tell()
	tell()
	keys, _ = os.ReadFile(filepath.Join(home, "keys"))
	file, _ = run.ReadJSON(seatFile("acme"))
	if string(keys) != line+"\nEnter\n" || file.Truthy("owed_lines") {
		t.Fatalf("keys=%q; still owed=%s", keys, run.Line(file))
	}
}

// A move's line into a harness Go types nothing into stays Python's to send: Go carries none of
// that queue and leaves it as it was.
func TestAMovesLineGoCannotTypeIsLeftToPython(t *testing.T) {
	home := sandbox(t)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.mid]\nharness = 'opencode'\nmodel = 'acme/model-1'\n"+
		"effort = 'high'\nprovider = 'fuel'\n[providers.fuel]\nmode = 'subscription'\n")
	record(t, home, "acme", map[string]any{"orchestrator": "mid", "workers": []string{"mid"}})
	bin := filepath.Join(home, "bin")
	write(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *list-sessions*) printf 'acme\t1\n' ;;
  *list-panes*) printf '%%1 0\n' ;;
esac
`)
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	queue := `{"owed_lines": [{"line": "/ak-model acme/model-1 high", "switch": true, "pane": "%1", "id": "a"}]}`
	write(t, seatFile("acme"), queue)
	if !Watching("acme") {
		t.Fatal("the seat does not read as up for a line")
	}
	carried, err := TellOwed("acme", func(string) {})
	after, _ := os.ReadFile(seatFile("acme"))
	if carried || err != nil || string(after) != queue {
		t.Fatalf("carried=%v err=%v, the queue now %s", carried, err, after)
	}
}
