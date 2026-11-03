package loop

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/handin"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

func TestNotNeededEndsOnlyAFixRunsFirstTurn(t *testing.T) {
	for _, each := range []struct {
		body  string
		prior bool
		ends  bool
	}{{"ordinary task", false, false}, {task.FixTheCommand, false, true}, {task.FixTheCommand, true, false}} {
		l := &loop{dir: t.TempDir(), body: each.body}
		record := run.NewObject()
		if each.prior {
			record.Set("round_summaries", []any{run.NewObject()})
		}
		if err := os.WriteFile(filepath.Join(l.dir, "run.json"), []byte(run.Line(record)), 0o600); err != nil {
			t.Fatal(err)
		}
		submitted := &handin.Review{Records: []*run.Object{run.Fields("kind", "not-needed", "why", "already done")}}
		if got := l.notNeeded(submitted) != nil; got != each.ends {
			t.Fatalf("prior=%v: ended=%v", each.prior, got)
		}
	}
}
