package update

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"agentkit/internal/config"
)

func TestATickWithNoLiveGateAsksItsHarnessesTheirLatestRelease(t *testing.T) {
	for _, each := range []struct{ name, record, calls string }{
		// the ask before found 2.0.0, so this one finds it behind
		{"found", `{"gamma": {"found": "2.0.0"}}`, "--version latest"},
		// a login held 2.0.0, which an ask found, before `found` was recorded: no ask until it lasts
		{"waits", `{"gamma": {"waits": "2.0.0"}}`, "--version"},
	} {
		t.Run(each.name, func(t *testing.T) {
			home, _ := harnessHome(t)
			checkout := filepath.Join(home, "agentkit") // ~/agentkit's own tick, with no live gate
			// somebody's work: the upgrade the ask finds behind is held, not started
			if out, err := exec.Command("git", "init", "-q", "-b", "fix-api", checkout).CombinedOutput(); err != nil {
				t.Fatalf("git init: %v: %s", err, out)
			}
			path := filepath.Join(home, ".agentkit", "state", "harness-latest.json")
			if err := os.WriteFile(path, []byte(each.record), 0o600); err != nil {
				t.Fatal(err)
			}
			var said []string
			err := KeepCurrent(config.Resolve(checkout), func(line string) { said = append(said, line) }, nil)
			record, _ := os.ReadFile(path)
			var written map[string]struct{ Asked float64 }
			want := []string{"gamma 1.0.0 is behind 2.0.0: upgraded once " + checkout +
				" is main as origin left it, not on fix-api, not main: its gates test it"}
			if got := calls(t, home); err != nil || strings.Join(got, " ") != each.calls ||
				json.Unmarshal(record, &written) != nil || written["gamma"].Asked == 0 || !reflect.DeepEqual(said, want) {
				t.Fatalf("gave %v, calls %q, recorded %s, said %q", err, got, record, said)
			}
		})
	}
}
