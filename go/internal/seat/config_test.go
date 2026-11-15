package seat

import (
	"os"
	"path/filepath"
	"strings"
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
	write(t, path, `{"orchestrator":"fable","workers":["gone","astra"],"reviewers":["fable"],"efforts":{"astra":{"effort":"medium","review_effort":"high"}},"conversation":"second","custom":17}`)
	saved, err := SaveMarks("acme", func(current *run.Object) (*run.Object, string) {
		current.Set("workers", append(current.List("workers"), "fable"))
		return current, ""
	})
	if err != nil {
		t.Fatal(err)
	}
	disk, err := run.ReadJSON(path)
	if err != nil || !run.Equal(saved, disk) || disk.Str("conversation") != "second" || disk.Get("custom") != run.Number("17") {
		t.Fatalf("record lost a newer value: %s, %v", run.Line(disk), err)
	}
	if run.Line(disk.Get("workers")) != `["astra", "fable"]` || run.Line(disk.Get("reviewers")) != `["fable"]` {
		t.Fatalf("a mark lost the current roles: %s", run.Line(disk))
	}
	wanted, _ := run.Decode([]byte(`{"astra":{"effort":"medium","review_effort":"high"},"fable":{"effort":"xhigh"}}`))
	if !run.Equal(disk.Get("efforts"), wanted) {
		t.Fatalf("efforts moved: %s", run.Line(disk.Get("efforts")))
	}
}

func TestATakeOfAModelTheConfigRunsNoMoreLeavesTheRecord(t *testing.T) {
	home := sandbox(t)
	t.Setenv("PATH", t.TempDir())
	path := filepath.Join(home, ".agentkit", "state", "session-acme.json")
	record := `{"orchestrator":"fable","workers":["fable"],"reviewers":["opus"]}`
	write(t, path, record)
	// another window took astra out of the config since the screen read it
	write(t, filepath.Join(home, ".agentkit", "config.toml"), strings.Replace(testConfig, "[models.astra]", "[gone.astra]", 1))
	for _, role := range []int{1, 2} {
		_, err := SaveMarks("acme", func(current *run.Object) (*run.Object, string) {
			changed := current.Copy()
			changed.Set([]string{1: "workers", 2: "reviewers"}[role], []any{"astra"})
			return changed, ""
		}, Step{"astra", "exec_effort", "high"})
		if disk, _ := os.ReadFile(path); err == nil || !strings.HasPrefix(err.Error(), "unknown model 'astra'") || string(disk) != record {
			t.Fatalf("role %d: %v, the record %s", role, err, disk)
		}
	}
}
