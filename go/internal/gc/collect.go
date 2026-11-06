package gc

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

// What the collector takes, as Python's gc.cmd_gc, sweep, gc, schedule_gc and record_gc take it:
// the plan read family by family, each item checked again by its family's removal as it goes.

// CollectVerb is the unlisted command the tick starts its collection with: `ak gc-collect`.
const CollectVerb = "gc-collect"

const logLimit = 1 << 20 // gc.log rolls over to gc.log.1 past this (gc.GC_LOG_LIMIT)

// collection is one pass taking what its plan names.
type collection struct {
	report   func(string)
	failed   error           // the automatic collection's log could not be written: the pass ends
	balked   map[string]bool // a harness whose own way of ending a conversation failed this pass
	held     []string        // what every process holds, read once for the pass's removals
	heldRead bool
}

func newCollection(report func(string)) *collection {
	return &collection{report: report, balked: map[string]bool{}}
}

// Collect is `ak run gc`: the sweep, then the collector's plan, each said as it goes, then the
// merged checkouts and sandboxes the sweep took and the space they held.  ErrPython, before
// anything goes, where goTakes says so.
func Collect(out io.Writer) error {
	if err := goTakes(); err != nil {
		return err
	}
	say := func(line string) { fmt.Fprintln(out, line) }
	c := newCollection(say)
	// the sweep goes first, so the line below counts every merged checkout and sandbox it took
	trees, boxes, freed := 0, 0, int64(0)
	c.locked(func() {
		for _, item := range newReads().sweep() {
			size := treeBytes(item.Path)
			if !c.take(item) {
				continue
			}
			freed += size
			if item.Kind == "merged-worktree" {
				trees++
			} else {
				boxes++
			}
		}
	})
	removed := 0
	c.locked(func() { removed = c.pass() })
	switch {
	case trees+boxes > 0:
		say(fmt.Sprintf("gc: removed %d merged worktree%s and %d smoke sandbox%s, %s freed",
			trees, plural(trees, "s"), boxes, plural(boxes, "es"), sizeWords(float64(freed))))
	case removed == 0:
		say("gc: no eligible artifacts")
	}
	return nil
}

// Automatic is the collection the tick starts, Python's gc.gc(automatic=True): while one is due,
// its start written to gc.log and gc.json first, every line after it to gc.log, the user
// manager's units cleared before the plan is taken.  ErrPython, before anything goes, where
// goTakes says so.
func Automatic() error {
	if err := goTakes(); err != nil {
		return err
	}
	c := newCollection(nil)
	c.report = func(line string) {
		if c.failed == nil {
			c.failed = record(line)
		}
	}
	c.locked(func() {
		state := filepath.Join(config.Home(), "state")
		stamp := filepath.Join(state, "gc.json")
		if !Due() || !safe(state) || unsafe(stamp) || unsafe(filepath.Join(state, "gc.tmp")) {
			return
		}
		c.report("gc: automatic collection started")
		if c.failed == nil && writeJSON(stamp, run.Fields("started_at", run.Float(epoch()))) == nil {
			clearUnits(c.report)
			c.pass()
		}
	})
	return nil
}

// Schedule is the tick's collection row (gc.schedule_gc): where the home reads without a change
// and a collection is due, a collector of Go's own starts, detached and unmarked, to outlive the
// tick.  One that cannot start is logged.  False, before it starts, where a user manager runs and
// goTakes says the collection is Python's: there the tick went to Python, which clears the units
// with it, before Go cleared them, and a detached collector's handover reaches nobody.  Elsewhere
// the tick goes on, as it always has.
func Schedule(log func(string)) bool {
	probe, err := reading(config.Home(), true)
	if err != nil {
		return true
	}
	probe.Close()
	if !Due() {
		return true
	}
	if host.UserManager() && goTakes() != nil {
		return false
	}
	if err := start(); err != nil {
		log("WARN could not start retention: " + config.PyError(err))
	}
	return true
}

func start() error {
	self, err := os.Executable()
	if err != nil {
		return err
	}
	env, err := config.ChildEnv()
	if err != nil {
		return err
	}
	collector := exec.Command(self, CollectVerb)
	collector.Env = host.Unmarked(env)
	collector.SysProcAttr = host.Detached()
	if err := collector.Start(); err != nil {
		return err
	}
	return collector.Process.Release()
}

// Due is whether a collection is due: none started within the last day, by gc.json's mark; a
// mark from the future or not a number holds nothing off (gc.gc_due).
func Due() bool {
	mark := (&reads{}).json(filepath.Join(config.Home(), "state", "gc.json"))
	if mark == nil {
		return true
	}
	_, number := mark.Get("started_at").(run.Number)
	at, _ := run.Num(mark.Get("started_at"))
	now := epoch()
	return !(number && now-day < at && at <= now)
}

