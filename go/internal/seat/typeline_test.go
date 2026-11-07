package seat

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
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

// Under the send lock a pass reads its pane's process again: the pane answering by its id, linked
// into another session, gives that session's birth and is the same pane running the same process,
// and a read tmux does not answer proves nothing.
func TestMarkConfirmedUnderTheLockByThePanesProcess(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	bin := filepath.Join(home, "bin")
	write(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *capture-pane*) cat "$HOME/shown" ;;
  *"-t =acme: #{pane_id}"*) printf '%%1\t1000\t4242\n' ;;
  *"-t %1 #{pane_id}"*) [ -e "$HOME/unanswered" ] && exit 1; printf '%%1\t1001\t4242\n' ;;
  *send-keys*)
    for last do :; done
    if [ "$last" = Enter ]; then cp "$HOME/prompt" "$HOME/shown"
    else sed "s/❯/❯ $last/" "$HOME/prompt" > "$HOME/shown"; fi ;;
esac
`)
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	write(t, filepath.Join(home, "prompt"), prompting)
	write(t, filepath.Join(home, "shown"), prompting)
	line := "run r-build is still going"
	var mark *run.Object
	if !TypeAtPrompt("acme", line, nil, func(got *run.Object) error { mark = got; return nil }, func(string) {}) {
		t.Fatal("the unchanged pane took no line")
	}
	// no receipt: only a line typed anew takes one, and a mark matched types nothing
	if !TypeAtPrompt("acme", line, mark, nil, func(string) {}) {
		t.Fatal("the process the line went into did not confirm its mark")
	}
	write(t, filepath.Join(home, "unanswered"), "")
	if TypeAtPrompt("acme", line, mark, nil, func(string) {}) {
		t.Fatal("a read tmux did not answer confirmed the mark")
	}
}
