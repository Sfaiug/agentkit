package adapters

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/lock"
)

// Auth answers `auth [seat]` as the Python adapters do: 0 where a turn, or with `seat` the seat's
// own login, can sign in, else 1, with one line saying so, a yes on stdout and a no on stderr.
// A login that lapsed where only a turn of its harness renews it gets that turn first.
func Auth(name string, args []string, out, errOut io.Writer) int {
	seat := len(args) > 0 && args[0] == "seat"
	login, _, err := config.Account(name)
	answer, ok := harness.Auth(name, login, seat)
	if err != nil || !ok {
		return refused(name, "auth", err, errOut)
	}
	if answer.Lapsed {
		renew(name, login)
		answer, _ = harness.Auth(name, login, seat)
	}
	if !answer.Yes {
		fmt.Fprintln(errOut, answer.Line)
		return 1
	}
	fmt.Fprintln(out, answer.Line)
	return 0
}

// renew runs the harness's `[launch] renew` turn, `hi` down its stdin, in ak's tmp, one per login
// at a time under its `[login] lock`, which its Python adapter takes too: whoever waited finds the
// login renewed and starts none.  Silent: `auth` answers in one line.
func renew(name string, login config.Login) {
	tmp := filepath.Join(config.Home(), "tmp")
	path := config.LoginPath(name, "lock", login)
	words, ok, err := config.Launch(name, "renew", nil)
	if !ok || err != nil || path == "" || os.MkdirAll(tmp, 0o777) != nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	held, err := lock.Wait(ctx, path)
	if err != nil {
		return
	}
	defer held.Close()
	if answer, _ := harness.Auth(name, login, true); !answer.Lapsed {
		return
	}
	words, env := environ(words, login.Environ(os.Environ()))
	program := ""
	if len(words) > 0 {
		program = harness.Binary(words[0])
	}
	if program == "" {
		return
	}
	cmd := exec.Command(program, words[1:]...)
	cmd.Args[0], cmd.Dir, cmd.Env, cmd.Stdin = words[0], tmp, env, strings.NewReader("hi\n")
	cmd.Run()
}
