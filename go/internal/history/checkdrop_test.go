package history

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// A check handed on takes back every row written under it, checks and named tests alike, and no
// other: not another check's of the run, nor another run's row given the id of one dropped before.
func TestAHandedOnCheckLeavesNoRow(t *testing.T) {
	home := home(t)
	log, lines := said()
	for _, id := range []string{"fix-api", "fix-ui"} {
		dir := filepath.Join(home, ".agentkit", "runs", id)
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, "run.json"), []byte(`{"run_id": "`+id+`"}`), 0o600); err != nil {
			t.Fatal(err)
		}
		Start(record(t, `{"run_id": "`+id+`", "state": "running"}`), log)
	}
	zero, one := 0, 1
	handed := &Checked{Run: "fix-api", Kind: "landing", Tree: "abc"}
	kept := &Checked{Run: "fix-api", Kind: "landing", Tree: "def"}
	Check(handed, "true", 1.0, "", log).End(&zero)
	Check(kept, "true", 2.0, "", log).End(&zero)
	TestReds(handed, []string{"t/a.sh"}, []string{"t/b.sh"}, log)
	last := Check(handed, "AK_SHARD=1/1 sh suite.sh", 3.0, "acme-mac", log)
	last.End(&one)
	last.Drop()
	other := Check(&Checked{Run: "fix-ui", Round: 1, Kind: "done-when", Tree: "abc"}, "true", 4.0, "", log)
	other.End(&zero)
	if other.id != last.id {
		t.Fatalf("another run's row took id %d, not the dropped %d", other.id, last.id)
	}
	handed.Drop(log)
	db, err := Open()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var got [][]any
	for _, row := range query(t, db, "SELECT run_id, round, kind, tree FROM checks ORDER BY rowid") {
		got = append(got, []any{row["run_id"], row["round"], row["kind"], row["tree"]})
	}
	want := [][]any{{"fix-api", nil, "landing", "def"}, {"fix-ui", int64(1), "done-when", "abc"}}
	if !reflect.DeepEqual(got, want) || len(*lines) > 0 {
		t.Fatalf("rows %v, said %q", got, *lines)
	}
	if named := query(t, db, "SELECT test FROM test_reds"); len(named) > 0 {
		t.Fatalf("named tests kept %v", named)
	}
}
