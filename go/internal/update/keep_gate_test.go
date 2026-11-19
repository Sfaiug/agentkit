package update

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"agentkit/internal/config"
)

func TestATickWithNoLiveGateAsksItsHarnessesTheirLatestRelease(t *testing.T) {
	asked := int64(now()) - 60
	// today's homes may hold a release a login held in an entry's `waits`, which nothing reads, so
	// the record written drops it, from an entry not asked too
	beta := `"beta": {"asked": 1, "found": "1.1.0", "waits": "1.1.0"}`
	for _, each := range []struct {
		name, record, calls string
		behind              bool
	}{
		// the first ask records 2.0.0 and neither starts nor holds it
		{"first", "{" + beta + "}", "--version latest", false},
		// the ask before found 2.0.0, so this one finds it behind
		{"found", `{"gamma": {"found": "2.0.0"}, ` + beta + "}", "--version latest", true},
		// a login held 2.0.0, which the ask before found: this one finds it behind
		{"both", fmt.Sprintf(`{"gamma": {"asked": %d, "found": "2.0.0", "waits": "2.0.0"}, %s}`,
			asked-askEvery, beta), "--version latest", true},
		// a login held 2.0.0 before `found` was recorded: this ask finds it a first time
		{"waits", fmt.Sprintf(`{"gamma": {"asked": %d, "waits": "2.0.0"}, %s}`, asked-askEvery, beta),
			"--version latest", false},
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
			var said, want []string
			if each.behind {
				want = []string{"gamma 1.0.0 is behind 2.0.0: upgraded once " + checkout +
					" is main as origin left it, not on fix-api, not main: its gates test it"}
			}
			err := KeepCurrent(config.Resolve(checkout), func(line string) { said = append(said, line) }, nil)
			record, _ := os.ReadFile(path)
			var written map[string]map[string]any
			err = errors.Join(err, json.Unmarshal(record, &written))
			at, _ := written["gamma"]["asked"].(float64)
			if got := calls(t, home); err != nil || strings.Join(got, " ") != each.calls ||
				at <= float64(asked) || !reflect.DeepEqual(written, map[string]map[string]any{
				"gamma": {"asked": at, "found": "2.0.0"}, "beta": {"asked": 1.0, "found": "1.1.0"},
			}) || !reflect.DeepEqual(said, want) {
				t.Fatalf("gave %v, calls %q, recorded %s, said %q", err, got, record, said)
			}
		})
	}
}

// Today's homes may keep a release a login held as the entry's `waits`, which no tick reads: the
// entry is asked once its hour is up, as one without it is, and no sooner.
func TestAReleaseALoginHeldIsAskedOnlyOnceItsHourIsUp(t *testing.T) {
	home, _ := harnessHome(t)
	checkout := filepath.Join(home, "agentkit") // ~/agentkit's own tick
	if err := os.Mkdir(checkout, 0o700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(home, ".agentkit", "state", "harness-latest.json")
	asked := int64(now()) - 60
	record := fmt.Sprintf(`{"gamma": {"asked": %d, "found": "2.0.0", "waits": "2.0.0"}}`, asked)
	if err := os.WriteFile(path, []byte(record), 0o600); err != nil {
		t.Fatal(err)
	}
	err := KeepCurrent(config.Resolve(checkout), func(line string) { t.Errorf("said %q", line) }, nil)
	written, _ := os.ReadFile(path)
	if got := calls(t, home); err != nil || len(got) != 0 || string(written) != record {
		t.Fatalf("gave %v, calls %q, recorded %s", err, got, written)
	}
}
