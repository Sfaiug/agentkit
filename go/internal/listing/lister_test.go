package listing

import (
	"path/filepath"
	"reflect"
	"testing"

	"agentkit/internal/config"
)

// A named adapter folder's script is asked, whatever the harness, and one it lacks lists nothing;
// with no folder, a harness with a `models` verb of its own is asked through this program, no
// script run.
func TestAHarnessWithItsOwnModelsVerbIsAskedThroughThisProgram(t *testing.T) {
	adapter(t, "exit 1", table)
	if words, ok := Lister("acme"); !ok || len(words) != 1 || filepath.Base(words[0]) != "acme.sh" {
		t.Errorf("acme in a folder: %q %v", words, ok)
	}
	if words, ok := Lister("claude"); !ok || words != nil {
		t.Errorf("claude in a folder without its script: %q %v", words, ok)
	}
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	program, _, _ := config.Running()
	if words, ok := Lister("claude"); !ok || !reflect.DeepEqual(words, []string{program, "adapter", filepath.Dir(filepath.Dir(program)), "claude"}) {
		t.Errorf("claude with no folder: %q %v", words, ok)
	}
}
