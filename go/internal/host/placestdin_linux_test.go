package host

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// Work given a stdin reads it, from its scope or started plainly where only a service could be
// made, which the manager would start without it.
func TestWorkGivenAStdinReadsIt(t *testing.T) {
	for name, each := range map[string]struct {
		inManager     bool
		scope, reason string
	}{
		"in a scope":                       {true, "agentkit-live-fix-api", ""},
		"where only a service can be made": {false, "none", "a service would not inherit its stdin"},
	} {
		t.Run(name, func(t *testing.T) {
			log, ran, called := placing(t, `while [ "$1" != -- ]; do shift; done; shift; exec "$@"`, each.inManager)
			given := filepath.Join(t.TempDir(), "given")
			os.WriteFile(given, []byte("held"), 0o600)
			stdin, err := os.Open(given)
			if err != nil {
				t.Fatal(err)
			}
			defer stdin.Close()
			cmd := exec.Command("/bin/sh", "-c", `[ -z "$AK_PLACED" ] || printf %s "$$" >"$AK_PLACED" || exit 1; cat >"$0.in"; echo "$$" >>"$0"`, ran)
			cmd.Stdin = stdin
			pid, scope, reason, err := Place(cmd, log, "agentkit-live-fix-api", nil, true)
			if err != nil || scope != each.scope || reason != each.reason || pid != ranAs(t, ran) {
				t.Fatalf("pid %d, %q %q %v", pid, scope, reason, err)
			}
			if read, _ := os.ReadFile(ran + ".in"); string(read) != "held" {
				t.Errorf("its stdin read %q", read)
			}
			if words, _ := os.ReadFile(called); strings.Contains(string(words), "--unit=") != each.inManager {
				t.Errorf("systemd-run %q", words)
			}
		})
	}
}
