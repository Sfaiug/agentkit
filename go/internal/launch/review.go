package launch

import (
	"errors"
	"fmt"
	"io"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/pick"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/task"
)

// Review launches a review of the pull request at url, Python's review_pr_main: `ak run`'s exit
// status, and why the launch is refused.  Its numbers are read first, as every launch's.  From no
// session it is a review of somebody else's pull request; one with a session name is a seat's, with
// or without its record (ownReview).
func Review(url string, values map[string]string, flags map[string]bool, out, errOut io.Writer) (int, string, error) {
	parts := gh.PullURL.FindStringSubmatch(url)
	numbersIn, err := reviewNumbers(parts[1] + "/" + parts[2])
	if errors.Is(err, ErrPython) {
		return 0, "", err
	} else if err != nil {
		return 2, err.Error(), nil
	}
	if session, _, unnamed := config.CurrentSession(); session != "" || unnamed != nil {
		return ownReview(url, numbersIn, values, flags, out, errOut)
	}
	bound, unbound := config.Bind()
	_, rules := pick.Load()
	if unbound != nil || ungated("") || seated() || len(bound.Workers) == 0 || !readable(slices.Collect(maps.Values(values))...) ||
		values["--review"] != "" || !rules || !driverHere() || unreadRun() {
		return 0, "", ErrPython
	}
	on := installed() // the ak whose preflight this is, read before it is
	pull, unread := gh.View(url)
	if errors.Is(unread, gh.ErrPython) {
		return 0, "", ErrPython
	}
	dir, err := freeDir(time.Now().Format("20060102-1504-") + "review-pr-" + task.Slug(parts[2]) + "-" + parts[3])
	if err != nil {
		return 0, "", err
	}
	admitted, err := admitReview(dir, "", flags)
	if err != nil {
		return 0, "", err
	}
	defer admitted.release()
	log, unstopped := logger(dir, out), guarded(dir, out)
	taken := ""
	for _, step := range []func() error{
		config.EnsureDirs,
		func() error { return os.Mkdir(dir, 0o777) },
		func() error { return os.WriteFile(filepath.Join(dir, "log.txt"), nil, 0o666) },
		func() (err error) {
			taken, err = receiveReview(dir, url, run.Capture(dir, "", values, flags, bound, ""), admitted)
			return err
		},
		func() error { recorded(dir); return nil },
	} {
		if err := step(); err != nil {
			return 0, "", err
		}
	}
	if taken != "" {
		return refuse(dir, fmt.Sprintf("run %s on %s has not ended; `ak wait %s`, then launch again if it is still needed", taken, url, taken), "", log)
	}
	if unread != nil {
		return refuse(dir, unread.Error(), "", log)
	}
	if err := unstopped(func(record *run.Object) {
		run.SetAll(record, "title", fmt.Sprintf("Review PR #%s: %s", pull.Number, pull.Title), "own_pr", false, "own_orchestrator", nil,
			"own_orchestrator_effort", nil, "policy", run.Fields(numbersIn.Said()...), "judged_on", on)
	}); err != nil {
		return 0, "", err
	}
	code, err := underWay(dir, []string{"--- preflight",
		fmt.Sprintf("repo: %s/%s | base: %s | target: %s | merge: none (review only)", pull.Owner, pull.Name, pull.Base, pull.Base),
		fmt.Sprintf("delivery: review %s at %s; publish findings", url, pull.Head),
		"done-when: AGENTS.md tests: command from the target, else the PR checkout",
	}, "notification: verdict on GitHub; PASS with green checks offered to "+config.Inbox()+" and needs to Discord (stderr if unconfigured)", flags, log, out, errOut)
	return code, "", err
}

// admitReview is a review's first poll for its slot, as a task's (admit), from the seat named, ""
// for none: it holds the slots lock until its receipt claims it (receiveReview).  Told --bg,
// nothing here follows it.
func admitReview(dir, seat string, flags map[string]bool) (*admission, error) {
	depth, _ := runDepth()
	return admit(filepath.Base(dir), flags["--first"], seat, depth, !flags["--bg"])
}

// receiveReview writes a review's receipt as receive does, and is the run on its pull request that
// has not ended, "" for none, read under the lock the receipt is written in: of two launches at once,
// the second sees the first, as two reviews of one PR would each post and offer it.
func receiveReview(dir, url string, receipt *run.Object, admitted *admission) (string, error) {
	if admitted != nil {
		taken := runOn(url)
		return taken, admitted.claim(dir, receipt)
	}
	slots, err := holdSlots()
	if err != nil {
		return "", err
	}
	defer slots.Close()
	taken := runOn(url)
	return taken, run.Create(dir, receipt)
}

// unreadRun is whether a run's record holds what Go cannot read: it may be on this pull request.
func unreadRun() bool {
	return slices.ContainsFunc(run.Dirs(), func(dir string) bool {
		_, err := run.Read(dir)
		return errors.Is(err, run.ErrLoneSurrogate)
	})
}

// runOn is the id of a run on that pull request that has not ended, whatever its URL's spelling, ""
// for none.
func runOn(url string) string {
	for _, dir := range run.Dirs() {
		record, _ := run.Read(dir)
		if record != nil && !run.Ended(record) && (samePull(record.Str("review_pr"), url) || samePull(record.Str("pr"), url)) {
			return filepath.Base(dir)
		}
	}
	return ""
}

// samePull is whether two URLs name one pull request: owner and repository case-folded, a trailing
// slash ignored.
func samePull(one, two string) bool {
	a, b := gh.PullURL.FindStringSubmatch(one), gh.PullURL.FindStringSubmatch(two)
	return a != nil && b != nil && strings.EqualFold(a[1], b[1]) && strings.EqualFold(a[2], b[2]) && a[3] == b[3]
}

// reviewNumbers is the numbers in force for a review of that repository: its checkout's here, else
// the host's.
func reviewNumbers(slug string) (config.Numbers, error) {
	return numbers(seat.CheckoutFor(slug), true)
}
