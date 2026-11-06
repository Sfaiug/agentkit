package handback

import (
	"cmp"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/lock"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// StartFollowups hands a merged review's commands on under the lock that closes its seat.
// prepare writes a queued seat receipt and returns its start, so the plan exists before any
// fix can deliver it. A cut-off handoff finds its receipts again, even a fix stopped since.
// Items with no command remain unclaimed for Python's regression-test follow-up path.
func StartFollowups(dir string, prepare func(string, *run.Object, *run.Object) (func() error, error), say func(string)) error {
	state, err := run.Read(dir)
	if state == nil || !state.Truthy("merged") || !state.Truthy("followups") || run.Seat(state) == "" ||
		!state.Truthy("repo") || state.Truthy("scratch") || state.Truthy("review_pr") && !state.Truthy("own_pr") {
		return err
	}
	held, err := lock.Wait(context.Background(), filepath.Join(config.Home(), "state", "watch.lock"))
	if err != nil {
		return err
	}
	defer held.Close()
	state, err = run.Read(dir)
	if err != nil || state == nil || state.Has("followup_runs") {
		return err
	}
	session, lists, err := seatLists(state)
	if err != nil || lists == nil {
		return err
	}
	repo := mainCheckout(state.Str("repo"))
	state.Set("repo", repo)
	fixers := fixers(lists)
	runs, entries, complete := []any{}, []any{}, true
	var starts []func() error
	checks, commits := cmp.Or(state.Dict("followup_checks"), run.NewObject()), cmp.Or(state.Dict("followup_commits"), run.NewObject())
	for _, value := range state.List("followups") {
		item := run.Text(value)
		check := strings.TrimFunc(checks.Str(item), config.Space)
		if check == "" {
			complete = false
			continue
		}
		started, opened := followupTaken(state, filepath.Base(dir), item, check)
		var start func() error
		if fixers && started == "" && !opened {
			var child string
			child, err = followupTask(state, "Fix "+config.SplitLines(item)[0], item+"\n\n"+task.FixTheCommand, check)
			if err == nil {
				origin := run.Fields("followup", run.Fields("run", filepath.Base(dir), "text", item,
					"place", followupPlace(item), "check", check), "repo", repo)
				start, err = prepare(child, state, origin)
				if err == nil {
					started, opened = filepath.Base(child), true
				}
			}
			if err != nil {
				say(fmt.Sprintf("follow-up could not start: %v", err))
				_, opened = followupTaken(state, filepath.Base(dir), item, check)
			}
		}
		outcome := "Fix " + strings.ReplaceAll(config.SplitLines(item)[0], "·", "-")
		line, refused := plan.AddProven(context.Background(), session, repo, outcome, check,
			cmp.Or(commits.Str(item), state.Str("base_sha")), opened)
		entry := run.Fields("outcome", outcome, "deferred", plan.Deferred(line))
		if refused != nil {
			entry = run.Fields("outcome", outcome, "refused", refused.Error())
		}
		entries = append(entries, entry)
		if start != nil {
			starts = append(starts, start)
		}
		if started != "" {
			runs = append(runs, started)
		}
	}
	// Recovery, then delivery, then the record's lock: Python's followups_handed order.
	err = run.Change(dir, func(*run.Object) error {
		held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
		if err != nil {
			return err
		}
		defer held.Close()
		return run.Deliver(dir, func(current *run.Object) error {
			current.Set("followup_plan", entries)
			if complete {
				current.Set("followup_runs", runs)
			}
			return nil
		})
	})
	if err != nil {
		return err
	}
	// The whole handoff is durable before a fast fix can deliver any of its lines.
	// A start that fails leaves a queued receipt the tick carries on.
	for _, start := range starts {
		if err := start(); err != nil {
			say(fmt.Sprintf("follow-up could not start: %v", err))
		}
	}
	return nil
}

func followupTaken(state *run.Object, parent, item, check string) (started string, opened bool) {
	for _, dir := range run.Dirs() {
		other, _ := run.Read(dir)
		if other == nil {
			continue
		}
		followup := other.Dict("followup")
		if followup == nil {
			continue
		}
		if followup.Str("run") == parent && followup.Str("text") == item {
			started = filepath.Base(dir)
			opened = true
		}
		if run.Seat(other) == run.Seat(state) && other.Str("repo") == state.Str("repo") && !other.Truthy("repair") &&
			strings.TrimSpace(followup.Str("check")) == strings.TrimSpace(check) && onItsWay(other) {
			opened = true
		}
	}
	return
}

// onItsWay is whether that fix run is still on its way: running, about to, or resuming itself.
func onItsWay(record *run.Object) bool {
	return record.Str("state") == "running" || record.Str("state") == "queued" && record.Truthy("slot_waiting") || run.Going(record, time.Now())
}

// seatLists is the seat state was launched from and its lists, none where it is closed: stopped,
// or holding no record.
func seatLists(state *run.Object) (string, map[string]any, error) {
	session, lists, err := config.ResolveSession(run.Seat(state))
	closed, _ := run.ReadJSON(filepath.Join(config.Home(), "state", "seat-"+session+".json"))
	if err != nil || closed != nil && closed.Truthy("stopped_at") {
		return session, nil, err
	}
	return session, lists, nil
}

// fixers is whether a run can take a seat's line: its lists name executors, or none at all.
func fixers(lists map[string]any) bool {
	workers, ok := lists["workers"].([]any)
	return !ok || len(workers) > 0
}

// mainCheckout is the checkout of repo's repository that owns its plan.
func mainCheckout(repo string) string {
	if common, err := (gitcall.Git{Repo: repo}).Must("rev-parse", "--path-format=absolute", "--git-common-dir"); err == nil {
		common = config.Resolve(common)
		repo = filepath.Dir(common)
		// ak's versioned checkouts share a bare repository; its live checkout owns the plan.
		if common == config.Resolve(filepath.Join(config.Home(), "agentkit.git")) {
			repo = filepath.Join(config.UserHome(), "agentkit")
		}
	}
	return config.Resolve(repo)
}

var followupSite = regexp.MustCompile("([^\\s`*]+):([0-9]+)\\b")

func followupPlace(item string) string {
	if found := followupSite.FindStringSubmatch(item); found != nil {
		return strings.TrimPrefix(found[1], "./") + ":" + cmp.Or(strings.TrimLeft(found[2], "0"), "0")
	}
	return strings.TrimSpace(config.SplitLines(item)[0])
}

// followupTask is a new run directory holding the task of that title, its text body and its
// done-when check, in the repository and target state names.
func followupTask(state *run.Object, title, body, check string) (string, error) {
	if letters := []rune(title); len(letters) > 256 {
		title = string(letters[:255]) + "…"
	}
	id := time.Now().Format("20060102-1504-") + task.Slug(title)
	for n := 1; ; n++ {
		name := id
		if n > 1 {
			name += fmt.Sprintf("-%d", n)
		}
		dir := filepath.Join(run.Runs(), name)
		if err := os.Mkdir(dir, 0o777); os.IsExist(err) {
			continue
		} else if err != nil {
			return "", err
		}
		target := strings.TrimPrefix(cmp.Or(state.Str("target"), state.Str("base")), "origin/")
		text := fmt.Sprintf("---\nrepo: %s\nbase: origin/%s\ntarget: %s\n---\n# %s\n\n%s\n\n## Done when\n```bash\n%s\n```\n",
			state.Str("repo"), target, target, title, body, check)
		if err := os.WriteFile(filepath.Join(dir, "task.md"), []byte(text), 0o666); err != nil {
			return "", err
		}
		return dir, os.WriteFile(filepath.Join(dir, "log.txt"), nil, 0o666)
	}
}
