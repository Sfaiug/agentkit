package history

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// A check's row is written as it starts, its exit and end once it ends, nil for one that never
// returned; a command that, or a list holding it, already ran on the tree is a re-run, and the
// tests a suite named stay under its check.  A suite's run, and a run with no row, keep none.
func TestEachCheckLeavesItsRow(t *testing.T) {
	home := home(t)
	for id, text := range map[string]string{"20261105-1200-fix-api": `{"run_id": "20261105-1200-fix-api"}`,
		"20261105-1300-fix-ui": `{"run_id": "20261105-1300-fix-ui", "notify_sink": "dry-run"}`,
		"20261105-1400-fix-db": `{"run_id": "20261105-1400-fix-db"}`} {
		dir := filepath.Join(home, ".agentkit", "runs", id)
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, "run.json"), []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	log, lines := said()
	Start(record(t, `{"run_id": "20261105-1200-fix-api", "state": "running"}`), log)
	head := &Checked{Run: "20261105-1200-fix-api", Round: 1, Kind: "done-when", Tree: "abc"}
	zero, one := 0, 1
	Check(head, "test -f a\ntrue", 1.0, "acme-mac", log)(&one)
	Check(head, "true", 2.0, "", log)(&zero)
	hung := Check(head, "sleep 300", 3.0, "", log)
	Check(&Checked{Run: "20261105-1200-fix-api", Round: 1, Kind: "base-proof", Tree: "def"}, "true", 4.0, "", log)(&zero)
	Check(&Checked{Run: "20261105-1200-fix-api", Round: 1, Kind: "done-when"}, "true", 5.0, "", log)(nil)
	Check(&Checked{Run: "20261105-1300-fix-ui", Round: 1, Kind: "done-when"}, "true", 6.0, "", log)(&zero)
	Check(&Checked{Run: "20261105-1400-fix-db", Round: 1, Kind: "done-when"}, "true", 7.0, "", log)(&zero)
	Check(nil, "true", 8.0, "", log)(&zero)
	TestReds(head, []string{"tests/test_api.py", "tests/test_api.py"}, []string{"tests/test_web.py"}, log)
	db, err := Open()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	host, _ := os.Hostname()
	var got [][]any
	for _, row := range query(t, db, "SELECT * FROM checks ORDER BY rowid") {
		got = append(got, []any{row["run_id"], row["round"], row["kind"], row["command"], row["tree"], row["place"],
			row["exit"], row["requested_at"], row["rerun"], row["started_at"] != nil, row["finished_at"] != nil})
	}
	want := [][]any{
		{"20261105-1200-fix-api", int64(1), "done-when", "test -f a\ntrue", "abc", "acme-mac", int64(1), 1.0, int64(0), true, true},
		{"20261105-1200-fix-api", int64(1), "done-when", "true", "abc", host, int64(0), 2.0, int64(1), true, true},
		{"20261105-1200-fix-api", int64(1), "done-when", "sleep 300", "abc", host, nil, 3.0, int64(0), true, false},
		{"20261105-1200-fix-api", int64(1), "base-proof", "true", "def", host, int64(0), 4.0, int64(0), true, true},
		{"20261105-1200-fix-api", int64(1), "done-when", "true", nil, host, nil, 5.0, int64(0), true, true},
	}
	if !reflect.DeepEqual(got, want) || len(*lines) > 0 {
		t.Fatalf("rows %v, said %q", got, *lines)
	}
	got = nil
	for _, row := range query(t, db, "SELECT run_id, round, kind, tree, test, flaky FROM test_reds ORDER BY rowid") {
		got = append(got, []any{row["run_id"], row["round"], row["kind"], row["tree"], row["test"], row["flaky"]})
	}
	want = [][]any{{"20261105-1200-fix-api", int64(1), "done-when", "abc", "tests/test_api.py", int64(0)},
		{"20261105-1200-fix-api", int64(1), "done-when", "abc", "tests/test_web.py", int64(1)}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("named %v", got)
	}
	hung(nil)
}
