//go:build linux

package tick

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/host"
	"agentkit/internal/run"
)

func TestFrozenLoopsLeaveTheirStallClocksToPython(t *testing.T) {
	ak, _ := idleHome(t, answers)
	root := t.TempDir()
	t.Setenv("AK_CGROUP_ROOT", root)
	identity, known := host.ReadIdentity(os.Getpid())
	if !known {
		t.Fatal("test process identity unreadable")
	}
	for _, frozen := range []bool{false, true} {
		for _, saved := range []bool{false, true} {
			for _, delivery := range []bool{false, true} {
				t.Run(fmt.Sprintf("frozen=%v/saved=%v/delivery=%v", frozen, saved, delivery), func(t *testing.T) {
					value := "0\n"
					if frozen {
						value = "1\n"
					}
					put(t, filepath.Join(root, "cgroup.freeze"), value)
					record := run.Fields("state", "running", "pid", os.Getpid(), "process_identity",
						run.Fields("boot", identity.Boot, "ticks", int(identity.Ticks)))
					if saved {
						record.Set("frozen_since", 1)
					}
					if delivery {
						record.Set("delivery_wait", os.Getpid())
					}
					path := filepath.Join(ak, "runs", "r-build", "run.json")
					put(t, path, run.Line(record))
					if !run.ProcessActive(record) {
						t.Fatal("test loop not active")
					}
					tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
					if left, want := errors.Is(tick.stallRecovery(), errLeft), frozen || saved; left != want {
						t.Fatalf("stall row left=%v, want %v", left, want)
					}
					if read(t, path) != run.Line(record) {
						t.Fatal("Go changed the freeze bookkeeping left to Python")
					}
				})
			}
		}
	}
}

// stalledRun is a run the seat acme launched whose live loop has been silent 22 minutes, past the
// rungs stalls holds, on a box bwrap answers as that script does.
func stalledRun(t *testing.T, bwrap string, stalls ...any) (string, *run.Object, *ticking) {
	t.Helper()
	ak, _ := idleHome(t, answers)
	bin, adapters := filepath.SplitList(os.Getenv("PATH"))[0], t.TempDir()
	for key, value := range map[string]string{"AGENTKIT_ADAPTER_DIR": adapters, "AGENTKIT_RUN_DIR": "", "AGENTKIT_RUN": "",
		"AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"} {
		t.Setenv(key, value)
	}
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non=false\n[defaults]\nworkers=['opus','astra']\n"+
		"[models.opus]\nharness='claude'\nmodel='opus'\neffort='high'\nprovider='anthropic'\n"+
		"[models.astra]\nharness='codex'\nmodel='astra'\neffort='high'\nprovider='openai'\n"+
		"[providers.anthropic]\nmode='subscription'\n[providers.openai]\nmode='subscription'\n")
	for path, body := range map[string]string{filepath.Join(bin, "claude"): "exit 0", filepath.Join(bin, "codex"): "exit 0",
		filepath.Join(adapters, "claude.sh"): "printf 'ready\\n'", filepath.Join(adapters, "codex.sh"): "printf 'ready\\n'",
		filepath.Join(bin, "bwrap"): bwrap} {
		put(t, path, "#!/bin/sh\n"+body+"\n")
		if err := os.Chmod(path, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	now := time.Now()
	put(t, filepath.Join(ak, "state", "usage.json"), run.Line(run.Fields("fetched_at", epoch(now), "providers",
		run.Fields("anthropic", run.Fields("resets", 0), "openai", run.Fields("resets", 0)))))
	put(t, filepath.Join(ak, "state", "session-acme.json"), `{"orchestrator":"opus"}`)
	loop := exec.Command("sleep", "600")
	if err := loop.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { loop.Process.Kill(); loop.Wait() })
	born, ok := host.ReadIdentity(loop.Process.Pid)
	if !ok {
		t.Fatal("loop identity unreadable")
	}
	dir := filepath.Join(ak, "runs", "fix-api")
	record := run.Fields("state", "running", "run_id", "fix-api", "pid", loop.Process.Pid,
		"process_identity", run.Fields("boot", born.Boot, "ticks", int(born.Ticks), "started_at", born.StartedAt),
		"worktree", t.TempDir(), "no_merge", true, "scratch", true, "rounds", 3, "round_summaries", []any{},
		"executor", "opus", "reviewer", "astra", "workers", []any{"opus", "astra"}, "reviewers", []any{"opus", "astra"},
		"launched_session", "acme", "silence_minutes", 20, "ceiling_hours", 6, "stalls", append([]any{}, stalls...))
	put(t, filepath.Join(dir, "task.md"), "# Retry\n\n## Done when\n```bash\ntrue\n```\n")
	put(t, filepath.Join(dir, "log.txt"), "")
	return dir, record, &ticking{log: newLog(io.Discard, io.Discard), clock: func() time.Time { return now }}
}

