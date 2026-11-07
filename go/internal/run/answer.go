package run

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os/exec"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
)

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
// runs in a session of its own, and one past wait, or running when ctx ends, is killed with
// everything it started, so a `set` said to have failed never lands after.
func ProjectOutput(ctx context.Context, command, checkout string, env []string, wait time.Duration, what string) ([]byte, string) {
	ctx, cancel := context.WithTimeout(ctx, wait)
	defer cancel()
	cmd := exec.CommandContext(ctx, "/bin/sh", "-c", command)
	cmd.Dir, cmd.WaitDelay = checkout, wait // one gone to a session of its own is let go of then
	cmd.Env = slices.DeleteFunc(slices.Clone(env), func(pair string) bool { return strings.HasPrefix(pair, "AGENTKIT_SESSION=") })
	var out, said bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &said
	stop := host.Group(cmd)
	err := cmd.Start()
	if err == nil {
		// past the wait its session goes, even once the shell is gone: what it started may still
		// hold the output open, and exec stops watching the deadline when the shell exits
		defer context.AfterFunc(ctx, stop)()
		err = cmd.Wait()
	}
	var exit *exec.ExitError
	switch {
	case ctx.Err() != nil:
		return nil, fmt.Sprintf("%s: no answer in %d s", what, wait/time.Second)
	case errors.As(err, &exit):
		if lines := config.SplitLines(gitcall.Strip(said.String())); len(lines) > 0 {
			return nil, lines[len(lines)-1]
		}
		return nil, fmt.Sprintf("%s exited %d", what, exit.ExitCode())
	case err != nil:
		return nil, what + ": " + config.PyError(err)
	}
	return []byte(gitcall.Decoded(out.String())), ""
}
