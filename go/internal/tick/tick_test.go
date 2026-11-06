//go:build unix

package tick

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"agentkit/internal/lock"
)

// stamped is a log's line beginning with its date and time.
var stamped = regexp.MustCompile(`^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d `)

// tickHome is a home holding ak's state and tmp folders, and where the tick's lock, log and kept
// log go in them.
func tickHome(t *testing.T) (lockFile, live, kept string) {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	for _, place := range []string{"state", "tmp"} {
		if err := os.MkdirAll(filepath.Join(home, ".agentkit", place), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	tmp := filepath.Join(home, ".agentkit", "tmp")
	return filepath.Join(home, ".agentkit", "state", "watch.tick.lock"), filepath.Join(tmp, logName), filepath.Join(tmp, logKept)
}

func held(t *testing.T, path string) {
	t.Helper()
	holding, err := lock.Try(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { holding.Close() })
}

func read(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

// appending is a stream as cron's `>>` opens one.
func appending(t *testing.T, path string) *os.File {
	t.Helper()
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { file.Close() })
	return file
}

// The holder's pid reads as Python's int() reads the lock file's stripped text, else 0.
func TestHolderPidReadsAsPythonsInt(t *testing.T) {
	t.Setenv("PYTHONINTMAXSTRDIGITS", "")
	path := filepath.Join(t.TempDir(), "watch.tick.lock")
	nines := strings.Repeat("9", 4300)
	for text, want := range map[string]string{
		"4242\n": "4242", " +007 ": "7", "-12": "-12", "-0": "0", "0042": "42", "1_000": "1000",
		"\x1f42\u0085": "42", "٤٢\u3000": "42", "𝟗𝟘": "90", nines: nines, "0" + nines: "0", nines + "9": "0",
		"": "0", " \n": "0", "_1": "0", "1_": "0", "1__0": "0", "+": "0", "+-5": "0", "- 5": "0", "4 2": "0",
		"0x10": "0", "4.2": "0", "4\x002": "0", "4242\xff": "0", "\xff4242": "0", "\ufeff42": "0",
	} {
		if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
		if got, _ := holder(path); got.String() != want {
			t.Errorf("%.20q: read %.20s, want %.20s", text, got, want)
		}
	}
}

// When the holder began is the file's mtime, a clock behind it as much as one ahead, and a file
// gone reads nobody's pid, beginning now.
func TestHolderBeganAtTheFilesMtime(t *testing.T) {
	path := filepath.Join(t.TempDir(), "watch.tick.lock")
	before := time.Now()
	if pid, began := holder(path); pid.Sign() != 0 || began.Before(before) || began.After(time.Now()) {
		t.Fatalf("a missing file: %s, %v", pid, began)
	}
	if err := os.WriteFile(path, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	for _, ago := range []time.Duration{time.Hour, -time.Hour} {
		mtime := time.Now().Add(-ago).Truncate(time.Second)
		if err := os.Chtimes(path, time.Time{}, mtime); err != nil {
			t.Fatal(err)
		}
		if _, began := holder(path); !began.Equal(mtime) {
			t.Errorf("mtime %v ago: began %v", ago, began)
		}
	}
}

// What Go does not carry out it leaves as it found: a missing lock, a free one, and a held one
// where ak's folders cannot be made, as Python fails at that folder.
func TestOverlapLeavesToPythonWhatItCannotAnswer(t *testing.T) {
	var out, errOut bytes.Buffer
	lockFile, live, _ := tickHome(t)
	if Overlap(&out, &errOut) {
		t.Error("a missing lock read as held")
	}
	if _, err := os.Stat(lockFile); !os.IsNotExist(err) {
		t.Errorf("the look made the lock: %v", err)
	}
	if err := os.WriteFile(lockFile, []byte("4242\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if Overlap(&out, &errOut) {
		t.Error("a free lock read as held")
	}
	if got := read(t, lockFile); got != "4242\n" {
		t.Errorf("the look wrote %q into the lock", got)
	}
	held(t, lockFile)
	if err := os.RemoveAll(filepath.Dir(live)); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Dir(live), nil, 0o600); err != nil {
		t.Fatal(err)
	}
	if Overlap(&out, &errOut) {
		t.Error("a file where a folder goes still printed the holder")
	}
	if out.Len()+errOut.Len() != 0 {
		t.Errorf("printed %q %q", out.String(), errOut.String())
	}
}

// ak's folders come first, as Python's main makes them before it tries the lock.
func TestOverlapMakesAksFoldersFirst(t *testing.T) {
	lockFile, live, _ := tickHome(t)
	held(t, lockFile)
	if err := os.RemoveAll(filepath.Dir(live)); err != nil {
		t.Fatal(err)
	}
	if !Overlap(io.Discard, io.Discard) {
		t.Fatal("a held lock read as free")
	}
	if info, err := os.Stat(filepath.Dir(live)); err != nil || !info.IsDir() {
		t.Fatalf("tmp after the tick: %v %v", info, err)
	}
}

// Past the limit the log moves aside, and both of cron's streams rejoin a new one.
func TestARollMovesTheLogAndBothStreamsRejoinIt(t *testing.T) {
	lockFile, live, kept := tickHome(t)
	held(t, lockFile)
	out, errOut := appending(t, live), appending(t, live)
	if err := os.Truncate(live, logMax+1); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(kept, []byte("old"), 0o600); err != nil {
		t.Fatal(err)
	}
	if !Overlap(out, errOut) {
		t.Fatal("a held lock read as free")
	}
	if info, err := os.Stat(kept); err != nil || info.Size() != logMax+1 {
		t.Fatalf("the kept log: %v %v", info, err)
	}
	errOut.WriteString("said on stderr\n")
	if got := read(t, live); !stamped.MatchString(got) || !strings.Contains(got, "tick already running") || !strings.HasSuffix(got, "\nsaid on stderr\n") {
		t.Fatalf("the new log holds %q", got)
	}
	if _, err := os.Stat(filepath.Join(filepath.Dir(lockFile), logName+".lock")); err != nil {
		t.Fatalf("the roll took no lock: %v", err)
	}
}

// A stream another tick's roll left on the kept generation rejoins the live log unrolled.
func TestAStreamOneRollBehindRejoinsTheLiveLog(t *testing.T) {
	lockFile, live, kept := tickHome(t)
	held(t, lockFile)
	out := appending(t, live)
	if err := os.Rename(live, kept); err != nil {
		t.Fatal(err)
	}
	if !Overlap(out, io.Discard) {
		t.Fatal("a held lock read as free")
	}
	if got := read(t, kept); got != "" {
		t.Errorf("the kept log took %q", got)
	}
	if got := read(t, live); !stamped.MatchString(got) || !strings.Contains(got, "tick already running") {
		t.Errorf("the live log holds %q", got)
	}
}

// Only a stream that is the log counts: stdout elsewhere stays there while stderr rolls and
// rejoins, and with neither stream on it the log is left whatever its size.
func TestAStreamElsewhereStaysThere(t *testing.T) {
	lockFile, live, kept := tickHome(t)
	held(t, lockFile)
	elsewhere := live + ".elsewhere"
	out, errOut := appending(t, elsewhere), appending(t, elsewhere)
	if err := os.WriteFile(live, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Truncate(live, logMax+1); err != nil {
		t.Fatal(err)
	}
	Overlap(out, errOut)
	if info, err := os.Stat(live); err != nil || info.Size() != logMax+1 {
		t.Fatalf("no stream on the log, and the log became %v %v", info, err)
	}
	if _, err := os.Stat(kept); !os.IsNotExist(err) {
		t.Fatalf("no stream on the log, and it rolled: %v", err)
	}
	errOut = appending(t, live)
	Overlap(out, errOut)
	if info, err := os.Stat(kept); err != nil || info.Size() != logMax+1 {
		t.Fatalf("stderr on the log, and the kept log is %v %v", info, err)
	}
	errOut.WriteString("said on stderr\n")
	if got := read(t, live); got != "said on stderr\n" {
		t.Errorf("the new log holds %q", got)
	}
	if got := read(t, elsewhere); strings.Count(got, "tick already running") != 2 || !strings.HasPrefix(got, "tick already running") {
		t.Errorf("elsewhere holds %q", got)
	}
}
