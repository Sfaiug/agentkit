package launch

import (
	"testing"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

// A history.db that stands leaves every new launch to Python, which records more of a run than
// its row; a run Go carried from its launch goes on in Go, its lander's wake among them.
func TestARunGoCarriedGoesOnInGo(t *testing.T) {
	home := t.TempDir()
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "AK_MAX_RUNS": "0", "TZ": "",
		"AGENTKIT_RUN_DIR": "", "AK_NOTIFY_SINK": "", "AK_RUN_DEPTH": "", "AK_PARENT_RUN": ""} {
		t.Setenv(key, value)
	}
	if unread("") || unread("fix-api") {
		t.Fatal("no history.db, yet unread")
	}
	history.Start(run.Fields("run_id", "fix-api", "state", "queued"), nil)
	if !unread("") || unread("fix-api") {
		t.Fatalf("with its row: a launch %v, the run going on %v", unread(""), unread("fix-api"))
	}
}
