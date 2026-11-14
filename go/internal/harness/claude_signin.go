package harness

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/terminal"
)

func init() {
	verbs["claude login"] = claudeSignIn
	verbs["claude forget"] = claudeForget
}

// claudeSignIn is adapters/claude.sh's `login [again]`, for the login $AGENTKIT_ACCOUNT names: 2
// where Claude Code is not installed; 0, signing nothing in, where that login is there and `again`
// is not asked; 1 off a terminal; else Claude Code's own sign-in, whose exit is the verb's.
func claudeSignIn(args []string, out, errOut io.Writer) int {
	login, _, err := config.Account("claude")
	if err != nil {
		fmt.Fprintf(errOut, "ak adapter: %s\n", err)
		return 2
	}
	program := Binary("claude")
	if program == "" {
		fmt.Fprintln(errOut, "claude.sh login: claude is not installed")
		return 2
	}
	if _, blob, _ := claudeLogin(login); (len(args) == 0 || args[0] != "again") &&
		strings.Contains(string(blob), `"accessToken"`) {
		fmt.Fprintln(out, "claude: already logged in")
		return 0
	}
	if !terminal.TypedHere() {
		fmt.Fprintln(errOut, "claude: not logged in; run `claude auth login` in a terminal")
		return 1
	}
	// a handler, unlike an ignored signal, is not inherited by Claude Code, which ^C ends, and this
	// verb then ends as it did, as the script's bash waits for it
	interrupts := make(chan os.Signal, 1)
	signal.Notify(interrupts, os.Interrupt)
	defer signal.Stop(interrupts)
	return claudeAuthRun("login", program, login.Environ(os.Environ()), out, errOut)
}

// claudeForget is adapters/claude.sh's `forget`: the named login $AGENTKIT_ACCOUNT names taken away,
// its config directory and its worker token, a link in them removed, never what it leads to.  The
// usual login is never forgotten (2).
func claudeForget(_ []string, _, errOut io.Writer) int {
	login, _, err := config.Account("claude")
	if err != nil {
		fmt.Fprintf(errOut, "ak adapter: %s\n", err)
		return 2
	}
	if login.Account == "" {
		fmt.Fprintln(errOut, "claude.sh forget: the usual login is never forgotten")
		return 2
	}
	token, _ := config.WorkerToken("claude", login)
	if err := errors.Join(os.RemoveAll(login.Home), os.RemoveAll(token)); err != nil {
		fmt.Fprintf(errOut, "claude forget: %s\n", err)
		return 1
	}
	return 0
}
