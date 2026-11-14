//go:build unix

package tick

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// A line ak's editor typed into the audit seat, its receipt naming the pane, is Python's to finish,
// before anything is written: not the next week's line.
func TestAnAuditLeavesATypedLineItDoesNotFinishToPython(t *testing.T) {
	ak, _ := idleHome(t, answers)
	bin := t.TempDir()
	put(t, filepath.Join(bin, "tmux"), "#!/bin/sh\ncase \"$*\" in *list-sessions*) printf 'audit\\t1\\n' ;; *list-panes*) printf 'audit\\t0\\n' ;; "+
		"*send-keys*) touch \"$HOME/typed\" ;; esac\n")
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non=true\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n"+
		"[providers.test]\nmode='subscription'\n")
	put(t, filepath.Join(ak, "state", "session-audit.json"), `{"orchestrator":"opus","conversation":"conv-audit"}`)
	path := filepath.Join(ak, "state", "audit.json")
	before := `{"week":"2026-W44","line":"earlier work","typed":{"line":"earlier work","seat":1,"pane":"%3"},"delivered":null}`
	put(t, path, before)
	tick := &ticking{clock: func() time.Time { return time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC) }, log: newLog(io.Discard, io.Discard)}
	tick.report = func(time.Time) ([]string, string, bool) { return nil, "fixture loss", true }
	if err := tick.audit(); !errors.Is(err, errLeft) || read(t, path) != before {
		t.Fatal(err, read(t, path))
	}
	if _, err := os.Stat(filepath.Join(os.Getenv("HOME"), "typed")); err == nil {
		t.Fatal("a key was typed")
	}
}
