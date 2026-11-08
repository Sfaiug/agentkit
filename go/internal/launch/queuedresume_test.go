//go:build linux

package launch

import (
	"bytes"
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
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

// TestMain is the box's first process, a run's driver or a `--bg` job's launcher, where a test
// starts this program as one: a driver leaves in its run's `waits-as` the run AGENTKIT_RUN_DIR
// names as it waits for its slot, or finds its task done where AK_TEST_DONE says so (done).
func TestMain(m *testing.M) {
	if code, first := box.First(); first {
		os.Exit(code)
	}
	if len(os.Args) == 4 && os.Args[1] == "run" && os.Args[2] == "resume" {
		code, err := ResumeJob(os.Args[3], os.Stdout)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			code = 2
		}
		os.Exit(code)
	}
	if len(os.Args) == 4 && os.Args[1] == "run" && os.Args[2] == loop.DriveFlag && os.Getenv("AK_TEST_DONE") != "" {
		os.Exit(done(os.Args[3]))
	}
	if len(os.Args) == 4 && os.Args[1] == "run" && os.Args[2] == loop.DriveFlag {
		wait := loop.WaitSlot
		loop.WaitSlot = func(ctx context.Context, dir string) error {
			os.WriteFile(filepath.Join(dir, "waits-as"), []byte(os.Getenv("AGENTKIT_RUN_DIR")), 0o600)
			return wait(ctx, dir)
		}
		os.Exit(loop.Drive(os.Args[3]))
	}
	os.Exit(m.Run())
}

// A launch whose own process died while it waited for its slot is resumed in the background under
// the gate: the launcher says where the run is, and a process of its own holds the receipt, queued
// since it first queued and resuming from its interruption, says so and waits in line again as
// that run, on its launch's options, ahead of a launch that queued after it.
func TestAQueuedRunResumedAfterItsLauncherDiedKeepsItsPlace(t *testing.T) {
	queuedHome(t)
	held(t, "held")
	gone := died(t)
	launched := waiter(t, "acme", time.Hour, gone, "")
	waiter(t, "later", time.Minute, os.Getpid(), "")

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
	if named, _ := os.ReadFile(filepath.Join(dir, "waits-as")); string(named) != dir {
		t.Fatalf("waits as AGENTKIT_RUN_DIR=%q", named)
	}
	record, _ = run.Read(dir)
	at, _ := record.Num("queued_at")
	was, _ := launched.Num("queued_at")
	if record.Str("state") != "queued" || !record.Truthy("slot_waiting") || at != was || record.Str("resume_from") != "interrupted" ||
		!run.Equal(record.Get("launch_opts"), launched.Get("launch_opts")) || pid == gone || pid == os.Getpid() || !run.ProcessActive(record) {
		t.Fatalf("the receipt: %s", run.Line(record))
	}
	if line, _ := queued(); !slices.Equal(line.queue, []string{"acme", "later"}) {
		t.Fatalf("the line: %v", line.queue)
	}
}

// A waiter the gate holds where no suite's sink marks it, whose wait history.db would count, is
// Python's, as in any real home: its resume hands it over before anything is written, its
// repository getting no origin/HEAD from the launch's preflight, which passes as it stands.
func TestAResumeTheGateLeavesToPythonWritesNothing(t *testing.T) {
	home := queuedHome(t)
	repo, origin := filepath.Join(home, "acme"), filepath.Join(home, "origin.git")
	write(t, filepath.Join(repo, "AGENTS.md"), "---\nusers: none\ntests: none\nhealth: none\n---\n")
	for _, args := range [][]string{{"init", "--bare", "--initial-branch=main", origin}, {"init", "--initial-branch=main", repo},
		{"-C", repo, "add", "AGENTS.md"}, {"-C", repo, "-c", "user.name=Acme", "-c", "user.email=acme@example.invalid", "commit", "-m", "Initial"},
		{"-C", repo, "remote", "add", "origin", origin}, {"-C", repo, "push", "--quiet", "origin", "main"}} {
		if said, err := exec.Command("git", args...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v %s", args, err, said)
		}
	}
	held(t, "held")
	t.Setenv("AK_NOTIFY_SINK", "")
	receipt := waiter(t, "acme", time.Hour, died(t), repo)
	before := files(t, home)
	if _, _, err := Resume("acme", 0, true, io.Discard, io.Discard); !errors.Is(err, ErrPython) {
		t.Fatalf("not handed over: %v", err)
	}
	untouched(t, home, before)
	t.Setenv("AK_NOTIFY_SINK", "dry-run")
	if !launchStands(filepath.Join(run.Runs(), "acme"), receipt) {
		t.Fatal("its launch would not start as it stands")
	}
}

// queuedHome is a gated home whose runs Go can drive: a box, models with adapters, no seat, and no
// user manager, so a driver starts plainly.
func queuedHome(t *testing.T) string {
	if err := box.Check(); err != nil {
		t.Skip(err) // Python's refusal, before the run's
	}
	home, adapters := gatedHome(t, "dry-run"), t.TempDir()
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
	return home
}

// waiter is a launch's receipt waiting in line for its slot since ago, under that pid, in repo (""
// for a scratch run), its --no-merge task's check passing.
func waiter(t *testing.T, id string, ago time.Duration, pid int, repo string) *run.Object {
	dir := filepath.Join(run.Runs(), id)
	write(t, filepath.Join(dir, "task.md"), "---\nrepo: "+cmp.Or(repo, "none")+"\n---\n# Fix the API\n\n## Done when\n```bash\ntrue\n```\n")
	write(t, filepath.Join(dir, "log.txt"), "")
	at := float64(time.Now().Add(-ago).UnixNano()) / 1e9
	var where any
	if repo != "" {
		where = repo
	}
	receipt := run.SetAll(run.Capture(dir, "", nil, map[string]bool{"--bg": true, "--no-merge": true}, config.Binding{}, ""),
		"state", "queued", "slot_waiting", true, "queued_at", at, "started_at", at, "pid", pid,
		"repo", where, "scratch", repo == "", "no_merge", true, "scope", "none", "slot_waited", true,
		"slot_wait_reason", "waiting for a slot · limit full (1 running) · 0 ahead", "slot_wait_kind", "count")
	receipt.Delete("slot_started_at")
	receipt.Delete("reservation_pending")
	if err := run.Create(dir, receipt); err != nil {
		t.Fatal(err)
	}
	return receipt
}

// died is the pid of a process that has ended.
func died(t *testing.T) int {
	gone := exec.Command("true")
	if err := gone.Run(); err != nil {
		t.Fatal(err)
	}
	return gone.Process.Pid
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
