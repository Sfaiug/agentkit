package usage

import (
	"cmp"

	"agentkit/internal/config"
	"agentkit/internal/history"
	"agentkit/internal/logins"
	"agentkit/internal/run"
)

// keepProbed keeps the meters a probe read when they were measured after the reading the snapshot
// holds, spent or not, Python's usage._keep_probed: an adapter's own cache read again, or a refused
// probe, is no new reading.
func keepProbed(src source, cached, fresh *run.Object) {
	at, dated := number(taken(fresh))
	stood, stands := number(taken(cached))
	if fresh.Truthy("meters") && dated && (!stands || at > stood) {
		keep(src, objects(fresh.Get("meters")), at, "probe")
	}
}

// keep is one fresh reading's meters, each a row of history.db's meter_readings measured at that
// moment by a probe or a turn, with the plan its login is on as state/logins.json names it now,
// Python's usage._keep.
func keep(src source, meters []*run.Object, at float64, by string) {
	var plan any
	if login := logins.Of(src.Name, src.account); login != nil {
		plan = login.Get("plan")
	}
	finite := func(value any) any { // Python's _number: a column of a value that is none is NULL
		if parsed, ok := number(value); ok {
			return parsed
		}
		return nil
	}
	var rows [][]any
	for _, meter := range meters {
		rows = append(rows, []any{src.Name, cmp.Or(src.account, config.DefaultAccount), meter.Get("name"),
			finite(meter.Get("used")), finite(meter.Get("resets_at")), finite(meter.Get("window_secs")), at, by, plan})
	}
	history.KeepReadings(rows)
}
