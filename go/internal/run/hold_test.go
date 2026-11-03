package run

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// A change made while the process holds the run's recovery lock takes that hold as its own, as
// Python's reentrant recovery_lock does, rather than waiting on itself.
func TestAChangeUnderHoldIsWrittenAtOnce(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "run.json"), []byte(`{"run_id": "acme-fix"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	release, err := Hold(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	done := make(chan error, 1)
	go func() {
		done <- Change(dir, func(record *Object) error {
			record.Set("checkout_kept", true)
			return nil
		})
	}()
	select {
	case err := <-done:
		if record, _ := Read(dir); err != nil || record == nil || !record.Truthy("checkout_kept") {
			t.Fatalf("not written: %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("the change waited on the hold it is made under")
	}
}
