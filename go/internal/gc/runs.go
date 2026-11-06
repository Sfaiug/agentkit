package gc

import (
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/job"
	"agentkit/internal/run"
)

// What the collector plans for runs and jobs, and the sweep `ak run gc` makes past its proofs.

// generated is what a merged run's directory holds that ak wrote and gzips: its log, each
// round's done-when log and each turn's streams.
var generated = regexp.MustCompile(`^(?:log\.txt|round-[0-9]+/donewhen\.log|round-[0-9]+/(?:executor|reviewer)(?:-[A-Za-z0-9_-]+)?/(?:events\.jsonl|stderr\.log|stdout\.log))$`)

// jobEnded is each state a job's task ends in (job.JOB_TERMINAL).
var jobEnded = []string{"merged", "passed", "failed", "blocked", "skipped", "stopped"}

// record is the run.json of a run directory, nil where there is none or it names another run.
func (r *reads) record(dir string) *run.Object {
	record := r.json(filepath.Join(dir, "run.json"))
	if record == nil || record.Str("run_id") != filepath.Base(dir) {
		return nil
	}
	return record
}

// sweep is what `ak run gc` takes past the collector's proofs: every merged run's own checkout,
// whatever it holds, and every smoke sandbox a day old (gc.sweep_plan).
func (r *reads) sweep() []Item {
	var found []Item
	for _, dir := range children(runsDir()) {
		record := r.record(dir)
		if record == nil || record.Truthy("scratch") || record.Str("state") != "pass" || !record.Truthy("merged") ||
			!provablyFinal(record) || run.Writing(dir) {
			continue
		}
		repo, worktree := record.Str("repo"), record.Get("worktree")
		wt, ok := worktree.(string)
		if repo == "" || !ok || config.Pure(wt) != filepath.Join(wtDir(), filepath.Base(dir)) || config.Pure(repo) == config.Pure(wt) {
			continue
		}
		wt = config.Pure(wt)
		if config.UnderCode(wt) || !present(wt) || !safe(wt) || busy(wt, r.paths) || r.left[wt] {
			continue
		}
		found = append(found, Item{"remove", "merged-worktree", wt, "", takeMerged(dir, wt)})
	}
	for _, path := range children(tmpDir()) {
		if !strings.HasPrefix(filepath.Base(path), "smoke-") || !safe(path) || !isDir(path) {
			continue
		}
		receipt := r.json(marker(path))
		if receipt == nil {
			receipt = run.NewObject()
		}
		if receipt.Get("pid") != nil && writerActive(receipt) {
			continue
		}
		at := first(receipt, "finished_at", "created_at")
		if at == nil {
			info, _ := os.Lstat(path)
			at = mtime(info)
		}
		if expired(at, r.now, day) && !busy(path, r.paths) && !r.left[path] {
			found = append(found, Item{"remove", "smoke-sandbox", path, "", takeSandbox(path)})
		}
	}
	return found
}

// goneJobs is a stop for every job nobody is coming back for, planned before any run goes: the
// old-run rule's removal of a task's run would take its last write with it (gc.gone_jobs).
func (r *reads) goneJobs() []Item {
	if !safe(job.Jobs()) {
		return nil
	}
	var found []Item
	for _, dir := range children(job.Jobs()) {
		if job := r.json(job.ReceiptPath(filepath.Base(dir))); job != nil && isList(job.Get("tasks")) && r.jobAgedOut(dir, job) {
			stop := takeGoneJob(dir)
			if r.goneJobPython(dir, job) {
				stop = nil
			}
			found = append(found, Item{"stop", "gone-job", dir, "the job's launcher gone and nothing written for 30 days", stop})
		}
	}
	return found
}

// jobAgedOut is a job's launcher gone and nothing written for a run directory's age, in its
// directory or that of any run of it, no link directly in any of them (gc.job_aged_out).
func (r *reads) jobAgedOut(dir string, job *run.Object) bool {
	quiet := func(top string) bool { return lastWrite(top, ".lock") <= r.now-runAge }
	if job.Truthy("finished_at") || run.ProcessActive(job) || !quiet(dir) {
		return false
	}
	dirs := append([]string{dir}, r.jobRuns(dir, job)...)
	for _, top := range dirs {
		if !safe(top) || slices.ContainsFunc(children(top), func(path string) bool { return !safe(path) }) {
			return false
		}
	}
	return !slices.ContainsFunc(dirs, func(top string) bool { return !quiet(top) })
}

// jobRuns is every run of a job: named on its receipt, or naming the job (job.job_runs).
func (r *reads) jobRuns(dir string, job *run.Object) []string {
	named := map[string]bool{}
	for _, task := range job.List("tasks") {
		if task, ok := task.(*run.Object); ok && task.Str("run_id") != "" {
			named[task.Str("run_id")] = true
		}
	}
	var found []string
	entries, _ := os.ReadDir(runsDir())
	for _, entry := range entries {
		path := filepath.Join(runsDir(), entry.Name())
		if !isDir(path) {
			continue
		}
		if record := r.json(filepath.Join(path, "run.json")); named[entry.Name()] || record != nil && record.Str("job_id") == filepath.Base(dir) {
			found = append(found, path)
		}
	}
	return found
}

