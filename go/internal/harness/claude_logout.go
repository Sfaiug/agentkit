package harness

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"slices"
	"strings"

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
	if err := os.Remove(token); err != nil && !errors.Is(err, fs.ErrNotExist) {
		fmt.Fprintf(errOut, "claude logout: %s\n", err)
		return 1
	}
	if _, err := os.Stat(config.LoginPath("claude", "credentials", login)); err != nil {
		keychain := claudeKeychain(login)
		if keychain == "" || exec.Command("security", "find-generic-password", "-s", keychain).Run() != nil {
			return 0
		}
	}
	program := Binary("claude")
	if program == "" {
		fmt.Fprintln(errOut, "claude.sh logout: claude is not installed")
		return 127
	}
	cmd := exec.Command(program, "auth", "logout")
	cmd.Args[0] = "claude"
	cmd.Env = slices.DeleteFunc(login.Environ(os.Environ()), func(pair string) bool {
		return strings.HasPrefix(pair, variable+"=")
	})
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, out, errOut
	if err := cmd.Run(); cmd.ProcessState == nil {
		fmt.Fprintf(errOut, "claude logout: %s\n", err)
		return 126
	}
	return cmd.ProcessState.ExitCode()
}
