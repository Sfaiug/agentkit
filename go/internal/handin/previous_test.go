package handin

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAResumedTurnKeepsItsRecordsAndNotItsCompletion(t *testing.T) {
	dir := t.TempDir()
	before := filepath.Join(dir, "before", File)
	if err := os.MkdirAll(filepath.Dir(before), 0o777); err != nil {
		t.Fatal(err)
	}
	row := `{"kind":"finding","path":"a.go","line":1,"what":"w","why":"y","evidence":{"quote":"q"}}`
	if err := os.WriteFile(before, []byte(`{"kind":"turn","role":"reviewer","workspace":"/w","findings":[{"path":"b.go"}]}`+"\n"+row+"\n"+`{"kind":"done"}`+"\n"), 0o666); err != nil {
		t.Fatal(err)
	}
	if _, err := Start(dir, dir, "reviewer", "", before, nil); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(dir, File))
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(string(data)), "\n")
	if len(lines) != 2 || !strings.Contains(lines[0], `"b.go"`) || !strings.Contains(lines[1], `"finding"`) {
		t.Fatalf("file %q", data)
	}
}
