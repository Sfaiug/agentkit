package handback

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestAnUnheardEndingOverAnHourOldIsMarkedNeverReplayed(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	now := seconds()
	ended := map[string]*run.Object{
		"20261020-0900-old":     run.Fields("state", "fail", "finished_at", run.Float(now-2*maxAge)),
		"20261020-0901-fresh":   run.Fields("state", "fail", "finished_at", run.Float(now-60)),
		"20261020-0902-pending": run.Fields("state", "fail", "finished_at", run.Float(now-2*maxAge), "handback_pending", true),
	}
	for id, record := range ended {
		dir := filepath.Join(home, ".agentkit", "runs", id)
		os.MkdirAll(dir, 0o700)
		if err := os.WriteFile(filepath.Join(dir, "run.json"), []byte(run.Line(record)), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	var said []string
	if !MarkHistory(func(line string) { said = append(said, line) }) {
		t.Fatal("left readable records to Python")
	}
	for id := range ended {
		record, _ := run.Read(filepath.Join(home, ".agentkit", "runs", id))
		if marked := record.Str("handback_note") == preexisting && record.Truthy("handed_back"); marked != (id == "20261020-0900-old") {
			t.Errorf("%s: %s", id, run.Line(record))
		}
	}
	if len(said) != 1 || said[0] != "marked 1 pre-existing endings as handed back without replaying (pre-existing ending; not replayed): 20261020-0900-old" {
		t.Fatalf("said %q", said)
	}
}
