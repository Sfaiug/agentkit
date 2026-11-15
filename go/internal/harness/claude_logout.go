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
	if _, err := os.Stat(claudeCredentials(login)); err != nil {
		keychain := claudeKeychain(login)
		if keychain == "" || exec.Command("security", "find-generic-password", "-s", keychain).Run() != nil {
			return 0
		}
	}
	cmd := claudeCommand("claude", "auth", "logout")
	if cmd.Err != nil {
		// bash, finding no claude on $PATH it may run, starts the first there all the same
		for _, dir := range filepath.SplitList(os.Getenv("PATH")) {
			if info, err := os.Stat(filepath.Join(dir, "claude")); err == nil && !info.IsDir() {
				cmd.Path, cmd.Err = filepath.Join(dir, "claude"), nil
				break
			}
		}
	}
	if cmd.Err != nil {
		fmt.Fprintln(errOut, "claude.sh logout: claude is not installed")
		return 127
	}
	cmd.Env = slices.DeleteFunc(login.Environ(cmd.Env), func(pair string) bool {
		return strings.HasPrefix(pair, variable+"=")
	})
	return claudeAuthRun(cmd, out, errOut)
}

// claudeAuthRun runs cmd, Claude Code's `claude auth <verb>` (claudeCommand), as the script's bash
// runs it, and gives the status bash gives it.
func claudeAuthRun(cmd *exec.Cmd, out, errOut io.Writer) int {
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, out, errOut
	err := cmd.Run()
	if errors.Is(err, syscall.ENOEXEC) {
		// a file the system starts no program from, bash reads as its own script, as it reads one
		// named to it, and refuses with 126 where it cannot read it or finds it binary
		script := exec.Command("/bin/bash", append([]string{cmd.Path}, cmd.Args[1:]...)...)
		script.Env, script.Stdin, script.Stdout, script.Stderr = cmd.Env, cmd.Stdin, cmd.Stdout, cmd.Stderr
		cmd, err = script, script.Run()
	}
	// the status bash gives it: 127 for a file it names that is not there, its interpreter, 126
	// for any other that does not start, 128 and the signal's number for one a signal ends
	if cmd.ProcessState == nil {
		fmt.Fprintf(errOut, "claude %s: %s\n", cmd.Args[len(cmd.Args)-1], err)
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

// claudeCredentials is the login's credentials file as the script names it, its home's name taken
// literally: config.LoginPath would read a `$` in it as a variable, and find no login where one is.
func claudeCredentials(login config.Login) string {
	return login.Home + "/.credentials.json"
}
