//go:build unix

package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/config"
)

// A seat an older ak put to sleep is reopened with nobody at it, as one tmux still holds is left as
// it is, its mark then dropped, as from one awake or closed by the owner since; one whose directory
// is gone keeps it and says why; one Go does not reopen is Python's, its mark kept.
func TestReopenSleptBringsBackOnlyASleptSeat(t *testing.T) {
	for name, each := range map[string]struct {
		record        map[string]any
		file, held    string
		carried, kept bool
		said          string
	}{
		"awake":          {map[string]any{"launched": 9, "asleep": 3}, "", "0", true, false, ""},
		"closed":         {map[string]any{"launched": 3, "asleep": 9}, `{"stopped_at": 1, "closed_by_owner": true}`, "0", true, false, ""},
		"directory gone": {map[string]any{"launched": 3, "asleep": 9, "cwd": "/nonexistent/acme"}, "", "0", true, true, "WARN could not reopen acme, which an older ak had put to sleep: acme: recorded directory is unavailable: /nonexistent/acme"},
		"held by tmux":   {map[string]any{"launched": 3, "asleep": 9}, "", "1", true, false, "reopened acme, which an older ak had put to sleep"},
		"cut off asking": {map[string]any{"launched": 3, "asleep": 9}, "", "0", false, true, ""},
	} {
		t.Run(name, func(t *testing.T) {
			home, _ := questionRecoveryHome(t)
			record(t, home, "acme", each.record)
			if each.file != "" {
				write(t, stateFile(home, "seat-acme.json"), each.file)
			}
			t.Setenv("RECOVERY_HELD", each.held)
			var said []string
			carried, err := ReopenSlept(func(line string) { said = append(said, line) })
			if carried != each.carried || err != nil || strings.Join(said, "\n") != each.said {
				t.Fatalf("carried %v, %v, said %q", carried, err, said)
			}
			if _, after, _ := config.ResolveSession("acme"); (after["asleep"] != nil) != each.kept {
				t.Fatalf("the record: %v", after)
			}
			if _, err := os.Stat(filepath.Join(home, "started")); !os.IsNotExist(err) {
				t.Fatal("a harness was started")
			}
		})
	}
}
