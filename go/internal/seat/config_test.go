package seat

import (
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestConfigMarksKeepTheCurrentRecordAndItsOwnEfforts(t *testing.T) {
	home := sandbox(t)
	t.Setenv("PATH", t.TempDir()) // Redress may only reach a fake, never the host's tmux.
	path := filepath.Join(home, ".agentkit", "state", "session-acme.json")
	write(t, path, `{"orchestrator":"fable","workers":["gone","astra"],"efforts":{"astra":{"effort":"low"}},"conversation":"first"}`)
	selected, err := ConfigSelection("acme")
	if err != nil || run.Line(selected.Get("workers")) != `["astra"]` {
		t.Fatalf("read selection: %v, %v", selected, err)
	}
	selected.Set("workers", []any{"astra", "fable"})
	selected.Set("reviewers", []any{"astra"})
	write(t, path, `{"orchestrator":"fable","workers":["gone","astra"],"efforts":{"astra":{"effort":"medium","review_effort":"high"}},"conversation":"second","custom":17}`)
	saved, err := SaveMarks("acme", selected)
	if err != nil {
		t.Fatal(err)
	}
	disk, err := run.ReadJSON(path)
	if err != nil || !run.Equal(saved, disk) || disk.Str("conversation") != "second" || disk.Get("custom") != run.Number("17") {
		t.Fatalf("record lost a newer value: %s, %v", run.Line(disk), err)
	}
	wanted, _ := run.Decode([]byte(`{"astra":{"effort":"medium","review_effort":"high"},"fable":{"effort":"xhigh"}}`))
	if !run.Equal(disk.Get("efforts"), wanted) {
		t.Fatalf("efforts moved: %s", run.Line(disk.Get("efforts")))
	}
}
