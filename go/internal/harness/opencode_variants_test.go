package harness

import "testing"

func TestOpenCodeWithNoAdapterFolderReadsGosOwnVariants(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	for _, each := range []struct {
		model, effort string
		takes         bool
	}{{"acme/m", "high", true}, {"acme/m", "none", false}, {"acme/m#none", "high", false},
		{"mimo/m", "max", true}, {"mimo/m", "high", false}, {"mimo/m#high", "max", false}} {
		if Switchable("opencode", each.model, each.effort) != each.takes {
			t.Errorf("%s at %s: switchable=%v", each.model, each.effort, !each.takes)
		}
	}
}
