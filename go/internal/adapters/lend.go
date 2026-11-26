package adapters

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/harness"
)

// Lend answers `lend <home> [own]` as the Python adapters do: the login a turn on another
// machine runs on, copied to where a turn run with HOME=home reads it, and on stdout the epoch
// second it lapses, where it does.  With own and an account named, that is where a turn naming
// the account reads it; else where one naming none does, as a machine's turn runs.  It answers
// 1, with a line on stderr, where there is no login to lend, and 2 where home is this HOME, whose
// own login the copy would stand in for, or something is there already; either way it writes
// nothing.
func Lend(name string, args []string, out, errOut io.Writer) int {
	if len(args) < 1 {
		fmt.Fprintf(errOut, "%s.sh lend needs <home>\n", name)
		return 2
	}
	login, err := account(name)
	loan, ok := harness.Lend(name, login)
	if err != nil || !ok {
		return refused(name, "lend", err, errOut)
	}
	if loan.Copy == "" {
		fmt.Fprintln(errOut, loan.Line)
		return 1
	}
	usual, _ := os.UserHomeDir()
	this, _ := os.Stat(usual)
	if there, _ := os.Stat(args[0]); os.SameFile(there, this) {
		fmt.Fprintf(errOut, "lend: %s is this HOME; lend into another\n", args[0])
		return 2
	}
	file := loan.File
	if len(args) < 2 || args[1] != "own" || login.Account == "" {
		// a turn naming no account reads the usual login, whatever this call's environment names:
		// the first of the logins a turn carries that a bare HOME names
		logins, _ := config.Words(name, "worker", "logins")
		file = ""
		if paths := config.ManifestPaths(logins, map[string]string{"HOME": usual}, ""); len(paths) > 0 {
			file = paths[0]
		}
	}
	at, err := filepath.Rel(usual, file)
	if err == nil {
		at = filepath.Join(args[0], at)
		err = keep(at, loan.Copy)
	}
	if errors.Is(err, fs.ErrExist) {
		fmt.Fprintf(errOut, "lend: %s is there already; lend into a HOME holding no login\n", at)
		return 2
	}
	if err != nil {
		fmt.Fprintf(errOut, "lend: %s\n", err)
		return 2
	}
	if loan.Ends != 0 {
		fmt.Fprintln(out, loan.Ends)
	}
	return 0
}

// keep puts text at path whole or not at all, owner-only, and never over anything there: from a
// temp file beside it, linked into place, which fails where something is.
func keep(path, text string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
		return err
	}
	temporary, err := os.CreateTemp(filepath.Dir(path), filepath.Base(path)+".*.tmp")
	if err != nil {
		return err
	}
	defer os.Remove(temporary.Name())
	_, err = temporary.WriteString(text)
	if closed := temporary.Close(); err == nil {
		err = closed
	}
	if err == nil {
		err = os.Link(temporary.Name(), path)
	}
	return err
}
