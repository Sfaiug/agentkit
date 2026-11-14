package launch

import (
	"cmp"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"agentkit/internal/commandhelp"
	"agentkit/internal/gh"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// judge is the run's launch, still waiting for its slot in this process, judged again on the
// version installed now (on), Python's judge_queued: once for each version it waits on, so a rule
// landing while it waits refuses it then, not once a slot comes.  A refusal is the error it
// returns, which the driver ends the run with as a refused launch ends; a read that failed, of
// GitHub or of git, refuses nothing, and the version stays unjudged for the next one, or the run,
// to ask again.  loop.ErrLeft where Python reads what Go cannot.
func judge(dir, on string) error {
	record, _ := run.Read(dir)
	if on == "" || record == nil || !waitingHere(record) || record.Str("judged_on") == on {
		return nil
	}
	var why string
	var err error
	if url := record.Str("review_pr"); url != "" {
		why, err = pullRefusal(dir, url, record)
	} else {
		why, err = taskRefusal(dir, record)
	}
	switch {
	case errors.Is(err, gh.ErrPython):
		return loop.ErrLeft
	case err != nil:
		return nil
	case why != "":
		return errors.New(why)
	}
	return run.Change(dir, func(record *run.Object) error {
		if waitingHere(record) {
			record.Set("judged_on", on)
		}
		return nil
	})
}

// waitingHere is whether the record is a launch this process waits for a slot for.
func waitingHere(record *run.Object) bool {
	pid, _ := record.Int("pid")
	return record.Str("state") == "queued" && pid == os.Getpid()
}

// taskRefusal is why the launch of the run's task is refused in the repository its preflight
// settled, as Python's preflight judges a launch already waiting.
func taskRefusal(dir string, record *run.Object) (string, error) {
	path := filepath.Join(dir, "task.md")
	meta, cmds, err := task.Read(path)
	if err != nil {
		return "", err
	}
	opts := record.Dict("launch_opts")
	flags := map[string]bool{"--no-merge": record.Truthy("no_merge"), "--no-worktree": opts != nil && opts.Truthy("--no-worktree")}
	_, _, why, err := laterRefusal(record.Str("repo"), path, meta, cmds, flags)
	return why, err
}

// pullRefusal is why the review of the pull request at url is refused: a seat's own as its launch
// refuses it (loop.OwnRefusal); somebody else's never, once GitHub answers for it.
func pullRefusal(dir, url string, record *run.Object) (string, error) {
	pull, err := gh.View(url)
	if err != nil || !record.Truthy("own_pr") {
		return "", err
	}
	return loop.OwnRefusal(dir, pull)
}

// laterRefusal is why Python's preflight refuses a run of the task in repo, "" for a scratch run,
// once its base is settled, "" for none: more than 3 checks a round runs, or a `from:` the run
// cannot start from, named in the run's own copy of the task (copied).  With the checks a round
// runs and those it runs once.
func laterRefusal(repo, copied string, meta map[string]string, cmds []string, flags map[string]bool) (every, once []string, why string, err error) {
	landing := repo != "" && !flags["--no-merge"]
	suite := ""
	if landing {
		spelled := cmp.Or(meta["target"], meta["base"])
		if spelled == "" {
			head, _, ok, err := git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
			if err != nil {
				return nil, nil, "", err
			}
			if ok {
				spelled = head
			}
		}
		suite = run.DeclaredSuite(repo, spelled)
	}
	every, once = task.Group(task.RoundCommands(cmds, suite, landing))
	why = task.ChecksRefusal(every)
	switch from := meta["from"]; {
	case why != "" || from == "":
	case repo == "":
		why = copied + ": from: needs a repository; a scratch run has no branch to start from"
	case flags["--no-worktree"]:
		why = copied + ": from: needs a worktree; drop --no-worktree so the run gets its own checkout"
	default:
		branch, _, _, err := git(repo, "rev-parse", "--verify", "--quiet", "refs/heads/"+from)
		if err != nil {
			return nil, nil, "", err
		}
		if branch == "" {
			why = fmt.Sprintf("%s: from: %s is not a local branch", copied, commandhelp.Quote(from))
		}
	}
	return every, once, why, nil
}