// silenced writes the run's record as it stands and back-dates every file of the run past its limit.
func silenced(t *testing.T, dir string, record *run.Object) string {
	t.Helper()
	put(t, filepath.Join(dir, "run.json"), run.Line(record))
	old := time.Now().Add(-22 * time.Minute)
	if err := filepath.WalkDir(dir, func(path string, _ os.DirEntry, err error) error {
		return cmp.Or(err, os.Chtimes(path, old, old))
	}); err != nil {
		t.Fatal(err)
	}
	return read(t, filepath.Join(dir, "run.json"))
}

// A rung Go does not carry, a park whose seat takes no line now or a resume Go's own does not take,
// is Python's before the loop is ended or anything of the run is written.
func TestARungGoDoesNotCarryHandsOverBeforeItEndsOrWritesAnything(t *testing.T) {
	for name, rung := range map[string]struct {
		bwrap  string
		stalls []any
	}{
		"park at a busy seat": {"exit 0", []any{run.Fields("action", "killed step"), run.Fields("action", "resumed")}},
		"resume on no box":    {"exit 1", nil},
	} {
		t.Run(name, func(t *testing.T) {
			dir, record, tick := stalledRun(t, rung.bwrap, rung.stalls...)
			// a seat up, its screen busy with a turn
			tmux := filepath.Join(filepath.SplitList(os.Getenv("PATH"))[0], "tmux")
			put(t, tmux, "#!/bin/sh\ncase \"$*\" in\n*list-sessions*) printf 'acme\\t1\\n';;\n*list-panes*) printf '%%1 0\\n';;\n"+
				"*capture-pane*) printf 'Working on the patch...\\n';;\n*display-message*) printf '%%1\\t1000\\n';;\nesac\n")
			if err := os.Chmod(tmux, 0o700); err != nil {
				t.Fatal(err)
			}
			before := silenced(t, dir, record)
			if err := tick.stallRecovery(); !errors.Is(err, errLeft) || read(t, filepath.Join(dir, "run.json")) != before ||
				!run.ProcessActive(record) {
				t.Fatalf("left=%v, loop alive=%v, record:\n%s", err, run.ProcessActive(record), read(t, filepath.Join(dir, "run.json")))
			}
		})
	}
}

// The resume rung ends the loop and starts the new one on a record of any age: its stall lands with
// the resume's own write, whatever limits an older ak left on the record.
func TestTheResumeRungStartsTheNewLoopOnAnOlderRecord(t *testing.T) {
	for _, key := range []string{"ceiling_hours", "silence_minutes", "done_when_minutes", "turn_hours", "stall_minutes"} {
		t.Run(key, func(t *testing.T) {
			dir, record, tick := stalledRun(t, "exit 0")
			if record.Has(key) {
				record.Delete(key)
			} else {
				record.Set(key, 60)
			}
			silenced(t, dir, record)
			if err := tick.stallRecovery(); err != nil {
				t.Fatal(err)
			}
			after, _ := run.Read(dir)
			stalls := after.List("stalls")
			if run.ProcessActive(record) || run.Equal(after.Get("pid"), record.Get("pid")) || len(stalls) != 1 ||
				stalls[0].(*run.Object).Str("action") != "resumed" {
				t.Fatalf("old loop alive=%v, record:\n%s", run.ProcessActive(record), run.Line(after))
			}
		})
	}
}
