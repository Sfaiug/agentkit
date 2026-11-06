package plan

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

const (
	proven       = 14 * 24 * time.Hour // on for everyone this long, a switch is proven: Python's retire.PROVEN
	featuresWait = 20 * time.Second    // the longest a features `list` is waited for: Python's menu.FEATURES_WAIT
)

// unproven refuses the check Python's retirement writes for a proven switch while the project's
// switch list dates that proof in the future, as Python's retire.vet_check does: ak plans that
// line itself once the switch is proven, so a seat never holds work only time can finish.
func unproven(ctx context.Context, checkout, check string) error {
	words, ok := commandhelp.ShellSplit(check)
	if !ok || len(words) < 2 || words[len(words)-1] != "proven" {
		return nil
	}
	id := words[len(words)-2]
	if check != `python3 -c "import sys; sys.path.insert(0, `+commandhelp.Quote(config.Repo())+
		`); from agentkit import retire; retire.check_main()" `+commandhelp.ShellJoin([]string{id})+" proven" {
		return nil
	}
	for _, row := range switches(ctx, checkout) {
		if at, ok := since(row); ok && run.Text(row.Get("id")) == id && time.Since(at) < proven {
			return fmt.Errorf("%s's switch %s is not yet proven; ak plans this line itself into a seat at work once it "+
				"is proven on %s; the seat holds no line for it before then",
				filepath.Base(checkout), id, at.Add(proven).UTC().Format(time.DateOnly))
		}
	}
	return nil
}

// since is when the row last went on for everyone, as Python's retire.since reads it: its
// `everyone` true and its `everyone_since` a date, each Z in it +00:00.
func since(row *run.Object) (time.Time, bool) {
	stamp, ok := row.Get("everyone_since").(string)
	if row.Get("everyone") != true || !ok {
		return time.Time{}, false
	}
	return fromISO(strings.ReplaceAll(stamp, "Z", "+00:00"))
}

// switches is the rows with an id the checkout's features `list` answers, as Python's
// menu.features_run and menu.switch_rows read them: its own command, carrying no seat's name, in
// a session of its own, killed with all it started past featuresWait.  None where AGENTS.md
// names no command, or the command fails or answers no list.
func switches(ctx context.Context, checkout string) []*run.Object {
	command := gitcall.Declared(checkout, "features")
	env, err := config.ChildEnv()
	if command == "" || err != nil {
		return nil
	}
	limited, cancel := context.WithTimeout(ctx, featuresWait)
	defer cancel()
	cmd := exec.CommandContext(limited, "/bin/sh", "-c", command+" list")
	var out bytes.Buffer
	cmd.Dir, cmd.Stdout, cmd.WaitDelay = checkout, &out, time.Second // a child left holding the answer is not waited for
	cmd.Env = slices.DeleteFunc(env, func(pair string) bool { return strings.HasPrefix(pair, "AGENTKIT_SESSION=") })
	host.Group(cmd)
	if cmd.Run() != nil {
		return nil
	}
	answer, _ := run.Decode([]byte(gitcall.Decoded(out.String())))
	list, _ := answer.([]any)
	var rows []*run.Object
	for _, each := range list {
		if row, ok := each.(*run.Object); ok && row.Has("id") {
			rows = append(rows, row)
		}
	}
	return rows
}
