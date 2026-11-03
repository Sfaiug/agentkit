//go:build unix

package tick

import (
	"bytes"
	"io"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// checkoutHome is an idle home whose gh names nobody, holding ~/code/api, a clone of an origin
// whose AGENTS.md is agents.
func checkoutHome(t *testing.T, agents string) (ak, api string) {
	t.Helper()
	ak, _ = idleHome(t, `echo "gh: not logged in" >&2; exit 1`)
	origin, api := filepath.Join(t.TempDir(), "origin"), filepath.Join(filepath.Dir(ak), "code", "api")
	put(t, filepath.Join(origin, "AGENTS.md"), agents)
	for _, args := range [][]string{
		{"init", "-q", "-b", "main", origin},
		{"-C", origin, "add", "-A"},
		{"-C", origin, "-c", "user.name=acme", "-c", "user.email=acme@example.com", "commit", "-q", "-m", "init"},
		{"clone", "-q", origin, api},
	} {
		if out, err := exec.Command("git", args...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %s", args, out)
		}
	}
	return ak, api
}

// Logged out, a home with a checkout is carried: fetched, its rows stamped, its gc run.
func TestACheckoutIsTended(t *testing.T) {
	ak, api := checkoutHome(t, "# acme\n")
	var out bytes.Buffer
	if !Carry(&out, io.Discard) {
		t.Fatalf("left it to Python, printing %q", out.String())
	}
	if !strings.Contains(out.String(), "git gc: "+api) {
		t.Errorf("printed %q", out.String())
	}
	if retire := read(t, filepath.Join(ak, "state", "retire.json")); !strings.HasPrefix(retire, "{\n  \"asked\": ") {
		t.Errorf("retire.json holds %s", retire)
	}
	if nightly := read(t, filepath.Join(ak, "state", "nightly.json")); !strings.HasPrefix(nightly, `{"asked": {"`+api+`": `) {
		t.Errorf("nightly.json holds %s", nightly)
	}
	if settings := read(t, filepath.Join(api, ".git", "config")); !strings.Contains(settings, "auto = 0") {
		t.Errorf("gc.auto is not off: %s", settings)
	}
}

// A checkout naming its switches or a night read is Python's, and nothing is written.
func TestADeclaredReadIsPythons(t *testing.T) {
	for _, key := range []string{"features", "nightly"} {
		t.Run(key, func(t *testing.T) {
			ak, _ := checkoutHome(t, "---\n"+key+": tools/"+key+"\n---\n# acme\n")
			before := files(t, filepath.Dir(ak))
			if Carry(io.Discard, io.Discard) {
				t.Fatal("carried it")
			}
			if after := files(t, filepath.Dir(ak)); !reflect.DeepEqual(before, after) {
				t.Error("wrote what it left to Python")
			}
		})
	}
}
