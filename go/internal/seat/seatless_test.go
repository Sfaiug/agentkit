//go:build unix

package seat

import (
	"os"
	"path/filepath"
	"testing"
)

// Each server's listing fails here, so only what tmux says of the one session decides.
func TestSeatlessAsksTheSessionNotAListing(t *testing.T) {
	home := sandbox(t)
	bin := filepath.Join(home, "fake")
	write(t, filepath.Join(bin, "tmux"), `#!/bin/sh
server=$DEFAULT_HOLDS; [ "$1" = -L ] && { server=$OWN_HOLDS; shift 2; }
[ "$1" = -u ] && shift
case "$1" in
  list-sessions) echo 'error connecting to it (Permission denied)' >&2; exit 1 ;;
  has-session) [ -n "$server" ] || { echo "can't find session: acme" >&2; exit 1; } ;;
  display-message) [ "$server" = marked ] && echo 1 || echo ;;
  list-panes) printf 'acme\t1\t1\n' ;;
esac
`)
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	for _, each := range []struct {
		defaults, own string
		seatless      bool
	}{
		{"marked", "", false}, // a legacy seat on the person's own server
		{"", "marked", false}, // a seat of ak's whose panes are dead
		{"", "bare", true},    // somebody's session by that name with no agent in it
		{"", "", true},
	} {
		t.Setenv("DEFAULT_HOLDS", each.defaults)
		t.Setenv("OWN_HOLDS", each.own)
		if got := seatless("acme"); got != each.seatless {
			t.Errorf("default %q, own %q: seatless is %v", each.defaults, each.own, got)
		}
	}
}
