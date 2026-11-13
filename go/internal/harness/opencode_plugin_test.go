package harness

import (
	"os"
	"path/filepath"
	"testing"
)

// The Go build ships OpenCode's seat plugin as hooks/opencode-seat/ is, every byte: the plugin
// runs the hooks beside it, so in go/hooks/ it hands each event to Go's own, in the one protocol
// both programs' hooks read.
//
//go:generate sh -c "rm -rf ../../hooks/opencode-seat && cp -R ../../../hooks/opencode-seat ../../hooks/"
func TestShippedSeatPlugin(t *testing.T) {
	source, _ := filepath.Glob("../../../hooks/opencode-seat/*")
	shipped, _ := filepath.Glob("../../hooks/opencode-seat/*")
	if len(source) == 0 || len(source) != len(shipped) {
		t.Fatal("go/hooks/opencode-seat/ differs from hooks/opencode-seat/; run go generate ./internal/harness")
	}
	for i, path := range source {
		want, _ := os.ReadFile(path)
		if got, _ := os.ReadFile(shipped[i]); filepath.Base(shipped[i]) != filepath.Base(path) || string(got) != string(want) {
			t.Fatalf("%s differs from hooks/opencode-seat/; run go generate ./internal/harness", path)
		}
	}
}
