//go:build linux

package loop

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// A resume whose harness streamed its closing event and says it holds no such conversation goes on
// in a new one at once, on a retry's attempt as on the first, Python's Harness.lost.
func TestAResumeItsHarnessCannotOpenGoesOnInANewConversationAtOnce(t *testing.T) {
	l, c := adapterRig(t, time.Minute, `1) echo '{"type":"result"}' > "$out/events.jsonl"; echo "API Error: 500" > "$out/stderr.log"; exit 1;;
2) echo '{"type":"result"}' > "$out/events.jsonl"; echo "No conversation found with session ID: $session" > "$out/stderr.log"; exit 1;;
3) echo "## Summary" > "$out/final.md";;`)
	adapters := os.Getenv("AGENTKIT_ADAPTER_DIR")
	manifest, err := os.OpenFile(filepath.Join(adapters, "acme.toml"), os.O_APPEND|os.O_WRONLY, 0)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := manifest.WriteString("lost = [\"No conversation found with session ID\"]\n"); err != nil {
		t.Fatal(err)
	}
	manifest.Close()
	c.session = "gone"
	if _, err := c.run(); err != nil {
		t.Fatal(err)
	}
	resumed, _ := os.ReadFile(filepath.Join(adapters, "sessions"))
	if string(resumed) != "gone\ngone\n\n" || c.session != "sid-3" || !strings.Contains(l.logged(t), "resume of gone failed; fresh conversation") {
		t.Fatalf("resumed %q, session %q: %s", resumed, c.session, l.logged(t))
	}
}
