package logins

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"agentkit/internal/config"
)

// A named adapter folder's script is asked, whatever the harness; with no folder, a harness with a
// `login-end` of its own is asked through this program, no script run.
func TestAHarnessWithItsOwnLoginEndIsAskedThroughThisProgram(t *testing.T) {
	adapters := t.TempDir()
	t.Setenv("HOME", t.TempDir())
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	os.WriteFile(filepath.Join(adapters, "claude.sh"), []byte("#!/bin/sh\n"), 0o755)
	if words, _ := asking("claude"); !reflect.DeepEqual(words, []string{filepath.Join(adapters, "claude.sh")}) {
		t.Errorf("claude in a folder: %q", words)
	}
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	program, _, _ := config.Running()
	for _, harness := range []string{"claude", "codex"} {
		if words, err := asking(harness); err != nil || !reflect.DeepEqual(words, []string{program, "adapter", filepath.Dir(filepath.Dir(program)), harness}) {
			t.Errorf("%s with no folder: %q %v", harness, words, err)
		}
	}
}
