//go:build unix

package tick

import (
	"bytes"
	"io"
	"os"
	"os/exec"
	"path/filepath"
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
	if !carries(&out, io.Discard) {
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

// A checkout naming its switches or a night read ends the tick at that row, before its stamp, what
// the rows before did standing.
func TestADeclaredReadEndsTheTickThere(t *testing.T) {
	for key, row := range map[string]struct {
		stamp string
		swept bool // the git housekeeping row, between the two, ran
	}{"features": {"retire.json", false}, "nightly": {"nightly.json", true}} {
		t.Run(key, func(t *testing.T) {
			ak, api := checkoutHome(t, "---\n"+key+": tools/"+key+"\n---\n# acme\n")
			said := ""
			if row.swept {
				said = "git gc: " + api + "\n"
			}
			endedThere(t, ak, said)
			if _, err := os.Stat(filepath.Join(ak, "state", row.stamp)); err == nil {
				t.Errorf("%s was stamped", row.stamp)
			}
			if swept := strings.Contains(read(t, filepath.Join(api, ".git", "config")), "auto = 0"); swept != row.swept {
				t.Errorf("git housekeeping ran: %v", swept)
			}
		})
	}
}
