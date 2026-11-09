// Package gc is what ak's collector would take, planned as Python's gc.cmd_gc plans a dry run.
// It hides each family's scan, in the collector's order, and what they share, read once: the
// paths this user's processes hold, those every process holds, the seats tmux holds, the disk's
// pressure and the trees gc already gave up on.  Its interface is the plan, which a collection
// re-checks item by item before it takes one, as Python's gc does.
package gc

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/seat"
)

// ErrPython is a plan Go cannot make as Python does: a read not ported to this platform, or a
// record Go does not read as Python reads it.
var ErrPython = errors.New("the plan is Python's")

const (
	day      = 86400.0
	gcAge    = 7 * day  // failed, blocked and stopped checkouts, finished jobs (gc.GC_AGE)
	runAge   = 30 * day // a run directory whose seat is gone, a conversation (gc.RUN_DIR_AGE)
	tmpAge   = 2 * day  // a /tmp entry nothing changed (gc.TMP_AGE)
	diskFull = 85.0     // pressure shortens retention to a day (gc.DISK_LIMIT)
)

// An Item is one thing the collector would take: what it does, to what kind, where, and why
// where the family says; and how its family takes it, nil where Python takes it.
type Item struct {
	Action, Kind, Path, Why string
	take                    func(*collection) (bool, error)
}

// Line is the item as a dry run prints it.
func (item Item) Line() string { return "gc: would " + item.words() }

// said is the item as the collection says it went.
func (item Item) said() string { return "gc: " + item.words() }

func (item Item) words() string {
	why := ""
	if item.Why != "" {
		why = ": " + item.Why
	}
	return fmt.Sprintf("%s %s %s%s", item.Action, item.Kind, item.Path, why)
}

// families is the collector's plan in Python's order (gc.gc_candidates), each family a scan of
// its own whose items carry their removal: the collection takes each family's just after it.
var families = []func(*reads) []Item{
	(*reads).goneJobs,
	(*reads).runs,
	(*reads).finishedJobs,
	(*reads).ephemeral,
	(*reads).staleWorktrees,
	(*reads).seatFiles,
	(*reads).harnessEntries,
	(*reads).tmpEntries,
	(*reads).repoTmpEntries,
	(*reads).homeEntries,
	(*reads).conversations,
}

// DryRun is `ak run gc --dry-run`'s plan: what the sweep takes past the collector's proofs, then
// each of the collector's items the sweep does not already name.  It writes nothing.
func DryRun() ([]Item, error) {
	if !ported {
		return nil, ErrPython
	}
	r := newReads()
	plan := r.sweep()
	listed := map[string]bool{}
	for _, item := range plan {
		listed[item.Path] = true
	}
	for _, family := range families {
		for _, item := range family(r) {
			if !listed[item.Path] {
				plan = append(plan, item)
			}
		}
	}
	if r.python {
		return nil, ErrPython
	}
	return plan, nil
}

// newReads is a pass's reads: its clock, what this user's processes hold, what gc gave up on and
// the disk's pressure, read as it begins (gc.gc_candidates).
func newReads() *reads {
	r := &reads{now: epoch(), paths: processPaths()}
	r.left = r.leftovers()
	r.pressure = diskPressure()
	return r
}

func epoch() float64 { return float64(time.Now().UnixNano()) / 1e9 }

// reads is what the families share, each read once.
type reads struct {
	now      float64
	pressure bool
	paths    []string        // what this user's processes hold; nil where unknown, which keeps all
	left     map[string]bool // trees gc reported left behind (gc.leftovers)
	python   bool            // a read Go does not make as Python does
	held     []string        // what every process holds (gc.tmp_processes), once asked
	heldRead bool
	names    *seat.Names
	holds    func(harness, conversation string) bool // what the seats hold, once asked
}

func (r *reads) leftovers() map[string]bool {
	left := map[string]bool{}
	if record := r.json(filepath.Join(config.Home(), "state", "gc-leftovers.json")); record != nil {
		for _, key := range record.Keys() {
			left[key] = true
		}
	}
	return left
}

// age is how long a finished job or a throwaway run stays: a day on a full disk.
func (r *reads) age() float64 {
	if r.pressure {
		return day
	}
	return gcAge
}

// every is what every process holds, as Python's gc.tmp_processes reads it, nil where that
// proves nothing idle.  A process hiding its own is one Python asks `sudo -n` to read, which Go
// does not: where sudo would let it, the plan is Python's.
func (r *reads) every() []string {
	if !r.heldRead {
		r.heldRead = true
		held, ok := host.Held()
		switch {
		case ok:
			r.held = append([]string{}, held...)
		case sudoReads():
			r.python = true
		}
	}
	return r.held
}

// sudoReads is whether `sudo -n` would run Python's process inspector as root; no answer is
// no proof it would not.
func sudoReads() bool {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return exec.CommandContext(ctx, "sudo", "-n", "-l", "/usr/bin/python3").Run() == nil || ctx.Err() != nil
}

// seated is whether tmux holds a seat by that name.
func (r *reads) seated(name string) bool {
	if r.names == nil {
		names := seat.ReadNames()
		r.names = &names
	}
	return r.names.Seat(name)
}

// sessionLives is whether that seat still exists: its record, or tmux holding it; a name that
// cannot be a seat's is no proof it is gone (gc.session_lives).
func (r *reads) sessionLives(name string) bool {
	if name == "" {
		return false
	}
	path, err := config.SessionPath(name)
	if err != nil {
		return true
	}
	if _, err := os.Stat(path); err == nil {
		return true
	}
	// orch.find: a name with a space is also the seat its slug names
	return r.seated(name) || strings.Contains(name, " ") && r.seated(config.SessionName(name))
}

// diskPressure is whether the disk holding ~/.agentkit is fuller than the limit,
// $AGENTKIT_GC_DISK_PERCENT where set (gc.disk_pressure).
func diskPressure() bool {
	limit := diskFull
	if raw := os.Getenv("AGENTKIT_GC_DISK_PERCENT"); raw != "" {
		if parsed, err := strconv.ParseFloat(strings.TrimSpace(raw), 64); err == nil {
			limit = parsed
		}
	}
	where := config.Home()
	if _, err := os.Stat(where); err != nil {
		where = config.UserHome()
	}
	used, total, ok := diskUse(where)
	if !ok || total == 0 {
		return false
	}
	return 100*float64(used)/float64(total) > limit
}

// ak's own folders.
func runsDir() string { return filepath.Join(config.Home(), "runs") }
func wtDir() string   { return filepath.Join(config.Home(), "wt") }
func tmpDir() string  { return filepath.Join(config.Home(), "tmp") }
