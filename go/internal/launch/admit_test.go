package launch

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"testing"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

// A launch the gate decides is handed over wherever history.db stands, one in WAL mode holding no
// run's row among them, and opens no database: SQLite's -wal and -shm files and its compile cache
// never appear, and the home is left as it was but for the runs folder and its slots lock, which
// Python's own first poll makes.  Without history.db the same launch is let in.
func TestAHandedOverLaunchLeavesItsHistoryUnopened(t *testing.T) {
	home := t.TempDir()
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "XDG_CACHE_HOME": "",
		"AK_NOTIFY_SINK": "", "AK_RUN_DEPTH": "", "AGENTKIT_RUN_DIR": "", "AK_PARENT_RUN": "",
		"AK_HOST_READINGS": `{"free_mb": 64000, "mem_total_mb": 128000, "cpus": 8, "load": 0.1}`} {
		t.Setenv(key, value)
	}
	for _, key := range []string{"AK_MAX_RUNS", "AK_SLOT_POLL", "AK_MIN_FREE_MB", "AK_MAX_LOAD"} {
		t.Setenv(key, "")
		os.Unsetenv(key)
	}
	if err := os.MkdirAll(filepath.Dir(history.Path()), 0o777); err != nil {
		t.Fatal(err)
	}
	conn, err := sqlite3.Open(history.Path())
	if err == nil {
		err = conn.Exec("PRAGMA journal_mode=WAL; CREATE TABLE runs (run_id TEXT PRIMARY KEY, state TEXT)")
		err = errors.Join(err, conn.Close())
	}
	if err != nil {
		t.Fatal(err)
	}
	before := files(t, home)
	if unread("") {
		t.Fatal("the launch is left to Python before its admission")
	}
	if admitted, err := admit(false); !errors.Is(err, ErrPython) {
		admitted.release()
		t.Fatalf("admitted beside history.db: %v", err)
	}
	after := files(t, home)
	for _, made := range []string{run.Runs(), filepath.Join(run.Runs(), ".slots.lock")} {
		delete(after, made)
	}
	var changed []string
	for path, is := range after {
		if was, found := before[path]; !found || was != is {
			changed = append(changed, path)
		}
	}
	for path := range before {
		if _, found := after[path]; !found {
			changed = append(changed, path)
		}
	}
	if changed != nil {
		t.Fatalf("the hand-over changed %v", changed)
	}
	if err := os.Remove(history.Path()); err != nil {
		t.Fatal(err)
	}
	admitted, err := admit(false)
	admitted.release()
	if admitted == nil || err != nil {
		t.Fatalf("not admitted without history.db: %v", err)
	}
}

// files is each path under root with its contents, "" for a folder.
func files(t *testing.T, root string) map[string]string {
	found := map[string]string{}
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			found[path] = ""
			return err
		}
		data, err := os.ReadFile(path)
		found[path] = "file " + string(data)
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
	return found
}
