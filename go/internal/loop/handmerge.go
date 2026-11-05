package loop

import (
	"cmp"
	"errors"
	"io"
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/gitcall"
	"agentkit/internal/run"
)

// `ak run merge <id>`, Python's cmd_merge: a passed run whose delivery stopped short is delivered
// again by hand, through the delivery the run's own ending takes.  Work that passed review is never
// thrown away over one refused merge.

// MergeRefused is why the run named id has nothing waiting to merge, "" where it has, Python's
// cmd_merge on the record alone and in its order: only a finished PASS that a delivery set out on,
// and stands on no dependency's unmerged work.
func MergeRefused(id string) string {
	record, _ := run.Read(filepath.Join(run.Runs(), id))
	switch {
	case record == nil || record.Str("verdict") != "PASS" || record.Str("state") != "pass":
		return id + ": merge requires a finished PASS"
	case dependency(record) != "":
		return id + ": " + dependency(record)
	case record.Truthy("review_pr") || record.Truthy("scratch") || !record.Truthy("pr") && !record.Truthy("merge_failed"):
		return id + ": no delivery PR to merge"
	}
	return ""
}

// dependency is why a record from before `after:` went cannot go on, "" where it can, Python's
// stands_on_dependency: its branch stands on a dependency's passed tip, whose commits landing it
// would deliver unreviewed.
func dependency(record *run.Object) string {
	after := record.Dict("from_pass")
	if after == nil || record.Get("base_sha") != nil && !run.Equal(record.Get("base_sha"), after.Get("tip")) {
		return ""
	}
	dep := run.Text(after.Get("task"))
	if !record.Truthy("branch") {
		return "this run was to start from " + dep + "'s passed work, which `after:` no longer waits for; once that has merged, launch its task again"
	}
	return "this branch stands on " + dep + "'s passed work, which `after:` no longer waits for; once that has merged, relaunch with `from: " + record.Str("branch") + "`"
}

// Mergeable is whether Go carries a hand merge of that run: one on no road of
// Python's, delivering from its own account rather than a fork's, out of a checkout still there.
func Mergeable(record *run.Object) bool {
	for _, key := range pythonRoads {
		if key != "waiting_on" && record.Truthy(key) {
			return false
		}
	}
	return !record.Truthy("foreign") && record.Truthy("repo") && (record.Truthy("merged") || isDir(record.Str("worktree")))
}

// Merge delivers the passed run at dir again, in this process as Python's cmd_merge does, its log
// followed on out: a merged one says so and merges nothing.  It is the exit status, and why it
// refused.
func Merge(dir string, out, errOut io.Writer) (int, string, error) {
	if Logging(dir) {
		// A detached retry already writes here; replaying its log would feed it back into itself.
		out = io.Discard
	}
	id := filepath.Base(dir)
	record, err := run.Read(dir)
	if record == nil {
		return 0, "", cmp.Or(err, errors.New("run.json cannot be read"))
	}
	if record.Truthy("merged") {
		said := stamped(run.Delivery(record, run.Models()))
		appendLog(dir, said)
		io.WriteString(out, said)
		return 0, "", nil
	}
	if record.Truthy("pr") && !record.Truthy("delivery_sha") {
		return 2, id + ": no recorded delivery SHA; cannot safely retry the merge", nil
	}
	log, err := os.Open(filepath.Join(dir, "log.txt"))
	if err != nil {
		return 0, "", err
	}
	defer log.Close()
	log.Seek(0, io.SeekEnd)
	stoppedOn := cmp.Or(record.Str("merge_note"), "delivery did not finish")
	// this process owns the run while it delivers: one killed here leaves a `running` record naming
	// it, for the reaper to call interrupted, never a PASS with its failure cleared and nobody on it
	if err := run.Change(dir, func(current *run.Object) error {
		if !run.Equal(current, record) {
			return ErrChanged
		}
		for _, key := range append(delivery, "quota_dry") {
			current.Delete(key)
		}
		run.SetAll(current, "state", "running", "merge_failed", false, "merge_note", nil, "on_target", false,
			"reported", false, "finished_at", nil, "pid", os.Getpid(), "process_identity", Identity(os.Getpid()))
		return nil
	}); errors.Is(err, ErrChanged) {
		return 2, err.Error(), nil
	} else if err != nil {
		return 0, "", err
	}
	done := make(chan int, 1)
	go func() {
		done <- drive(dir, func(l *loop) error {
			l.say("merge " + l.id + ": " + filepath.Join(dir, "task.md"))
			return l.redeliver(stoppedOn)
		})
	}()
	for {
		select {
		case code := <-done:
			io.Copy(out, log)
			if record, _ := run.Read(dir); parkedInLine(record) {
				// back in its line: followed through its lander's wake, as a launch is
				at, _ := log.Seek(0, io.SeekCurrent)
				return Follow(dir, at, out, errOut), "", nil
			}
			return code, "", nil
		case <-time.After(followEvery):
			io.Copy(out, log)
		}
	}
}

// redeliver is Python's cmd_merge from its delivery: a run that never reached its PR is delivered
// again from integration; one with a PR, while that PR is still this delivery, open, at the
// reviewed commit.  One GitHub merged already is recorded merged.
func (l *loop) redeliver(stoppedOn string) error {
	if err := l.open(); err != nil {
		return err
	}
	if err := l.pick(); err != nil {
		return err
	}
	r := l.place.(*repoPlace) // a repository's run: MergeRefused and Mergeable saw to it
	record, err := read(l)
	if err != nil {
		return err
	}
	url := record.Str("pr")
	if url == "" {
		l.say("no delivery PR: " + stoppedOn + "; delivering again from integration")
		return r.merge(l)
	}
	current, err := prHead(l.dir, url)
	var stopped *gitcall.Stopped
	switch {
	case errors.As(err, &stopped):
		return r.note(l, stopped.Why, true)
	case err != nil:
		return r.note(l, err.Error(), true)
	case !isDelivery(record, current, r.upstream()):
		return r.note(l, "PR head or target changed since PASS; a new run is required", true)
	case current.Truthy("merged"):
		// a merge that went through before its record did
		return r.merged(l, url, cmp.Or(record.Str("merge_method"), "squash"))
	case current.Str("state") != "open":
		return r.note(l, "PR is closed without a merge", true)
	}
	if err := r.requireReviewPass(l); err != nil {
		return err
	}
	if cmp.Or(record.Dict("review"), run.NewObject()).Str("head_sha") != record.Str("delivery_sha") {
		return &exhausted{"saved delivery SHA has no matching done-when and review; resume the run to obtain review", false}
	}
	return r.merge(l)
}
