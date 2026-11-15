// Package livefollow is a project's one live follower as the merges handed to it know it: however
// many merges of one project wait to go live, one process follows them all (`ak watch --live`,
// tick's FollowLive), started by the write that first records one of them merged.
package livefollow

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// Merged is what each write recording the run at dir merged calls once it is written, the record
// before it and after, Python's write_state: a write that first records the run merged with a
// `health:` to prove it live hands it to its project's live follower, where it awaits that proof,
// its finish taken as now where it has none (start_live_probe).  Under the live lock, where the
// follower lock is held, the run goes on the list for the follower's next look; otherwise this
// process takes the follower lock and starts `ak watch --live RUN` with that lock on its stdin, so
// it is held from the start.  A start that fails is passed over: the tick still follows the run.
func Merged(dir string, before, after *run.Object) {
	now := time.Now()
	pending := after
	if after.Get("finished_at") == nil {
		pending = after.Copy()
		pending.Set("finished_at", run.Float(float64(now.UnixNano())/1e9))
	}
	if before.Truthy("merged") && proves(before) || !seat.AwaitingLive(pending, now) {
		return
	}
	repo, name := after.Str("repo"), filepath.Base(dir)
	handing, err := lock.Wait(context.Background(), Path(repo, "lock"))
	if err != nil {
		return
	}
	defer handing.Close()
	follower, err := lock.Try(Path(repo, "follower"))
	if errors.Is(err, lock.ErrHeld) {
		Runs(repo, name) // the live follower takes it at its next look
		return
	} else if err != nil {
		return
	}
	defer follower.Close()
	cmd, err := host.Serving("watch", "--live", name)
	if err != nil {
		return
	}
	cmd.Stdin = follower
	host.Place(cmd, filepath.Join(dir, "live.log"), fmt.Sprintf("agentkit-live-%s-%d", name, now.UnixNano()), nil, true)
}

// proves is whether the record holds a `health:` that proves its project live.
func proves(record *run.Object) bool {
	health := record.Dict("health")
	return health != nil && health.Truthy("command")
}

// Path is the "lock" a run of repo's project is handed over and its live follower ends under, the
// "follower" lock it holds for life, and the "runs" handed to it (watch.live_path): one follower a
// project, as each has its merges' settings, which no other's may have.
func Path(repo, kind string) string {
	return filepath.Join(run.Runs(), ".live-"+filepath.Base(repo)+"."+kind)
}

// Runs is, under the live lock, the runs handed to the follower that it has yet to take, handed
// added, else all taken (watch.live_runs); written whole, so a writer stopped anywhere leaves the
// list it found.
func Runs(repo, handed string) ([]string, error) {
	path := Path(repo, "runs")
	data, err := os.ReadFile(path)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return nil, err
	}
	runs := config.SplitLines(string(data))
	if handed != "" {
		tmp := fmt.Sprintf("%s.%d.tmp", path, os.Getpid())
		if err := os.WriteFile(tmp, []byte(strings.Join(append(runs, handed), "\n")), 0o666); err != nil {
			return nil, err
		}
		return runs, os.Rename(tmp, path)
	}
	if err := os.Remove(path); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return nil, err
	}
	return runs, nil
}
