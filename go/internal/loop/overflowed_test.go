//go:build linux

package loop

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/lock"
)

// overflowing is a loop whose process cgroup is a fake one that ran out of memory 0 times yet, on a
// host whose free memory fits 4 pieces of 500 MB, and the path of suite's cost, which holds cost.
func overflowing(t *testing.T, suite, cost string) (*loop, string) {
	t.Helper()
	l := rig(t, time.Minute)
	t.Setenv("AK_HOST_READINGS", `{"cpus":64,"free_mb":2000,"mem_total_mb":65536}`)
	cgroup := filepath.Join(l.workspace, "cgroup")
	membership := filepath.Join(t.TempDir(), "membership")
	path := filepath.Join(config.Home(), "state", fmt.Sprintf("suite-%x.json", sha256.Sum256([]byte(config.Resolve(l.workspace)+"\n"+suite))))
	for file, text := range map[string]string{
		filepath.Join(cgroup, "acme", "memory.events"): "oom 0\noom_kill 0\n",
		membership: "0::/acme\n",
		path:       cost,
	} {
		if err := os.MkdirAll(filepath.Dir(file), 0o777); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(file, []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("AK_CGROUP_ROOT", cgroup)
	t.Setenv("AK_CGROUP_FILE", membership)
	return l, path
}

// A suite's pass in pieces during which its cgroup ran out of memory, its first piece red, prices
// the suite at twice the memory per piece it was planned at, its other fields kept, and its next pass
// is cut into at most half as many pieces; that pass, which did not run out, leaves the cost as it was.
func TestAnOverflowedPassCostsTwiceItsPlan(t *testing.T) {
	// the kernel reclaimed, killing nothing: only `oom` counts the overflow
	suite := `echo "$AK_SHARD" >>shards
case $AK_SHARD in 1/*) printf "oom 1\noom_kill 0\n" >cgroup/acme/memory.events; exit 1 ;; esac # AK_SHARD`
	l, cost := overflowing(t, suite, `{"wall_seconds": 300.5, "run_id": "acme", "mem_mb": 500, "quiet": [12]}`)
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

// A driver stopped once its suite ran out of memory prices the overflow where the state lock is
// free, and waits for none another process holds: its error is the stop's.
func TestAStoppedDriverPricesItsOverflowButWaitsForNoLock(t *testing.T) {
	suite := `case $AK_SHARD in 1/*)
  n=$(sed -n "s/^oom //p" cgroup/acme/memory.events); printf "oom %s\noom_kill 0\n" $((n + 1)) >cgroup/acme/memory.events
  touch overflowed ;;
esac
sleep 30 # AK_SHARD`
	l, cost := overflowing(t, suite, `{"mem_mb": 500}`)
	// a pass stopped once its first piece ran out of memory, its siblings still running, and the cost
	// it left
	stopped := func() string {
		t.Helper()
		os.Remove(filepath.Join(l.workspace, "overflowed"))
		ctx, cancel := context.WithCancelCause(context.Background())
		defer cancel(nil)
		l.ctx = ctx
		stop := errors.New("the driver got SIGTERM")
		go func() {
			for ctx.Err() == nil {
				if _, err := os.Stat(filepath.Join(l.workspace, "overflowed")); err == nil {
					cancel(stop)
				}
				time.Sleep(10 * time.Millisecond)
			}
		}()
		if _, _, err := l.checks([]string{suite}, filepath.Join(l.roundDir(), "donewhen.log")); !errors.Is(err, stop) {
			t.Fatalf("the suite ended with %v", err)
		}
		kept, _ := os.ReadFile(cost)
		return string(kept)
	}
	if kept := stopped(); kept != `{"mem_mb": 1000}` {
		t.Fatalf("the stopped pass left the cost %s", kept)
	}
	held, err := lock.Try(filepath.Join(config.Home(), "state", "watch.lock"))
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	if kept := stopped(); kept != `{"mem_mb": 1000}` {
		t.Fatalf("pricing without the state lock left the cost %s", kept)
	}
}
