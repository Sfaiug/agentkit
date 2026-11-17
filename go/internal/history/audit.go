package history

import (
	"math"
	"os"
	"slices"
	"strconv"
	"strings"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/host"
	"agentkit/internal/quality"
)

// An Audit is what history.db holds of one repository's tests, Python's history.test_audit.
type Audit struct {
	// Reds are each test file's flakes, catches and main_red.
	Reds map[string]Row
	// Target is the median seconds of a piece of the repository's latest landing check that ran
	// the suite whole: no file is over it where none did.
	Target float64
	// Days is the span of the rows read.
	Days float64
}

// TestAudit reads the repository's rows as Python does, through a connection that cannot write.
// An older database lacks what it has no table for, and none where no history.db stands; an
// error where SQLite cannot read the one that does, which Go leaves to Python ak.
func TestAudit(repo string) (Audit, error) {
	audit := Audit{Reds: map[string]Row{}, Target: math.Inf(1)}
	if _, err := os.Stat(Path()); err != nil {
		return audit, nil
	}
	db, err := connect(Path(), sqlite3.OPEN_READONLY)
	if err != nil {
		return audit, err
	}
	defer db.Close()
	tables, err := db.rows("SELECT name FROM sqlite_master WHERE type='table'")
	have := map[string]bool{}
	for _, table := range tables {
		have[table.Text("name")] = true
	}
	var reds, pieces []Row
	if err == nil && have["test_reds"] {
		reds, err = db.rows("SELECT test, SUM(CASE WHEN flaky=1 THEN 1 ELSE 0 END) AS flakes, "+
			"COUNT(DISTINCT CASE WHEN flaky=0 AND t.kind IN "+
			"('done-when','rules','landing') THEN t.run_id END) AS catches, "+
			"COUNT(DISTINCT CASE WHEN flaky=0 AND t.kind='tip' THEN t.run_id END) "+
			"AS main_red, MIN(at) AS first, MAX(at) AS last "+
			"FROM test_reds t JOIN runs r USING (run_id) WHERE r.repo=? GROUP BY test", repo)
	}
	if err == nil && have["checks"] {
		pieces, err = db.rows("SELECT c.run_id, c.tree, c.command, "+
			"c.kind='landing' AND c.rerun=0 AS first, c.exit, c.started_at, c.finished_at "+
			"FROM checks c JOIN runs r USING (run_id) WHERE r.repo=? "+
			"AND command GLOB 'AK_SHARD=*' AND c.finished_at>=c.started_at", repo)
	}
	if err != nil {
		return audit, err
	}
	var took, moments []float64
	for _, row := range reds {
		audit.Reds[row.Text("test")] = row
		moments = append(moments, numbers(row, "first", "last")...)
	}
	// Each first run of a piece of a landing check that ran to its end, by check: a first run
	// holds each share of `AK_SHARD=k/N` once (rerun), so N of them are all N.
	type check struct{ run, tree, suite, count string }
	var order []check
	checks := map[check][]Row{}
	for _, piece := range pieces {
		moments = append(moments, numbers(piece, "started_at", "finished_at")...)
		if code, ok := piece.Num("exit"); ok && piece.Truthy("first") && host.RanToEnd(int(code)) {
			share, suite, _ := strings.Cut(piece.Text("command"), " ")
			_, count, _ := strings.Cut(share, "/")
			key := check{piece.Text("run_id"), piece.Text("tree"), suite, count}
			if checks[key] == nil {
				order = append(order, key)
			}
			checks[key] = append(checks[key], piece)
		}
	}
	var whole []Row
	last := math.Inf(-1)
	for _, key := range order {
		if ran := checks[key]; key.count == strconv.Itoa(len(ran)) && key.count != "1" {
			for _, piece := range ran {
				if ended, _ := piece.Num("finished_at"); ended > last {
					last, whole = ended, ran
				}
			}
		}
	}
	for _, piece := range whole {
		started, _ := piece.Num("started_at")
		ended, _ := piece.Num("finished_at")
		took = append(took, ended-started)
	}
	if len(took) > 0 {
		audit.Target = quality.Median(took)
	}
	if len(moments) > 0 {
		audit.Days = (slices.Max(moments) - slices.Min(moments)) / 86400
	}
	return audit, nil
}

// numbers are the row's values of the columns that hold one.
func numbers(row Row, columns ...string) []float64 {
	var found []float64
	for _, column := range columns {
		if value, ok := row.Num(column); ok {
			found = append(found, value)
		}
	}
	return found
}
