package task

import (
	"os"
	"path/filepath"
	"slices"
	"testing"
)

// A task saved with Windows line endings reads as Python reads it.
func TestReadReadsAnyLineEnding(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.md")
	if err := os.WriteFile(path, []byte("---\r\nrounds: 2\r\n---\r\n# fix api\r\n\r\n## Done when\r\n\r\n```bash\r\nmake test\r\n```\r\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if meta, cmds, err := Read(path); err != nil || meta["rounds"] != "2" || !slices.Equal(cmds, []string{"make test"}) {
		t.Fatalf("got %q, %q, %v", meta, cmds, err)
	}
}

// A round budget reads as Python's int() reads it, and only one over three is refused.
func TestRoundsRefusalReadsAsPython(t *testing.T) {
	for value, want := range map[string]string{"4": "4", "+4": "4", "0004": "4", "1_0": "10", "3": "", "-5": "", "4_": "", "_4": "", "1__0": "", "four": "", "": ""} {
		got := RoundsRefusal(value, "task rounds")
		if (want == "") != (got == "") || want != "" && got != "task rounds "+want+" is over the budget: 3 rounds, then a run goes back to its orchestrator to split or re-scope" {
			t.Errorf("%q: got %q", value, got)
		}
	}
}
