package update

import (
	"bytes"
	"cmp"
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
	command.Dir, command.Env = dir, env
	stop := host.Group(command)
	stdout, err := command.StdoutPipe()
	stderr, unpiped := command.StderrPipe()
	if err = cmp.Or(err, unpiped); err == nil {
		err = command.Start()
	}
	if err != nil {
		return config.PyError(err), 1
	}
	// the cap holds until its output closes, as Python's communicate reads it, and then all of its
	// session goes, and what it started elsewhere that still holds that open is read no further
	killed := make(chan struct{})
	ended := context.AfterFunc(ctx, func() {
		defer close(killed)
		stop()
		stdout.Close()
		stderr.Close()
	})
	var out, errOut bytes.Buffer
	read := make(chan struct{})
	go func() { errOut.ReadFrom(stderr); close(read) }() // both at once: either can fill first
	out.ReadFrom(stdout)
	<-read
	err = command.Wait()
	if !ended() { // the cap or a ^C, however far it got
		<-killed
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