// lastWrite is the newest change of a file under the folder, links to folders unfollowed and
// names ending in skip uncounted (watch.run_last_write).
func lastWrite(dir, skip string) float64 {
	latest := 0.0
	entries, _ := os.ReadDir(dir)
	for _, entry := range entries {
		path := filepath.Join(dir, entry.Name())
		if isDir(path) {
			if entry.Type()&fs.ModeSymlink == 0 {
				latest = max(latest, lastWrite(path, skip))
			}
		} else if info, err := os.Stat(path); err == nil && !strings.HasSuffix(entry.Name(), skip) {
			latest = max(latest, mtime(info))
		}
	}
	return latest
}

// runs is each run directory's items, in name order (gc.gc_candidates).
func (r *reads) runs() []Item {
	var found []Item
	for _, dir := range children(runsDir()) {
		record := r.record(dir)
		if record == nil {
			continue
		}
		quiet := !writerActive(record) && !busy(dir, r.paths) && !run.Writing(dir)
		// a throwaway repo's run is the smoke suite's own: on nobody's list, naming no project
		if throwaway(record.Get("repo")) && expired(first(record, "finished_at", "started_at"), r.now, r.age()) &&
			!record.Truthy("notification_pending") && !record.Truthy("pending_inbox") && !record.Truthy("handback_pending") &&
			quiet && safe(dir) {
			found = append(found, Item{"remove", "throwaway-run", dir, "", takeWhole(dir, false, nil)})
			continue
		}
		// a seat that still exists keeps its runs however old: they are what it is made of
		interrupted := idleInterrupted(record, r.now)
		if (interrupted != nil || provablyFinal(record) && runAgedOut(dir, record, r.now)) && quiet && safe(dir) {
			seat, named := launchedSession(record)
			lives := false
			if named {
				name, _, err := config.ResolveSession(seat)
				lives = err != nil || r.sessionLives(name)
			}
			if !lives {
				found = append(found, Item{"remove", "old-run", dir, "", takeWhole(dir, true, interrupted)})
				continue
			}
		}
		worktree, _ := record.Get("worktree").(string)
		if (run.Failed(record) || record.Str("state") == "stopped") && provablyFinal(record) && quiet &&
			(expired(record.Get("finished_at"), r.now, gcAge) ||
				handedBack(record) && !record.Truthy("checkout_kept") && !resumeHoldsTree(record, dir)) &&
			disposable(dir, record) && !r.left[worktree] && !busy(config.Pure(worktree), r.paths) {
			found = append(found, Item{"remove", "ended-worktree", worktree, "", takeCheckout(dir, config.Pure(worktree), true)})
		}
		if record.Truthy("scratch") || record.Str("state") != "pass" || !record.Truthy("merged") || !provablyFinal(record) ||
			record.Truthy("notification_pending") || record.Truthy("pending_inbox") || record.Truthy("handback_pending") ||
			!quiet || !collectible(dir, record) {
			continue
		}
		wt := config.Pure(worktree)
		if busy(wt, r.paths) {
			continue
		}
		if present(wt) && !r.left[wt] {
			found = append(found, Item{"remove", "merged-worktree", wt, "", takeCheckout(dir, wt, false)})
		}
		// a final run's generated streams are gzipped beside where they are, at the first pass
		snapshot, _ := tree(dir, nil, nil)
		for _, each := range snapshot {
			relative, _ := filepath.Rel(dir, each.path)
			if !generated.MatchString(relative) || !safe(each.path) || !isFile(each.path) ||
				present(each.path+".gz") && !sameArchive(each.path) {
				continue
			}
			found = append(found, Item{"compress", "merged-log", each.path, "", takeLog(dir, each.path, each.stat)})
		}
	}
	return found
}

// finishedJobs is each job every task of which ended, its age past (gc.gc_candidates).
func (r *reads) finishedJobs() []Item {
	if !safe(job.Jobs()) {
		return nil
	}
	var found []Item
	for _, dir := range children(job.Jobs()) {
		job := r.json(job.ReceiptPath(filepath.Base(dir)))
		if job == nil || !tasksEnded(job) || !expired(job.Get("finished_at"), r.now, r.age()) || job.Truthy("handback_pending") || writerActive(job) ||
			busy(dir, r.paths) || present(filepath.Join(dir, "job.tmp")) {
			continue
		}
		found = append(found, Item{"remove", "finished-job", dir, "", takeFinishedJob(dir)})
	}
	return found
}

func isList(value any) bool {
	_, ok := value.([]any)
	return ok
}

// first is the first of those keys' values Python reads as true, nil for none.
func first(record *run.Object, keys ...string) any {
	for _, key := range keys {
		if record.Truthy(key) {
			return record.Get(key)
		}
	}
	return nil
}

func mtime(info fs.FileInfo) float64 {
	if info == nil {
		return 0
	}
	return float64(info.ModTime().UnixNano()) / 1e9
}

