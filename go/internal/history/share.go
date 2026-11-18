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
			for kind, count := range countsOf(row) {
				sum[kind] += count
			}
			kept[row["model"]] = sum
		}
		if total && when > began && (later == "" || when < next || when == next && turn < later) {
			later, next = turn, when
		}
	}
	if totals {
		for at, each := range counts {
			for kind, then := range kept[each.Model] {
				counts[at].Spent[kind] = max(0, each.Spent[kind]-then)
			}
		}
	}
	for _, row := range rows {
		for _, each := range counts {
			was, left := countsOf(row), [4]int64{}
			for kind := range left {
				left[kind] = max(0, was[kind]-each.Spent[kind])
			}
			if row.Text("turn") != later || !run.Equal(row["model"], each.Model) || left == was {
				continue
			}
			if err := db.exec("UPDATE turn_usage SET input=?, cache_write=?, cache_read=?, output=?, listed_usd=? WHERE turn=? AND model IS ?",
				left[0], left[1], left[2], left[3], price(each.Model, left), later, each.Model); err != nil {
				return err
			}
		}
	}
	return nil
}

// countsOf is a turn_usage row's counts by kind.
func countsOf(row Row) [4]int64 {
	var counts [4]int64
	for kind, column := range []string{"input", "cache_write", "cache_read", "output"} {
		counts[kind], _ = row[column].(int64)
	}
	return counts
}
