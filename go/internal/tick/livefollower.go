package tick

import (
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/handback"
	"agentkit/internal/handover"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// liveInterval is how long a live follower waits after a probe ends before its next, so slow
// probes never overlap (watch.LIVE_INTERVAL).
const liveInterval = 15 * time.Second

// lasting is the live lock a follower ends under, kept from the collector, which would close it:
// held till the process is gone, so the next follower starts after it.
var lasting *os.File

// FollowLive is `ak watch --live RUN`, Python's live_follower: the run goes to its project's one
// live follower, this process where no other holds the follower lock, which follows it and every
// run handed to it after, each on a goroutine of its own, so a slow probe moves no other's times,
// and ends once none is left: a process per merge held 6.4 GB of a 15 GB host (6 Nov 2026).  What
// it logs goes to out.  Left is where it hands the run over, before it takes any lock: one the
// merge checks leave to Python, and any on Windows, where every tick is Python's.  Failed is a
// lock or the list of runs that cannot be had, said on errOut, as Python's raise ends it.
func FollowLive(name string, out, errOut io.Writer) (left string, failed bool) {
	record, err := run.Read(filepath.Join(run.Runs(), name))
	if errors.Is(err, run.ErrLoneSurrogate) || errors.Is(err, run.ErrLimit) {
		return handover.Here(0), false
	}
	if record == nil || record.Str("repo") == "" {
		return "", false // no project, so nothing proves it live (seat.AwaitingLive)
	}
	if runtime.GOOS == "windows" || pythons(record, epoch(time.Now())) {
		return handover.Here(0), false
	}
	repo, say, shared := record.Str("repo"), func(line string) { fmt.Fprintln(out, line) }, &census{}
	follower, runs, following := heldOnStdin(livePath(repo, "follower")), []string{name}, atomic.Int64{}
	fail := func(err error) (string, bool) {
		fmt.Fprintf(errOut, "ak watch: %s\n", config.PyError(err))
		return "", true
	}
	for {
		live, err := lock.Wait(context.Background(), livePath(repo, "lock"))
		if err != nil {
			return fail(err)
		}
		if follower == nil {
			if follower, err = lock.Try(livePath(repo, "follower")); errors.Is(err, lock.ErrHeld) {
				_, err = liveRuns(repo, name) // an older run process started this one for its merge
				live.Close()
				if err != nil {
					return fail(err)
				}
				return "", false
			} else if err != nil {
				return fail(err)
			}
		}
		taken, err := liveRuns(repo, "")
		if err != nil {
			return fail(err)
		}
		if runs = append(runs, taken...); following.Load() == 0 && len(runs) == 0 {
			follower.Close()
			lasting = live
			return "", false
		}
		live.Close()
		for _, each := range runs {
			following.Add(1)
			go func() {
				defer following.Add(-1)
				if err := followLive(filepath.Join(run.Runs(), each), shared, say); err != nil && !errors.Is(err, errLeft) {
					say(fmt.Sprintf("WARN run %s's health could not be followed: %s", each, config.PyError(err)))
				}
			}()
		}
		runs = nil
		time.Sleep(time.Second) // what a run handed over waits at most for its follow to start
	}
}

// followLive follows one run's merge to live, Python's follow_live, under the run's live.lock, a
// run whose lock another holds being that one's to follow, for as long as goesOn says.  Each round
// reads the merge checks' verdict; on a pass, its ending is said where it carries the change gone
// live, and a pass its seat need not hear now ends the follow.  A run the merge checks leave to
// Python is left to the tick, errLeft with nothing written for it.
func followLive(dir string, shared *census, say func(string)) error {
	held, err := lock.Try(filepath.Join(dir, "live.lock"))
	if errors.Is(err, lock.ErrHeld) {
		return nil
	} else if err != nil {
		return err
	}
	defer held.Close()
	began := epoch(time.Now())
	for {
		record, census, on, err := goesOn(dir, began, shared)
		if !on || err != nil {
			return err
		}
		if record.Get("finished_at") == nil {
			time.Sleep(100 * time.Millisecond) // a merge precedes its ending; delivery must see that stable attempt
			continue
		}
		now := epoch(time.Now())
		if pythons(record, now) {
			return errLeft
		}
		each := &merge{name: filepath.Base(dir), pr: record.Str("pr"), record: record}
		if err := verdict(each, record.Str("repo"), now, map[[2]string]probe{}, census, say, false); err != nil {
			return err
		}
		if each.verdict == "passed" {
			if record, census, on, err = goesOn(dir, began, shared); !on || err != nil {
				return err
			}
			carried, err := handback.CarriesLive(record, census)
			if err != nil {
				return errLeft
			}
			if carried && handback.Announce(dir, census, say) {
				if _, _, on, err = goesOn(dir, began, shared); !on || err != nil {
					return err
				}
			}
		}
		time.Sleep(liveInterval)
	}
}

// goesOn is the run's record as it stands, the census, and whether its follow goes on: while the
// run waits on its health, one not ended yet read as ending at began, or while a pass inside its
// window is owed to its seat now.  ErrLeft where Go cannot read the run, or what its seat is owed,
// as Python does.
func goesOn(dir string, began float64, shared *census) (*run.Object, []*run.Object, bool, error) {
	record, err := run.Read(dir)
	if errors.Is(err, run.ErrLoneSurrogate) || errors.Is(err, run.ErrLimit) {
		return nil, nil, false, errLeft
	}
	at := time.Now()
	switch {
	case record == nil:
		return nil, nil, false, nil
	case record.Get("finished_at") == nil:
		pending := record.Copy()
		pending.Set("finished_at", run.Float(began))
		return record, nil, seat.AwaitingLive(pending, at), nil
	}
	census, err := shared.read()
	if err != nil {
		return nil, nil, false, err
	}
	owed, err := handback.LiveOwedNow(record, census)
	if err != nil {
		return nil, nil, false, errLeft
	}
	finished, _ := record.Num("finished_at")
	age := epoch(at) - finished
	return record, census, seat.AwaitingLive(record, at) || owed && 0 <= age && age <= mergeWindow, nil
}

// A census is every run's record as a live follower's follows ask of it, Python's Census: read
// whole when an ask first needs it and shared by every ask within a liveInterval of that read; past
// it, the next ask reads again while the others wait for it.  A run going at that read is read again
// at each ask, which decides from its seat's other runs going: one taken for going after it ended
// would settle a notice as routine that its seat was owed.  A read for each ask grew with the square
// of the runs followed: 27 waited to go live on one seat on 6 Nov 2026.
type census struct {
	mu      sync.Mutex
	at      time.Time
	dirs    []string
	records []*run.Object
}

// read is the census as an ask takes it; errLeft where a record holds what Go cannot keep.
func (c *census) read() ([]*run.Object, error) {
	c.mu.Lock()
	if time.Since(c.at) >= liveInterval {
		c.dirs, c.records = nil, nil
		if !run.Every(func(dir string, record *run.Object) bool {
			c.dirs, c.records = append(c.dirs, dir), append(c.records, record)
			return true
		}) {
			c.mu.Unlock()
			return nil, errLeft
		}
		c.at = time.Now()
	}
	dirs, records := c.dirs, slices.Clone(c.records)
	c.mu.Unlock()
	now := time.Now()
	for i, record := range records {
		if run.Going(record, now) {
			records[i], _ = run.Read(dirs[i])
		}
	}
	return slices.DeleteFunc(records, func(record *run.Object) bool { return record == nil }), nil
}

// livePath is the "lock" a run of repo's project is handed over and its live follower ends under,
// the "follower" lock it holds for life, and the "runs" handed to it (watch.live_path): one
// follower a project, as each has its merges' settings, which no other's may have.
func livePath(repo, kind string) string {
	return filepath.Join(run.Runs(), ".live-"+filepath.Base(repo)+"."+kind)
}

// liveRuns is, under the live lock, the runs handed to the follower that it has yet to take, handed
// added, else all taken (watch.live_runs); written whole, so a writer stopped anywhere leaves the
// list it found.
func liveRuns(repo, handed string) ([]string, error) {
	path := livePath(repo, "runs")
	data, err := os.ReadFile(path)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return nil, err
	}
	runs := config.SplitLines(string(data))
	if handed != "" {
		return runs, replaceFile(path, strings.Join(append(runs, handed), "\n"))
	}
	if err := os.Remove(path); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return nil, err
	}
	return runs, nil
}

// heldOnStdin is the follower lock at path on stdin, from the merge that started this process and
// held since its fork (start_live_probe), else nil.  Stdin then reads /dev/null: Go hands a child
// what os.Stdin names, never its own descriptor 0, so nothing it runs keeps the lock.
func heldOnStdin(path string) *os.File {
	in, err := os.Stdin.Stat()
	if err != nil {
		return nil
	}
	if follower, err := os.Stat(path); err != nil || !os.SameFile(in, follower) {
		return nil
	}
	held := os.Stdin
	if null, err := os.Open(os.DevNull); err == nil {
		os.Stdin = null
	}
	return held
}
