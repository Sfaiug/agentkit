package run

// ReviewOff is whether the run's launch captured zero review rounds, Python's review_off: such a
// run delivers on its checks alone and spends no review round of its change.
func ReviewOff(record *Object) bool {
	policy := record.Dict("policy")
	return policy != nil && Equal(policy.Get("review_rounds"), Number("0"))
}

// checksPassed is the evidence a run with review off delivers on, Python's review_pass for it: its
// checks passed on the commit the review names, the executor's, and no reviewer's is asked for.
func checksPassed(record, evidence *Object) bool {
	return evidence.Get("no_review") == true && evidence.Get("done_when") == true && evidence.Str("verdict") == "PASS" &&
		zero(evidence.Get("returncode")) && Equal(evidence.Get("executor"), record.Get("executor")) &&
		evidence.Get("reviewer") == nil && record.Get("reviewer") == nil
}
