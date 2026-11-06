package launch

import (
	"testing"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

// A history.db where Python kept a run's steps leaves every new launch to Python, which records
// more of a run than Go does, and one holding Go's rows alone leaves it Go's; a run Go carried from
// its launch goes on in Go, its lander's wake among them.
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
	if unread("") || unread("fix-api") {
		t.Fatalf("with Go's row: a launch %v, the run going on %v", unread(""), unread("fix-api"))
	}
	conn, err := sqlite3.Open(history.Path())
	if err == nil {
		err = conn.Exec("INSERT INTO phases VALUES ('fix-ui', 'executor', 1.0, 2.0, NULL)")
		conn.Close()
	}
	if err != nil {
		t.Fatal(err)
	}
	if !unread("") || !unread("fix-ui") || unread("fix-api") {
		t.Fatalf("with Python's step: a launch %v, its run going on %v, Go's %v", unread(""), unread("fix-ui"), unread("fix-api"))
	}
}
