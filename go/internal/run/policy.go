package run

import "agentkit/internal/config"

// recordedAs is each number under the name Python records it, then the one Go records it under,
// which Python reads as the same (config.rename_policy).
var recordedAs = map[string]string{"review_rounds": "rounds", "executor_lines": "review_lines", "orchestrator_lines": "seat_lines"}

// Policy is the numbers a run holds to, Python's policy_of: those its record kept as its
// directory was made, else the host's.
func Policy(record *Object) (config.Numbers, error) {
	held := record.Dict("policy")
	if held == nil || len(held.Keys()) == 0 {
		return config.HostNumbers()
	}
	return config.Recorded(func(key string) (any, bool) {
		for _, name := range []string{key, recordedAs[key]} {
			if number, whole := held.Int(name); whole {
				return number, true
			}
			if held.Has(name) {
				return held.Get(name), true
			}
		}
		return nil, false
	})
}

// Carried is whether Go carries a run held to these numbers: review on, executors on, and each
// line limit a number.  A run with review off or no limit is Python's whole, since Go cannot write
// history.db yet, and so is one with executors off, which Python refuses a task; Go hands it over
// where Python reads the number.
func Carried(numbers config.Numbers) bool {
	executor, limited := numbers.ReviewLines.Most()
	_, orchestrator := numbers.SeatLines.Most()
	return numbers.Rounds > 0 && limited && executor > 0 && orchestrator
}

// Carries is whether Go carries the run this record is: the numbers it holds to read, and carried.
func Carries(record *Object) bool {
	numbers, err := Policy(record)
	return err == nil && Carried(numbers)
}
