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

// Carries is whether Go carries the run this record is: the numbers it holds to read, and not a
// review of a pull request with review off, which Python delivers on its checks alone.
func Carries(record *Object) bool {
	_, err := Policy(record)
	return err == nil && !(ReviewOff(record) && record.Truthy("review_pr"))
}
