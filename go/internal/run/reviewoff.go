package run

// ReviewOff is whether the run's launch captured zero review rounds, Python's review_off: such a
// run delivers on its checks alone and spends no review round of its change.
func ReviewOff(record *Object) bool {
	policy := record.Dict("policy")
	return policy != nil && Equal(policy.Get("review_rounds"), Number("0"))
}
