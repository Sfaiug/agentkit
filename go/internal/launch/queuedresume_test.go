//go:build linux

package launch

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"syscall"
	"testing"
	"time"

	"agentkit/internal/box"
	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// TestMain is the box's first process, or a run's driver, where a test starts this program as one.
func TestMain(m *testing.M) {
	if code, first := box.First(); first {
		os.Exit(code)
	}
	if len(os.Args) == 4 && os.Args[1] == "run" && os.Args[2] == loop.DriveFlag {
		os.Exit(loop.Drive(os.Args[3]))
	}
	os.Exit(m.Run())
}

// A launch whose own process died while it waited for its slot is resumed in the background under
// the gate: the launcher says where the run is, and a process of its own holds the receipt, queued
// since it first queued and resuming from its interruption, says so and waits in line again on its
// launch's options, ahead of a launch that queued after it.
func TestAQueuedRunResumedAfterItsLauncherDiedKeepsItsPlace(t *testing.T) {
	if err := box.Check(); err != nil {
		t.Skip(err) // Python's refusal, before the run's
	}
	home := gatedHome(t, "dry-run")
	adapters := t.TempDir()
	// no user manager, so the driver starts plainly, and no seat
	for key, value := range map[string]string{"AGENTKIT_SESSION": "", "AGENTKIT_ADAPTER_DIR": adapters, "XDG_RUNTIME_DIR": t.TempDir()} {
		t.Setenv(key, value)
	}
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "[defaults]\nworkers = ['opus', 'astra']\n"+
		"[models.opus]\nharness = 'claude'\nmodel = 'opus'\neffort = 'high'\nprovider = 'anthropic'\n"+
		"[models.astra]\nharness = 'codex'\nmodel = 'astra'\neffort = 'high'\nprovider = 'openai'\n"+
		"[providers.anthropic]\nmode = 'subscription'\n[providers.openai]\nmode = 'subscription'\n")
	for _, name := range []string{"claude", "codex"} {
		write(t, filepath.Join(adapters, name+".sh"), "#!/bin/sh\nprintf 'ready\\n'\n")
	}
	held(t, "held")
	waiter := func(id string, ago time.Duration, pid int) *run.Object {
		dir := filepath.Join(run.Runs(), id)
		write(t, filepath.Join(dir, "task.md"), "---\nrepo: none\n---\n# Fix the API\n\n## Done when\n```bash\ntrue\n```\n")
		write(t, filepath.Join(dir, "log.txt"), "")
		at := float64(time.Now().Add(-ago).UnixNano()) / 1e9
		receipt := run.SetAll(run.Capture(dir, "", nil, map[string]bool{"--bg": true}, config.Binding{}, ""),
			"state", "queued", "slot_waiting", true, "queued_at", at, "started_at", at, "pid", pid,
			"repo", nil, "scratch", true, "no_merge", true, "scope", "none", "slot_waited", true,
			"slot_wait_reason", "waiting for a slot · limit full (1 running) · 0 ahead", "slot_wait_kind", "count")
		receipt.Delete("slot_started_at")
		receipt.Delete("reservation_pending")
		if err := run.Create(dir, receipt); err != nil {
			t.Fatal(err)
		}
		return receipt
	}
	gone := exec.Command("true")
	if err := gone.Run(); err != nil {
		t.Fatal(err)
	}
	launched := waiter("acme", time.Hour, gone.Process.Pid)
	waiter("later", time.Minute, os.Getpid())

	dir := filepath.Join(run.Runs(), "acme")
	var out, errOut bytes.Buffer
	code, why, err := Resume("acme", 0, true, &out, &errOut)
	record, _ := run.Read(dir)
	pid, _ := record.Int("pid")
	t.Cleanup(func() {
		// the driver waits in line for good: ended before its HOME goes
		syscall.Kill(pid, syscall.SIGKILL)
		for deadline := time.Now().Add(10 * time.Second); time.Now().Before(deadline); time.Sleep(5 * time.Millisecond) {
			if stat, known := host.ReadStat(pid); !known || stat.Exited() {
				return
			}
		}
	})
	if code != 0 || why != "" || err != nil || out.String() != "acme\n"+filepath.Join(dir, "result.md")+"\n" {
		t.Fatalf("resumed (%d, %q, %v), said %q %q", code, why, err, out.String(), errOut.String())
	}
	const waits = "waiting for a slot · limit full (1 running) · 0 ahead\n"
	var logged string
	for deadline := time.Now().Add(30 * time.Second); time.Now().Before(deadline) && !strings.Contains(logged, waits); time.Sleep(20 * time.Millisecond) {
		data, _ := os.ReadFile(filepath.Join(dir, "log.txt"))
		logged = string(data)
	}
	resumed := strings.Index(logged, " resume acme: "+filepath.Join(dir, "task.md")+"\n")
	if resumed < 0 || strings.Index(logged, waits) < resumed {
		t.Fatalf("logged %q", logged)
	}
	record, _ = run.Read(dir)
	at, _ := record.Num("queued_at")
	was, _ := launched.Num("queued_at")
	if record.Str("state") != "queued" || !record.Truthy("slot_waiting") || at != was || record.Str("resume_from") != "interrupted" ||
		!run.Equal(record.Get("launch_opts"), launched.Get("launch_opts")) || pid == gone.Process.Pid || pid == os.Getpid() || !run.ProcessActive(record) {
		t.Fatalf("the receipt: %s", run.Line(record))
	}
	if line, _ := queued(); !slices.Equal(line.queue, []string{"acme", "later"}) {
		t.Fatalf("the line: %v", line.queue)
	}
}

func write(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o700); err != nil {
		t.Fatal(err)
	}
}
