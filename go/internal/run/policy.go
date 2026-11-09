package run

import "agentkit/internal/config"

// Policy is the numbers a run holds to, Python's policy_of: those its record kept as its
// directory was made, else the host's.
func Policy(record *Object) (config.Numbers, error) {
	held := record.Dict("policy")
	if held == nil || len(held.Keys()) == 0 {
		return config.HostNumbers()
	}
	return config.Recorded(func(key string) (any, bool) {
		if number, whole := held.Int(key); whole {
			return number, true
		}
		return held.Get(key), held.Has(key)
	})
}

// Carried is whether Go carries a run held to these numbers: review on and executors on.  A run
// with review off is Python's whole, and so is one with executors off, which only a review
// launches (a task's launch is refused first); Go hands it over where Python reads the number.
func Carried(numbers config.Numbers) bool {
	return numbers.Rounds > 0 && numbers.ReviewLines != config.AtMost(0)
}

// Carries is whether Go carries the run this record is: the numbers it holds to read, and carried.
func Carries(record *Object) bool {
	numbers, err := Policy(record)
	return err == nil && Carried(numbers)
}
