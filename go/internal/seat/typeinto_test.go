package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// typeInto is watch.type_into: its text goes only into a composer read empty, and the Enter
// completing it goes whatever the composer shows by then, words the owner typed in the gap
// among them, as no Enter withheld leaves a draft nobody can take back.
func TestTypeIntoTypesOnlyIntoAnEmptyComposerAndEntersWhateverItShows(t *testing.T) {
	const line = "Which colour?"
	home := sandbox(t)
	record(t, home, "acme", nil)
	bin := filepath.Join(home, "bin")
	// its tmux draws $HOME/typed once the text goes in, and its prompt again at Enter
	write(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *list-sessions*) printf 'acme\t1\n' ;;
  *list-panes*) echo '0 1 %1 0' ;;
  *capture-pane*) cat "$HOME/shown" ;;
  *display-message*'#{pane_id}'*) printf '%%1\t1000\n' ;;
  *send-keys*)
    for last do :; done
    printf '%s\n' "$last" >> "$HOME/keys"
    if [ "$last" = Enter ]; then cp "$HOME/prompt" "$HOME/shown"
    else cp "$HOME/typed" "$HOME/shown"; fi ;;
esac
`)
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	write(t, filepath.Join(home, "prompt"), prompting)
	for _, each := range []struct{ shown, typed, keys string }{
		{prompting, "❯ " + line, line + "\nEnter\n"},
		{prompting, "❯ " + line + " and the owner's own words", line + "\nEnter\n"},
		{prompting, "", line + "\nEnter\n"}, // no composer drawn
		{drafted, "❯ " + line, ""},
	} {
		os.Remove(filepath.Join(home, "keys"))
		write(t, filepath.Join(home, "shown"), each.shown)
		write(t, filepath.Join(home, "typed"), strings.Replace(prompting, "❯", each.typed, 1))
		sent := typeInto("acme", line, func(string) {}, func(string) bool { return false })
		if keys, _ := os.ReadFile(filepath.Join(home, "keys")); string(keys) != each.keys || sent != (each.keys != "") {
			t.Fatalf("composer %q, then %q: sent=%v keys=%q", each.shown, each.typed, sent, keys)
		}
	}
}
