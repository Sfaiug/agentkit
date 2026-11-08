package cli

import (
	"cmp"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"slices"
	"strings"

	"agentkit/internal/adapters"
	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/logins"
	"agentkit/internal/menu"
	"agentkit/internal/terminal"
	"agentkit/internal/worker"
)

// signIn is a subscription's `↻ log in again` (menu.sign_in): its adapter's `login again` under its
// account and provider (adapterVerbs), its login left where it was by one that did not finish, which
// is said under the page; one that finished is asked its end (logins.Renewed).  What to say under the
// page, or "".
func signIn(cell menu.Cell, keyboard *terminal.Keyboard, painter *terminal.Painter) string {
	if adapterVerbs(keyboard, painter, cell.Harness, []string{"login again"}, cell.Account, cell.Provider, false) != "" {
		return cell.Label + "'s sign-in did not finish"
	}
	logins.Renewed(cell.Provider, cell.Account, cell.Harness)
	return ""
}

// adapterVerbs runs each of verbs of that harness's adapter, `install` or a sign-in, for account's
// login and provider's (menu._adapter_verbs): the terminal given back on a screen of its own, each
// verb said in a line as it starts, since a harness can take seconds to draw its own screen; then the
// terminal taken again.  The first that does not finish ends them and waits until what it said has
// been read (Python's pause); with fresh, account being a name no subscription lists yet, it takes
// what the harness made for it with it (its adapter's `forget`), as a login nobody lists is one
// nobody signs out.  The verb that did not finish, or "".
func adapterVerbs(keyboard *terminal.Keyboard, painter *terminal.Painter, harness string, verbs []string, account, provider string, fresh bool) string {
	if len(verbs) == 0 {
		return "" // nothing to run, and the terminal stays
	}
	keyboard.Give()
	fmt.Print("\x1b[2J\x1b[H") // the screen given back still shows the last sign-in's lines
	for _, verb := range verbs {
		if !ranVerb(harness, verb, account, provider) {
			if fresh {
				forget(harness, account)
			}
			showMenuNotices(nil, keyboard, painter) // a keyboard gone there reads eof on the page too
			return verb
		}
	}
	keyboard.Take()
	painter.Forget()
	return ""
}

// ranVerb is whether that verb of the harness's adapter finished on the terminal: it exited 0 and, for
// a sign-in, its harness does not say it has no interactive login for it now, as one cut short can.
func ranVerb(harness, verb, account, provider string) bool {
	name, login := config.HarnessName(harness), strings.HasPrefix(verb, "login")
	if login {
		fmt.Println("Opening " + name + " to log in…")
	} else {
		fmt.Println("Installing " + name + "…")
	}
	// a handler, unlike an ignored signal, is not inherited by the harness, which ^C ends
	interrupts := make(chan os.Signal, 1)
	signal.Notify(interrupts, os.Interrupt)
	defer signal.Stop(interrupts)
	run, err := adapterCall(harness, account, provider, strings.Fields(verb)...)
	if err != nil {
		fmt.Println(harness + ": " + err.Error())
		return false
	}
	if login {
		run.Env = host.Unmarked(run.Env) // a browser a sign-in opens is the owner's, and outlives ak
	}
	run.Stdin, run.Stdout, run.Stderr = os.Stdin, os.Stdout, os.Stderr
	if run.Run() != nil {
		return false
	}
	if !login {
		return true
	}
	// its `auth` is its script's, whoever signed it in
	script, _ := config.LoginAdapter(harness)
	if answered, yes, _ := worker.Login(script, run.Env, "seat"); answered && !yes {
		return false
	}
	signedIn[harness] = true // c reads its models again
	return true
}

// adapterCall is that verb of the harness's adapter (adapters.SignIn) for account's login and
// provider's, in the environment ak's children get with adapterTold added.
func adapterCall(harness, account, provider string, verb ...string) (*exec.Cmd, error) {
	adapter, err := adapters.SignIn(harness, verb[0])
	env, envErr := config.ChildEnv()
	if err = cmp.Or(err, envErr); err != nil {
		return nil, err
	}
	call := exec.Command(adapter[0], slices.Concat(adapter[1:], verb)...)
	call.Env = append(env, adapterTold(account, provider)...)
	return call, nil
}

// adapterTold is what an adapter call for account's login and provider's is told (config.account_env,
// config.provider_env).
func adapterTold(account, provider string) []string {
	return []string{config.AccountEnv(account), "AGENTKIT_PROVIDER=" + provider}
}

// forget is what that harness made for account, a login that did not finish, taken away.
func forget(harness, account string) {
	adapter, err := adapters.SignIn(harness, "forget")
	env, envErr := config.ChildEnv()
	if cmp.Or(err, envErr) != nil {
		return // no adapter to run: nothing ran to make anything either
	}
	run := exec.Command(adapter[0], slices.Concat(adapter[1:], []string{"forget"})...)
	run.Env = append(env, config.AccountEnv(account))
	run.Run()
}
