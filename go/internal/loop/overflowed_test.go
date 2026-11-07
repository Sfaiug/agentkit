//go:build linux

package loop

import (
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/config"
)

// A suite's pass in pieces during which its cgroup ran out of memory, its first piece red, prices
// the suite at twice the memory per piece it was planned at, its other fields kept, and its next pass
// is cut into at most half as many pieces; that pass, which did not run out, leaves the cost as it was.
func TestAnOverflowedPassCostsTwiceItsPlan(t *testing.T) {
	l := rig(t, time.Minute)
	t.Setenv("AK_HOST_READINGS", `{"cpus":64,"free_mb":2000,"mem_total_mb":65536}`) // 4 pieces of 500 MB
	cgroup := filepath.Join(l.workspace, "cgroup")
	membership := filepath.Join(t.TempDir(), "membership")
	if err := os.MkdirAll(filepath.Join(cgroup, "acme"), 0o777); err != nil {
		t.Fatal(err)
	}
	// the kernel reclaimed, killing nothing: only `oom` counts the overflow
	suite := `echo "$AK_SHARD" >>shards
case $AK_SHARD in 1/*) printf "oom 1\noom_kill 0\n" >cgroup/acme/memory.events; exit 1 ;; esac # AK_SHARD`
	cost := filepath.Join(config.Home(), "state", fmt.Sprintf("suite-%x.json", sha256.Sum256([]byte(config.Resolve(l.workspace)+"\n"+suite))))
	for path, text := range map[string]string{
		filepath.Join(cgroup, "acme", "memory.events"): "oom 0\noom_kill 0\n",
		membership: "0::/acme\n",
		cost:       `{"wall_seconds": 300.5, "run_id": "acme", "mem_mb": 500, "quiet": [12]}`,
	} {
		if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("AK_CGROUP_ROOT", cgroup)
	t.Setenv("AK_CGROUP_FILE", membership)
	pass := func() (pieces string, kept string) {
		t.Helper()
		os.Remove(filepath.Join(l.workspace, "shards"))
		if ok, text := l.checked(t, suite); ok {
			t.Fatalf("the first piece was red, yet the suite passed: %s", text)
		}
		shards, _ := os.ReadFile(filepath.Join(l.workspace, "shards"))
		_, pieces, _ = strings.Cut(strings.SplitN(string(shards), "\n", 2)[0], "/")
		written, _ := os.ReadFile(cost)
		return pieces, string(written)
	}
	if pieces, kept := pass(); pieces != "4" || kept != `{"wall_seconds": 300.5, "run_id": "acme", "mem_mb": 1000, "quiet": [12]}` {
		t.Fatalf("the overflowed pass ran in %s pieces and left the cost %s", pieces, kept)
	}
	if pieces, kept := pass(); pieces != "2" || kept != `{"wall_seconds": 300.5, "run_id": "acme", "mem_mb": 1000, "quiet": [12]}` {
		t.Fatalf("the next pass ran in %s pieces and left the cost %s", pieces, kept)
	}
}
