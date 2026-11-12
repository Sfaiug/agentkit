package logins

import (
	"bytes"
	"context"
	"errors"
	"os/exec"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
)

const authCap = 20 * time.Second // the `auth` verb reads a file; one still silent after this is not answering

// Auth is what the adapter's `auth` verb says of the login env names, as Python's
// worker.auth_ok reads it: answered where it said one line exiting 0 or 1, yes for 0, and that
// line. The seat's probe adds "seat" to ask about its interactive login.
func Auth(adapter string, env []string, args ...string) (answered, yes bool, line string) {
	ctx, cancel := context.WithTimeout(context.Background(), authCap)
	defer cancel()
	var stdout, stderr bytes.Buffer
	cmd := exec.CommandContext(ctx, adapter, append([]string{"auth"}, args...)...)
	// A stdin closed at once: asking opens no file of its own on a machine watching for that.
	cmd.Env, cmd.Stdin, cmd.Stdout, cmd.Stderr, cmd.WaitDelay = env, strings.NewReader(""), &stdout, &stderr, time.Second
	host.AdapterCall(cmd)
	if err := cmd.Run(); err != nil && !errors.As(err, new(*exec.ExitError)) {
		return false, false, ""
	}
	var lines []string
	for _, line := range config.SplitLines(stdout.String() + stderr.String()) {
		if line = strings.TrimFunc(line, config.Space); line != "" {
			lines = append(lines, line)
		}
	}
	if code := cmd.ProcessState.ExitCode(); len(lines) == 1 && (code == 0 || code == 1) {
		return true, code == 0, lines[0]
	}
	return false, false, ""
}
