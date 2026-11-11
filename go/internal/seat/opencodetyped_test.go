package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

// An OpenCode seat on OpenCode's own screens (tests/fixtures/opencode-cursor-*) whose launch
// reported ses_Free (harness/testdata/opencode.db), where the owner typed one message and the
// model answered.  Its tmux answers the cursor's row from $HOME/cursor, refusing where that holds
// none; the line's text draws it into the composer and an Enter sends it.  The model dialog is drawn
// clear of the composer's box, as in a pane taller than the capture, so only the cursor tells it is up.
func TestAnOpenCodeSeatIsTypedOnlyWhileItsCursorIsInItsComposer(t *testing.T) {
	const line = "Build finished."
	home := sandbox(t)
	write(t, filepath.Join(home, ".agentkit", "config.toml"), opencodeConfig)
	database, err := os.ReadFile(filepath.Join("..", "harness", "testdata", "opencode.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("XDG_DATA_HOME", filepath.Join(home, "share"))
	t.Setenv("OPENCODE_DB", "opencode.db")
	write(t, filepath.Join(home, "share", "opencode", "opencode.db"), string(database))
	token := strings.Repeat("a", 32)
	write(t, filepath.Join(stateFile(home, "opencode-launch-"+token), "session"), "ses_Free\n")
	record(t, home, "acme", map[string]any{"orchestrator": "vela", "workers": []string{"vela"},
		"opencode_launch": token, "conversation": nil, "id_source": nil})
	pane := func(name string) []string {
		data, err := os.ReadFile(filepath.Join("..", "..", "..", "tests", "fixtures", name))
		if err != nil {
			t.Fatal(err)
		}
		return strings.Split(string(data), "\n")
	}
	screen := pane("opencode-cursor-prompt-pane.txt")
	prompt := strings.Join(screen, "\n")
	screen[23] = "  ┃  " + line // the composer's first row
	drafted := strings.Join(screen, "\n")
	screen = pane("opencode-cursor-model-dialog-pane.txt")
	screen[23] = "  ┃"
	dialog := strings.Join(screen, "\n")
	write(t, filepath.Join(home, "prompt"), prompt)
	write(t, filepath.Join(home, "drafted"), drafted)
	write(t, filepath.Join(home, "bin", "tmux"), `#!/bin/sh
case "$*" in
  *list-sessions*) printf 'acme\t1\n' ;;
  *list-panes*) echo '%1' ;;
  *'#{cursor_y}'*) cat "$HOME/cursor" ;;
  *'#{pane_id}'*) printf '%%1\t1000\t4242\n' ;;
  *capture-pane*) cat "$HOME/shown" ;;
  *send-keys*)
    for last do :; done
    printf '%s\n' "$last" >> "$HOME/keys"
    if [ "$last" = Enter ]; then cp "$HOME/prompt" "$HOME/shown"; else cp "$HOME/drafted" "$HOME/shown"; fi ;;
esac
`)
	if err := os.Chmod(filepath.Join(home, "bin", "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", filepath.Join(home, "bin")+string(os.PathListSeparator)+os.Getenv("PATH"))
	// typedInto types the line on that screen with the cursor on that row, "" for one tmux cannot
	// say, `typed` marking one in the composer already: whether it was sent, the keys that went in
	// and the receipts written.
	typedInto := func(shown, cursor string, typed *run.Object) (bool, string, []*run.Object) {
		t.Helper()
		for _, file := range []string{filepath.Join(home, "keys"), filepath.Join(home, "cursor"), stateFile(home, "input-acme.jsonl")} {
			os.Remove(file)
		}
		write(t, filepath.Join(home, "shown"), shown)
		if cursor != "" {
			write(t, filepath.Join(home, "cursor"), cursor+"\n")
		}
		sent := TypeAtPrompt("acme", line, typed, func(*run.Object) error { return nil }, func(string) {})
		keys, _ := os.ReadFile(filepath.Join(home, "keys"))
		data, _ := os.ReadFile(stateFile(home, "input-acme.jsonl"))
		var receipts []*run.Object
		for _, each := range strings.Split(strings.TrimSpace(string(data)), "\n") {
			if value, err := run.Decode([]byte(each)); err == nil {
				receipts = append(receipts, value.(*run.Object))
			}
		}
		return sent, string(keys), receipts
	}
	// on the dialog's search row a key would go into its search, and an Enter pick a model
	if sent, keys, receipts := typedInto(dialog, "11", nil); sent || keys != "" || receipts != nil {
		t.Fatalf("typed into a dialog: sent=%v keys=%q receipts=%v", sent, keys, receipts)
	}
	if sent, keys, receipts := typedInto(prompt, "", nil); sent || keys != "" || receipts != nil {
		t.Fatalf("typed with no cursor read: sent=%v keys=%q receipts=%v", sent, keys, receipts)
	}
	// a line in before the dialog opened gets its Enter once the cursor is back
	mark := run.Fields("line", line, "seat", 1000, "pid", 4242)
	if _, keys, _ := typedInto(drafted, "11", mark); keys != "" {
		t.Fatalf("an Enter went into a dialog: %q", keys)
	}
	if _, keys, _ := typedInto(drafted, "24", mark); keys != "Enter\n" {
		t.Fatalf("no Enter with the cursor back: %q", keys)
	}
	sent, keys, receipts := typedInto(prompt, "24", nil)
	if !sent || keys != line+"\nEnter\n" || len(receipts) != 1 {
		t.Fatalf("not typed at its composer: sent=%v keys=%q receipts=%v", sent, keys, receipts)
	}
	// the owner's message is before it, the model's answer nobody's
	receipt := receipts[0]
	if after, _ := receipt.Num("after"); receipt.Str("harness") != "opencode" || receipt.Str("conversation") != "ses_Free" || after != 1 || receipt.Has("launch") {
		t.Fatalf("receipt %s", run.Line(receipt))
	}
}
