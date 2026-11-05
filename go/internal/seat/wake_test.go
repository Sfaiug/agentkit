//go:build unix

package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// A seat ak put to sleep is woken by a reopen with nobody at it: one awake, or closed by the owner
// since, is left alone; one whose directory is gone stays asleep and says why; one tmux still
// holds is left as it is.
func TestWakeReopensOnlyASleepingSeat(t *testing.T) {
	for name, each := range map[string]struct {
		record     map[string]any
		file, held string
		awake      bool
		said       string
	}{
		"awake":          {map[string]any{"launched": 9, "asleep": 3}, "", "0", true, ""},
		"closed":         {map[string]any{"launched": 3, "asleep": 9}, `{"stopped_at": 1}`, "0", true, ""},
		"directory gone": {map[string]any{"launched": 3, "asleep": 9, "cwd": "/nonexistent/acme"}, "", "0", false, "WARN could not wake acme: acme: recorded directory is unavailable: /nonexistent/acme"},
		"held by tmux":   {map[string]any{"launched": 3, "asleep": 9}, "", "1", true, "woke acme"},
	} {
		t.Run(name, func(t *testing.T) {
			home, _ := questionRecoveryHome(t)
			record(t, home, "acme", each.record)
			if each.file != "" {
				write(t, stateFile(home, "seat-acme.json"), each.file)
			}
			t.Setenv("RECOVERY_HELD", each.held)
			var said []string
			awake, carried := Wake("acme", func(line string) { said = append(said, line) })
			if awake != each.awake || !carried || strings.Join(said, "\n") != each.said {
				t.Fatalf("awake %v, carried %v, said %q", awake, carried, said)
			}
			if _, err := os.Stat(filepath.Join(home, "started")); !os.IsNotExist(err) {
				t.Fatal("a harness was started")
			}
		})
	}
}
