package run

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// A look marks the record as Python's record() and record_limits write it, laid out as
// json.dumps(indent=2) lays it out: the changed members replaced, dropped or appended, every
// other one in the text it was read in.
func TestALookKeepsWhatItLeavesAsItWasRead(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "run.json")
	read := `{"run_id": "x", "state": "fail", "turn_hours": 2, "big": 0.1234567890123456789012345,` +
		` "error_retries": 2, "nested": {"a":"caf\u00e9 é", "b": [1E2, -0, {}, [ ]], "c": {"d": "{,:["}},` +
		` "run_id": "y", "silence_minutes": 5}`
	if err := os.WriteFile(path, []byte(read), 0600); err != nil {
		t.Fatal(err)
	}
	marked := false
	look := func(record *Object) error {
		marked = LookedAt(record, time.Unix(1792000000, 5e8))
		return nil
	}
	if err := Change(dir, look); !marked || err != nil {
		t.Fatalf("not marked: %v", err)
	}
	want := `{
  "run_id": "y",
  "state": "fail",
  "big": 0.1234567890123456789012345,
  "nested": {
    "a": "caf\u00e9 é",
    "b": [
      1E2,
      -0,
      {},
      []
    ],
    "c": {
      "d": "{,:["
    }
  },
  "silence_minutes": 5,
  "recovery_acknowledged_at": 1792000000.5,
  "ceiling_hours": 6
}`
	if data, _ := os.ReadFile(path); string(data) != want {
		t.Fatalf("wrote %q", data)
	}
	if err := Change(dir, look); marked || err != nil {
		t.Fatalf("a second look marked: %v", err)
	}
	if data, _ := os.ReadFile(path); string(data) != want {
		t.Fatalf("looked at twice: %q", data)
	}
	if _, err := os.Stat(filepath.Join(dir, "run.tmp")); !os.IsNotExist(err) {
		t.Fatalf("run.tmp left: %v", err)
	}
}

// A member replaced or appended is laid out at its depth, as one kept is.
func TestAChangedMemberIsLaidOutAtItsDepth(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "run.json")
	if err := os.WriteFile(path, []byte(`{"nested": {"a": 1}, "silence_minutes": 20, "ceiling_hours": 6}`), 0600); err != nil {
		t.Fatal(err)
	}
	Change(dir, func(record *Object) error {
		record.Dict("nested").Set("a", []any{Number("2"), NewObject()})
		record.Set("added", decoded(t, `{"b": {"c": null}}`))
		return nil
	})
	want := `{
  "nested": {
    "a": [
      2,
      {}
    ]
  },
  "silence_minutes": 20,
  "ceiling_hours": 6,
  "added": {
    "b": {
      "c": null
    }
  }
}`
	if data, _ := os.ReadFile(path); string(data) != want {
		t.Fatalf("wrote %q", data)
	}
}
