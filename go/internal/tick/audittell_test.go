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

// A line typed into the audit seat that Go does not finish is Python's, before anything is
// written: not the next week's line, nor that an owner's close holds it.
func TestAnAuditLeavesATypedLineItDoesNotFinishToPython(t *testing.T) {
	up := "*list-sessions*) printf 'audit\\t1\\n' ;; *list-panes*) printf 'audit\\t0\\n' ;;"
	for _, each := range []struct{ name, tmux, typed, mark, stall string }{
		// a seat not up, its composer gone with it (milestone 140a3), which the owner closed
		{"gone", "", `{"line":"earlier work","seat":1}`, `{"closed_by_owner":true}`, `{}`},
		// ak's editor's receipt, naming the pane it went into, in a seat up at Claude
		{"through the editor", up, `{"line":"earlier work","seat":1,"pane":"%3"}`, `{}`, `{}`},
		// a stall's line, sent before the week's is written (milestone 140b)
		{"behind a stall's line", up, `null`, `{}`, `{"line":"ak stalled","typed":{"line":"ak stalled","seat":1},"delivered":null}`},
	} {
		t.Run(each.name, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			bin := t.TempDir()
			put(t, filepath.Join(bin, "tmux"), "#!/bin/sh\ncase \"$*\" in "+each.tmux+" *send-keys*) touch \"$HOME/typed\" ;; esac\n")
			if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
				t.Fatal(err)
			}
			t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
			put(t, filepath.Join(ak, "config.toml"), "[audit]\non=true\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n"+
				"[providers.test]\nmode='subscription'\n")
			put(t, filepath.Join(ak, "state", "session-audit.json"), `{"orchestrator":"opus","conversation":"conv-audit"}`)
			put(t, filepath.Join(ak, "state", "seat-audit.json"), each.mark)
			put(t, filepath.Join(ak, "state", "stuck.json"), each.stall)
			path := filepath.Join(ak, "state", "audit.json")
			before := `{"week":"2026-W44","line":"earlier work","typed":` + each.typed + `,"delivered":null}`
			put(t, path, before)
			tick := &ticking{clock: func() time.Time { return time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC) }, log: newLog(io.Discard, io.Discard)}
			tick.report = func(time.Time) ([]string, string) { return nil, "fixture loss" }
			if err := tick.audit(); !errors.Is(err, errLeft) || read(t, path) != before {
				t.Fatal(err, read(t, path))
			}
			if _, err := os.Stat(filepath.Join(os.Getenv("HOME"), "typed")); err == nil {
				t.Fatal("a key was typed")
			}
		})
	}
}
