package parsed

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// A file is parsed again once its stat changed, and at every read while it changed within the
// last second; otherwise every read gets the parse it was kept with.
func TestAFileIsParsedAgainOnlyOnceItChanged(t *testing.T) {
	path, parses := filepath.Join(t.TempDir(), "seat-acme.json"), 0
	text := Of(func(path string) (string, error) {
		parses++
		data, err := os.ReadFile(path)
		return string(data), err
	})
	read := func(want string, parsed int) {
		t.Helper()
		if got, err := text.Read(path); err != nil || got != want || parses != parsed {
			t.Fatalf("read %q, %v after %d parses; want %q after %d", got, err, parses, want, parsed)
		}
	}
	write := func(data string) {
		t.Helper()
		if err := os.WriteFile(path, []byte(data), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	write("idle")
	read("idle", 1) // fresh: its stat vouches for nothing yet
	read("idle", 2)
	time.Sleep(fresh + 100*time.Millisecond)
	read("idle", 3)
	read("idle", 3)
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	write("done") // in place, the same size, its mtime set back: only its ctime says it changed
	if err := os.Chtimes(path, info.ModTime(), info.ModTime()); err != nil {
		t.Fatal(err)
	}
	read("done", 4)
	os.Remove(path)
	if _, err := text.Read(path); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("a file gone reads as %v", err)
	}
}
