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
	stop := host.Group(command)
	if err := command.Start(); err != nil {
		return config.PyError(err), 1
	}
	// Wait goes on until its output closes, past its exit, as Python's communicate reads it
	waited := make(chan error, 1)
	go func() { waited <- command.Wait() }()
	var err error
	select {
	case err = <-waited:
	case <-ctx.Done():
	}
	if ctx.Err() != nil { // the cap or a ^C, however far it got: what still holds its output goes too
		stop()
		if interrupted.Err() != nil {
			heard() // its prepare gone, the ^C goes on to end ak as it would have
			if self, err := os.FindProcess(os.Getpid()); err == nil {
				self.Signal(os.Interrupt)
			}
		}
		return failure(ctx.Err(), argv, stepCap), 1
	}
	var exited *exec.ExitError
	code := 0
	switch {
	case errors.As(err, &exited):
		code = returncode(exited)
	case err != nil:
		return config.PyError(err), 1
	}
	return strings.TrimFunc(gitcall.Decoded(out.String())+gitcall.Decoded(errOut.String()), config.Space), code
}
