//go:build linux

package gc

import (
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"agentkit/internal/host"
)

// systemd answers as the user manager would: two days into the boot, each unit's timestamp in
// microseconds since it began.
func manager(t *testing.T, answers map[string]string) *[]string {
	t.Setenv("HOME", t.TempDir())
	clock, systemctl, asked := monotonic, host.Systemctl, &[]string{}
	monotonic = func() float64 { return 2 * day }
	host.Systemctl = func(args ...string) (int, string, error) {
		call := strings.Join(args, " ")
		*asked = append(*asked, call)
		for prefix, out := range answers {
			if strings.HasPrefix(call, prefix) {
				return 0, out, nil
			}
		}
		return 0, "", nil
	}
	t.Cleanup(func() { monotonic, host.Systemctl = clock, systemctl })
	return asked
}

func runRecord(t *testing.T, run, text string) {
	path := filepath.Join(os.Getenv("HOME"), ".agentkit", "runs", run, "run.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestOnlyADayOldFailureNoRunHoldsIsForgotten(t *testing.T) {
	asked := manager(t, map[string]string{
		"list-units":                "agentkit-run-a.scope loaded failed failed run\n \nagentkit-old.service loaded failed failed\n  agentkit-new.service loaded failed failed\n",
		"show agentkit-old.service": "ActiveState=failed\nStateChangeTimestampMonotonic=1000000\n",
		"show agentkit-new.service": "ActiveState=failed\nStateChangeTimestampMonotonic=172000000000\n",
		"show agentkit-run-a.scope": "ActiveState=failed\nStateChangeTimestampMonotonic=1000000\n",
	})
	runRecord(t, "acme-1", `{"state": "running", "scope": "agentkit-run-a"}`)
	runRecord(t, "acme-2", `{"state": "pass", "scope": "agentkit-old"}`)
	var said []string
	forgetFailedUnits(func(line string) { said = append(said, line) })
	if !slices.Equal(said, []string{"gc: reset-failed agentkit-old.service"}) {
		t.Fatalf("said %q, asked %q", said, *asked)
	}
	if slices.Contains(*asked, "show agentkit-run-a.scope -p ActiveState -p StateChangeTimestampMonotonic") {
		t.Fatalf("asked about the scope of a run going on: %q", *asked)
	}
}

func TestARecordThatCannotBeReadKeepsEveryFailure(t *testing.T) {
	asked := manager(t, nil)
	runRecord(t, "acme-1", `{"state": `)
	forgetFailedUnits(func(string) {})
	if len(*asked) != 0 {
		t.Fatalf("asked %q", *asked)
	}
}

func TestOnlyATestSlicesUnitActiveForADayIsStopped(t *testing.T) {
	asked := manager(t, map[string]string{
		"list-units": "agentkit-test-a.scope loaded active running\n\t\nagentkit-test-b.scope loaded active running\nacme.service loaded active running\n",
		"show": "Id=agentkit-test-a.scope\nSlice=agentkit-test-1.slice\nActiveEnterTimestampMonotonic=1000000\n\n" +
			"Id=agentkit-test-b.scope\nSlice=agentkit-test-1.slice\nActiveEnterTimestampMonotonic=172000000000\n\n" +
			"Id=acme.service\nSlice=app.slice\nActiveEnterTimestampMonotonic=1000000\n",
	})
	var said []string
	stopTestUnits(func(line string) { said = append(said, line) })
	if !slices.Equal(said, []string{"gc: stopped agentkit-test-a.scope, a test suite's unit a day old"}) ||
		!slices.Contains(*asked, "stop --no-block agentkit-test-a.scope") {
		t.Fatalf("said %q, asked %q", said, *asked)
	}
}
