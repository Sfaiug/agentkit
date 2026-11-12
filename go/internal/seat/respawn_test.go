package seat

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

func TestARespawnRetypesAnUnsentLineWithoutRepeatingIt(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	bin := filepath.Join(home, "fake")
	write(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *respawn-pane*) cp "$HOME/prompt" "$HOME/shown"; echo 2 > "$HOME/pid" ;;
  *list-sessions*) printf 'acme\t1\n' ;;
  *list-panes*) echo '0 1 %1 0' ;;
  *show-options*) echo %1 ;;
  *capture-pane*display-message*) cat "$HOME/shown"; printf '\n0\n' ;;
  *capture-pane*) cat "$HOME/shown" ;;
  *display-message*'#{pane_id}'*) printf '%%1\t1000\t%s\n' "$(cat "$HOME/pid" 2>/dev/null || echo 1)" ;;
  *display-message*'#{session_name}'*) echo acme ;;
  *display-message*'#{pane_dead}'*) echo 0 ;;
  *send-keys*)
    for last do :; done
    printf '%s\n' "$last" >> "$HOME/keys"
    if [ "$last" = Enter ]; then cp "$HOME/prompt" "$HOME/shown"
    else sed "s/❯/❯ $last/" "$HOME/prompt" > "$HOME/shown"; fi ;;
esac
`)
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	write(t, filepath.Join(home, "prompt"), prompting)
	write(t, filepath.Join(home, "shown"), drafted)
	line := "run r-build is still going"
	// typed into the harness the respawn replaces: the same birth, another process
	owed := run.Fields("id", "old-death", "line", line, "typed", run.Fields("line", line, "seat", 1000, "pid", 1))
	write(t, seatFile("acme"), run.Line(run.Fields("owed_lines", []any{owed})))
	rulebook := filepath.Join(home, "rulebook.md")
	write(t, rulebook, "The seat's rules.\n")
	model, err := config.ModelNamed("opus")
	if err != nil {
		t.Fatal(err)
	}
	seat := reopening{name: "acme", held: true, model: model}
	if _, err := seat.launch(stateFile(home, ""), rulebook, []string{"true"}, "conv-acme"); err != nil {
		t.Fatal(err)
	}
	file, _ := run.ReadJSON(seatFile("acme"))
	first := file.List("owed_lines")[0].(*run.Object)
	if first.Str("id") != "old-death" || first.Str("line") != line {
		t.Fatalf("respawn lost its queued line: %s", run.Line(file))
	}
	for range 3 {
		if carried, err := TellOwed("acme", func(string) {}); !carried || err != nil {
			t.Fatal(carried, err)
		}
	}
	keys, _ := os.ReadFile(filepath.Join(home, "keys"))
	file, _ = run.ReadJSON(seatFile("acme"))
	if string(keys) != line+"\nEnter\n" || file.Truthy("owed_lines") {
		t.Fatalf("keys=%q; still owed=%s", keys, run.Line(file))
	}
}
