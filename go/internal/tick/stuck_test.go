//go:build unix

package tick

import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

var stallNow = time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC)

// stallHome is a home with the audit on, its seat's record and the run first in line for a slot
// for two hours, where the last firsts let in waited a quarter of an hour.  Its path holds what a
// pattern reads otherwise, as a home's may.
func stallHome(t *testing.T) string {
	idle, _ := idleHome(t, answers)
	home := filepath.Join(t.TempDir(), "acme[1")
	ak := filepath.Join(home, ".agentkit")
	if err := os.Mkdir(home, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(idle, ak); err != nil {
		t.Fatal(err)
	}
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non=true\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n"+
		"[providers.test]\nmode='subscription'\n")
	put(t, filepath.Join(ak, "state", "session-audit.json"), `{"orchestrator":"opus","conversation":"conv-audit"}`)
	at := epoch(stallNow)
	put(t, filepath.Join(ak, "runs", ".slots.queue"), run.Line(run.Fields("at", run.Float(at), "running", 1,
		"queue", []any{"20261105-0900-fix-api", "20261105-0901-fix-web"}, "since", run.Float(at-7200),
		"took", []any{run.Number("600"), run.Number("900"), run.Number("1200")}, "last_in", run.Float(at-7200), "turns", []any{})))
	return ak
}

// A stall's line typed and not yet delivered goes before a new week's line is written, through
// the week's steps: here an owner's close holds it, saying what it is about.
func TestAStallsTypedLineGoesBeforeTheWeeksThroughTheSameSteps(t *testing.T) {
	ak := stallHome(t)
	bin := t.TempDir()
	put(t, filepath.Join(bin, "tmux"), "#!/bin/sh\ncase \"$*\" in *list-sessions*) printf 'audit\\t1\\n' ;; *list-panes*) printf 'audit\\t0\\n' ;; esac\n")
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	put(t, filepath.Join(ak, "state", "seat-audit.json"), `{"closed_by_owner":true}`)
	week := filepath.Join(ak, "state", "audit.json")
	before := `{"week":"2026-W44","line":"earlier work","typed":null,"delivered":1}`
	put(t, week, before)
	stall := filepath.Join(ak, "state", "stuck.json")
	put(t, stall, `{"about":"the stall of the slot queue","line":"ak stalled","typed":{"line":"ak stalled","seat":1},"delivered":null,"told":["slot:x"]}`)
	var said bytes.Buffer
	tick := &ticking{clock: func() time.Time { return stallNow }, log: newLog(&said, io.Discard)}
	tick.report = func(time.Time) ([]string, string) { return nil, "fixture loss" }
	if err := tick.audit(); err != nil || read(t, week) != before {
		t.Fatal(err, read(t, week))
	}
	if state, _ := run.ReadJSON(stall); !state.Truthy("held") || state.Str("line") != "ak stalled" {
		t.Fatal(read(t, stall))
	}
	if !strings.Contains(said.String(), "its line about the stall of the slot queue waits for them to open it") {
		t.Fatal(said.String())
	}
}

// A stall told leaves `told` on file once it ends, though nothing new is stuck.
func TestAnEndedStallLeavesToldOnFile(t *testing.T) {
	ak := stallHome(t)
	if err := os.Remove(filepath.Join(ak, "runs", ".slots.queue")); err != nil {
		t.Fatal(err)
	}
	put(t, filepath.Join(ak, "state", "audit.json"), `{"week":"2026-W45","line":"this week","typed":null,"delivered":1}`)
	stall := filepath.Join(ak, "state", "stuck.json")
	put(t, stall, `{"about":"the stall of the slot queue","line":"ak stalled","typed":null,"delivered":1,"told":["slot:x"]}`)
	tick := &ticking{clock: func() time.Time { return stallNow }, log: newLog(io.Discard, io.Discard)}
	if err := tick.audit(); err != nil {
		t.Fatal(err)
	}
	if state, _ := run.ReadJSON(stall); state == nil || len(state.List("told")) != 0 || state.Str("line") != "ak stalled" {
		t.Fatal(read(t, stall))
	}
}

// A stall Go does not read leaves the tick to Python before a stall's line is written, though
// the slot queue's is due.
func TestAStallGoDoesNotReadIsLeftBeforeAnythingIsWritten(t *testing.T) {
	for _, each := range []struct {
		name  string
		stall func(t *testing.T, ak string)
	}{
		{"a landing line's check pass under way", func(t *testing.T, ak string) {
			born, known := host.ReadIdentity(os.Getpid())
			if !known {
				t.Skip("no /proc to read this process's identity from")
			}
			put(t, filepath.Join(ak, "runs", ".merge-acme.passes"), run.Line(run.Fields("took", []any{run.Number("60"), run.Number("60"), run.Number("60")},
				"started", run.Float(epoch(stallNow)-60), "pid", os.Getpid(), "process_identity",
				run.Fields("boot", born.Boot, "ticks", int(born.Ticks), "started_at", born.StartedAt))))
		}},
		{"~/agentkit is this checkout", func(t *testing.T, ak string) {
			if err := os.Symlink(config.Repo(), filepath.Join(filepath.Dir(ak), "agentkit")); err != nil {
				t.Fatal(err)
			}
		}},
	} {
		t.Run(each.name, func(t *testing.T) {
			ak := stallHome(t)
			put(t, filepath.Join(ak, "state", "audit.json"), `{"week":"2026-W45","line":"this week","typed":null,"delivered":1}`)
			each.stall(t, ak)
			tick := &ticking{clock: func() time.Time { return stallNow }, log: newLog(io.Discard, io.Discard)}
			if err := tick.audit(); !errors.Is(err, errLeft) {
				t.Fatal(err)
			}
			if _, err := os.Stat(filepath.Join(ak, "state", "stuck.json")); !errors.Is(err, os.ErrNotExist) {
				t.Fatal("a stall was written", err)
			}
		})
	}
}
