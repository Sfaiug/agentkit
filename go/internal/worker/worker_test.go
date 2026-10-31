package worker

import (
	"os"
	"path/filepath"
	"testing"
)

func TestTheConversationIsTheAdaptersElseTheLastItsEventsStreamed(t *testing.T) {
	out := t.TempDir()
	events := `{"type":"system","session_id":"sid-acme-1"}
not json
{"type":"thread.started","thread_id":"  thread-2  "}
{"type":"turn","session_id":"","stream":{"id":"stream-3"}}
{"type":"turn","session_id":5,"stream":{"id":"never"}}
["sid-in-a-list"]
`
	if err := os.WriteFile(filepath.Join(out, "events.jsonl"), []byte(events), 0o600); err != nil {
		t.Fatal(err)
	}
	if got := conversation(out); got != "stream-3" {
		t.Fatalf("a killed turn's conversation: %q", got)
	}
	if err := os.WriteFile(filepath.Join(out, "session_id"), []byte(" sid-acme-9\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if got := conversation(out); got != "sid-acme-9" {
		t.Fatalf("the adapter's conversation: %q", got)
	}
}
