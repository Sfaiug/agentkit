package launch

import (
	"fmt"
	"io"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gh"
	"agentkit/internal/handback"
	"agentkit/internal/loop"
	"agentkit/internal/pick"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/task"
)

// ownReview launches a review from a session, Python's review_pr_main where the run has a session
// name: Go's where it is the seat's own pull request, by this host's GitHub login, launched with
// --no-merge.  One it lands, or of somebody else's pull request, it leaves to Python, deciding so
// before it writes anything.  A refusal is printed where the seat typed it, so it is handed back.
func ownReview(url string, numbersIn config.Numbers, values map[string]string, flags map[string]bool, out, errOut io.Writer) (int, string, error) {
	session, record, unnamed := config.CurrentSession()
	_, pointer := record[config.Renamed]
	bound, unbound := bind()
	_, rules := pick.Within(names(bound.Workers), names(bound.Reviewers))
	if unnamed != nil || pointer || unbound != nil || surroundings() || !flags["--no-merge"] || len(bound.Workers) == 0 ||
		!readable(slices.Collect(maps.Values(values))...) || values["--review"] != "" || !rules || !driverHere() || unreadRun() {
		return 0, "", ErrPython
	}
	pull, err := gh.View(url)
	if err != nil || !gh.ByViewer(pull.Author) {
		return 0, "", ErrPython
	}
	dir, err := freeDir(time.Now().Format("20060102-1504-") + "review-pr-" + task.Slug(pull.Name) + "-" + pull.Number)
	if err != nil {
		return 0, "", err
	}
	log, unstopped := logger(dir, out), guarded(dir, out)
	refused := func(why string) (int, string, error) {
		code, reason, err := refuse(dir, why, "", log)
		if err == nil {
			err = handback.PrintedAtLaunch(dir, func(line string) { log(line) })
		}
		return code, reason, err
	}
	taken := ""
	for _, step := range []func() error{
		config.EnsureDirs,
		func() error { return os.Mkdir(dir, 0o777) },
		func() error { return os.WriteFile(filepath.Join(dir, "log.txt"), nil, 0o666) },
		func() error {
			slots, err := holdSlots()
			if err != nil {
				return err
			}
			defer slots.Close()
			taken = runOn(url)
			// a seat launched it, never the tick: its first record says no launch it descends from
			return run.Create(dir, run.Capture(dir, "", values, flags, bound, session))
		},
		func() error { seat.Redress(session); return nil }, // the seat's bar says it from the start
	} {
		if err := step(); err != nil {
			return 0, "", err
		}
	}
	if taken != "" {
		return refused(fmt.Sprintf("run %s on %s has not ended; `ak wait %s`, then launch again if it is still needed", taken, url, taken))
	}
	if err := unstopped(func(receipt *run.Object) {
		// the writer the reviewer's independence is judged against, captured once: a session
		// record rewritten since must not replace it
		var writer, effort any
		if name, _ := record["orchestrator"].(string); name != "" {
			if model, err := config.ModelNamed(name); err == nil {
				writer, effort = name, model.Efforts["effort"]
				if held := receipt.Dict("efforts"); held != nil && held.Dict(name) != nil {
					effort = held.Dict(name).Get("effort")
				}
			}
		}
		run.SetAll(receipt, "title", fmt.Sprintf("Review PR #%s: %s", pull.Number, pull.Title), "own_pr", true, "own_orchestrator", writer,
			"own_orchestrator_effort", effort, "policy", run.Fields(numbersIn.Said()...))
	}); err != nil {
		return 0, "", err
	}
	// as Python's preflight refuses one: any read that fails refuses it too
	if why, err := loop.OwnRefusal(dir, pull); err != nil || why != "" {
		if err != nil {
			why = err.Error()
		}
		return refused(why)
	}
	code, err := underWay(dir, []string{"--- preflight",
		fmt.Sprintf("repo: %s/%s | base: %s | target: %s | merge: squash", pull.Owner, pull.Name, pull.Base, pull.Base),
		fmt.Sprintf("delivery: review %s at %s; merge on PASS with green checks", url, pull.Head),
		"done-when: AGENTS.md tests: command from the target, else the PR checkout",
	}, "notification: verdict on GitHub; PASS with green checks merges, FAIL hands back to the seat (stderr if unconfigured)", flags, log, out, errOut)
	return code, "", err
}
