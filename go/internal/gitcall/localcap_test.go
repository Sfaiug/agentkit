//go:build unix

package gitcall

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// A git asking no remote gets the base limit times the host's load per core, where that is over
// one, and the hour at most; a fetch gets the base limit however busy the host.  The git is a
// script that takes 3 s, the base limit 1 s.
func TestAGitAskingNoRemoteGetsTimeByLoad(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	shim := t.TempDir()
	if err := os.WriteFile(filepath.Join(shim, "git"), []byte("#!/bin/sh\nexec sleep 3\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", shim+string(os.PathListSeparator)+os.Getenv("PATH"))
	defer func(was time.Duration, read func() (float64, int)) { base, hostLoad = was, read }(base, hostLoad)
	base = time.Second
	at := func(perCore float64) { hostLoad = func() (float64, int) { return perCore * 4, 4 } }
	code := func(verb string) int {
		code, _, _, err := Git{}.Bytes(verb)
		if err != nil {
			t.Fatal(err)
		}
		return code
	}
	at(600)
	if got := code("status"); got != 0 {
		t.Errorf("a status at 600 times the cores' load: exit %d, want 0", got)
	}
	if got := code("fetch"); got != timedOut {
		t.Errorf("a fetch at 600 times the cores' load: exit %d, want killed at the base limit", got)
	}
	at(0.5)
	if got := code("status"); got != timedOut {
		t.Errorf("a status with a core free: exit %d, want killed at the base limit", got)
	}
	at(1e12)
	if got := defaultCap([]string{"status"}); got != time.Hour {
		t.Errorf("a status at 1e12 times the cores' load gets %v, want the hour", got)
	}
}
