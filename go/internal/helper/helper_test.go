package helper

import (
	"bytes"
	"io/fs"
	"os"
	"path/filepath"
	"testing"
)

// Each script this program carries is tools/helper's, byte for byte, so the two cannot drift.
func TestTheCarriedScriptsAreToolsHelpers(t *testing.T) {
	names, err := fs.Glob(carried, "*")
	if err != nil || len(names) == 0 {
		t.Fatalf("carries %v: %v", names, err)
	}
	for _, name := range names {
		have, _ := carried.ReadFile(name)
		want, err := os.ReadFile(filepath.Join("..", "..", "..", "tools", "helper", name))
		if err != nil || !bytes.Equal(have, want) {
			t.Errorf("go/internal/helper/%s is not tools/helper/%s (%v): copy it over", name, name, err)
		}
	}
}
