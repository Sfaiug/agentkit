//go:build unix

package lock

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
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

// Readers share a file's lock, which keeps an exclusive holder out until both close, and never
// make the file: a reader is never kept waiting by another, as Python's LOCK_SH readers are not.
func TestReadersShareAFileTheyNeverMake(t *testing.T) {
	path := filepath.Join(t.TempDir(), "receipt.json")
	if _, err := Read(path); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("Read on a missing file answered %v, want it left missing", err)
	}
	if err := os.WriteFile(path, []byte("{}"), 0o600); err != nil {
		t.Fatal(err)
	}
	first, err := Read(path)
	if err != nil {
		t.Fatal(err)
	}
	second, err := Read(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Try(path); !errors.Is(err, ErrHeld) {
		t.Fatalf("Try while readers hold the lock answered %v, want ErrHeld", err)
	}
	first.Close()
	second.Close()
	held, err := Try(path)
	if err != nil {
		t.Fatal(err)
	}
	held.Close()
}
