//go:build unix

package tick

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/seat"
)

func TestOnlyAnUnansweredLoginLeavesLogoutWordsQuiet(t *testing.T) {
	idleHome(t, answers)
	adapters := t.TempDir()
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	for script, quiet := range map[string]bool{
		"printf 'Traceback\\n  {broken'; exit 1": true,
		"exit 0":                                 true,
		"echo unsupported; exit 2":               true,
		"echo expired; exit 1":                   false,
		"echo authenticated":                     false,
	} {
		put(t, filepath.Join(adapters, "claude.sh"), "#!/bin/sh\n[ \"$*\" = 'auth seat' ] || exit 3\n"+script+"\n")
		if err := os.Chmod(filepath.Join(adapters, "claude.sh"), 0o700); err != nil {
			t.Fatal(err)
		}
		if got := quietLogin(seat.Live{Own: "claude", Login: "Please run /login", Stuck: true}); got != quiet {
			t.Errorf("%s: quiet %v, want %v", script, got, quiet)
		}
	}
}
