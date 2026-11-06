package loop

import (
	"io"

	"agentkit/internal/run"
)

// exhaustedPickup is whether Go carries on a run waiting on a provider's window, Python's resume of
// one run dry: cut off where Go goes on from, and either its saved pair goes on, the window it ran
// dry on refilled, or nothing can run it yet, which its resume parks again (ParkDry).  A handover
// is the tick's to write first (ResumeModels), and a run that merges delivers as any other.
func exhaustedPickup(dir string, record *run.Object) bool {
	if !windowed(record) || !cutOff(dir, record) {
		return false
	}
	rules, room, ok := picking(record)
	if !ok {
		return false
	}
	_, _, dry := resumeModels(record, rules, room)
	return dry != "" || asIs(dir, record, rules, room)
}

// windowed is whether the run waits on a provider's window for its executor's turn, Python's
// resume_needs_executor of a run dry: one whose review alone is left picks only a reviewer.
func windowed(record *run.Object) bool {
	return run.ExhaustedWait(record) == "window" && (record.Str("step") == "executor" || !record.Truthy("review_pending"))
}

// ResumeModels is the pair a resume of a run waiting on a provider's window goes on with
// (resumeModels), or why none can run it yet; false where that pick is not Go's.
func ResumeModels(record *run.Object) (executor, reviewer, dry string, ok bool) {
	if !windowed(record) {
		return "", "", "", false
	}
	rules, room, read := picking(record)
	if !read {
		return "", "", "", false
	}
	executor, reviewer, dry = resumeModels(record, rules, room)
	return executor, reviewer, dry, executor != "" || dry != ""
}

// Dry is why nothing can run the resume of a run waiting on a provider's window yet, Python's
// QuotaDry on a resume: "" once something can, and for any other run.
func Dry(record *run.Object) string {
	_, _, dry, _ := ResumeModels(record)
	return dry
}

// ParkDry keeps waiting a run nothing can run yet, Python's resume_run on its QuotaDry: parked again
// on the record as it was read, with the order the tick gave, no slot and no turn, and its log and
// out say why.
func ParkDry(dir string, read *run.Object, order func(*run.Object), why string, out io.Writer) error {
	err := run.Change(dir, func(record *run.Object) error {
		if !run.Equal(record, read) {
			return ErrChanged
		}
		if order != nil {
			order(record)
		}
		run.SetAll(record, "state", "exhausted", "error", why, "quota_dry", true, "slot_waiting", false)
		return nil
	})
	if err == nil {
		line := stamped("exhausted: " + why)
		appendLog(dir, line)
		io.WriteString(out, line)
	}
	return err
}
