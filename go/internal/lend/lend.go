// Package lend lends a check's throwaway HOME each harness's login as a copy nothing can renew,
// as Python's lend.into does: on 28 Oct 2026 a check renewed the host's login in the HOME it
// was linked into, retiring the one every seat held, and nothing lent goes back.
package lend

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// A Loan is what Into lent: each harness lent, then the paths it placed under home; the epoch
// second the first of them lapses and whose, Whose "" where none does; and {provider: account}
// of each subscription lent by name, in the order lent.
type Loan struct {
	Lent   [][]string
	Ends   int64
	Whose  string
	Named  *run.Object
	placed []string // every link made, taken back where the loan fails
}

// Lenders are the harnesses that lend, in name order, as Python's lend._lenders: each whose
// manifest lists `[worker] logins` and whose adapter is here.
func Lenders() ([]string, error) {
	names, err := config.ManifestNames()
	var lenders []string
	for _, name := range names {
		logins, _ := config.Words(name, "worker", "logins")
		if _, missing := os.Stat(config.AdapterPath(name)); len(logins) > 0 && missing == nil {
			lenders = append(lenders, name)
		}
	}
	return lenders, err
}

// Into lends home, made where missing, each lender's usual login: its adapter's `lend`, told no
// account.  With subscriptions, a harness with none to lend tries next each subscription the
// caller's config lists on a provider it runs, until one lends.  A lend failing, or a place it
// takes in home being taken, fails it all, every link it made taken back: no caller is told
// what to keep out of what it saves.
func Into(home string, subscriptions bool) (Loan, error) {
	if err := os.MkdirAll(home, 0o777); err != nil {
		return Loan{}, err
	}
	listed := map[string][][2]string{}
	if subscriptions {
		listed = accounts()
	}
	lenders, err := Lenders()
	if err != nil {
		return Loan{}, err
	}
	loan := Loan{Named: run.NewObject()}
	for _, harness := range lenders {
		adapter, err := config.LoginAdapter(harness)
		tries := append([][2]string{{}}, listed[harness]...)
		for lent := false; !lent && err == nil && len(tries) > 0; tries = tries[1:] {
			lent, err = loan.add(home, harness, adapter, tries[0])
		}
		if err != nil {
			for _, place := range loan.placed {
				os.Remove(place)
			}
			return Loan{}, err
		}
	}
	return loan, nil
}

// add is harness's lend of account, {provider, name}, its usual login where unnamed: false
// where it has none to lend.  It lends into a folder of its own under home, so what it placed
// is known without its harness's layout, and is linked from there into home, refusing a place
// taken.
func (loan *Loan) add(home, harness, adapter string, account [2]string) (bool, error) {
	staging, err := os.MkdirTemp(home, ".lend-")
	if err != nil {
		return false, err
	}
	defer os.RemoveAll(staging)
	args := []string{"lend", staging}
	if account[1] != "" {
		args = append(args, "own")
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute) // asking for saved keys boots a server
	defer cancel()
	command := exec.CommandContext(ctx, adapter, args...)
	var stdout, stderr bytes.Buffer
	command.Env = append(os.Environ(), config.AccountEnv(account[1]), "AGENTKIT_PROVIDER="+account[0])
	// a program it left holding its output open is waited for no longer than the cap
	command.Stdout, command.Stderr, command.WaitDelay = &stdout, &stderr, time.Minute
	err = command.Run()
	var exited *exec.ExitError
	switch {
	case err != nil && ctx.Err() != nil:
		return false, fmt.Errorf("%s lend took more than a minute", harness)
	case errors.As(err, &exited) && exited.ExitCode() == 1:
		return false, nil // none to lend
	case errors.As(err, &exited):
		return false, fmt.Errorf("%s lend exited %d: %s", harness, exited.ExitCode(), strings.TrimFunc(stderr.String(), config.Space))
	case err != nil:
		return false, err
	}
	said := strings.TrimFunc(stdout.String(), config.Space)
	ends, unread := strconv.ParseInt(said, 10, 64)
	if !utf8.Valid(stdout.Bytes()) || said != "" && unread != nil {
		return false, fmt.Errorf("%s lend printed %s, not the second its login lapses", harness, strconv.Quote(said))
	}
	placed := []string{harness}
	err = filepath.WalkDir(staging, func(path string, _ fs.DirEntry, err error) error {
		if info, unseen := os.Stat(path); err != nil || unseen != nil || !info.Mode().IsRegular() {
			return err
		}
		rel, _ := filepath.Rel(staging, path)
		place := filepath.Join(home, rel)
		if err := os.MkdirAll(filepath.Dir(place), 0o777); err != nil {
			return err
		}
		if err := os.Link(path, place); err != nil {
			return err
		}
		loan.placed, placed = append(loan.placed, place), append(placed, rel)
		return nil
	})
	if err != nil {
		return false, err
	}
	loan.Lent = append(loan.Lent, placed)
	if said != "" && (loan.Whose == "" || ends < loan.Ends) {
		loan.Ends, loan.Whose = ends, harness
	}
	if account[1] != "" {
		loan.Named.Set(account[0], account[1])
	}
	return true, nil
}

// accounts is {harness: [{provider, account}]}, each subscription the caller's config lists by
// name, in its order, under each harness its provider runs on, as Python's lend._listed:
// ProviderHarnesses, so one whose models were all removed still counts.  The default account
// is the usual login, and a config that cannot be read lists none.
func accounts() map[string][][2]string {
	listed := map[string][][2]string{}
	providers, _, err := config.ProviderNames()
	if err != nil {
		return listed
	}
	for _, provider := range providers {
		harnesses, _ := config.ProviderHarnesses(provider)
		names, _ := config.Accounts(provider)
		for _, harness := range harnesses {
			for _, name := range names {
				if name != config.DefaultAccount {
					listed[harness] = append(listed[harness], [2]string{provider, name})
				}
			}
		}
	}
	return listed
}
