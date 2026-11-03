package seat

import (
	"os"
	"path/filepath"
	"testing"
)

func TestEditorKeptForSeatPanesOrPinnedPane(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	bin := filepath.Join(home, "bin")
	path := filepath.Join(bin, "tmux")
	write(t, path, `#!/bin/sh
case "$*" in
  *list-buffers*)
    [ "$FAIL" != list-buffers ] || exit 1
    printf '%s' "$BUFFERS" ;;
  *'list-panes -s -t =acme: -F #{pane_id}')
    [ "$FAIL" != list-panes ] || exit 1
    printf '%s' "$PANES" ;;
  *) exit 2 ;;
esac
`)
	if err := os.Chmod(path, 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	for _, each := range []struct {
		name, buffers, panes, fail string
		want                       bool
	}{
		{"no kept text", "", "%1\n", "", false},
		{"another seat", "ak_aside-2\n", "%1\n", "", false},
		{"selected pane", "ak_aside-1\n", "%1\n", "", true},
		{"another pane of the seat", "ak_aside-3\n", "%1\n%3\n", "", true},
		{"pinned pane moved away", "ak_aside-1\n", "%3\n", "", true},
		{"another pane number", "ak_aside-10\n", "%1\n", "", false},
		{"another buffer name", "ak_aside-1-extra\n", "%1\n", "", false},
		{"buffers unreadable", "", "%1\n", "list-buffers", true},
		{"panes unreadable", "ak_aside-2\n", "%1\n", "list-panes", true},
		{"no editor buffers", "notes\n", "%1\n", "list-panes", false},
	} {
		t.Run(each.name, func(t *testing.T) {
			t.Setenv("BUFFERS", each.buffers)
			t.Setenv("PANES", each.panes)
			t.Setenv("FAIL", each.fail)
			at := seatAt{name: "acme", pane: "%1"}
			if got := at.editorKept(); got != each.want {
				t.Fatalf("editorKept() = %v, want %v", got, each.want)
			}
		})
	}
}
