//go:build unix

package lock

import (
	"errors"
	"testing"
)

// Shared holders share a directory's lock, which keeps an exclusive one out until both close.
func TestSharedHoldersShareTheLock(t *testing.T) {
	dir := t.TempDir()
	first, err := Shared(dir)
	if err != nil {
		t.Fatal(err)
	}
	second, err := Shared(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Try(dir); !errors.Is(err, ErrHeld) {
		t.Fatalf("Try answered %v", err)
	}
	first.Close()
	second.Close()
	held, err := Try(dir)
	if err != nil {
		t.Fatal(err)
	}
	held.Close()
}
