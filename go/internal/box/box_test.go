//go:build linux

package box

import (
	"context"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"agentkit/internal/host"
)

// TestMain is the box's first process where Run starts this test program as one.
func TestMain(m *testing.M) {
	if code, first := First(); first {
		os.Exit(code)
	}
	os.Exit(m.Run())
}

func TestACommandStillRunningAfterItsGraceIsNamedAmongWhatTheBoxStopped(t *testing.T) {
	if err := Check(); err != nil {
		t.Skip(err)
	}
	dir := t.TempDir()
	written := filepath.Join(dir, "pid")
	ctx, stop := context.WithCancel(context.Background())
	defer stop()
	go func() {
		for ctx.Err() == nil {
			if _, err := os.Stat(written); err == nil {
				stop()
			}
			time.Sleep(10 * time.Millisecond)
		}
	}()
	argv := []string{"/bin/sh", "-c", `trap '' TERM; echo $$ >"$0"; exec sleep 60`, written}
	code, left, err := Run(ctx, argv, map[string]string{"PATH": os.Getenv("PATH"), "HOME": dir}, dir, dir, nil, nil, nil, os.Stderr)
	if err != nil {
		t.Fatal(err)
	}
	said, err := os.ReadFile(written)
	if err != nil {
		t.Fatal(err)
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(said)))
	if err != nil {
		t.Fatal(err)
	}
	if code != -int(syscall.SIGKILL) || left[pid] != "sleep 60" {
		t.Fatalf("the box ended %d and named %q, not process %d", code, left, pid)
	}
}

func TestTheRunCopyLeavesOutWhatIsHiddenByItsPathAndByTheInodeItHasAsTheCopyStarts(t *testing.T) {
	source, copied := t.TempDir(), t.TempDir()
	for _, name := range []string{"hosts.yml", "motd", "renamed"} {
		if err := os.WriteFile(filepath.Join(source, name), []byte("fixture-"+name), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	// the credential replaced by rename once its mask was made, its new file linked from elsewhere
	if err := os.Link(filepath.Join(source, "renamed"), filepath.Join(source, "linked")); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(filepath.Join(source, "renamed"), filepath.Join(source, "hosts.yml")); err != nil {
		t.Fatal(err)
	}
	if err := copyRun(source, copied, "", []string{filepath.Join(source, "hosts.yml")}); err != nil {
		t.Fatal(err)
	}
	var names []string
	entries, _ := os.ReadDir(copied)
	for _, entry := range entries {
		names = append(names, entry.Name())
	}
	if !slices.Equal(names, []string{"motd"}) {
		t.Fatalf("the copy holds %q", names)
	}
}

func TestACheckRunsToItsOutputsEndWithAThrowawayHome(t *testing.T) {
	if err := Check(); err != nil {
		t.Skip(err)
	}
	home, out, workspace := t.TempDir(), t.TempDir(), t.TempDir()
	output, err := os.Create(filepath.Join(out, "output"))
	if err != nil {
		t.Fatal(err)
	}
	defer output.Close()
	env := map[string]string{"HOME": home, "PATH": os.Getenv("PATH")}
	code, _, err := RunCheck(context.Background(), host.Watch{}, []string{"bash", "-c", "touch ~/leak && (sleep 1; echo late) & echo early; exit 7"}, env, workspace, out, output)
	if err != nil || code != 7 {
		t.Fatalf("exit %d, %v", code, err)
	}
	said, _ := os.ReadFile(output.Name())
	if string(said) != "early\nlate\n" {
		t.Fatalf("said %q", said)
	}
	if _, err := os.Stat(filepath.Join(home, "leak")); err == nil {
		t.Fatal("a check wrote its home")
	}
	report, _ := os.ReadFile(filepath.Join(out, "box-processes.json"))
	if !strings.HasPrefix(string(report), `{"returncode":7,"processes":[],"cpu_seconds":`) {
		t.Fatalf("report %s", report)
	}
	code, _, err = RunCheck(context.Background(), host.Watch{}, []string{"no-such-program"}, env, workspace, out, output)
	if err != nil || code != 127 {
		t.Fatalf("a command that cannot start: exit %d, %v", code, err)
	}
}
