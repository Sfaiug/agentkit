//go:build unix

package seat

import (
	"os"
	"path/filepath"
	"testing"
)

// Wakes, read without waking, is what Wake carries: not the launch of a seat in a git checkout,
// nor of one cut off mid-question, which Go leaves to Python, and so the endings row hands such a
// seat's ending over before it is offered.
func TestWakesIsWhatWakeCarries(t *testing.T) {
	for name, each := range map[string]struct {
		record                      map[string]any
		checkout, question, carried bool
		held                        string
	}{
		"launched":       {map[string]any{"launched": 3, "asleep": 9}, false, false, true, "0"},
		"git checkout":   {map[string]any{"launched": 3, "asleep": 9}, true, false, false, "0"},
		"question":       {map[string]any{"launched": 3, "asleep": 9}, false, true, false, "0"},
		"directory gone": {map[string]any{"launched": 3, "asleep": 9, "cwd": "/nonexistent/acme"}, false, false, true, "0"},
		"held by tmux":   {map[string]any{"launched": 3, "asleep": 9}, false, false, true, "1"},
		"awake":          {map[string]any{"launched": 9, "asleep": 3}, false, false, true, "0"},
	} {
		t.Run(name, func(t *testing.T) {
			home, _ := questionRecoveryHome(t)
			record(t, home, "acme", each.record)
			if each.checkout {
				write(t, filepath.Join(home, "work", "acme", ".git", "HEAD"), "ref: refs/heads/main\n")
			}
			if !each.question {
				os.Remove(stateFile(home, "notify-acme.json"))
			}
			t.Setenv("RECOVERY_HELD", each.held)
			wakes, asleep := Wakes("acme"), Asleep("acme")
			if _, carried := Wake("acme", func(string) {}); carried != each.carried || wakes != (asleep && carried) {
				t.Fatalf("Wakes %v, asleep %v, and Wake carried %v", wakes, asleep, carried)
			}
		})
	}
}
