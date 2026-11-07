package tick

import (
	"cmp"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/launch"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/task"
)

const (
	nightEvery   = 3600             // how often a checkout's night is read, Python's nightly.EVERY
	nightCeiling = 60 * time.Second // a read still running then fails
	// The most names a fix run's check takes: a shell line has a limit, more failures than that
	// usually share a cause, and the next night names what is left.
	nightFirst = 100
)

// nights is the night reads row (nightly.tick): each checkout's night read once every nightEvery,
// in state/nightly.json beside the last night a fix run started for. Each keeps its own stamp,
// taken as its read starts: a slow read before it must not shorten its hour. A read that finds
// what Go does not carry leaves the tick to Python there, its checkout unstamped.
func (t *ticking) nights() error {
	checkouts, seen := seat.Checkouts()
	if !seen {
		return errLeft
	}
	path := statePath("nightly.json")
	record := run.NewObject()
	if data, err := os.ReadFile(path); err == nil {
		if value, err := run.DecodeLimited(data); err == nil {
			if read, ok := value.(*run.Object); ok {
				record = read
			}
		}
	}
	// a number is the one stamp the version before kept: every checkout's, until it has its own
	before := record.Get("asked")
	asked, ok := before.(*run.Object)
	if !ok {
		asked = run.NewObject()
	}
	record.Set("asked", asked)
	for i := len(checkouts) - 1; i >= 0; i-- {
		checkout, now, last := checkouts[i], epoch(t.clock()), before
		if asked.Has(checkout) {
			last = asked.Get(checkout)
		}
		if at, ok := run.Num(last); ok && 0 <= now-at && now-at < nightEvery {
			continue
		}
		started, err := t.night(checkout, record.Get(checkout))
		if err != nil {
			return err
		}
		asked.Set(checkout, now)
		if started != "" {
			record.Set(checkout, started)
		}
		if err := replaceFile(path, run.Line(record)); err != nil {
			return err
		}
	}
	return nil
}

// night is the checkout's night once a fix run started for it, handled being the last that did;
// "" for all else, with one line logged where something is wrong (nightly._read).
func (t *ticking) night(checkout string, handled any) (string, error) {
	env := gitcall.ProjectEnv(checkout)
	command := gitcall.DeclaredAt(checkout, rulesRef, "nightly", env...)
	if command == "" {
		return "", nil
	}
	own, err := config.ChildEnv()
	if err != nil {
		return "", err
	}
	name := filepath.Base(checkout)
	answer, why := run.ProjectAnswer(context.Background(), command, checkout, own, nightCeiling, "nightly")
	night, _ := answer.(*run.Object)
	if night == nil {
		night = run.NewObject()
	}
	passed, read := night.Get("passed").(bool)
	if !oneLine(night.Get("started")) || !read {
		t.log.line(fmt.Sprintf("WARN %s: its night is unread: %s", name, cmp.Or(why, "no usable JSON")))
		return "", nil
	}
	started := night.Str("started")
	if passed || handled == any(started) {
		return "", nil
	}
	var names []string
	failed, _ := night.Get("failed").([]any)
	for _, each := range failed {
		if oneLine(each) {
			names = append(names, strings.TrimFunc(each.(string), config.Space))
		}
	}
	tests := gitcall.DeclaredAt(checkout, rulesRef, "tests", env...)
	var fix string
	switch {
	case names == nil:
		err = errors.New("no failures named")
	case tests == "":
		err = errors.New("no tests: to check a fix by")
	default:
		fix, err = nightFix(checkout, started, names, tests)
	}
	if errors.Is(err, launch.ErrPython) {
		return "", errLeft
	}
	if err != nil {
		t.log.line(fmt.Sprintf("WARN %s: no fix run for its night %s: %s", name, started, config.PyError(err)))
		return "", nil
	}
	t.log.line(fmt.Sprintf("%s: its night %s failed; %s fixes it", name, started, fix))
	return started, nil
}

// oneLine is whether a night's value can stand as one line of a task, or of the file of names.
func oneLine(value any) bool {
	text, ok := value.(string)
	return ok && len(config.SplitLines(strings.TrimFunc(text, config.Space))) == 1
}

// nightFix writes the night's fix task and the file of names its done-when exports as AK_ONLY,
// the contract a red piece's retry uses, and starts its run on no seat (launch.Night); the run's
// id.  Both files are named for a hash of what the night says, so a read writing them, refused or
// not, never changes a running fix's list.
func nightFix(checkout, started string, names []string, tests string) (string, error) {
	said := []any{}
	for _, name := range names {
		said = append(said, name)
	}
	held := sha256.Sum256([]byte(run.Line([]any{started, said})))
	path := filepath.Join(config.Home(), "tasks", filepath.Base(checkout), "night-"+hex.EncodeToString(held[:])[:16]+".md")
	only := strings.TrimSuffix(path, ".md") + ".names"
	listed := ""
	for _, name := range names {
		listed += "- " + name + "\n"
	}
	text := fmt.Sprintf("---\nrepo: %s\n---\n# Fix the tests %s's last night failed\n\n"+
		"The night %s failed these tests:\n\n%s\n"+
		"The command below runs the first %d at most; the next night names what is left.\n\n"+
		"%s\n\n## Done when\n```bash\nexport AK_ONLY=%s; %s\n```\n",
		checkout, filepath.Base(checkout), started, listed, nightFirst, task.FixTheCommand,
		commandhelp.ShellJoin([]string{only}), tests)
	for _, step := range []func() error{
		func() error { return os.MkdirAll(filepath.Dir(path), 0o777) },
		func() error { return replaceFile(only, strings.Join(names[:min(len(names), nightFirst)], "\n")+"\n") },
		func() error { return os.WriteFile(path, []byte(text), 0o666) },
	} {
		if err := step(); err != nil {
			return "", err
		}
	}
	return launch.Night(path, run.Fields("night", started, "repo", checkout))
}
