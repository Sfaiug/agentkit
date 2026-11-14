package seat

import (
	"path/filepath"
	"testing"
)

func TestAHomeALanderMeasuredASuiteInIsStillRead(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	write(t, filepath.Join(home, ".agentkit", "state", "suite-2258521d5750a137f26d85955fff7987c4f665ecf32958f4b74e74ed7bc95614.json"),
		`{"wall_seconds": 0.5, "run_id": "fix-1"}`)
	if _, known := Read(moment); !known {
		t.Fatal("Read does not know a home whose lander kept a suite's cost")
	}
}
