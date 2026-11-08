package update

import (
	"bytes"
	"context"
	"errors"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
)

// prepare readies the version checked out at dir to run, as Python's versions.switch has its
// `install.sh --prepare` run there by versions.run: what it said, decoded as Python decodes it and
// stripped, and its exit code, 1 where it could not start or ran past stepCap.  Every seat's hooks
// and the tick run ~/agentkit/bin/ak, and Go's is built from go/, which git does not track, so a
// version goes live ready.  Its stdin is empty, and it runs in a session of its own that goes
// whole past the cap or at a ^C to ak, which that session keeps from reaching it: a build left
// running would go on writing in the version removed for it.
func prepare(env []string, dir string) (string, int) {
	argv := []string{filepath.Join(dir, "install.sh"), "--prepare"}
	interrupted, heard := signal.NotifyContext(context.Background(), os.Interrupt)
	defer heard()
	ctx, cancel := context.WithTimeout(interrupted, stepCap)
	defer cancel()
	command := exec.CommandContext(ctx, argv[0], argv[1:]...)
	var out, errOut bytes.Buffer
	command.Dir, command.Env, command.Stdout, command.Stderr = dir, env, &out, &errOut
	// a program it left holding its output open is waited for no longer than the cap
	command.WaitDelay = stepCap
	host.Group(command)
	err := command.Run()
	if interrupted.Err() != nil {
		heard() // its prepare gone, the ^C goes on to end ak as it would have
		if self, err := os.FindProcess(os.Getpid()); err == nil {
			self.Signal(os.Interrupt)
		}
	}
	var exited *exec.ExitError
	code := 0
	switch {
	case err != nil && ctx.Err() != nil:
		return failure(ctx.Err(), argv, stepCap), 1
	case errors.As(err, &exited):
		code = returncode(exited)
	case err != nil:
		return config.PyError(err), 1
	}
	return strings.TrimFunc(gitcall.Decoded(out.String())+gitcall.Decoded(errOut.String()), config.Space), code
}
