package harness

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"syscall"

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
	cmd := claudeCommand("claude", "auth", "login")
	if cmd.Err != nil {
		fmt.Fprintln(errOut, "claude.sh login: claude is not installed")
		return 2
	}
	saved, _ := os.ReadFile(claudeCredentials(login))
	keychain := claudeKeychain(login)
	if (len(args) == 0 || args[0] != "again") && (bytes.Contains(saved, []byte(`"accessToken"`)) ||
		keychain != "" && exec.Command("security", "find-generic-password", "-s", keychain, "-w").Run() == nil) {
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
	cmd.Env = login.Environ(cmd.Env)
	return claudeAuthRun(cmd, out, errOut)
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
	remove := func(path string) error {
		// the script's `rm -rf`: a path under a folder that is no folder is as absent as one not there
		if err := os.RemoveAll(path); !errors.Is(err, syscall.ENOTDIR) {
			return err
		}
		return nil
	}
	if err := errors.Join(remove(login.Home), remove(token)); err != nil {
		fmt.Fprintf(errOut, "claude forget: %s\n", err)
		return 1
	}
	return 0
}
