package history

import (
	"bytes"
	"testing"
)

// A review an older reviews table keeps, from before reviews recorded their effort, counts as
// Python counts it once its migration brings the table up to today's, and looking writes nothing.
func TestAnOlderReviewsTableIsReadAsPythonBringsItUp(t *testing.T) {
	home(t)
	older(t, "CREATE TABLE reviews (run_id TEXT, review_id TEXT, harness TEXT, model TEXT, round INTEGER, verdict TEXT)",
		"INSERT INTO reviews VALUES ('20261001-1200-fix-api', 'review-1', 'claude', 'anvil-1', 1, 'PASS')")
	before := read(Path())
	db := Look()
	rows, ok := db.ReviewedRuns("claude", "anvil-1")
	db.Close()
	if !ok || len(rows) != 1 || rows[0]["effort"] != nil || rows[0]["COUNT(DISTINCT run_id)"] != int64(1) {
		t.Fatalf("got (%v, %v)", rows, ok)
	}
	if !bytes.Equal(read(Path()), before) {
		t.Fatal("looking wrote to the history")
	}
}
