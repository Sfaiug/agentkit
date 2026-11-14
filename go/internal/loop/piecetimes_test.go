//go:build linux

package loop

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/suitetimes"
)

// Each piece here is handed the record of the tests' seconds in the file AK_TIMES names, as one
// there is, so the pieces of one suite cut the same shares wherever each runs.
func TestEachPieceHereIsHandedTheTimes(t *testing.T) {
	l := rig(t, time.Minute)
	t.Setenv("AK_HOST_READINGS", `{"cpus":8,"free_mb":16400,"mem_total_mb":65536}`)
	if err := os.WriteFile(filepath.Join(l.workspace, "t.sh"), nil, 0o666); err != nil {
		t.Fatal(err)
	}
	suitetimes.Keep(l.workspace, map[string]float64{"t.sh": 1.5})
	times := suitetimes.Handed(l.workspace)
	if ok, text := l.checked(t, `cat "$AK_TIMES" >"times-${AK_SHARD%/*}" # AK_SHARD`); !ok || times == "" {
		t.Fatalf("ok=%v, times %q:\n%s", ok, times, text)
	}
	handed, _ := filepath.Glob(filepath.Join(l.workspace, "times-*"))
	for _, each := range handed {
		if got, err := os.ReadFile(each); err != nil || string(got) != times {
			t.Errorf("%s was handed %q (%v), want %q", filepath.Base(each), got, err, times)
		}
	}
	if len(handed) < 2 {
		t.Fatalf("ran in %d pieces", len(handed))
	}
}
