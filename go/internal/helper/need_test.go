package helper

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"testing"
	"time"
)

// A suite goes to a rental that serves by its route, and asks the tick for a machine where the
// only one with room ends within a rent and a pass, or none takes it; one lasting asks for none. A
// rental ended, or keeping a route but serving no more though named as the suite helper, is never
// asked, and while ak may not rent nothing is.
func TestASuiteAsksTheTickForAMachineInTime(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the machines are a shell script standing in for ssh")
	}
	root := t.TempDir()
	home, bin, repo := filepath.Join(root, "home"), filepath.Join(root, "bin"), filepath.Join(root, "repo")
	ak := filepath.Join(home, ".agentkit")
	write := func(path, content string) {
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(content), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	// each verb goes to `said` with whether the tick's routes reached it; every machine fits pieces
	write(filepath.Join(bin, "ssh"), "#!/bin/sh\ndir=${0%/*} routed=$7\nwhile [ $# -gt 2 ]; do shift; done\n"+
		"alias=$1\neval \"set -- $2\"\necho \"$alias $5 $routed\" >>\"$dir/said\"\n"+
		"case $5 in\nprobe) echo 'cpus 8'; echo 'load 0'; echo 'room_mb 65536' ;;\nprepare) cat >/dev/null ;;\nesac\n")
	write(filepath.Join(repo, recipe), "FROM scratch\n")
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "GIT_CONFIG_NOSYSTEM": "1",
		"PATH": bin + string(os.PathListSeparator) + os.Getenv("PATH")} {
		t.Setenv(key, value)
	}
	for _, args := range [][]string{{"init", "-q", "-b", "main", repo}, {"-C", repo, "add", "-A"},
		{"-C", repo, "-c", "user.name=Ada", "-c", "user.email=ada@example.com", "commit", "-q", "-m", "first"}} {
		if said, err := exec.Command("git", args...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, said)
		}
	}
	route := func(name string, ends time.Duration) string {
		until := ""
		if ends != 0 {
			until = fmt.Sprintf("  # until %d\n", time.Now().Add(ends).Unix())
		}
		return "Host " + name + "\n" + until + "  HostName \"203.0.113.1\"\n"
	}
	soon, later, ended, gone := route("acme-soon", 5*time.Minute), route("acme-later", time.Hour), route("acme-ended", -time.Minute), route("acme-gone", 0)
	for _, each := range []struct {
		name, active, routes, placed, asked, need string
	}{
		{name: "the only one ending soon", active: "true", routes: soon + gone, placed: "acme-soon",
			asked: "acme-soon probe -F\nacme-soon known -F\nacme-soon prepare -F\n", need: "2276 tests\n"},
		{name: "one with room lasting", active: "true", routes: later + soon + gone, placed: "acme-later",
			asked: "acme-later probe -F\nacme-soon probe -F\nacme-later known -F\nacme-later prepare -F\n"},
		{name: "none serving", active: "true", routes: ended + gone, need: "2276 tests\n"},
		{name: "renting off", active: "false", routes: soon + gone},
	} {
		write(filepath.Join(ak, "config.toml"), "suite_helper = \"acme-gone\"\n[google_cloud]\nactive = "+each.active+"\n")
		write(filepath.Join(ak, "state", "google-cloud-ssh-config"), each.routes+"Host *\n  Include ~/.ssh/config\n")
		write(filepath.Join(bin, "said"), "")
		os.Remove(filepath.Join(ak, "state", "google-cloud-need"))
		away, why, err := Start(repo, 1, 2048, "make test", "", "", nil, func(string) {})
		said, _ := os.ReadFile(filepath.Join(bin, "said"))
		need, _ := os.ReadFile(filepath.Join(ak, "state", "google-cloud-need"))
		placed := ""
		if away != nil {
			placed = away.Alias
		}
		if err != nil || placed != each.placed || placed == "" && why != "no suite helper set up" {
			t.Errorf("%s: placed on %q, not %q (%q, %v)", each.name, placed, each.placed, why, err)
		}
		if string(said) != each.asked {
			t.Errorf("%s: the machines were asked\n%s\nnot\n%s", each.name, said, each.asked)
		}
		if string(need) != each.need {
			t.Errorf("%s: noted a need of %q, not %q", each.name, need, each.need)
		}
	}
}
