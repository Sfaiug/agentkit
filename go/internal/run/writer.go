package run

// ScratchMark is the file in a folder a process makes in a run's folder for throwaway work that
// names its maker as a record names its writer, `pid` and `process_identity` (record.SCRATCH):
// the collector keeps the run of one whose maker lives, and takes one whose maker is gone.
const ScratchMark = ".ak-scratch"

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
