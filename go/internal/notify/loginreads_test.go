//go:build unix

package notify

import (
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestAFailedLoginEndKeepsItsAnswerAndWaitsBeforeAskingAgain(t *testing.T) {
	_, write := questionHome(t)
	adapters := t.TempDir()
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	path := filepath.Join(state(), "logins.json")
	for _, script := range []string{
		"printf 'Traceback\\n  {broken'; exit 1",
		`echo '{"ends":1}'; exit 1`,
		`echo '[]'`,
		`echo '{"email":2}'`,
		`echo '{"plan":""}'`,
		`echo '{"ends":true}'`,
	} {
		t.Run(script, func(t *testing.T) {
			last := run.Fields("email", "owner@acme.test", "plan", "pro", "ends", clock()+10*86400, "checked_at", 1)
			write(path, run.Encode(run.Fields("test", run.Fields("default", last))))
			write(filepath.Join(adapters, "claude.sh"), "#!/bin/sh\n"+script+"\n")
			if _, err := RefreshLogins(clock()); err != nil {
				t.Fatal(err)
			}
			stored, err := run.ReadJSON(path)
			if err != nil {
				t.Fatal(err)
			}
			got := stored.Dict("test").Dict("default")
			checked, dated := got.Num("checked_at")
			if !dated || checked <= 1 {
				t.Fatal(run.Line(got))
			}
			got.Set("checked_at", 1)
			if !run.Equal(last, got) {
				t.Fatal("failed read replaced the answer: " + run.Line(got))
			}
			// If the failure was not dated, this newly available expiry would be read.
			write(filepath.Join(adapters, "claude.sh"), "#!/bin/sh\necho '{\"ends\":1}'\n")
			if kept, err := RefreshLogins(clock()); err != nil || number(kept.Dict("test").Dict("default"), "ends") == 1 {
				t.Fatal("asked again inside the cadence", err)
			}
		})
	}
}
