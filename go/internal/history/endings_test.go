package history

import (
	"bytes"
	"reflect"
	"testing"
)

// The runs realWork counts that finished are counted from the first of them carrying
// changed_lines on, in start order: a merge in the round its rounds_used names, 0 with review off,
// a fail in none, nothing else; none without a database or before a counted run carries
// changed_lines.  runs is read as another program wrote it, and nothing is written.
func TestRoundEndingsCountFromTheFirstRunWithChangedLines(t *testing.T) {
	home(t)
	if ended := RoundEndings(); ended != nil {
		t.Fatalf("with no database, got %v", ended)
	}
	// each run carrying changed_lines here, counted, would count the fail after it
	write(t, "CREATE TABLE runs (run_id, repo, final_state, rounds_used, changed_lines, started_at, finished_at)",
		"INSERT INTO runs VALUES ('stopped', 'acme', 'stopped', 1, 40, 1.0, 1.5), "+
			"('unknown', 'acme', 'unknown', 1, 40, 2.0, 2.5), ('smoke', 'agentkit-smoke', 'pass', 1, 40, 3.0, 3.5), "+
			"('running', 'acme', 'running', 1, 40, 4.0, NULL), ('failed-early', 'acme', 'fail', 3, NULL, 5.0, 5.5)")
	if ended := RoundEndings(); ended != nil {
		t.Fatalf("with no counted run carrying changed_lines, got %v", ended)
	}
	write(t, "INSERT INTO runs VALUES ('review-two', 'acme', 'pass', 2, 40, 9.0, 9.5), "+
		"('failed', 'acme', 'fail', 3, NULL, 8.0, 8.25), ('review-one', 'acme', 'pass', 1, 30, 6.0, 6.5), "+
		"('review-off', 'acme', 'pass', 0, 15, 7.0, 7.5), ('unmerged', 'acme', 'pass', 1, NULL, 7.1, 7.6), "+
		"('error', 'acme', 'error', 0, NULL, 7.2, 7.7), ('no-round', 'acme', 'pass', NULL, 50, 7.3, 7.8), "+
		"('stopped-late', 'acme', 'stopped', 1, 40, 7.4, 7.9)")
	before := read(Path())
	want := []Row{{"started_at": 6.0, "finished_at": 6.5, "round": int64(1)},
		{"started_at": 7.0, "finished_at": 7.5, "round": int64(0)},
		{"started_at": 8.0, "finished_at": 8.25, "round": nil},
		{"started_at": 9.0, "finished_at": 9.5, "round": int64(2)}}
	if ended := RoundEndings(); !reflect.DeepEqual(ended, want) {
		t.Fatalf("got %v, want %v", ended, want)
	}
	if !bytes.Equal(read(Path()), before) {
		t.Fatal("reading wrote to the history")
	}
}
