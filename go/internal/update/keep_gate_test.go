package update

import (
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"agentkit/internal/config"
)

func TestATickWithNoLiveGateAsksItsHarnessesTheirLatestRelease(t *testing.T) {
	home, _ := harnessHome(t)
	checkout := filepath.Join(home, "agentkit") // ~/agentkit's own tick, with no live gate
	// somebody's work: the upgrade the ask finds behind is held, not started
	if out, err := exec.Command("git", "init", "-q", "-b", "fix-api", checkout).CombinedOutput(); err != nil {
		t.Fatalf("git init: %v: %s", err, out)
	}
	var said []string
	err := KeepCurrent(config.Resolve(checkout), func(line string) { said = append(said, line) })
	record, _ := os.ReadFile(filepath.Join(home, ".agentkit", "state", "harness-latest.json"))
	want := []string{"gamma 1.0.0 is behind 2.0.0: upgraded once " + checkout +
		" is main as origin left it, not on fix-api, not main: its gates test it"}
	if got := calls(t, home); err != nil || strings.Join(got, " ") != "--version latest" ||
		!strings.HasPrefix(string(record), `{"gamma": {"asked": `) || !reflect.DeepEqual(said, want) {
		t.Fatalf("gave %v, calls %q, recorded %s, said %q", err, got, record, said)
	}
}
