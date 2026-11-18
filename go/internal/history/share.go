package history

import (
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// share makes counts, of the turn of the run id that began at began, its share of the session
// holding them, Python's _turn_usage.  Counts that total the session become what each exceeds the
// same model's rows kept for the session's turns that began before it, never below 0: measured
// against their rows, not what they report now, as a transcript coming home later changes a
// killed turn's report, never its rows.  Turns are counted in whatever order their collectors find
// them, so the earliest of the session's totals kept that began after this turn gives its counts
// back, and a row whose counts that changes is priced anew at price: its dollars were what its old
// counts cost.  One whose counts stay keeps its dollars, though the boards dropped its model since.
// The session's turns are the run's turns with rows and a beginning whose report, read again with
// the harness name, names the session.
func (db *DB) share(id any, name string, session any, totals bool, began float64, counts []harness.Counts, price func(any, [4]int64) any) error {
	rows, err := db.rows("SELECT turn, began, model, input, cache_write, cache_read, output FROM turn_usage "+
		"WHERE run_id=? AND began IS NOT NULL", id)
	if err != nil {
		return err
	}
	ours, read := map[string]bool{}, map[string]bool{} // each of the session's turns, whether it totals it
	for _, row := range rows {
		if turn := row.Text("turn"); !read[turn] {
			read[turn] = true
			if named, total, _, ok := harness.TurnCounts(name, turn); ok && run.Equal(named, session) {
				ours[turn] = total
			}
		}
	}
	kept, later, next := map[any][4]int64{}, "", 0.0
	for _, row := range rows {
		turn := row.Text("turn")
		total, theirs := ours[turn]
		when, _ := row.Num("began")
		if theirs && when < began {
			sum := kept[row["model"]]
			numbers, _ := countsOf(row)
			for kind, count := range numbers {
				sum[kind] += count
			}
			kept[row["model"]] = sum
		}
		if total && when > began && (later == "" || when < next || when == next && turn < later) {
			later, next = turn, when
		}
	}
	if totals {
		// Each model's total is measured against that model's rows alone, where Python's _less takes what
		// they exceed it by off the others in turn: here a session counts twice what its turn reported
		// under no model, as a result without `modelUsage` does, before a total named a model.
		for at, each := range counts {
			for kind, then := range kept[each.Model] {
				counts[at].Spent[kind] = max(0, each.Spent[kind]-then)
			}
		}
	}
	if later == "" {
		return nil
	}
	theirs := map[any][4]int64{} // the later total's counts by model, of a row knowing each
	for _, row := range rows {
		if numbers, known := countsOf(row); known && row.Text("turn") == later {
			theirs[row["model"]] = numbers
		}
	}
	for _, each := range counts {
		// a row with a count unknown keeps it unknown and stays unpriced, as spend prices no such row
		var dollars any
		if left, known := theirs[each.Model]; known {
			for kind := range left {
				left[kind] = max(0, left[kind]-each.Spent[kind])
			}
			dollars = price(each.Model, left)
		}
		// The turn's path alone names its rows, as in Python: it holds its run's id, and two runs'
		// receipts under one directory (a link from one run to the other's turn) is left so: an input
		// no home holds is not served.
		if err := db.exec("UPDATE turn_usage SET (input, cache_write, cache_read, output, listed_usd) = (MAX(0, input-?1), "+
			"MAX(0, cache_write-?2), MAX(0, cache_read-?3), MAX(0, output-?4), ?7) WHERE turn=?5 AND model IS ?6 AND "+
			"(input, cache_write, cache_read, output) IS NOT (MAX(0, input-?1), MAX(0, cache_write-?2), MAX(0, cache_read-?3), MAX(0, output-?4))",
			each.Spent[0], each.Spent[1], each.Spent[2], each.Spent[3], later, each.Model, dollars); err != nil {
			return err
		}
	}
	return nil
}

// countsOf is a turn_usage row's counts by kind, an unknown one 0, and whether it knows each.
func countsOf(row Row) ([4]int64, bool) {
	var counts [4]int64
	known := true
	for kind, column := range []string{"input", "cache_write", "cache_read", "output"} {
		count, ok := row[column].(int64)
		counts[kind], known = count, known && ok
	}
	return counts, known
}
