package adapters

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/terminal"
)

// SignIn is what runs that verb of a harness's adapter for the menu, `install`, `login [again]`,
// `logout` or `forget`: the script $AGENTKIT_ADAPTER_DIR holds; else this program for a login and
// its forget, where the manifest gives it the words of a sign-in (`[launch] login`); else the shell
// adapter shipped beside the manifest.
func SignIn(name, verb string) ([]string, error) {
	_, err := config.Adapter(name)
	if _, ok, _ := config.Launch(name, "login", nil); ok && errors.Is(err, config.ErrNoAdapterDir) &&
		(verb == "login" || verb == "forget") {
		return self(name)
	}
	adapter, err := config.LoginAdapter(name)
	return []string{adapter}, err
}

// self is this program as the stubs under go/adapters hand it that harness's verbs.
func self(name string) ([]string, error) {
	program, _ := os.Executable()
	program, err := filepath.EvalSymlinks(program)
	return []string{program, "adapter", filepath.Dir(filepath.Dir(program)), name}, err
}

// Login is `login [again]`, the login $AGENTKIT_ACCOUNT names signed in by the manifest's `[launch]
// login` words, as the Python adapters check before it: 2 where its program is not installed; 0,
// signing nothing in, where its `[login] credentials` hold anything and `again` is not asked; 1 off
// a terminal; 2 where a named login cannot share the usual one's conversations and settings; else
// the sign-in's own exit code.
func Login(name string, args []string, out, errOut io.Writer) int {
	words, ok, err := config.Launch(name, "login", nil)
	login, _, accountErr := config.Account(name)
	if err = cmp.Or(err, accountErr); err != nil || !ok {
		return refused(name, "login", err, errOut)
	}
	program := harness.Binary(words[0])
	if program == "" {
		fmt.Fprintf(errOut, "%s.sh login: %s is not installed\n", name, words[0])
		return 2
	}
	saved, _ := os.ReadFile(config.LoginPath(name, "credentials", login))
	if (len(args) == 0 || args[0] != "again") && strings.TrimFunc(string(saved), config.Space) != "" {
		fmt.Fprintln(out, words[0]+": already logged in")
		return 0
	}
	if !terminal.TypedHere() {
		fmt.Fprintf(errOut, "%s: not logged in; run `%s` in a terminal\n", words[0], strings.Join(words, " "))
		return 1
	}
	if login.Account != "" {
		if err := share(login); err != nil {
			fmt.Fprintf(errOut, "%s login: %s\n", name, err)
			return 2
		}
	}
	cmd := exec.Command(program, words[1:]...)
	cmd.Args[0], cmd.Env = words[0], login.Environ(os.Environ())
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	// a handler, unlike an ignored signal, is not inherited by the harness, which ^C ends
	interrupts := make(chan os.Signal, 1)
	signal.Notify(interrupts, os.Interrupt)
	defer signal.Stop(interrupts)
	if err := cmd.Run(); cmd.ProcessState == nil {
		fmt.Fprintf(errOut, "ak adapter: %s: %s\n", words[0], err)
		return 126
	}
	return exitCode(cmd.ProcessState)
}

// Forget is `forget`, what a sign-in made for the named login $AGENTKIT_ACCOUNT names taken away, as
// the Python adapters take it: its home and its refusal ([login] refused).  The usual login is never
// forgotten (2).
func Forget(name string, errOut io.Writer) int {
	login, kept, err := config.Account(name)
	if _, ok, _ := config.Launch(name, "login", nil); err != nil || !kept || !ok {
		return refused(name, "forget", err, errOut)
	}
	if login.Account == "" {
		fmt.Fprintf(errOut, "%s.sh forget: the usual login is never forgotten\n", name)
		return 2
	}
	if err := errors.Join(os.RemoveAll(login.Home), os.RemoveAll(config.LoginPath(name, "refused", login))); err != nil {
		fmt.Fprintf(errOut, "%s forget: %s\n", name, err)
		return 1
	}
	return 0
}
