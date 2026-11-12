package seat

import (
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// A line typed before its harness names the conversation, as into an OpenCode seat whose launch
// has not reported its session, keeps that launch, which names the session once it has.
func TestAReceiptTypedBeforeItsConversationIsNamedKeepsItsLaunch(t *testing.T) {
	home := sandbox(t)
	t.Setenv("OPENCODE_DB", filepath.Join(home, "none.db"))
	token := strings.Repeat("d", 32)
	record := map[string]any{"orchestrator": "mid", "opencode_launch": token, "resumable": false, "before": nil,
		"title_sync": map[string]any{"id": "r1", "at": 1.5}}
	sent, err := typingReceipt("opencode", record, "Rename the acme report.")
	if err != nil {
		t.Fatal(err)
	}
	launch := `{"resumable": false, "opencode_launch": "` + token + `", "title_sync": {"at": 1.5, "id": "r1"}}`
	if sent.Get("conversation") != nil || run.Line(sent.Get("launch")) != launch {
		t.Fatalf("receipt %s", run.Encode(sent))
	}
	write(t, filepath.Join(stateFile(home, "opencode-launch-"+token), "session"), "ses_A012z")
	if went := harness.WentInto("opencode", sent); went != "ses_A012z" {
		t.Fatalf("went into %q", went)
	}
	record["conversation"] = "conv-1"
	if sent, _ := typingReceipt("claude", record, "go on"); sent.Has("launch") {
		t.Fatalf("a receipt naming its conversation keeps a launch: %s", run.Encode(sent))
	}
}

// A receipt counts the messages already in its conversation: where they cannot be read there is
// none, as counting none would take an earlier message of the owner's in its words for ak's.
func TestNoReceiptWhereTheConversationCannotBeRead(t *testing.T) {
	home := sandbox(t)
	database := filepath.Join(home, "opencode.db")
	write(t, database, "not a SQLite database")
	t.Setenv("OPENCODE_DB", database)
	token := strings.Repeat("d", 32)
	write(t, filepath.Join(stateFile(home, "opencode-launch-"+token), "session"), "ses_Free")
	record := map[string]any{"orchestrator": "mid", "opencode_launch": token}
	if sent, err := typingReceipt("opencode", record, "Build finished."); sent != nil || err == nil {
		t.Fatalf("receipt %s from a conversation that cannot be read", run.Encode(sent))
	}
}
