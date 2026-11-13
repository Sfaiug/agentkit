package launch

import (
	"fmt"
	"slices"
	"strings"

	"agentkit/internal/gitcall"
	"agentkit/internal/job"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// JobRefusal is the sentence for a job's task file at path that cannot start as written, "" for
// none, Python's job_refusal, asked at launch and again at the task's start of the file as it reads
// then: a task of an ordered job names no branch of its own (ownBranch); then Refusal.
func JobRefusal(path string, meta map[string]string, cmds []string, flags map[string]bool) (string, error) {
	if flags["--in-order"] && ownBranch(meta) {
		return "an ordered job cuts each task from its repository's default branch, where the one before it merged: drop base:, target: and from:", nil
	}
	return Refusal(path, meta, cmds)
}

// ownBranch is whether the task names a branch of its own, which an ordered job's task may not: it
// is cut from its repository's default branch, where the one before it merged.
func ownBranch(meta map[string]string) bool {
	for _, key := range []string{"base", "target", "from"} {
		if _, named := meta[key]; named {
			return true
		}
	}
	return false
}

// behind is whether the queued task at i of an ordered job waits on the one before it, which has
// not merged: until that one ends, and for good once it ended unmerged, the task then skipped and
// never started (run_job_loop).
func (j *jobRun) behind(tasks []any, i int) (bool, error) {
	if !j.flags["--in-order"] || i == 0 {
		return false, nil
	}
	before := tasks[i-1].(*run.Object).Str("state")
	switch {
	case before == "merged":
		return false, nil
	case slices.Contains(job.Terminal, before):
		skipped := tasks[i].(*run.Object)
		return true, j.end(skipped, "skipped", "verdict_line", skipped.Str("name")+": not started")
	}
	return true, nil
}

// tip fetches every branch origin has into the checkout the ordered job's task at path works in,
// before the task is judged: the task is cut where the one before it merged, which only origin's
// tip holds, so its policy and refusals are read there and the tracking ref its run falls back to
// is that tip (job_start_task).  Nothing to fetch for a job in no order, a scratch task, or one
// whose file, checkout or own branch its judging then refuses.
func (j *jobRun) tip(path string) error {
	meta, _, unread := task.Read(path)
	if !j.flags["--in-order"] || unread != nil || ownBranch(meta) {
		return nil
	}
	repo, refused, err := checkout(meta, path, path)
	if err != nil || refused != "" || repo == "" {
		return nil
	}
	code, out, err := gitcall.Git{Repo: repo}.Fetch("origin", "--prune", "+refs/heads/*:refs/remotes/origin/*")
	if err == nil && code != 0 {
		why, _, _ := strings.Cut(out, "\n")
		err = fmt.Errorf("could not fetch origin, and an ordered job's task starts only on origin's tip: %s", why)
	}
	return err
}

// orderedLine is the line of an ordered job that ended at a task that did not merge: that task's
// own, and the tasks it left unstarted (job_ender); "" for a job in no order, or one whose every
// task merged.
func orderedLine(receipt *run.Object) string {
	if opts := receipt.Dict("opts"); opts == nil || !opts.Truthy("--in-order") {
		return ""
	}
	var ender *run.Object
	var unstarted []string
	for _, each := range receipt.List("tasks") {
		task := each.(*run.Object)
		if ender == nil && task.Str("state") != "merged" {
			ender = task
		}
		if task.Str("state") == "skipped" {
			unstarted = append(unstarted, task.Str("name"))
		}
	}
	if ender == nil {
		return ""
	}
	line := "job " + run.Text(receipt.Get("job_id")) + ": " + ender.Str("verdict_line")
	if len(unstarted) > 0 {
		line += "; not started: " + strings.Join(unstarted, ", ")
	}
	return line
}
