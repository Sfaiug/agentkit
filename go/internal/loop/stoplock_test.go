//go:build linux

package loop

import (
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/history"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/sqlite"
)

// A stop holds its run's lock until the workers it ends are gone and the row counts what they
// spent, so a tick's history sync, waiting on that lock, never counts a turn a worker still writes.
func TestAStopHoldsItsRunTillTheRowCountsWhatItsWorkersFinished(t *testing.T) {
	l := rig(t, time.Minute)
	t.Setenv("XDG_RUNTIME_DIR", t.TempDir())
	id := filepath.Base(l.dir)
	if err := run.Change(l.dir, func(record *run.Object) error { record.Set("run_id", id); return nil }); err != nil {
		t.Fatal(err)
	}
	launched, _ := run.Read(l.dir)
	history.Start(launched, nil)
	round := filepath.Join(l.dir, "round-1")
	turnIn(t, round, "executor-opus", map[string]string{"harness": "claude",
		"events.jsonl": `{"type": "message", "message": {"id": "1", "usage": {"input_tokens": 100}}}` + "\n"})
	// the worker, marked as the run's by the rig, finishes its last call once stopped and let go
	worker := exec.Command("sh", "-c", `trap 'touch "$1/signalled"; until [ -e "$1/go" ]; do sleep 0.01; done; echo "$2" >> "$3"; exit 0' TERM
touch "$1/ready"; while :; do sleep 0.01; done`, "-", l.dir,
		`{"type": "message", "message": {"id": "2", "usage": {"input_tokens": 250}}}`, filepath.Join(round, "executor-opus", "events.jsonl"))
	if err := worker.Start(); err != nil {
		t.Fatal(err)
	}
	defer worker.Process.Kill()
	go worker.Wait()
	await(t, filepath.Join(l.dir, "ready"))
	stopped := make(chan error, 1)
	go func() { stopped <- StopRun(id, true, io.Discard) }()
	await(t, filepath.Join(l.dir, "signalled"))
	held := lock.Held(filepath.Join(l.dir, run.RecoveryLock))
	if err := os.WriteFile(filepath.Join(l.dir, "go"), nil, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := <-stopped; err != nil || !held {
		t.Fatalf("stopped: %v, its run held while its worker wrote: %v", err, held)
	}
	db, err := sqlite.Open(history.Path(), sqlite3.OPEN_READONLY)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	row, _, err := db.Prepare("SELECT final_state, executor_tokens FROM runs")
	if err != nil {
		t.Fatal(err)
	}
	defer row.Close()
	if !row.Step() || row.ColumnText(0) != "stopped" || row.ColumnInt64(1) != 350 {
		t.Fatalf("row %q, %d", row.ColumnText(0), row.ColumnInt64(1))
	}
}

// await waits for the file at path to stand.
func await(t *testing.T, path string) {
	t.Helper()
	for late := time.Now().Add(10 * time.Second); ; time.Sleep(10 * time.Millisecond) {
		if _, err := os.Stat(path); err == nil {
			return
		}
		if time.Now().After(late) {
			t.Fatalf("no %s", path)
		}
	}
}
