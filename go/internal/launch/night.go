package launch

import (
	"cmp"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// nightFirst is the most names a night's fix run's check takes: a shell line has a limit, more
// failures than that usually share a cause, and the next night names what is left.
const nightFirst = 100

// Night starts the fix run of a checkout's failed night, Python's nightly._start: none where its
// task is refused as written (Refusal) or a run of it is under way (the launch's own check), else
// one launched on no seat, bound to the marked executors, else the orchestrator, and to the marked
// reviewers.  Its task names the failed tests, and its done-when exports a file of the first
// nightFirst of them as AK_ONLY, the contract a red piece's retry uses, before the project's
// tests; both are named for a hash of what the night says, so a read writing them, refused or
// not, never changes a running fix's list.  The run's id, or why none started; ErrPython, with
// nothing written, for a launch Go leaves to Python.
func Night(checkout, started string, names []string, tests string) (string, error) {
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
	meta, cmds, err := task.Parse(path, text)
	if err != nil {
		return "", err
	}
	if why, err := Refusal(path, meta, cmds); err != nil || why != "" {
		return "", cmp.Or(err, errors.New(why))
	}
	marked, err := config.Defaults()
	bound, unbound := config.Bind()
	if err != nil || unbound != nil {
		return "", ErrPython
	}
	workers, reviewers := marked.Workers, marked.Reviewers
	if len(workers) == 0 {
		workers = []string{marked.Orchestrator}
	}
	if reviewers == nil {
		reviewers = workers
	}
	bound.Workers, bound.Reviewers = nil, nil
	for _, name := range workers {
		bound.Workers = append(bound.Workers, name)
	}
	for _, name := range reviewers {
		bound.Reviewers = append(bound.Reviewers, name)
	}
	at := launcher{bound: bound, origin: run.Fields("night", started, "repo", checkout),
		files: [][2]string{{only, strings.Join(names[:min(len(names), nightFirst)], "\n") + "\n"}, {path, text}}}
	dir, _, why, err := at.launch(path, text, nil, map[string]bool{"--bg": true}, io.Discard, io.Discard)
	if err == nil && why != "" {
		err = errors.New(why)
	}
	if err != nil {
		return "", err
	}
	return filepath.Base(dir), nil
}

// write puts the tick's task files in place, each whole at once as Python's replace_file writes
// them, so no check reading a list reads half of one.
func (l launcher) write() error {
	for _, file := range l.files {
		if err := os.MkdirAll(filepath.Dir(file[0]), 0o777); err != nil {
			return err
		}
		tmp := fmt.Sprintf("%s.%d.tmp", file[0], os.Getpid())
		if err := os.WriteFile(tmp, []byte(file[1]), 0o666); err != nil {
			return err
		}
		if err := os.Rename(tmp, file[0]); err != nil {
			return err
		}
	}
	return nil
}

// unstaffed is why no pair of the bound lists, as a run held to these numbers picks (staffing), can
// run here, "" where one can.
func unstaffed(bound config.Binding, numbers config.Numbers) string {
	rules, ok := staffing(bound, numbers)
	if !ok {
		return ""
	}
	return loop.Unstaffed(rules)
}
