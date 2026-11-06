package launch

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/loop"
	"agentkit/internal/pick"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/task"
	"agentkit/internal/usage"
)

var namesShard = regexp.MustCompile(`\bAK_SHARD\b`)

// drivable is nil where Go can drive this task's run to its end, else ErrPython, decided
// before anything is written: a reviewer named outright, an executor no worker of its groups, a
// pick Go cannot read as Python does, a meter it cannot read or a home with no adapter directory unless nobody could run there anyway, a host
// with no box, one with a user manager to place the run under, or a turn on one of a provider's
// several accounts unless the run parks at its pick before any.
func drivable(values map[string]string, bound config.Binding) error {
	executors, reviewers := names(bound.Workers), names(bound.Reviewers)
	rules, ok := pick.Within(executors, reviewers)
	named := values["--exec"]
	if named != "" && !slices.Contains(executors, named) || values["--review"] != "" || !ok || !placed() ||
		usage.Check() != nil && !loop.Unstaffed(rules) || accountTurns() && !loop.Parks(rules, named) {
		return ErrPython
	}
	return nil
}

// names is a bound list as the picks read it, nil for none.
func names(list []any) (found []string) {
	for _, name := range list {
		found = append(found, name.(string))
	}
	return found
}

// drive is the rest of a launch: the receipt says what it will deliver, the log what Python's
// preflight says, and the run goes on in a driver of its own, followed here unless told --bg.  Its
// driver is what a stop ends; a foreground one shares this process's group, so a terminal that goes
// away takes the run with it, leaving a dead loop for `ak run resume`.
func drive(dir string, meta map[string]string, at place, warning string, flags map[string]bool, seated string, unstopped func(func(*run.Object)) error, log func(string) error, out, errOut io.Writer) (int, error) {
	title := ""
	if err := unstopped(func(record *run.Object) {
		title = record.Str("title")
		var project any
		if at.project != "" {
			project = at.project
		}
		record.Set("policy", run.Fields(at.numbers.Said()...)) // a scratch run's too, as Python's prepare
		if at.repo == "" {
			run.SetAll(record, "repo", nil, "scratch", true, "no_merge", true, "project", project)
			return
		}
		run.SetAll(record, "repo", at.repo, "scratch", false, "no_merge", flags["--no-merge"], "project", project)
	}); err != nil {
		return 0, err
	}
	if seated != "" {
		// filed under the project most of its runs belong to, this one now among them
		if err := seat.JoinProject(seated); err != nil {
			return 0, err
		}
	}
	lines := []string{}
	if warning != "" {
		lines = append(lines, warning)
	}
	for _, key := range []string{"done_when_minutes", "turn_hours", "stall_minutes"} {
		if _, retired := meta[key]; retired {
			lines = append(lines, "ignoring "+key+": the loop watches for silence")
		}
	}
	commands := strings.Join(at.every, " ; ")
	if len(at.once) > 0 {
		if commands != "" {
			commands += " ; "
		}
		commands += "once: " + strings.Join(at.once, " ; ")
	}
	said, base, target := "none (scratch)", "none", cmp.Or(meta["target"], "none")
	delivery := "deliver scratch workspace files"
	if at.repo != "" {
		said, base, target = at.repo, at.base, at.target
		delivery = "no push or merge; local commits"
		if !flags["--no-merge"] {
			branch := "new ak/" + task.Slug(title) + " branch (unique suffix if needed)"
			if flags["--no-worktree"] {
				head, _, _, err := git(at.repo, "rev-parse", "--abbrev-ref", "HEAD")
				if err != nil {
					return 0, err
				}
				branch = head
			}
			delivery = fmt.Sprintf("push %s to origin (fork if needed); PR into %s; merge after PASS", branch, target)
		}
	}
	lines = append(lines, "--- preflight")
	if at.alongside != "" {
		lines = append(lines, "--- preflight: started alongside "+at.alongside+" (--anyway)")
	}
	lines = append(lines,
		fmt.Sprintf("repo: %s | base: %s | target: %s | merge: %s", said, base, target, cmp.Or(meta["merge"], "squash")),
		"delivery: "+delivery, "done-when: "+commands)
	notification := "notification: none: no orchestrator session launched this run, so nothing is sent; the result is here and in `ak run status`"
	if seated != "" {
		notification = "notification: " + seated + "; dead-seat fallback: needs to Discord if that seat is gone at the end (stderr if unconfigured)"
	}
	return underWay(dir, lines, notification, flags, log, out, errOut)
}

// underWay says the rest of what a launch's log says, and the run goes on in a driver of its own,
// followed here unless told --bg.
func underWay(dir string, lines []string, notification string, flags map[string]bool, log func(string) error, out, errOut io.Writer) (int, error) {
	record, err := run.Read(dir)
	if record == nil {
		return 0, cmp.Or(err, errors.New("run.json cannot be read"))
	}
	for _, role := range []string{"workers", "reviewers"} {
		if list := record.List(role); list != nil {
			var names []string
			for _, name := range list {
				names = append(names, run.Text(name))
			}
			lines = append(lines, role+": "+strings.Join(names, ", "))
		}
	}
	lines = append(lines, fmt.Sprintf("limits: silence %dm | done-when ceiling %dh | git/gh %ds", run.SilenceMinutes, run.CeilingHours, gitcall.CapSeconds),
		"scope: pending", "result: "+filepath.Join(dir, "result.md")+" | log: "+filepath.Join(dir, "log.txt"), notification)
	for _, line := range lines {
		if err := log(line); err != nil {
			return 0, err
		}
	}
	info, err := os.Stat(filepath.Join(dir, "log.txt"))
	if err != nil {
		return 0, err
	}
	if err := start(dir, out, flags["--bg"]); errors.Is(err, loop.ErrStopped) {
		io.WriteString(out, "stopped "+filepath.Base(dir)+"\n")
		return 0, ErrStopped
	} else if err != nil {
		return 0, err
	}
	if flags["--bg"] {
		return 0, nil
	}
	return loop.Follow(dir, info.Size(), out, errOut), nil
}

// start hands the launched run its driver, a change to its admission like the receipt's.
func start(dir string, out io.Writer, detached bool) error {
	slots, err := holdSlots()
	if err != nil {
		return err
	}
	defer slots.Close()
	return loop.Start(dir, out, detached)
}
