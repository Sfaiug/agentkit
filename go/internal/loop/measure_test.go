//go:build linux

package loop

import (
	"context"
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/helper"
)

// A pass of four pieces, this process alone in its cgroup, keeps as the suite's cost per piece the
// most that cgroup held, swap included and less the file cache reclaim frees, over what it held as
// the pass began, divided by the four places; the same run's slower wall time stays, and each place's
// CPUs, every piece's read, are a heavy suite's first estimate at least.  A second pass with half its
// pieces on the suite helper divides what it held only by the two places that ran here.
func TestASuitePassKeepsItsPeakPerPiece(t *testing.T) {
	l := rig(t, time.Minute)
	t.Setenv("AK_HOST_READINGS", `{"cpus":64,"free_mb":2000,"mem_total_mb":65536}`)
	every := sampleEvery
	sampleEvery = 10 * time.Millisecond
	t.Cleanup(func() { sampleEvery = every })
	const mib = 1 << 20
	cgroup := filepath.Join(l.workspace, "cgroup", "acme")
	membership := filepath.Join(t.TempDir(), "membership")
	// 1000 MiB charged, 200 of it file cache: 800 held as the pass begins.  The first piece's cache,
	// then charge, then swap rise for a second and fall back, each file replaced whole, so no sample
	// reads more than it held at its peak.
	stat := "active_file %d\ninactive_file %d"
	suite := fmt.Sprintf(`put() { printf "$2\n" >cgroup/acme/new && mv cgroup/acme/new cgroup/acme/$1; }
case $AK_SHARD in 1/*)
  put memory.stat "`+stat+`"; put memory.current %d; put memory.swap.current %d
  sleep 1
  put memory.current %d; put memory.swap.current 0; put memory.stat "`+stat+`" ;;
esac # AK_SHARD`, 450*mib, 150*mib, 3000*mib, 400*mib, 1000*mib, 150*mib, 50*mib)
	cost := filepath.Join(config.Home(), "state", fmt.Sprintf("suite-%x.json", sha256.Sum256([]byte(config.Resolve(l.workspace)+"\n"+suite))))
	for file, text := range map[string]string{
		filepath.Join(cgroup, "cgroup.procs"):        strconv.Itoa(os.Getpid()) + "\n",
		filepath.Join(cgroup, "memory.current"):      strconv.Itoa(1000*mib) + "\n",
		filepath.Join(cgroup, "memory.stat"):         fmt.Sprintf(stat+"\n", 150*mib, 50*mib),
		filepath.Join(cgroup, "memory.swap.current"): "0\n",
		membership: "0::/acme\n",
		cost:       `{"wall_seconds": 300.5, "run_id": "acme", "quiet": [12]}`,
	} {
		if err := os.MkdirAll(filepath.Dir(file), 0o777); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(file, []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("AK_CGROUP_ROOT", filepath.Dir(cgroup))
	t.Setenv("AK_CGROUP_FILE", membership)
	if ok, text := l.checked(t, suite); !ok {
		t.Fatalf("the suite failed: %s", text)
	}
	// (3000 - 600 + 400 - 800) / 4
	if kept, _ := os.ReadFile(cost); string(kept) != `{"wall_seconds": 300.5, "run_id": "acme", "quiet": [12], "cpus": 0.7, "mem_mb": 500.0}` {
		t.Fatalf("the pass left the cost %s", kept)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	m := l.measuring(ctx)
	if err := os.WriteFile(filepath.Join(cgroup, "memory.current"), []byte(strconv.Itoa(2600*mib)), 0o666); err != nil {
		t.Fatal(err)
	}
	for deadline := time.Now().Add(time.Minute); ; time.Sleep(sampleEvery) {
		m.held.Lock()
		peak := m.peak
		m.held.Unlock()
		if peak > m.baseline || time.Now().After(deadline) {
			break
		}
	}
	spent, away := 0.0, &helper.Away{Alias: "acme-mac"}
	all := []*piece{{ended: ran{cpu: &spent}}, {there: away}, {ended: ran{cpu: &spent}}, {there: away}}
	if err := m.kept(ctx, cost, all, &placement{}); err != nil {
		t.Fatal(err)
	}
	// (2600 - 200 - 800) / 2
	if kept, _ := os.ReadFile(cost); string(kept) != `{"wall_seconds": 300.5, "run_id": "acme", "quiet": [12], "cpus": 0.7, "mem_mb": 800.0}` {
		t.Fatalf("the pass half on the suite helper left the cost %s", kept)
	}
}
