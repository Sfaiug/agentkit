package seat

import (
	"os"
	"path/filepath"
	"testing"
)

func TestNoKeyGoesInWhileTheCursorIsOffItsComposer(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	bin := filepath.Join(home, "bin")
	path := filepath.Join(bin, "tmux")
	write(t, path, `#!/bin/sh
case "$*" in
  *'#{cursor_y}'*) [ -n "$CURSOR" ] || exit 1; echo "$CURSOR" ;;
  *capture-pane*) printf '\n said\n┃\n┃  Build · vela\n╹\nctrl+p commands\n' ;;
  *send-keys*) touch "$HOME/typed" ;;
  *) exit 2 ;;
esac
`)
	if err := os.Chmod(path, 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	typed := filepath.Join(home, "typed")
	for _, each := range []struct {
		own, cursor string
		off         bool
	}{{"opencode", "2", false}, {"opencode", "4", false}, {"opencode", "1", true}, {"opencode", "5", true},
		{"opencode", "", true}, {"claude", "", false}} { // a harness keeping no cursor there is never off it
		t.Setenv("CURSOR", each.cursor)
		os.Remove(typed)
		at := seatAt{name: "acme", own: each.own, pane: "%1"}
		entered := at.enter(func(string) {})
		_, err := os.Stat(typed)
		if at.offComposer() != each.off || entered == each.off || os.IsNotExist(err) != each.off {
			t.Fatalf("%s, cursor %q: off=%v, an Enter went in=%v", each.own, each.cursor, !each.off, entered)
		}
	}
}
