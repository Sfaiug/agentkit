package handin

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

// proofsPass refuses a fixer's done while an earlier finding's proof still fails, as Python's
// check_fixer_proofs: each handed finding with a command, at a site no dispute of this turn names,
// runs again in the checkout (failedChecks).  One that cannot run or finish is a note, no refusal.
// beside is where its output is spooled, outside the checkout.
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
	var named [][2]string
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
		named = append(named, [2]string{site(finding) + " - " + finding.Str("what"), command})
	}
	failed, err := t.failedChecks(named, beside)
	if err != nil || len(failed) == 0 {
		return err
	}
	return errors.New("done refused: earlier findings still fail:\n" + strings.Join(failed, "\n") +
		"\nFix the code or dispute the finding with `ak hand-in dispute path:line \"why\" --run COMMAND` whose command exits 0.")
}

// stillFails is how a check failed, its exit and the last of what it said, "" where it did not,
// run by timeout for left at most, each silence of that long ending it too: the builder already
// has its checkout and sandbox, so its uncommitted work is never reset.  The bound it declares
// holds the turn's silence, never its own.
func stillFails(timeout, command, workspace, beside string, left, silence time.Duration) (string, error) {
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
	ctx, watched := host.Watch{Silence: silence, Ceiling: left, Heard: host.Written(spool.Name())}.Stop(context.Background())
	began := time.Now()
	cmd := exec.CommandContext(ctx, timeout, "-s", "KILL", strconv.FormatFloat(left.Seconds(), 'f', -1, 64), "bash", "-c", command)
	stop := host.Group(cmd)
	cmd.Dir, cmd.Stdout, cmd.Stderr = workspace, spool, spool
	cmd.Env = append(withoutTurn(), "PYTHONPYCACHEPREFIX="+cache)
	failure := cmd.Run()
	// timeout's own kill at the bound comes before the watch's next look: an end there is a stop
	killed := watched() != "" || time.Since(began) >= left
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
