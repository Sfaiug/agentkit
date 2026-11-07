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

// A manager listens; systemd-run, of 258, is scripted, logging its words; this process sits in
// the manager's own subtree where inManager.  The work, in a folder whose name holds a dollar,
// writes its own pid where it says, and where AK_PLACED says, as this program does (Placed).
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
	version := `[ "$1" != --version ] || { echo "systemd 258 (258.1-1)"; exit; }` + "\n"
	for name, script := range map[string]string{"systemd-run": version + systemdRun, "systemctl": "echo loaded"} {
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
	held := filepath.Join(dir, "${HOME}")
	os.Mkdir(held, 0o700)
	return filepath.Join(dir, "log.txt"), filepath.Join(held, "ran"), called
}

func work(ran string) *exec.Cmd {
	script := filepath.Join(filepath.Dir(ran), "work.sh")
	os.WriteFile(script, []byte(`[ -z "$AK_PLACED" ] || printf %s "$$" >"$AK_PLACED"; echo "$$" >"$1"`), 0o644)
	return exec.Command("/bin/sh", script, ran)
}

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
		// from 258 a scope's client expands a dollar in its command unless told not to
		"a scope the manager makes": {`while [ "$1" != -- ]; do [ "$1" != --expand-environment=no ] || literal=yes; shift; done; shift
case "$*" in *'$'*) [ -n "$literal" ] || exit 1;; esac; exec "$@"`,
			true, true, "agentkit-run-fix-api", "", ""},
		// the manager reads `$$` in a service's command as one dollar
		"a service whose client fails once the work ran": {`while [ "$1" != -- ]; do case $1 in --setenv=AK_PLACED=*) export AK_PLACED="${1#*=*=}";; esac; shift; done; shift
for word; do set -- "$@" "$(printf %s "$word" | sed 's/[$][$]/$/g')"; shift; done; "$@"; exit 1`,
			false, true, "agentkit-run-fix-api", "", ""},
		"a scope it refuses":       {"exit 1", true, true, "none", "systemd-run failed (nothing started in it)", "nothing started in it"},
		"a service it refuses":     {"exit 1", false, true, "none", "systemd-run failed (systemd-run exited 1)", "systemd-run exited 1"},
		"a foreground run outside": {"exit 1", false, false, "none", "started outside the user manager, which cannot move it", ""},
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

// The program's word that it started where it was placed reaches no process it starts.
func TestPlacedWorkSaysItStartedAndHandsNothingOn(t *testing.T) {
	marker := filepath.Join(t.TempDir(), "agentkit-run-fix-api.launched")
	t.Setenv(placedEnv, marker)
	Placed()
	if data, _ := os.ReadFile(marker); string(data) != strconv.Itoa(os.Getpid()) {
		t.Errorf("mark %q", data)
	}
	if _, set := os.LookupEnv(placedEnv); set {
		t.Error("what it starts inherits the mark's place")
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

// The manager takes the service, but its client's reply is lost and the manager cannot be asked
// about it: the work may yet come up, so nothing starts plainly and the claim stays for the next
// start, which starts nothing either while the unit is loaded.
func TestAStartNeitherConfirmedNorEndedStartsNothingMore(t *testing.T) {
	log, ran, called := placing(t, "exit 1", false)
	systemctl, _ := exec.LookPath("systemctl")
	os.WriteFile(systemctl, []byte("#!/bin/sh\nexit 1\n"), 0o755)
	if _, _, _, err := Place(work(ran), log, "agentkit-run-fix-api", nil, true); err == nil || !strings.Contains(err.Error(), "is neither running in") {
		t.Fatalf("err %v", err)
	}
	claim := filepath.Join(os.Getenv("HOME"), ".agentkit", "tmp", "agentkit-run-fix-api.placed")
	if data, _ := os.ReadFile(claim); string(data) != "agentkit-run-fix-api.service" {
		t.Fatalf("claim %q", data)
	}
	os.WriteFile(systemctl, []byte("#!/bin/sh\necho loaded\n"), 0o755)
	os.Remove(called)
	if _, _, _, err := Place(work(ran), log, "agentkit-run-fix-api", nil, true); err == nil || !strings.Contains(err.Error(), "from an earlier start is still in") {
		t.Fatalf("err %v", err)
	}
	if words, _ := os.ReadFile(called); len(words) != 0 {
		t.Errorf("placed again beside its earlier unit: %q", words)
	}
	if _, err := os.Stat(ran); err == nil {
		t.Error("the work started beside a unit that may yet come up")
	}
}
