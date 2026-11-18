package run

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
)

// group is how a project's command runs in a session of its own and is stopped (host.Group), and
// reap how its shell is found ended and reaped (host.Reap): variables, so a test records both.
var group, reap = host.Group, host.Reap

// ProjectAnswer is a project's own command's JSON answer, as Python's gitcall.project_answer
// reads it (ProjectOutput): read as Python reads it, so an id is the text Python's str() makes
// of it, or nil and the one line saying why, calling it what.
func ProjectAnswer(ctx context.Context, command, checkout string, env []string, wait time.Duration, what string) (any, string) {
	out, why := ProjectOutput(ctx, command, checkout, env, wait, what)
	if why != "" {
		return nil, why
	}
	answer, err := Decode(out)
	if err != nil {
		return nil, what + " answered no JSON"
	}
	return answer, ""
}

// ProjectOutput is what a project's own command printed in its checkout, run in env as Python's
// gitcall.project_answer runs it, and decoded as Python decodes it; or nil and the one line saying
// why it answered nothing, calling it what.  It reads nothing, so an ssh in it never reads the
// keys, and carries no seat's name (owner_env), so it is never a seat reaching the live host.  It
// runs in a session of its own and has answered once its output has ended and a look finds its
// shell ended, the last look at or past wait or ctx's end; one that has not is killed with
// everything it started, so a `set` said to have failed never lands after.
func ProjectOutput(ctx context.Context, command, checkout string, env []string, wait time.Duration, what string) ([]byte, string) {
	noAnswer := fmt.Sprintf("%s: no answer in %d s", what, wait/time.Second)
	// the deadline is read by the clock too: ctx's own timer can fire late on a loaded host
	deadline := time.Now().Add(wait)
	if end, ok := ctx.Deadline(); ok && end.Before(deadline) {
		deadline = end
	}
	passed := func() bool { return ctx.Err() != nil || !time.Now().Before(deadline) }
	// the shell reads what to run, the command as `/bin/sh -c` with nothing to read, from ak only once
	// ak has seen it start before the deadline, as starting can take past it
	cmd := exec.Command("/bin/sh", "-s", "--", command)
	cmd.Dir = checkout
	cmd.Env = env
	// what exec would run it in (a nil env being ak's own, at the checkout as named), less the seat
	cmd.Env = slices.DeleteFunc(cmd.Environ(), func(pair string) bool { return strings.HasPrefix(pair, "AGENTKIT_SESSION=") })
	stop := group(cmd)
	cmd.Cancel = nil // exec stops nothing: the stop is this goroutine's, and comes before the reap
	scriptR, scriptW, err := os.Pipe()
	if err != nil {
		return nil, what + ": " + config.PyError(err)
	}
	defer scriptR.Close()
	defer scriptW.Close()
	outR, outW, err := os.Pipe()
	if err != nil {
		return nil, what + ": " + config.PyError(err)
	}
	defer outR.Close()
	defer outW.Close()
	saidR, saidW, err := os.Pipe()
	if err != nil {
		return nil, what + ": " + config.PyError(err)
	}
	defer saidR.Close()
	defer saidW.Close()
	cmd.Stdin, cmd.Stdout, cmd.Stderr = scriptR, outW, saidW
	if passed() {
		return nil, noAnswer
	}
	err = cmd.Start()
	// the shell's ends go from ak: the output ends once the command and all it started close theirs
	scriptR.Close()
	outW.Close()
	saidW.Close()
	if err != nil {
		return nil, what + ": " + config.PyError(err)
	}
	// a helper reads the output to its end, each holder having closed it, so this goroutine alone
	// stops the session and reaps the shell, the stop always first
	var out, said bytes.Buffer
	read := make(chan struct{})
	go func() {
		saying := make(chan struct{})
		go func() { said.ReadFrom(saidR); close(saying) }()
		out.ReadFrom(outR)
		<-saying
		close(read)
	}()
	// the deadline seen first is no answer, whatever the output does after: a shell started past it
	// is never told what to run
	ended, code := false, 0
	if !passed() {
		io.WriteString(scriptW, `exec /bin/sh -c "$1" </dev/null`)
		scriptW.Close()
		select {
		case <-ctx.Done():
		case <-time.After(time.Until(deadline)):
		case <-read:
			// The shell is looked at until a look finds it ended, which reaps it, or one begun at or
			// past the deadline finds it running: one ending between the deadline and that last look
			// has answered, as with Python's subprocess timeout.
			for {
				last := passed()
				if ended, code, err = reap(cmd, false); ended || last {
					break
				}
				time.Sleep(5 * time.Millisecond)
			}
		}
	}
	if !ended {
		stop()
		reap(cmd, true)
		return nil, noAnswer
	}
	switch {
	case err != nil:
		return nil, what + ": " + config.PyError(err)
	case code != 0:
		if lines := config.SplitLines(gitcall.Strip(said.String())); len(lines) > 0 {
			return nil, lines[len(lines)-1]
		}
		return nil, fmt.Sprintf("%s exited %d", what, code)
	}
	return []byte(gitcall.Decoded(out.String())), ""
}
