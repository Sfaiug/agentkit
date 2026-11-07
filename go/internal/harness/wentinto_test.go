package harness

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestWentIntoIsTheConversationItsLaunchNamesWhereTheReceiptNamesNone(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	token := strings.Repeat("a", 32)
	receipt := filepath.Join(home, ".agentkit", "state", "muse-launch-"+token)
	if os.MkdirAll(receipt, 0o700) != nil || os.WriteFile(filepath.Join(receipt, "session"), []byte("acme-chat"), 0o600) != nil {
		t.Fatal(receipt)
	}
	launch := run.Fields("muse_launch", token)
	for _, sent := range []struct {
		receipt *run.Object
		want    string
	}{
		{run.Fields("conversation", "named", "launch", launch), "named"},
		{run.Fields("conversation", nil, "launch", launch), "acme-chat"}, // as Python writes one before SessionStart
		{run.Fields("conversation", nil, "launch", run.Fields("muse_launch", strings.Repeat("b", 32))), ""},
		{run.Fields("conversation", nil), ""},
	} {
		if got := WentInto("muse", sent.receipt); got != sent.want {
			t.Errorf("%s went into %q, want %q", run.Line(sent.receipt), got, sent.want)
		}
	}
}
