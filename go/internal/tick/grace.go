package tick

// Grace is the seconds a dead run may wait on the tick to resume it, as Python's runs_health
// gives it: two of the last tick's length, and never under cron's three-minute interval.
func Grace() float64 {
	took := 0.0
	if state, ok := loadState(); ok {
		if record := state.Dict("tick"); record != nil {
			ended, hasEnd := record.Num("ended_at")
			started, hasStart := record.Num("started_at")
			if hasEnd && hasStart {
				took = ended - started
			}
		}
	}
	return max(180, 2*took)
}
