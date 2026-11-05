package run

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestARunAtRestIsLookedAtAgainOnlyByAFullRead(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	week := time.Now().Add(-7 * 24 * time.Hour)
	write := func(name, state string, at time.Time) {
		path := filepath.Join(Runs(), name, "run.json")
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(`{"state": "`+state+`"}`), 0o644); err != nil {
			t.Fatal(err)
		}
		if err := os.Chtimes(path, at, at); err != nil {
			t.Fatal(err)
		}
	}
	states := func(reader *Reader) map[string]string {
		held, known := reader.Read()
		if !known {
			t.Fatal("the runs are unread")
		}
		found := map[string]string{}
		for _, each := range held {
			found[each.Name] = each.Record.Str("state")
		}
		return found
	}
	write("ended", "pass", week)
	write("going", "running", week)
	reader := &Reader{}
	states(reader)
	write("ended", "running", week.Add(time.Second))
	write("going", "pass", week.Add(time.Second))
	write("new", "running", time.Now())
	if found := states(reader); found["ended"] != "pass" || found["going"] != "pass" || found["new"] != "running" {
		t.Fatalf("a read looks at the open runs and the new, and leaves the rest: %v", found)
	}
	reader.due = time.Now()
	if found := states(reader); found["ended"] != "running" {
		t.Fatalf("a full read looks at every run: %v", found)
	}
	os.RemoveAll(filepath.Join(Runs(), "new"))
	if _, gone := states(reader)["new"]; gone {
		t.Fatal("a run goes with its directory")
	}
}
