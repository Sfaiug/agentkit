package host

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// An `ak` started in a seat's side session marks itself no seat's in /proc too, where a leftover
// sweep reads it: the tag's value is blank in its start environment, every other variable stays,
// and so does Go's own copy of them. The test binary, run again with the tag, is that `ak`.
func TestAMarkedProcessShowsNoTag(t *testing.T) {
	if shown := os.Getenv("AK_TEST_UNTAG"); shown != "" {
		Mark("ak watch")
		environ, err := os.ReadFile("/proc/self/environ")
		if err != nil || os.Getenv("AK_TMUX_OWNER") != "" || os.Getenv("AK_TEST_KEPT") != "kept" {
			t.Fatalf("read %v; Go's copy holds the tag %q, AK_TEST_KEPT %q", err, os.Getenv("AK_TMUX_OWNER"), os.Getenv("AK_TEST_KEPT"))
		}
		os.WriteFile(shown, environ, 0o644)
		return
	}
	shown := filepath.Join(t.TempDir(), "environ")
	child := exec.Command(os.Args[0], "-test.run=^TestAMarkedProcessShowsNoTag$")
	child.Env = append(os.Environ(), "AK_TMUX_OWNER=acme", "AK_TEST_KEPT=kept", "AK_TEST_UNTAG="+shown)
	if out, err := child.CombinedOutput(); err != nil {
		t.Fatalf("%v: %s", err, out)
	}
	environ, err := os.ReadFile(shown)
	if err != nil {
		t.Fatal(err)
	}
	env := map[string]string{}
	for _, pair := range strings.Split(string(environ), "\x00") {
		if name, value, ok := strings.Cut(pair, "="); ok {
			env[name] = value
		}
	}
	if tag, ok := env["AK_TMUX_OWNER"]; !ok || tag != "" || env["AK_TEST_KEPT"] != "kept" {
		t.Errorf("/proc shows the tag %q (%v), AK_TEST_KEPT %q", tag, ok, env["AK_TEST_KEPT"])
	}
}
