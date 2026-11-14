package handback

import (
	"cmp"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"agentkit/internal/commandhelp"
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
// An item with no command the plan can check starts a run proven by a regression test of its own.
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
	runs, entries := []any{}, []any{}
	var starts []func() error
	commits := cmp.Or(state.Dict("followup_commits"), run.NewObject())
	for _, value := range state.List("followups") {
		item := run.Text(value)
		check := followupCheck(state, item)
		started, opened := followupTaken(state, filepath.Base(dir), item, check)
		var start func() error
		if fixers && started == "" && !opened {
			followup := run.Fields("run", filepath.Base(dir), "text", item, "place", followupPlace(item))
			origin, body := run.Fields("followup", followup, "repo", repo), item+"\n\n"+task.FixTheCommand
			if check != "" {
				followup.Set("check", check)
			} else { // proven by the regression.sh its executor writes, not by its checks on base
				origin.Set("base_proof", "regression.sh")
				body = item
			}
			var child string
			child, err = followupTask(state, "Fix "+config.SplitLines(item)[0], body, check)
			if err == nil {
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
		if start != nil {
			starts = append(starts, start)
		}
		if started != "" {
			runs = append(runs, started)
		}
		if check == "" { // a plan line is checked by its command
			continue
		}
		outcome := "Fix " + strings.ReplaceAll(config.SplitLines(item)[0], "·", "-")
		line, refused := plan.AddProven(context.Background(), session, repo, outcome, check,
			cmp.Or(commits.Str(item), state.Str("base_sha")), opened)
		entry := run.Fields("outcome", outcome, "deferred", plan.Deferred(line))
		if refused != nil {
			entry = run.Fields("outcome", outcome, "refused", refused.Error())
		}
		entries = append(entries, entry)
	}
	// Recovery, then delivery, then the record's lock: Python's followups_handed order.
	err = run.Change(dir, func(*run.Object) error {
		held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
		if err != nil {
			return err
		}
		defer held.Close()
		return run.Deliver(dir, func(current *run.Object) error {
			run.SetAll(current, "followup_plan", entries, "followup_runs", runs)
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

// followupCheck is the failing command the review gave a follow-up, "" for none.
func followupCheck(record *run.Object, item string) string {
	return strings.TrimFunc(cmp.Or(record.Dict("followup_checks"), run.NewObject()).Str(item), config.Space)
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
		// a follow-up with no check has no command to name its fix by, so its site does
		same := strings.TrimSpace(followup.Str("check")) == strings.TrimSpace(check)
		if check == "" {
			same = followup.Str("run") != parent && followupPlace(followup.Str("text")) == followupPlace(item)
		}
		if run.Seat(other) == run.Seat(state) && other.Str("repo") == state.Str("repo") && !other.Truthy("repair") &&
			same && onItsWay(other) {
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

// followupPlace is a follow-up's site, whatever its wording: the path it begins with, every
// character as written, and its line, so `beta app/api.py:1`, `beta*/api.py:1` and
// `*alpha/api.py:1` are not `alpha...`'s.  It reads Python's `.+?:\d+\b` by hand, with Unicode's
// digits and word characters, which Go's regexp reads as ASCII's alone: a Greek letter after a
// path's `pkg:1` keeps the path whole.  Each program reads Unicode in its own version (Go's
// toolchain's; Python 3.11's is 14.0, 3.13's 15.1), and the two part only on characters the older
// one has not assigned yet.
func followupPlace(item string) string {
	line, _, _ := strings.Cut(item, "\n")
	for at, letter := range line {
		if letter != ':' || at == 0 {
			continue
		}
		rest := line[at+1:]
		digits := strings.IndexFunc(rest, func(r rune) bool { return !unicode.IsDigit(r) })
		if digits == -1 {
			digits = len(rest)
		}
		next, _ := utf8.DecodeRuneInString(rest[digits:])
		if digits > 0 && (digits == len(rest) || next != '_' && !unicode.IsLetter(next) && !unicode.IsNumber(next)) {
			return line[:at+1+digits]
		}
	}
	return strings.TrimSpace(config.SplitLines(item)[0])
}

// regressionTask is what a fix run with no check is told, of the runs, its seat, its repository,
// its own run and its regression.sh.
const regressionTask = "Your checkout starts on the target branch's tip, fetched when this run started: first check " +
	"that this defect still exists there. Inspect %s for another open run of session %s fixing this site in %s; " +
	"exclude this run (%s). If the defect is gone or another open run is fixing it, run " +
	"`ak hand-in not-needed \"<why>\"`, with no edits or PR. Otherwise fix it with a regression test: show it " +
	"failing before the fix and passing afterwards, and include both outputs in your summary. You may write %s " +
	"outside the checkout to run that test from the checkout; the loop runs it as a check. If only the owner can " +
	"decide, run `ak hand-in blocked \"<question>\"`."

// followupTask is a new run directory holding the task of that title, its text body and its
// done-when check, in the repository and target state names.  With no check, the run's executor
// writes one: a regression test in the run's own folder (run.Regression).
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
		if check == "" {
			script := run.Regression(dir)
			if err := os.Mkdir(filepath.Dir(script), 0o777); err != nil {
				return "", err
			}
			body += "\n\n" + fmt.Sprintf(regressionTask, filepath.Join(run.Runs(), "*", "run.json"), run.Seat(state),
				state.Str("repo"), name, script)
			check = "bash " + commandhelp.ShellJoin([]string{script})
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
