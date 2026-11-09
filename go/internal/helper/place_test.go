package helper

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"
)

// Of an 8-CPU and a 2-CPU machine that take turns and a 16-CPU one that takes only tests, a turn
// packs onto the 2-CPU one, holding its 2 CPUs there, and goes on to the 8-CPU one where the 2-CPU
// one takes no turns or lacks history; a suite still goes to the most room.
func TestATurnGoesToTheLeastRoomThatTakesIt(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the machines are a shell script standing in for ssh")
	}
	root := t.TempDir()
	home, bin, repo := filepath.Join(root, "home"), filepath.Join(root, "bin"), filepath.Join(root, "repo")
	// each verb's words go to `said`; a probe reads <alias>.probe, `prepare` exits <alias>.prepare
	// and keeps its parcel
	for path, content := range map[string]string{
		filepath.Join(home, ".agentkit", "config.toml"): "[machines.mid]\nwork = ['turns', 'tests']\n" +
			"[machines.small]\nwork = ['turns', 'tests']\n[machines.wide]\nwork = ['tests']\n",
		filepath.Join(bin, "ssh"): "#!/bin/sh\ndir=${0%/*} alias=$7\neval \"set -- $8\"\nverb=$5\nshift 5\n" +
			"echo \"$alias $verb $*\" >>\"$dir/said\"\ncase $verb in\nprobe) cat \"$dir/$alias.probe\" ;;\n" +
			"prepare) cat >\"$dir/$alias.parcel\"; read code <\"$dir/$alias.prepare\"; exit \"${code:-0}\" ;;\nesac\n",
		filepath.Join(bin, "wide.probe"): "cpus 16\nload 0\nroom_mb 65536\nturns 1\n",
		filepath.Join(bin, "mid.probe"):  "cpus 8\nload 0\nroom_mb 65536\nturns 1\n",
		filepath.Join(repo, recipe):      "FROM scratch\n",
	} {
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(content), 0o755); err != nil {
			t.Fatal(err)
		}
	}
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
	turn := map[string]file{"harness": made(0o644, []byte("gamma/1.4.2/gamma-cli"))}
	for _, each := range []struct {
		name, small, lacks string
		turn               map[string]file
		cpus               float64
		want               string
		holds              []string
	}{
		{name: "a turn", small: "turns 1", turn: turn, cpus: 2, want: "small", holds: []string{"2"}},
		{name: "a turn where small takes none", small: "turns 0", turn: turn, cpus: 2, want: "mid", holds: []string{"2"}},
		{name: "a turn where small lacks history", small: "turns 1", lacks: "3", turn: turn, cpus: 2, want: "mid", holds: []string{"2"}},
		{name: "a suite", small: "turns 1", cpus: 1, want: "wide"},
	} {
		for name, content := range map[string]string{"said": "", "small.probe": "cpus 2\nload 0\nroom_mb 65536\n" + each.small + "\n",
			"small.prepare": each.lacks + "\n"} {
			if err := os.WriteFile(filepath.Join(bin, name), []byte(content), 0o644); err != nil {
				t.Fatal(err)
			}
		}
		away, why, err := Start(repo, each.cpus, 2048, "make test", "", "", each.turn, func(string) {})
		said, _ := os.ReadFile(filepath.Join(bin, "said"))
		if err != nil || away == nil || away.Alias != each.want {
			t.Fatalf("%s: not placed on %s (%q, %v); the machines were asked\n%s", each.name, each.want, why, err, said)
		}
		var prepared []string
		for _, line := range strings.Split(string(said), "\n") {
			if words := strings.Fields(line); len(words) > 1 && words[1] == "prepare" && words[0] == each.want {
				prepared = words[5:]
			}
			if each.turn != nil && strings.HasPrefix(line, "wide ") {
				t.Errorf("%s: asked wide, which takes only tests: %s", each.name, line)
			}
		}
		if !slices.Equal(prepared, each.holds) {
			t.Errorf("%s: %s's prepare holds %q, not %q; the machines were asked\n%s", each.name, each.want, prepared, each.holds, said)
		}
		parcel, _ := os.ReadFile(filepath.Join(bin, each.want+".parcel"))
		if held := bytes.Contains(parcel, []byte("gamma/1.4.2/gamma-cli")); held != (each.turn != nil) {
			t.Errorf("%s: the parcel on %s holds the turn's files: %v", each.name, each.want, held)
		}
	}
}