// throwaway is a repo under ~/.agentkit/tmp: the smoke suite's, made for one suite.
func throwaway(repo any) bool {
	path, ok := repo.(string)
	return ok && path != "" && (config.Pure(path) == tmpDir() || below(path, tmpDir()))
}

// idleInterrupted is when a run interrupted longer than a run directory's age, its loop gone, was
// interrupted, as its record says it; nil for any other.
func idleInterrupted(record *run.Object, now float64) any {
	if when, ok := run.Num(record.Get("interrupted_at")); record.Str("state") == "interrupted" && ok && when <= now-runAge && pidGone(record) {
		return record.Get("interrupted_at")
	}
	return nil
}

// runAgedOut is the run's own clock, the newer of its start and finish, past a run directory's
// age; the directory's own time for a record with neither (gc.run_aged_out).
func runAgedOut(dir string, record *run.Object, now float64) bool {
	when := math.Inf(-1)
	for _, key := range []string{"finished_at", "started_at"} {
		if value, ok := run.Num(record.Get(key)); ok && value > 0 {
			when = max(when, value)
		}
	}
	if math.IsInf(when, -1) {
		info, err := os.Stat(dir)
		if err != nil {
			return false
		}
		when = mtime(info)
	}
	return when <= now-runAge
}

// launchedSession is the name of the seat that launched the run, false for none.
func launchedSession(record *run.Object) (string, bool) {
	key := "launched_session"
	if !record.Truthy(key) {
		key = "session"
	}
	name, ok := record.Get(key).(string)
	return name, ok && name != ""
}

// handedBack is whether this ending, and not an earlier attempt's, was handed back.
func handedBack(record *run.Object) bool {
	said, ok := run.Num(record.Get("handed_back"))
	if !ok {
		return record.Truthy("handed_back")
	}
	if ended, ok := run.Num(first(record, "finished_at", "interrupted_at")); ok {
		return said >= ended
	}
	return true
}

// resumeHoldsTree is whether `ak run resume` can still take the run, which needs its checkout
// (worktrees.resume_holds_tree).
func resumeHoldsTree(record *run.Object, dir string) bool {
	summaries := record.List("round_summaries")
	rounds, _ := run.Num(record.Get("rounds"))
	return needsRecovery(record) || run.AtBudget(record) || record.Str("state") == "error" && record.Truthy("own_pr_round_pending") ||
		float64(len(summaries)) < rounds && (integrationNote(record, dir) || judged(record, dir))
}

// needsRecovery is work a resume could carry on, never a line member's (transitions.needs_recovery).
func needsRecovery(record *run.Object) bool {
	waiting := record.Dict("waiting_on")
	return run.NeedsRecovery(record) && !(record.Str("state") == "waiting" && waiting != nil && waiting.Truthy("line"))
}

// integrationFail is a FAIL past the merge whose saved work and note name where it failed
// (transitions._integration_fail_guards).
func integrationFail(record *run.Object, dir string) bool {
	worktree, _ := record.Get("worktree").(string)
	if state := record.Str("state"); state != "fail" && state != "waiting" || record.Truthy("review_pr") || worktree == "" || !isDir(worktree) {
		return false
	}
	for _, key := range []string{"branch", "base", "base_sha", "rounds", "merge_note"} {
		if !record.Truthy(key) {
			return false
		}
	}
	log, err := os.ReadFile(filepath.Join(dir, "log.txt"))
	return err == nil && strings.Contains(string(log), "not merged:")
}

// judgedFail is a review's FAIL with a done-when value and the commit it judged.
func judgedFail(last *run.Object) bool {
	return last != nil && last.Str("verdict") == "FAIL" && last.Get("done_when") != nil && (last.Has("head_sha") || last.Has("tree_sha"))
}

// integrationNote is a FAIL whose last note came from integration, not the rounds.
func integrationNote(record *run.Object, dir string) bool {
	summaries := record.List("round_summaries")
	var last *run.Object
	if len(summaries) > 0 {
		last, _ = summaries[len(summaries)-1].(*run.Object)
	}
	return integrationFail(record, dir) && !judgedFail(record.Dict("review")) && !judgedFail(last)
}

// judged is a judged FAIL after the rebase with rounds left (transitions.judged_in_integration).
func judged(record *run.Object, dir string) bool {
	summaries := record.List("round_summaries")
	if len(summaries) == 0 {
		return false
	}
	last, _ := summaries[len(summaries)-1].(*run.Object)
	return integrationFail(record, dir) && judgedFail(last)
}

// disposable is the run's own registered checkout, never ~/code, the repo or a link
// (worktrees.disposable_workspace).
func disposable(dir string, record *run.Object) bool {
	wt, _ := record.Get("worktree").(string)
	repo := record.Str("repo")
	if wt == "" || config.UnderCode(wt) || isLink(wt) || !present(wt) || repo == "" || config.Pure(repo) == config.Pure(wt) {
		return false
	}
	return config.Pure(wt) == filepath.Join(wtDir(), filepath.Base(dir)) && safe(wt) && safe(repo)
}
