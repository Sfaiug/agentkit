package harness

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"syscall"

	"agentkit/internal/config"
)

func init() {
	verbs["claude logout"] = claudeLogout
}

// claudeLogout is adapters/claude.sh's `logout`, for the login $AGENTKIT_ACCOUNT names: its worker
// token removed, then, where its credentials file or its Keychain entry is there, Claude Code's own
// sign-out, whose exit is the verb's; 0 at once where neither is.  The sign-out runs with no worker
// token in its environment: it is the login's own, never a token's.
func claudeLogout(_ []string, out, errOut io.Writer) int {
	login, _, err := config.Account("claude")
	if err != nil {
		fmt.Fprintf(errOut, "ak adapter: %s\n", err)
		return 2
	}
	token, variable := config.WorkerToken("claude", login)
	// the script's `rm -f`: an unlink, so a directory in the token's place stays and fails the verb,
	// and a token under a folder that is no folder is as absent as one not there
	if err := syscall.Unlink(token); err != nil && !errors.Is(err, fs.ErrNotExist) && !errors.Is(err, syscall.ENOTDIR) {
		fmt.Fprintf(errOut, "claude logout: %s: %s\n", token, err)
		return 1
	}
	// the login's home as the script names it, literally: config.LoginPath would read a `$` in a
	// home's name as a variable, and find no login where one is
	if _, err := os.Stat(login.Home + "/.credentials.json"); err != nil {
		keychain := claudeKeychain(login)
		if keychain == "" || exec.Command("security", "find-generic-password", "-s", keychain).Run() != nil {
			return 0
		}
	}
	program := Binary("claude")
	if program == "" {
		// bash, finding no claude on $PATH it may run, starts the first there all the same
		for _, dir := range filepath.SplitList(os.Getenv("PATH")) {
			if info, err := os.Stat(filepath.Join(dir, "claude")); err == nil && !info.IsDir() {
				program = filepath.Join(dir, "claude")
				break
			}
		}
	}
	if program == "" {
		fmt.Fprintln(errOut, "claude.sh logout: claude is not installed")
		return 127
	}
	return claudeAuthRun("logout", program, slices.DeleteFunc(login.Environ(os.Environ()), func(pair string) bool {
		return strings.HasPrefix(pair, variable+"=")
	}), out, errOut)
}

// claudeAuthRun is `claude auth <verb>`, Claude Code at program run in env as the script's bash runs
// it, and the status bash gives it.
func claudeAuthRun(verb, program string, env []string, out, errOut io.Writer) int {
	cmd := exec.Command(program, "auth", verb)
	cmd.Args[0], cmd.Env = "claude", env
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, out, errOut
	err := cmd.Run()
	if errors.Is(err, syscall.ENOEXEC) {
		// a file the system starts no program from, bash reads as its own script, as it reads one
		// named to it, and refuses with 126 where it cannot read it or finds it binary
		script := exec.Command("/bin/bash", program, "auth", verb)
		script.Env, script.Stdin, script.Stdout, script.Stderr = cmd.Env, cmd.Stdin, cmd.Stdout, cmd.Stderr
		cmd, err = script, script.Run()
	}
	// the status bash gives it: 127 for a file it names that is not there, its interpreter, 126
	// for any other that does not start, 128 and the signal's number for one a signal ends
	if cmd.ProcessState == nil {
		fmt.Fprintf(errOut, "claude %s: %s\n", verb, err)
		if errors.Is(err, syscall.ENOENT) {
			return 127
		}
		return 126
	}
	if status, ok := cmd.ProcessState.Sys().(syscall.WaitStatus); ok && status.Signaled() {
		return 128 + int(status.Signal())
	}
	return cmd.ProcessState.ExitCode()
}
