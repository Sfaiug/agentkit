package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// typeInto is watch.type_into: its text goes only into a composer read empty while stale says no,
// and the Enter completing it, and one more where the line did not leave, goes whatever the
// composer and stale say by then, words the owner typed in the gap among them: an Enter withheld
// leaves a draft nobody can take back.  The line is sent once it left, whatever the owner drafts
// next.
func TestTypeIntoTypesOnlyIntoAnEmptyComposerAndEntersWhateverItShows(t *testing.T) {
	const line = "Which colour?"
	home := sandbox(t)
	record(t, home, "acme", nil)
	bin := filepath.Join(home, "bin")
	// its tmux draws $HOME/typed once the text goes in, $HOME/after at the first Enter and its
	// prompt at the next
	write(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *list-sessions*) printf 'acme\t1\n' ;;
  *list-panes*) echo '0 1 %1 0' ;;
  *capture-pane*) cat "$HOME/shown" ;;
  *display-message*'#{pane_id}'*) printf '%%1\t1000\n' ;;
  *send-keys*)
    for last do :; done
    printf '%s\n' "$last" >> "$HOME/keys"
    if [ "$last" != Enter ]; then cp "$HOME/typed" "$HOME/shown"
    elif [ -e "$HOME/entered" ]; then cp "$HOME/prompt" "$HOME/shown"
    else cp "$HOME/after" "$HOME/shown"; touch "$HOME/entered"; fi ;;
esac
`)
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	write(t, filepath.Join(home, "prompt"), prompting)
	keys := filepath.Join(home, "keys")
	// each composer as its prompt row draws it, "" for none drawn
	for _, each := range []struct {
		shown, typed, after string
		stale               bool // before the text; once a key is in, stale always says yes
		keys                string
	}{
		{"❯", "❯ " + line, "❯", false, line + "\nEnter\n"},
		{"❯", "❯ " + line + " and the owner's own words", "❯", false, line + "\nEnter\n"},
		{"❯", "", "❯", false, line + "\nEnter\n"},
		{"❯", "❯ " + line, "❯ " + line + " and the owner's own words", false, line + "\nEnter\nEnter\n"},
		{"❯", "❯ " + line, "❯ their next draft", false, line + "\nEnter\n"},
		{"❯ fix the build", "❯ " + line, "❯", false, ""},
		{"❯", "❯ " + line, "❯", true, ""},
	} {
		os.Remove(keys)
		os.Remove(filepath.Join(home, "entered"))
		for file, row := range map[string]string{"shown": each.shown, "typed": each.typed, "after": each.after} {
			write(t, filepath.Join(home, file), strings.Replace(prompting, "❯", row, 1))
		}
		stale := func(string) bool {
			_, err := os.Stat(keys)
			return each.stale || err == nil
		}
		sent := typeInto("acme", line, func(string) {}, stale)
		if typed, _ := os.ReadFile(keys); string(typed) != each.keys || sent != (each.keys != "") {
			t.Fatalf("composer %q, then %q, then %q: sent=%v keys=%q", each.shown, each.typed, each.after, sent, typed)
		}
	}
}
