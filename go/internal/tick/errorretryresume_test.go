//go:build linux

package tick

import (
	"bytes"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/host"
	"agentkit/internal/run"
)

// A due error retry climbs its rung with a resume Go makes, started or failed, and with nothing
// else: one Go's resume leaves to Python, even by a box that admits only the first time it is
// asked, or one another writer moves while it is admitted, is Python's as it stands.
func TestAnErrorRetryClimbsOnlyWithAResumeGoMakes(t *testing.T) {
	for _, each := range []struct {
		name, box string
		log       bool
		state     string // after the row; "" where the run is Python's, unwritten
	}{
		{"box refused", "exit 1", true, ""},
		{"record moved during admission", "sed -i 's/^{/{\"waiting_for\": \"other-run\", /' \"$HOME/.agentkit/runs/fix-api/run.json\"", true, ""},
		{"box admitting once", "[ -e \"$0.asked\" ] && exit 1\n: > \"$0.asked\"", true, "queued"},
		{"start failed before its resume wrote", "exit 0", false, "error"},
	} {
		t.Run(each.name, func(t *testing.T) {
			ak, _ := idleHome(t, "")
			for key, value := range map[string]string{"AGENTKIT_RUN_DIR": "", "AGENTKIT_RUN": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"} {
				t.Setenv(key, value)
			}
			put(t, filepath.Join(ak, "config.toml"), "[defaults]\nworkers=['opus','astra']\n[models.opus]\nharness='claude'\nmodel='opus'\neffort='high'\nprovider='anthropic'\n[models.astra]\nharness='codex'\nmodel='astra'\neffort='high'\nprovider='openai'\n[providers.anthropic]\nmode='subscription'\n[providers.openai]\nmode='subscription'\n")
			bin, adapters := filepath.SplitList(os.Getenv("PATH"))[0], t.TempDir()
			script := func(path, body string) {
				put(t, path, "#!/bin/sh\n"+body+"\n")
				if err := os.Chmod(path, 0o700); err != nil {
					t.Fatal(err)
				}
			}
			for _, name := range []string{"claude", "codex"} {
				script(filepath.Join(bin, name), "exit 0")
				script(filepath.Join(adapters, name+".sh"), "printf 'ready\\n'")
			}
			script(filepath.Join(bin, "bwrap"), each.box)
			t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
			now := time.Now()
			put(t, filepath.Join(ak, "state", "usage.json"), run.Line(run.Fields("fetched_at", epoch(now), "providers",
				run.Fields("anthropic", run.Fields("resets", 0), "openai", run.Fields("resets", 0)))))
			put(t, filepath.Join(ak, "state", "session-acme.json"), "{}")
			gone := exec.Command("true")
			if err := gone.Run(); err != nil {
				t.Fatal(err)
			}
			dir := filepath.Join(ak, "runs", "fix-api")
			record := run.Fields("state", "error", "run_id", "fix-api", "pid", gone.Process.Pid,
				"process_identity", run.Fields("boot", "acme-boot", "ticks", 0, "started_at", 0), "worktree", t.TempDir(),
				"no_merge", true, "scratch", true, "rounds", 3, "round_summaries", []any{}, "executor", "opus", "reviewer", "astra",
				"launched_session", "acme", "finished_at", epoch(now), "silence_minutes", run.SilenceMinutes,
				"ceiling_hours", run.CeilingHours, "error_retries", 0, "error_retry_at", epoch(now)-1)
			put(t, filepath.Join(dir, "run.json"), run.Line(record))
			put(t, filepath.Join(dir, "task.md"), "# Retry\n\n## Done when\n```bash\ntrue\n```\n")
			if each.log {
				put(t, filepath.Join(dir, "log.txt"), "")
			}
			var out bytes.Buffer
			err := (&ticking{log: newLog(&out, io.Discard), clock: func() time.Time { return now }}).errorRetry()
			after, readErr := run.Read(dir)
			if readErr != nil {
				t.Fatal(readErr)
			}
			if each.state == "" {
				// the other writer's key aside, the record is as the tick read it
				left := after.Copy()
				left.Delete("waiting_for")
				if !errors.Is(err, errLeft) || !run.Equal(left, record) {
					t.Fatalf("handed over %v, as %s from %s", err, run.Line(after), run.Line(record))
				}
				return
			}
			if each.state == "queued" {
				// the driver it started is this test program, gone at once: its HOME outlives it
				pid, _ := after.Int("pid")
				for deadline := time.Now().Add(10 * time.Second); time.Now().Before(deadline); time.Sleep(5 * time.Millisecond) {
					if stat, known := host.ReadStat(pid); !known || stat.Exited() {
						break
					}
				}
			}
			if retries, _ := after.Int("error_retries"); err != nil || after.Str("state") != each.state || retries != 1 {
				t.Fatalf("returned %v, left %s; said %q", err, run.Line(after), out.String())
			}
		})
	}
}
