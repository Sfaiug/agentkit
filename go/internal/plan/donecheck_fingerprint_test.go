package plan

import "testing"

// A check's fingerprint is Python's very one (done_check.fingerprint), so that either reads what
// the other kept: each value below is what Python gives for the same words and plan.
func TestADoneCheckFingerprintIsPythons(t *testing.T) {
	owner := []Said{
		{1793440800.0, "Add a retry button.", "x"},
		{1793440801.123457, "and a café — “quoted”\nline", "y"},
		{1793440802.5, "Yes", "card"},
	}
	text := []string{"# plan",
		"- [x] Retry button shown · check: `go test ./ui` · acme · written 2026-11-05 10:00 on abc1234 · done abc1234 passed",
		"  - [ ] Ask the owner · your eye · acme · written 2026-11-05 10:01",
		" * [ ] a box by hand  ", "not a box", "1. [x] numbered"}
	if got := Fingerprint(owner, text); got != "ef2fc3e4727aa68856bf130d461545e651f95ceab7f4a97b52019babbb1917ef" {
		t.Errorf("got %s", got)
	}
	if got := Fingerprint(nil, nil); got != "a683096011db3975a1e401e33b0047d1f2677a11efe85ef12806f016ae039795" {
		t.Errorf("nothing read: got %s", got)
	}
}
