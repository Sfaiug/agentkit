package run

// WriterActive is whether a record's writer may still run: a malformed identity is no proof it
// exited (retention.writer_active).
func WriterActive(record *Object) bool {
	if record.Get("pid") != nil {
		if pid, ok := record.Int("pid"); !ok || pid <= 0 {
			return true
		}
	}
	if identity := record.Get("process_identity"); identity != nil {
		saved, ok := identity.(*Object)
		if !ok || !saved.Truthy("boot") {
			return true
		}
		if _, ok := saved.Int("ticks"); !ok {
			return true
		}
	}
	return ProcessActive(record)
}
