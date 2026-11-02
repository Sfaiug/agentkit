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

	"agentkit/internal/box"
	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/loop"
	"agentkit/internal/pick"
	"agentkit/internal/run"
	"agentkit/internal/task"
	"agentkit/internal/usage"
)

var namesShard = regexp.MustCompile(`\bAK_SHARD\b`)

// drivable is nil where Go can drive this scratch task's run to its end, else ErrPython, decided
// before anything is written: a model named outright, a pick or a meter Go cannot read as Python
// does, a home with no adapter directory, a host with no box, one with a user manager to place the
// run under, a check that names a suite's share, the checkout a task folder is named for, or a run
// under way that Python's rival check would read.
func drivable(every []string, path string, values map[string]string) error {
	_, rules := pick.Load()
	if values["--exec"] != "" || values["--review"] != "" || !rules || !box.Supported || host.UserManager() ||
		filed(path) || going() || usage.Check() != nil ||
		slices.ContainsFunc(every, func(cmd string) bool { return namesShard.MatchString(cmd) }) {
		return ErrPython
	}
	return nil
}

// drive is the rest of a scratch task's launch: the receipt says what it will deliver, the log
// what Python's preflight says, and the run goes on in a driver of its own, followed here unless
// told --bg.  Its driver, not this process, is what a stop or a signal ends: a terminal that goes
// away leaves the run going.
func drive(dir string, meta map[string]string, cmds []string, flags map[string]bool, unstopped func(func(*run.Object)) error, log func(string) error, out, errOut io.Writer) (int, error) {
	if err := unstopped(func(record *run.Object) {
		run.SetAll(record, "repo", nil, "scratch", true, "no_merge", true, "project", nil)
	}); err != nil {
		return 0, err
	}
	record, err := run.Read(dir)
	if record == nil {
		return 0, cmp.Or(err, errors.New("run.json cannot be read"))
	}
	var every []string
	for _, cmd := range cmds {
		bare, _ := task.SplitOnce(cmd)
		every = append(every, bare)
	}
	lines := []string{}
	for _, key := range []string{"done_when_minutes", "turn_hours", "stall_minutes"} {
		if _, retired := meta[key]; retired {
			lines = append(lines, "ignoring "+key+": the loop watches for silence")
		}
	}
	lines = append(lines, "--- preflight",
		fmt.Sprintf("repo: none (scratch) | base: none | target: %s | merge: %s", cmp.Or(meta["target"], "none"), cmp.Or(meta["merge"], "squash")),
		"delivery: deliver scratch workspace files", "done-when: "+strings.Join(every, " ; "))
	for _, role := range []string{"workers", "reviewers"} {
		if list := record.List(role); list != nil {
			var names []string
			for _, name := range list {
				names = append(names, run.Text(name))
			}
			lines = append(lines, role+": "+strings.Join(names, ", "))
		}
	}
	lines = append(lines, fmt.Sprintf("limits: silence %dm | done-when ceiling %dh | git/gh %ds", run.SilenceMinutes, run.CeilingHours, toolCap),
		"scope: pending", "result: "+filepath.Join(dir, "result.md")+" | log: "+filepath.Join(dir, "log.txt"),
		"notification: none: no orchestrator session launched this run, so nothing is sent; the result is here and in `ak run status`")
	for _, line := range lines {
		if err := log(line); err != nil {
			return 0, err
		}
	}
	info, err := os.Stat(filepath.Join(dir, "log.txt"))
	if err != nil {
		return 0, err
	}
	if err := start(dir, out); errors.Is(err, loop.ErrStopped) {
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
func start(dir string, out io.Writer) error {
	slots, err := holdSlots()
	if err != nil {
		return err
	}
	defer slots.Close()
	return loop.Start(dir, out)
}

// going is whether any run is under way, one Python's rival check may name, or may be.
func going() bool {
	for _, dir := range run.Dirs() {
		if record, err := run.Read(dir); errors.Is(err, run.ErrLoneSurrogate) || record != nil && run.Active(record) {
			return true
		}
	}
	return false
}

// filed is whether the task file stands in a task folder of ~/.agentkit/tasks, which is named for
// a checkout.
func filed(path string) bool {
	tasks := config.Resolve(filepath.Join(config.Home(), "tasks")) + string(filepath.Separator)
	rest, under := strings.CutPrefix(path, tasks)
	return under && strings.ContainsRune(rest, filepath.Separator)
}
