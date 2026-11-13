//go:build linux && (amd64 || arm64)

package update

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"agentkit/internal/config"
)

func liveHome(t *testing.T) (home, checkout string, git func(string, ...string) string) {
	t.Helper()
	home, _ = sandbox(t)
	if err := config.EnsureDirs(); err != nil {
		t.Fatal(err)
	}
	checkout = filepath.Join(home, "agentkit")
	git = func(repo string, args ...string) string {
		t.Helper()
		out, err := exec.Command("git", append([]string{"-C", repo}, args...)...).CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v: %s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	if err := os.Mkdir(checkout, 0o700); err != nil {
		t.Fatal(err)
	}
	git(checkout, "init", "-q", "-b", "main")
	git(checkout, "-c", "user.name=acme", "-c", "user.email=acme@example.com",
		"commit", "-q", "--allow-empty", "-m", "first")
	return
}

func TestGoLiveHandsANewLiveScriptToPythonBeforeMoving(t *testing.T) {
	home, checkout, git := liveHome(t)
	before := git(checkout, "rev-parse", "HEAD")
	origin := t.TempDir()
	git(origin, "clone", "-q", checkout, ".")
	if err := os.Mkdir(filepath.Join(origin, "tests"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(origin, "tests", "live.sh"), []byte("exit 0\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	git(origin, "add", ".")
	git(origin, "-c", "user.name=acme", "-c", "user.email=acme@example.com", "commit", "-qm", "live check")
	git(checkout, "remote", "add", "origin", origin)
	if !LiveReady(checkout) {
		t.Fatal("handed over before the fetch found the live script")
	}
	// a hold said on an earlier tick is Python's to clear as it starts the check
	heard := filepath.Join(home, ".agentkit", "state", "live-check-held")
	if err := os.WriteFile(heard, []byte("tests/live.sh waits: gamma's login lapses at 2026-11-13 12:00, before it could end"), 0o600); err != nil {
		t.Fatal(err)
	}
	var said []string
	if err := GoLive(checkout, func(line string) { said = append(said, line) }); !errors.Is(err, ErrPython) {
		t.Fatalf("live script gave %v", err)
	}
	if git(checkout, "rev-parse", "HEAD") != before || len(said) > 0 || exists(filepath.Join(home, ".agentkit", "state", "agentkit-install-pending")) || !exists(heard) {
		t.Fatal("the handover moved or installed the unchecked commit, or cleared the hold Python clears")
	}
	check := filepath.Join(home, ".agentkit", "state", "live-checks", "acme-1")
	if err := os.MkdirAll(check, 0o700); err != nil {
		t.Fatal(err)
	}
	if LiveReady(checkout) {
		t.Fatal("live checks were not left to Python")
	}
	if err := GoLive(t.TempDir(), func(line string) { t.Errorf("another checkout said %q", line) }); err != nil {
		t.Fatalf("another checkout acted on live checks: %v", err)
	}
}

func TestGoLiveRetriesAnOwedInstallOffline(t *testing.T) {
	home, checkout, git := liveHome(t)
	git(checkout, "remote", "add", "origin", filepath.Join(home, "offline"))
	if err := os.WriteFile(filepath.Join(checkout, "install.sh"), []byte("#!/bin/sh\necho ran >>\"$HOME/install-runs\"\ntest -f \"$HOME/install-ok\"\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	git(checkout, "add", ".")
	git(checkout, "-c", "user.name=acme", "-c", "user.email=acme@example.com", "commit", "-qm", "installer")
	pending := filepath.Join(home, ".agentkit", "state", "agentkit-install-pending")
	if err := os.WriteFile(pending, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	var said []string
	run := func() {
		t.Helper()
		if err := GoLive(checkout, func(line string) { said = append(said, line) }); err != nil {
			t.Fatal(err)
		}
	}
	run()
	if !exists(pending) || len(said) == 0 || !strings.HasPrefix(said[0], "WARN agentkit did not go live at ") {
		t.Fatalf("failed install: pending=%v, said=%q", exists(pending), said)
	}
	if err := os.WriteFile(filepath.Join(home, "install-ok"), nil, 0o600); err != nil {
		t.Fatal(err)
	}
	said = nil
	run()
	want := []string{"agentkit is live at " + short(git(checkout, "rev-parse", "HEAD"))}
	ran, err := os.ReadFile(filepath.Join(home, "install-runs"))
	if err != nil || string(ran) != "ran\nran\n" || exists(pending) || !reflect.DeepEqual(said, want) {
		t.Fatalf("retry: ran=%q, err=%v, pending=%v, said=%q", ran, err, exists(pending), said)
	}
}