// goTakes is ErrPython where the collection is Python's, decided before anything goes: a plan
// Python makes, an item Go plans and does not take, or a seat record whose cursor Go cannot take out.
func goTakes() error {
	plan, err := DryRun()
	if err != nil {
		return err
	}
	if slices.ContainsFunc(plan, func(item Item) bool { return item.take == nil }) || cursorsPython() {
		return ErrPython
	}
	return nil
}

// locked runs the pass under the collector's lock, the home folder's own flock, taken without
// waiting: Python's collection takes the same one, and one held means another collection runs.
func (c *collection) locked(pass func()) {
	home, err := reading(config.Home(), true)
	if err != nil {
		return
	}
	defer home.Close()
	if unlocked(home) {
		pass()
	}
}

// pass takes the owner's saved words out, then the collector's plan family by family in the
// table's order, each family read just before its items go, as Python's plan is read while it is
// taken: how many items went.
func (c *collection) pass() int {
	c.forgetOwnerWords()
	r, removed := newReads(), 0
	for _, family := range families {
		for _, item := range family(r) {
			if c.failed != nil {
				return removed
			}
			if c.take(item) {
				removed++
			}
		}
	}
	return removed
}

// take takes one item and says so: whether it went.  What its removal could not do keeps it, said.
func (c *collection) take(item Item) bool {
	if item.take == nil {
		return false // Python's, planned since goTakes looked
	}
	done, err := item.take(c)
	if err != nil {
		c.report(fmt.Sprintf("gc: kept %s: %s", item.Path, config.PyError(err)))
		return false
	}
	if done {
		c.report(item.said())
	}
	return done
}

// every is what every process holds, read once for the pass's temporary entries; nil where that
// proves nothing idle.
func (c *collection) every() []string {
	if !c.heldRead {
		c.heldRead = true
		c.held = (&reads{}).every()
	}
	return c.held
}

// record writes a line to gc.log, rolled over to gc.log.1 past its limit (gc.record_gc).
func record(message string) error {
	path := filepath.Join(config.Home(), "state", "gc.log")
	if unsafe(path) || unsafe(path+".1") {
		return errors.New("unsafe collection log")
	}
	line := time.Now().Format("2006-01-02 15:04:05") + " " + message + "\n"
	if info, err := os.Lstat(path); err == nil && info.Size()+int64(len(line)) > logLimit {
		if err := os.Rename(path, path+".1"); err != nil {
			return err
		}
	}
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666)
	if err != nil {
		return err
	}
	_, err = file.WriteString(line)
	return errors.Join(err, file.Close())
}

// writeJSON replaces a state file whole through its `.tmp`, as Python's config._write_json does.
func writeJSON(path string, value any) error {
	if err := config.EnsureDirs(); err != nil {
		return err
	}
	tmp := strings.TrimSuffix(path, filepath.Ext(path)) + ".tmp"
	if err := os.WriteFile(tmp, []byte(run.Encode(value)+"\n"), 0o666); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// reading opens what retention may read, without moving an access time (retention.reading).
func reading(path string, directory bool) (*os.File, error) {
	if !safe(path) {
		return nil, errors.New("cannot read without changing metadata: " + path)
	}
	return open(path, directory)
}

// unsafe is something at the path that retention may not touch.
func unsafe(path string) bool { return present(path) && !safe(path) }

// treeBytes is what a tree's entries take on disk, a link counted as a link: what removing it
// gives back (gc.tree_bytes).
func treeBytes(path string) int64 {
	total := int64(0)
	filepath.WalkDir(path, func(at string, entry fs.DirEntry, err error) error {
		if err == nil && at != path {
			if info, err := entry.Info(); err == nil {
				total += diskBytes(info)
			}
		}
		return nil
	})
	return total
}

// sizeWords is the space freed the way `du -h` counts it: `16.0 GB`, `220.5 MB` (gc.size_words).
func sizeWords(count float64) string {
	for _, unit := range []string{"B", "kB", "MB", "GB"} {
		if count < 1024 {
			if unit == "B" {
				return fmt.Sprintf("%.0f B", count)
			}
			return fmt.Sprintf("%.1f %s", count, unit)
		}
		count /= 1024
	}
	return fmt.Sprintf("%.1f TB", count)
}

func plural(count int, ending string) string {
	if count == 1 {
		return ""
	}
	return ending
}
