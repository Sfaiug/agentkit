//go:build unix

package seat

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestAMoveOntoAnotherProviderTakesItsFirstWorkingAccount(t *testing.T) {
	home := moveHome(t)
	write(t, filepath.Join(home, "respawns"), "")
	config, _ := os.ReadFile(filepath.Join(home, ".agentkit", "config.toml"))
	write(t, filepath.Join(home, ".agentkit", "config.toml"), string(config)+`[models.nova]
harness='codex'
model='gpt-nova'
effort='xhigh'
provider='other'
[providers.other]
mode='subscription'
accounts=['first','second']
`)
	// the readings hold `first` alone: `second`, which they lack, comes after it
	write(t, stateFile(home, "usage.json"), `{"providers":{"other":{"accounts":{"first":{"meters":[]}}}}}`)
	write(t, filepath.Join(home, "adapters", "codex.sh"), `#!/bin/sh
case "$1" in
auth) echo "$AGENTKIT_ACCOUNT" >> "$HOME/asked"; [ "$AGENTKIT_ACCOUNT" = second ] || { echo 'login missing'; exit 1; }; echo 'signed in' ;;
interactive) case "$*" in *' new') exit 3 ;; esac; echo "$AGENTKIT_ACCOUNT" > "$HOME/launched-on"; echo '/bin/true' ;;
esac
`)
	known, err := Move("acme", "nova", func() (bool, bool) { return true, true })
	if !known || err != nil {
		t.Fatal(known, err)
	}
	asked, _ := os.ReadFile(filepath.Join(home, "asked"))
	on, _ := os.ReadFile(filepath.Join(home, "launched-on"))
	if string(asked) != "first\nsecond\n" || strings.TrimSpace(string(on)) != "second" {
		t.Fatalf("asked %q, launched on %q", asked, on)
	}
	launched, _ := run.ReadJSON(filepath.Join(home, "at-launch"))
	after, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
	for _, record := range []*run.Object{launched, after} {
		if record.Str("orchestrator") != "nova" || record.Str("account") != "second" || record.Str("home_account") != "second" {
			t.Fatal("the move is not homed on the account it took", run.Line(record))
		}
	}
}
