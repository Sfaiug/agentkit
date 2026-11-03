package gc

import (
	"compress/gzip"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/job"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// How the collector takes what runs and jobs leave, and what the sweep takes past its proofs.

// takeMerged is the sweep's take of a merged run's checkout: as a stop takes it, its branch too.
func takeMerged(dir, wt string) func(*collection) (bool, error) {
	return func(c *collection) (bool, error) {
		loop.StopCheckout(dir, orEmpty((&reads{}).json(filepath.Join(dir, "run.json"))), c.report, false)
		return !c.leftBehind(wt), nil
	}
}

// takeSandbox is the sweep's take of a smoke sandbox a day old: what this user can remove of it.
func takeSandbox(path string) func(*collection) (bool, error) {
	return func(c *collection) (bool, error) {
		if err := os.RemoveAll(path); err != nil {
			c.report(fmt.Sprintf("gc: kept %s: %s", path, config.PyError(err)))
		}
		return !c.leftBehind(path), nil
	}
}

// takeWhole takes a run's directory whole under its recovery lock: a throwaway run's while its
// record is as planned; an old run's while its seat is still gone and it is as final, or as long
// interrupted, as planned, its checkout and branch going first (gc.gc).
func takeWhole(dir string, old bool, interrupted any) func(*collection) (bool, error) {
	file := filepath.Join(dir, "run.json")
	identity, _ := fingerprint(file)
	return func(c *collection) (bool, error) {
		if !safe(dir) || !recoverySafe(dir) {
			return false, nil
		}
		r := &reads{now: epoch(), paths: processPaths()}
		release, err := holdRecovery(dir)
		if err != nil {
			return false, err
		}
		defer release()
		state := orEmpty(r.json(file))
		// a final run does not wait for a second look at its record; one resumed since does
		now, _ := fingerprint(file)
		same := old && interrupted == nil && provablyFinal(state) || now == identity
		if !same || writerActive(state) || busy(dir, r.paths) {
			return false, nil
		}
		if old {
			seat, named := launchedSession(state)
			if named {
				name, _, err := config.ResolveSession(seat)
				if err != nil {
					return false, nil
				}
				seat = name
			}
			still := provablyFinal(state)
			if interrupted != nil {
				still = run.Equal(idleInterrupted(state, r.now), interrupted)
			}
			if r.sessionLives(seat) || !still {
				return false, nil
			}
			// its checkout would stay with nothing naming it, and its branch would only crowd the
			// next run's name: a tree already reported left behind is not tried again
			if tree := ownTree(state); tree != "" && r.leftovers()[tree] {
				loop.DropBranch(state.Str("repo"), state.Str("branch"), c.report)
			} else if _, err := c.dropTree(state, tree, true, true); err != nil {
				return false, err
			}
		}
		if err := os.RemoveAll(dir); err != nil {
			return false, err
		}
		return !present(dir), nil
	}
}

// takeCheckout takes a final run's checkout, under its recovery lock: an ended run's while past
// its week or told and no resume holds it (loose), a merged run's while still clean (gc.gc).
func takeCheckout(dir, wt string, loose bool) func(*collection) (bool, error) {
	return func(c *collection) (bool, error) {
		return stillFinal(dir, !loose, func(state *run.Object) (bool, error) {
			if loose && !(expired(state.Get("finished_at"), epoch(), gcAge) ||
				handedBack(state) && !state.Truthy("checkout_kept") && !resumeHoldsTree(state, dir)) {
				return false, nil
			}
			return c.dropTree(state, wt, false, false)
		})
	}
}

// takeLog gzips a merged run's log while the run is final and the log as planned.
func takeLog(dir, path string, identity stat) func(*collection) (bool, error) {
	return func(*collection) (bool, error) {
		return stillFinal(dir, true, func(*run.Object) (bool, error) { return compress(path, identity) })
	}
}

// stillFinal hands the run's record, read under its recovery lock, to then while the run is
// final, nobody writes or holds it or its checkout, and a checkout planned clean still is.
func stillFinal(dir string, clean bool, then func(*run.Object) (bool, error)) (bool, error) {
	paths := processPaths()
	if !recoverySafe(dir) {
		return false, nil
	}
	release, err := holdRecovery(dir)
	if err != nil {
		return false, err
	}
	defer release()
	state := orEmpty((&reads{}).json(filepath.Join(dir, "run.json")))
	worktree, named := state.Get("worktree").(string)
	if !provablyFinal(state) || writerActive(state) || busy(dir, paths) || named && busy(worktree, paths) ||
		clean && !collectible(dir, state) {
		return false, nil
	}
	return then(state)
}

// compress gzips a log beside it, losslessly: published only where no archive stands, the log
// unlinked only once the archive holds it and the log is still as planned (retention.compress).
func compress(path string, expected stat) (bool, error) {
	same := func() bool {
		now, ok := fingerprint(path)
		return ok && now == expected
	}
	if !safe(path) || !same() {
		return false, nil
	}
	dest, part := path+".gz", path+".gz.part"
	if isLink(dest) || isLink(part) {
		return false, nil
	}
	if present(dest) {
		// an earlier pass published it and was cut short before the unlink
		if sameArchive(path) && same() {
			return true, os.Remove(path)
		}
		return false, nil // never over another archive
	}
	if unsafe(part) {
		return false, nil
	}
	if err := archive(path, part); err != nil {
		return false, err
	}
	if !same() {
		return false, os.Remove(part)
	}
	// published only where nobody made an archive meanwhile, its name durable before the log goes
	if err := os.Link(part, dest); err != nil {
		return false, err
	}
	if err := os.Remove(part); err != nil {
		return false, err
	}
	parent, err := reading(filepath.Dir(path), true)
	if err != nil {
		return false, err
	}
	err = parent.Sync()
	parent.Close()
	if err != nil || !same() {
		return false, err
	}
	return true, os.Remove(path)
}

// archive writes the log's gzip to part, named for it and dated 0, as Python's GzipFile does.
func archive(path, part string) error {
	source, err := reading(path, false)
	if err != nil {
		return err
	}
	defer source.Close()
	output, err := os.Create(part)
	if err != nil {
		return err
	}
	packed, _ := gzip.NewWriterLevel(output, gzip.BestCompression)
	packed.Name = filepath.Base(path)
	_, err = io.Copy(packed, source)
	return errors.Join(err, packed.Close(), output.Sync(), output.Close())
}

// takeFinishedJob takes a finished job's directory under its recovery lock, while its receipt is
// as planned and every task still ended (gc.gc).
func takeFinishedJob(dir string) func(*collection) (bool, error) {
	receipt := job.ReceiptPath(filepath.Base(dir))
	identity, _ := fingerprint(receipt)
	return func(*collection) (bool, error) {
		if !safe(dir) {
			return false, nil
		}
		paths := processPaths()
		release, err := holdRecovery(dir)
		if err != nil {
			return false, err
		}
		defer release()
		job := orEmpty((&reads{}).json(receipt))
		if now, _ := fingerprint(receipt); now != identity || writerActive(job) || busy(dir, paths) || !tasksEnded(job) {
			return false, nil
		}
		if err := os.RemoveAll(dir); err != nil {
			return false, err
		}
		return !present(dir), nil
	}
}

// takeGoneJob stops a job nobody is coming back for, judged again under the lock a resume writes
// its receipt under: each task left unfinished stopped and the job finished, as Python's
// stop.stop_job ends a job whose launcher is gone, with no unit and no run of it to end
// (goneJobPython).
func takeGoneJob(dir string) func(*collection) (bool, error) {
	return func(*collection) (bool, error) {
		if !safe(dir) {
			return false, nil
		}
		release, err := holdRecovery(dir)
		if err != nil {
			return false, err
		}
		defer release()
		receipt := job.ReceiptPath(filepath.Base(dir))
		record, _ := run.ReadJSON(receipt)
		if record == nil || !isList(record.Get("tasks")) {
			return false, fmt.Errorf("%s: cannot read %s", filepath.Base(dir), receipt)
		}
		r := &reads{now: epoch()}
		if !r.jobAgedOut(dir, record) || r.goneJobPython(dir, record) {
			return false, nil
		}
		for _, each := range record.List("tasks") {
			task, ok := each.(*run.Object)
			if !ok {
				return false, errors.New("a task that is not an object")
			}
			if slices.Contains(jobEnded, task.Str("state")) {
				continue
			}
			name, ok := task.Get("name").(string)
			if !ok {
				return false, errors.New("'name'")
			}
			run.SetAll(task, "state", "stopped", "finished_at", run.Float(epoch()), "verdict_line", name+": stopped")
		}
		record.Set("finished_at", run.Float(epoch()))
		tmp := filepath.Join(dir, "job.tmp")
		if err := os.WriteFile(tmp, []byte(run.EncodeText(record)), 0o666); err != nil {
			return false, err
		}
		return true, os.Rename(tmp, receipt)
	}
}

// goneJobPython is a gone job whose stop is Python's: its unit to stop, or a run of it still
// stoppable, which Python's stop.end ends.
func (r *reads) goneJobPython(dir string, record *run.Object) bool {
	return record.Truthy("scope") || slices.ContainsFunc(r.jobRuns(dir, record), func(path string) bool {
		state := r.json(filepath.Join(path, "run.json"))
		return state != nil && (!run.Ended(state) || state.Str("state") == "error" ||
			state.Str("state") == "stopped" && state.Dict("lease_wait") != nil && !state.Truthy("lease_restarted"))
	})
}

// tasksEnded is a receipt with tasks, every one of them ended.
func tasksEnded(job *run.Object) bool {
	return len(job.List("tasks")) > 0 && !slices.ContainsFunc(job.List("tasks"), func(each any) bool {
		task, ok := each.(*run.Object)
		return !ok || !slices.Contains(jobEnded, task.Str("state"))
	})
}

// fingerprint is what a path is now, as Python's retention.fingerprint tells it.
func fingerprint(path string) (stat, bool) {
	_, st, ok := lstat(path)
	return st, ok
}
