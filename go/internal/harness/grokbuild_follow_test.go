package harness

import (
	"testing"

	"agentkit/internal/run"
)

func TestGrokBuildOwnsTheSessionItsHookFollowed(t *testing.T) {
	for _, each := range []struct {
		source, conversation string
		owned                bool
	}{
		{"launcher", "s1", true},
		{grokHook, "s1", true},
		{claudeHook, "s1", false},
		{"", "s1", false},
		{"launcher", "", false},
		{grokHook, "", false},
	} {
		fields := map[string]any{"conversation": each.conversation, "id_source": each.source}
		record := run.NewObject()
		for key, value := range fields {
			record.Set(key, value)
		}
		if owned, known := Owns("grokbuild", record, each.conversation); owned != each.owned || !known {
			t.Errorf("%q from %q: %v, %v", each.conversation, each.source, owned, known)
		}
		if conversation, _ := Owned("grokbuild", fields); (conversation != "") != each.owned {
			t.Errorf("%q from %q owned as %q", each.conversation, each.source, conversation)
		}
	}
}
