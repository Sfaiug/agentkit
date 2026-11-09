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
	// only one line on exit 0 is a yes, as orch's seat_auth reads it: no line, or two, answer nothing
	for name, first := range map[string]string{"says no": "echo 'login missing'; exit 1", "says nothing": "exit 0",
		"says two lines": "printf 'warming up\\nsigned in\\n'"} {
		t.Run(name, func(t *testing.T) {
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
auth) echo "$AGENTKIT_ACCOUNT" >> "$HOME/asked"; [ "$AGENTKIT_ACCOUNT" = second ] && { echo 'signed in'; exit 0; }; `+first+` ;;
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
		})
	}
}

func TestAMoveInPlaceKeepsAnAccountRecoveredSinceItWasPlanned(t *testing.T) {
	home := moveHome(t)
	path := filepath.Join(home, ".agentkit", "config.toml")
	config, _ := os.ReadFile(path)
	write(t, path, string(config)+"accounts=['first','second']\n")
	record(t, home, "acme", map[string]any{"orchestrator": "fable", "account": "first", "home_account": "first"})
	plan, known := planMove("acme", "opus", "")
	if !known || plan == nil || plan.pane == "" {
		t.Fatal("no move in place", plan, known)
	}
	// the seat moves onto `second` between the plan and its lock, as a spent account's recovery does
	if err := update(filepath.Join(home, ".agentkit", "state"), "acme", set([]field{{"account", "second"}})); err != nil {
		t.Fatal(err)
	}
	if known, err := plan.carry(nil); !known || err != nil {
		t.Fatal(known, err)
	}
	after, _ := run.ReadJSON(stateFile(home, "session-acme.json"))
	if after.Str("orchestrator") != "opus" || after.Str("account") != "second" || after.Str("home_account") != "first" {
		t.Fatal("the move undid the account its harness runs on", run.Line(after))
	}
}
