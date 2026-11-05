package cli

import (
	"cmp"
	"fmt"
	"os"
	"os/exec"
	"os/signal"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/logins"
	"agentkit/internal/menu"
	"agentkit/internal/terminal"
	"agentkit/internal/worker"
)

// signIn is a subscription's `↻ log in again` (menu.sign_in): the terminal given back on a screen of
// its own, saying which harness opens, since one can take seconds to draw its login; its adapter's
// `login again` under its account and provider, ^C ending that and not ak; then the terminal taken
// again.  One that failed, or exited 0 with its harness saying it has no login for it now, as one cut
// short can, waits until what it said has been read (Python's pause) and is said under the page, its
// login left where it was; one that finished is asked its end (logins.Renewed).  What to say under
// the page, or "".
func signIn(cell menu.Cell, keyboard *terminal.Keyboard, painter *terminal.Painter) string {
	keyboard.Give()
	fmt.Print("\x1b[2J\x1b[H") // the screen given back still shows the last sign-in's lines
	fmt.Println("Opening " + config.HarnessName(cell.Harness) + " to log in…")
	// a handler, unlike an ignored signal, is not inherited by the harness, which ^C ends
	interrupts := make(chan os.Signal, 1)
	signal.Notify(interrupts, os.Interrupt)
	finished := signedIn(cell)
	signal.Stop(interrupts)
	if !finished {
		showMenuNotices(nil, keyboard, painter) // a keyboard gone there reads eof on the page too
		return cell.Label + "'s sign-in did not finish"
	}
	keyboard.Take()
	logins.Renewed(cell.Provider, cell.Account, cell.Harness)
	return ""
}

// signedIn is whether the adapter's `login again` for that subscription finished on the terminal: it
// exited 0 and its harness does not say it has no interactive login for it now.
func signedIn(cell menu.Cell) bool {
	adapter, err := config.LoginAdapter(cell.Harness)
	env, envErr := config.ChildEnv()
	if err = cmp.Or(err, envErr); err != nil {
		fmt.Println(cell.Harness + ": " + err.Error())
		return false
	}
	// a browser a sign-in opens is the owner's, and outlives ak
	env = append(host.Unmarked(env), config.AccountEnv(cell.Account), "AGENTKIT_PROVIDER="+cell.Provider)
	login := exec.Command(adapter, "login", "again")
	login.Env, login.Stdin, login.Stdout, login.Stderr = env, os.Stdin, os.Stdout, os.Stderr
	if login.Run() != nil {
		return false
	}
	answered, yes, _ := worker.Login(adapter, env, "seat")
	return !answered || yes
}
