package host

import (
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"agentkit/internal/tmux"
)

// A manager listens; systemd-run is scripted, logging its words; this process sits in the
// manager's own subtree where inManager.  The work writes its own pid where it says.
func placing(t *testing.T, systemdRun string, inManager bool) (log, ran, called string) {
	t.Setenv("HOME", t.TempDir())
	runtime, bin, dir := t.TempDir(), t.TempDir(), t.TempDir()
	t.Setenv("XDG_RUNTIME_DIR", runtime)
	os.MkdirAll(filepath.Join(runtime, "systemd"), 0o700)
	listener, err := net.Listen("unix", filepath.Join(runtime, "systemd", "private"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { listener.Close() })
	called = filepath.Join(dir, "called")
	for name, script := range map[string]string{"systemd-run": systemdRun, "systemctl": "echo loaded"} {
		os.WriteFile(filepath.Join(bin, name), []byte("#!/bin/sh\necho \"$*\" >>"+called+"\n"+script+"\n"), 0o755)
	}
	t.Setenv("PATH", bin+":"+os.Getenv("PATH"))
	group := "0::/user.slice/acme.scope\n"
	if inManager {
		group = fmt.Sprintf("0::/user.slice/user-%d.slice/user@%d.service/app.slice/acme.scope\n", os.Getuid(), os.Getuid())
	}
	membership := filepath.Join(dir, "cgroup")
	os.WriteFile(membership, []byte(group), 0o644)
	t.Setenv("AK_CGROUP_FILE", membership)
	return filepath.Join(dir, "log.txt"), filepath.Join(dir, "ran"), called
}

func work(ran string) *exec.Cmd { return exec.Command("/bin/sh", "-c", `echo "$$" >"$0"`, ran) }

func ranAs(t *testing.T, ran string) int {
	for deadline := time.Now().Add(10 * time.Second); time.Now().Before(deadline); time.Sleep(10 * time.Millisecond) {
		if data, _ := os.ReadFile(ran); strings.HasSuffix(string(data), "\n") {
			pid, _ := strconv.Atoi(strings.TrimSpace(string(data)))
			return pid
		}
	}
	t.Fatal("the work never ran")
	return 0
}

func TestWorkGoesIntoItsUnitOrStartsPlainlyWhereTheManagerRefuses(t *testing.T) {
	for name, each := range map[string]struct {
		systemdRun          string
		inManager, detached bool
		scope, reason, warn string
	}{
		"a scope the manager makes": {`while [ "$1" != -- ]; do shift; done; shift; exec "$@"`, true, true, "agentkit-run-fix-api", "", ""},
		"a scope it refuses":        {"exit 1", true, true, "none", "systemd-run failed (nothing started in it)", "nothing started in it"},
		"a service it refuses":      {"exit 1", false, true, "none", "systemd-run failed (systemd-run exited 1)", "systemd-run exited 1"},
		"a foreground run outside":  {"exit 1", false, false, "none", "started outside the user manager, which cannot move it", ""},
	} {
		t.Run(name, func(t *testing.T) {
			log, ran, called := placing(t, each.systemdRun, each.inManager)
			pid, scope, reason, err := Place(work(ran), log, "agentkit-run-fix-api", []string{"-p", "MemoryMax=400M"}, each.detached)
			if err != nil || scope != each.scope || reason != each.reason || pid != ranAs(t, ran) {
				t.Fatalf("pid %d, %q %q %v", pid, scope, reason, err)
			}
			said, _ := os.ReadFile(log)
			if warn := "WARN agentkit-run-fix-api did not go into " + tmux.Own() + "-runs.slice (" + each.warn + "); started plainly"; strings.Contains(string(said), warn) != (each.warn != "") {
				t.Errorf("log %q", said)
			}
			words, _ := os.ReadFile(called)
			if placed := strings.Contains(string(words), "--unit=agentkit-run-fix-api") && strings.Contains(string(words), "MemoryMax=400M"); placed != (name != "a foreground run outside") {
				t.Errorf("systemd-run %q", words)
			}
			if _, err := os.Stat(filepath.Join(os.Getenv("HOME"), ".agentkit", "tmp", "agentkit-run-fix-api.placed")); err == nil {
				t.Error("the claim outlived its start")
			}
		})
	}
}

func TestAnEarlierStartsUnitStillLoadedStartsNothing(t *testing.T) {
	log, ran, _ := placing(t, "exit 1", true)
	claim := filepath.Join(os.Getenv("HOME"), ".agentkit", "tmp", "agentkit-run-fix-api.placed")
	os.MkdirAll(filepath.Dir(claim), 0o700)
	os.WriteFile(claim, []byte("agentkit-run-fix-api.scope"), 0o644)
	if _, _, _, err := Place(work(ran), log, "agentkit-run-fix-api", nil, true); err == nil || !strings.Contains(err.Error(), "from an earlier start is still in") {
		t.Fatalf("err %v", err)
	}
	if _, err := os.Stat(ran); err == nil {
		t.Error("the work started beside its earlier unit")
	}
}
