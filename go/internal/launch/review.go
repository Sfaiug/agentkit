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

// Review launches a review of somebody else's pull request at url, Python's review_pr_main, from no
// seat: `ak run`'s exit status, and why the launch is refused.  Whose PR a seat is reviewing, and a
// launch a run on that PR refuses, stay with Python, decided before anything is written.
func Review(url string, values map[string]string, flags map[string]bool, out, errOut io.Writer) (int, string, error) {
	bound, unbound := config.Bind()
	_, rules := pick.Load()
	if unbound != nil || elsewhere() || len(bound.Workers) == 0 || !readable(slices.Collect(maps.Values(values))...) ||
		values["--review"] != "" || !rules || !driverHere(nil) || reviewGoing(url) {
		return 0, "", ErrPython
	}
	parts := gh.PullURL.FindStringSubmatch(url)
	numbersIn, err := reviewNumbers(parts[1] + "/" + parts[2])
	if err != nil {
		return 2, err.Error(), nil
	}
	pull, unread := gh.View(url)
	if errors.Is(unread, gh.ErrPython) {
		return 0, "", ErrPython
	}
	dir, err := freeDir(time.Now().Format("20060102-1504-") + "review-pr-" + task.Slug(parts[2]) + "-" + parts[3])
	if err != nil {
		return 0, "", err
	}
	log, unstopped := logger(dir, out), guarded(dir, out)
	for _, step := range []func() error{
		config.EnsureDirs,
		func() error { return os.Mkdir(dir, 0o777) },
		func() error { return os.WriteFile(filepath.Join(dir, "log.txt"), nil, 0o666) },
		func() error { return receive(dir, "", values, flags, bound) },
	} {
		if err := step(); err != nil {
			return 0, "", err
		}
	}
	if unread != nil {
		return refuse(dir, unread.Error(), "", log)
	}
	if err := unstopped(func(record *run.Object) {
		run.SetAll(record, "title", fmt.Sprintf("Review PR #%s: %s", pull.Number, pull.Title), "own_pr", false, "own_orchestrator", nil,
			"own_orchestrator_effort", nil, "policy", run.Fields("rounds", numbersIn.Rounds, "review_lines", numbersIn.ReviewLines, "seat_lines", numbersIn.SeatLines))
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

// reviewGoing is whether a run on that pull request has not ended, whatever its URL's spelling,
// which Python refuses in its own words, or a record Go cannot read may be one.
func reviewGoing(url string) bool {
	for _, dir := range run.Dirs() {
		record, err := run.Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) {
			return true
		}
		if record != nil && !run.Ended(record) && (samePull(record.Str("review_pr"), url) || samePull(record.Str("pr"), url)) {
			return true
		}
	}
	return false
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
	if checkout := seat.CheckoutFor(slug); checkout != "" {
		return numbers(checkout)
	}
	return config.HostNumbers()
}
