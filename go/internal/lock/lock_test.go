package lock

import (
	"context"
	"errors"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"
	"testing"
	"time"
)

func TestTryAnswersHeldUntilTheHolderCloses(t *testing.T) {
	path := filepath.Join(t.TempDir(), "acme.lock")
	first, err := Try(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Try(path); !errors.Is(err, ErrHeld) {
		t.Fatalf("a second Try answered %v, want ErrHeld", err)
	}
	first.Close()
	again, err := Try(path)
	if err != nil {
		t.Fatalf("Try after the holder closed: %v", err)
	}
	again.Close()
}

func TestWaitGivesUpWhenItsContextEnds(t *testing.T) {
	path := filepath.Join(t.TempDir(), "acme.lock")
	holder, err := Try(path)
	if err != nil {
		t.Fatal(err)
	}
	defer holder.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	if _, err := Wait(ctx, path); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Wait on a held lock answered %v, want the context's end", err)
	}
}

func TestWaitTakesTheLockOnceItIsFree(t *testing.T) {
	path := filepath.Join(t.TempDir(), "acme.lock")
	ending, cancel := context.WithCancel(context.Background())
	defer cancel()
	for _, ctx := range []context.Context{context.Background(), ending} {
		holder, err := Try(path)
		if err != nil {
			t.Fatal(err)
		}
		time.AfterFunc(50*time.Millisecond, func() { holder.Close() })
		file, err := Wait(ctx, path)
		if err != nil {
			t.Fatalf("Wait once the holder closed: %v", err)
		}
		file.Close()
	}
}

func TestHeldReadsTheLockAndNeverMakesTheFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "acme.lock")
	if Held(path) {
		t.Fatal("a missing file reads held")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("Held made the file: %v", err)
	}
	holder, err := Try(path)
	if err != nil {
		t.Fatal(err)
	}
	if !Held(path) {
		t.Fatal("a held lock reads free")
	}
	holder.Close()
	if Held(path) {
		t.Fatal("a lock its holder closed reads held")
	}
}

func TestADirectoryIsLockedOpenedToRead(t *testing.T) {
	dir := t.TempDir()
	holder, err := Wait(context.Background(), dir)
	if err != nil {
		t.Fatal(err)
	}
	defer holder.Close()
	second, err := Try(dir)
	if runtime.GOOS == "windows" {
		if err != nil {
			t.Fatalf("Windows locks no directory, yet Try answered %v", err)
		}
		second.Close()
		return
	}
	if !errors.Is(err, ErrHeld) {
		t.Fatalf("a second Try on a locked directory answered %v, want ErrHeld", err)
	}
}

func TestEditReadsAndWritesAFileItNeverMakes(t *testing.T) {
	path := filepath.Join(t.TempDir(), "hand-in.jsonl")
	if _, err := Edit(path); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("Edit on a missing file answered %v, want it left missing", err)
	}
	if err := os.WriteFile(path, []byte("first\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	holder, err := Edit(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Try(path); !errors.Is(err, ErrHeld) {
		t.Fatalf("Try while Edit holds the lock answered %v, want ErrHeld", err)
	}
	if data, err := io.ReadAll(holder); err != nil || string(data) != "first\n" {
		t.Fatalf("Edit read %q (%v)", data, err)
	}
	if _, err := holder.WriteString("second\n"); err != nil {
		t.Fatal(err)
	}
	holder.Close()
	if data, _ := os.ReadFile(path); string(data) != "first\nsecond\n" {
		t.Fatalf("the file holds %q, want the line appended", data)
	}
}
