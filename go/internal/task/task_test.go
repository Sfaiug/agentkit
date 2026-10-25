package task

import (
	"os"
	"path/filepath"
	"slices"
	"testing"
)

// A task saved with Windows line endings reads as Python reads it.
func TestDoneWhenReadsAnyLineEnding(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.md")
	if err := os.WriteFile(path, []byte("---\r\nrounds: 2\r\n---\r\n# fix api\r\n\r\n## Done when\r\n\r\n```bash\r\nmake test\r\n```\r\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if cmds, ok := DoneWhen(path); !ok || !slices.Equal(cmds, []string{"make test"}) {
		t.Fatalf("got %q, %v", cmds, ok)
	}
}
