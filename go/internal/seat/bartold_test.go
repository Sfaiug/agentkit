package seat

import (
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/tmux"
)

// Each want is statusbar._digest of the same told, so a bar Python told is left alone where Go
// would tell it the same.
func TestABarsDigestIsStatusbarsOwn(t *testing.T) {
	if got := barDigest(barTuple("! 1 other seat needs you", "it's", "é\n\"")); got != "2b0c79b01c228b45" {
		t.Errorf("right end: %s", got)
	}
	own := [][3]string{{"=a#b%:", "status", "2"}, {"=a#b%:", "set-titles-string", "a##b%% · idle"}}
	lists := barOwn(own, []barRow{{name: "a#b%", told: "dd832cf905f40942"}, {name: "c"}})
	if len(lists) != 0 {
		t.Errorf("a bar showing what it would be told is told again, or another bar is: %q", lists)
	}
	if lists := barOwn(own, []barRow{{name: "a#b%"}}); len(lists) != 1 || lists[0][len(lists[0])-1] != "dd832cf905f40942" {
		t.Errorf("a bar never told is not told whole: %q", lists)
	}
}

// Python 3.13's tables do not know U+1FAE9, which Go's print: its repr escapes it, so the same
// text has another digest there, and the bar read back is left as Python told it.
func TestABarPythonToldTheSameIsLeftAlone(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	paneDied(t, "acme")
	state, target, python := filepath.Join(home, ".agentkit", "state"), "=acme:", "79b9db178529caf1"
	if _, err := tmux.Ask(tmux.Own(), "set-option", "-t", target, barTold, python, ";", "set-option", "-t", target, barWhy, "\U0001fae9"); err != nil {
		t.Fatal(err)
	}
	for _, each := range []struct{ said, told string }{{"\U0001fae9", python}, {"\U0001fae9 again", ""}} {
		barTell(state, "acme", [][3]string{{target, barWhy, each.said}}, nil)
		shown, _ := tmux.Ask(tmux.Own(), "show-options", "-v", "-t", target, barWhy)
		told, _ := tmux.Ask(tmux.Own(), "show-options", "-v", "-t", target, barTold)
		if shown != each.said || (each.told != "") != (told == each.told) {
			t.Errorf("told %q: the bar shows %q under %s", each.said, shown, told)
		}
	}
}

// Five versions of line two holding a reason longer than a tmux message are more than one call
// carries, and each more than tmux takes whole: they are told one by one, each in pieces cut
// between characters, its last `;` still text, the digest last.
func TestABarLongerThanACallIsToldWhole(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	drawn(t, home, "acme", prompting)
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(state, "plan-acme.md"), strings.Replace(openLine, "Ship it", strings.Repeat("context é; ", 2000), 1))
	seat, err := LookedLive(state, "acme")
	if err != nil || seat.Word != "needs you" || len(seat.reason) < 20000 {
		t.Fatalf("look: %v, word %q, reason of %d bytes", err, seat.Word, len(seat.reason))
	}
	shown, _ := tmux.Ask(tmux.Own(), "show-options", "-v", "-t", "=acme:", barWhy+"4")
	told, _ := tmux.Ask(tmux.Own(), "show-options", "-v", "-t", "=acme:", barTold)
	if shown != strings.TrimSpace(seat.reason) || told == "" {
		t.Errorf("the bar shows %d bytes of the reason under digest %q", len(shown), told)
	}
}
