package loop

import (
	"testing"

	"agentkit/internal/run"
)

func TestAResumedErrorSaysItResumesFromTheError(t *testing.T) {
	l := rig(t, 0)
	if err := run.Change(l.dir, func(record *run.Object) error {
		run.SetAll(record, "state", "error", "error", "git failed", "error_retries", 1)
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	read, _ := run.Read(l.dir)
	if err := Reopen(l.dir, read); err != nil {
		t.Fatal(err)
	}
	record, _ := run.Read(l.dir)
	if record.Str("state") != "queued" || record.Str("resume_from") != "error" || record.Truthy("error") || record.Has("deaths") {
		t.Fatalf("record %s", run.Line(record))
	}
}
