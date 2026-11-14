package loop

import "slices"

// passesWhatItHolds is whether a run of just the tests only lists, exiting code, passed each one
// its tree holds, Python's gate.passes_what_it_holds: it named each as run (AK_RAN) but those it
// named as not there (AK_NOT_THERE), as a test file names a part only a later change adds, and
// failing, it named one at least as not there and none of the others as failed (AK_FAILED).  A
// narrowing step counts that stack as passing them (checkTests, probe); to a person and every
// other check the run exited as it did.
func passesWhatItHolds(code int, only, ran, failed, absent []string) bool {
	there := slices.DeleteFunc(slices.Clone(only), func(test string) bool { return slices.Contains(absent, test) })
	for _, test := range there {
		if !slices.Contains(ran, test) {
			return false
		}
	}
	return code == 0 || code > 0 && len(there) < len(only) &&
		!slices.ContainsFunc(there, func(test string) bool { return slices.Contains(failed, test) })
}
