package handin

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

// proofsPass refuses a fixer's done while an earlier finding's proof still fails, as Python's
// check_fixer_proofs: each handed finding with a command, at a site no dispute of this turn names,
// runs again in the checkout under a worker's limits.  One that cannot run or finish is a note, no
// refusal.  beside is where its output is spooled, outside the checkout.
func (t *turn) proofsPass(beside string) error {
	disputed := map[string]bool{}
	for _, record := range t.records {
		if kind := record.Str("kind"); !record.Has("kind") || kind == "dispute" && !sited(record) {
			return ErrPython
		} else if kind == "dispute" {
			disputed[site(record)] = true
		}
	}
	handed, err := t.handed()
	if err != nil {
		return err
	}
	workspace, ok := t.workspace.(string)
	if !ok {
		return ErrPython
	}
	var failed []string
	for _, finding := range handed {
		evidence := finding.Dict("evidence")
		if evidence == nil {
			return ErrPython
		}
		if !evidence.Truthy("run") || disputed[site(finding)] {
			continue
		}
		command, ok := evidence.Get("run").(string)
		if !ok {
			return ErrPython
		}
		said, err := stillFails(command, workspace, beside)
		if err != nil {
			return err
		}
		if said != "" {
			failed = append(failed, site(finding)+" - "+finding.Str("what")+" "+said)
		}
	}
	if len(failed) == 0 {
		return nil
	}
	return errors.New("done refused: earlier findings still fail:\n" + strings.Join(failed, "\n") +
		"\nFix the code or dispute the finding with `ak hand-in dispute path:line \"why\" --run COMMAND` whose command exits 0.")
}

// stillFails is how a proof failed, its exit and the last of what it said, "" where it did not:
// the fixer already has its checkout and sandbox, so its uncommitted fix is never reset.
func stillFails(command, workspace, beside string) (string, error) {
	cache, err := os.MkdirTemp(beside, "")
	if err != nil {
		return "", ErrPython
	}
	defer os.RemoveAll(cache)
	spool, err := os.CreateTemp(cache, "")
	if err != nil {
		return "", ErrPython
	}
	defer spool.Close()
	ctx, watched := host.Watch{Silence: run.SilenceMinutes * time.Minute, Ceiling: run.CeilingHours * time.Hour,
		Heard: host.Written(spool.Name()), Declared: host.Declared(os.Getenv(host.Marker))}.Stop(context.Background())
	cmd := exec.CommandContext(ctx, "bash", "-c", command)
	stop := host.Group(cmd)
	cmd.Dir, cmd.Stdout, cmd.Stderr = workspace, spool, spool
	cmd.Env = append(withoutTurn(), "PYTHONPYCACHEPREFIX="+cache)
	failure := cmd.Run()
	killed := watched() != ""
	if cmd.ProcessState == nil {
		// it never started, which shows nothing: bash or the checkout gone or forbidden
		if errors.Is(failure, fs.ErrNotExist) || errors.Is(failure, fs.ErrPermission) {
			return "", nil
		}
		return "", ErrPython
	}
	stop()
	code := exitOf(cmd)
	if !ProofFailed(run.Fields("returncode", code, "killed", killed)) {
		return "", nil
	}
	output, err := excerpt(spool)
	if err != nil {
		return "", err
	}
	lines := config.SplitLines(output)
	return fmt.Sprintf("[exit %d]\n%s", code, strings.Join(lines[max(0, len(lines)-10):], "\n")), nil
}
