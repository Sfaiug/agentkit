package run

// ResumeOrdered is whether a resume the tick ordered is still the one to adopt the record: its
// `stall_resume_at` inside handback.STALL_RESUME_GRACE, while reap leaves the dead loop alone.
func ResumeOrdered(record *Object, now float64) bool {
	at, ok := record.Num("stall_resume_at")
	return ok && 0 <= now-at && now-at < 600
}
